import os
from datetime import datetime
from collections import defaultdict
from src.database import (
    get_transactions, get_proventos, clear_custody, 
    update_custody_record, delete_custody_record, 
    update_losses_carryover, update_darf_record, get_darfs
)

def compute_portfolio(user_id: int):
    """
    Simulates the ledger chronologically to:
    1. Rebuild custody positions (average price & quantity).
    2. Calculate monthly profits/losses and sales volumes.
    3. Apply B3 tax rules (offset losses, 20k exemption, FII, Day Trade).
    4. Save results to database tables (custody, loss_carryover, darfs).
    
    Implementation is in pure Python for high performance and zero dependency issues.
    """
    # 1. Fetch data
    txs = get_transactions(user_id)
    provs = get_proventos(user_id)

    # Clean custody first
    clear_custody(user_id)

    if not txs:
        return 0.0, {}

    # Data structures for simulation
    custody_state = {} # ticker -> {qty, avg_price, market_type}
    
    # Financial indicators tracking
    running_realized_profit = 0.0
    running_cash_balance = 0.0
    min_cash_balance_seen = 0.0
    historical_monthly_raw = {}
    last_month_seen = None
    
    # Monthly aggregates
    # month_str (YYYY-MM) -> metrics
    monthly_sales = defaultdict(lambda: {"VISTA": 0.0, "BDR": 0.0, "OPCOES": 0.0, "FII": 0.0})
    monthly_dt_sales = defaultdict(float)  # Day trade sell volume per month
    monthly_profits = defaultdict(lambda: {
        "common_acoes": 0.0,  # potentially exempt
        "common_other": 0.0,  # BDR, OPCOES (never exempt)
        "day_trade": 0.0,
        "fii": 0.0
    })
    monthly_losses = defaultdict(lambda: {
        "common": 0.0,
        "day_trade": 0.0,
        "fii": 0.0
    })
    monthly_irrf = defaultdict(lambda: {"common": 0.0, "day_trade": 0.0})

    # Sort transactions chronologically by trade_date and id
    sorted_txs = sorted(txs, key=lambda x: (x['trade_date'], x['id']))

    # Group transactions by date
    date_groups = defaultdict(list)
    for tx in sorted_txs:
        date_groups[tx['trade_date']].append(tx)

    for date_str in sorted(date_groups.keys()):
        group = date_groups[date_str]
        month_str = date_str[:7] # YYYY-MM

        # Monthly state recording on month transition
        if last_month_seen and last_month_seen != month_str:
            historical_monthly_raw[last_month_seen] = {
                "custody": {t: dict(c) for t, c in custody_state.items() if c["qty"] != 0},
                "realized_profit_accum": running_realized_profit,
                "cash_balance": running_cash_balance,
                "min_cash_balance": min_cash_balance_seen
            }
        last_month_seen = month_str

        # Update cash balance for transactions on this date
        for tx in group:
            if tx['operation_type'] == 'COMPRA':
                running_cash_balance -= (tx['quantity'] * tx['price'] + tx['fees'])
            elif tx['operation_type'] == 'VENDA':
                running_cash_balance += (tx['quantity'] * tx['price'] - tx['fees'])
        min_cash_balance_seen = min(min_cash_balance_seen, running_cash_balance)

        # Group by ticker and broker to identify Day Trades
        group_by_tb = defaultdict(list)
        for tx in group:
            key = (tx['ticker'], tx['broker'])
            group_by_tb[key].append(tx)

        for (ticker, broker), sub_group in group_by_tb.items():
            buys = [t for t in sub_group if t['operation_type'] == 'COMPRA']
            sells = [t for t in sub_group if t['operation_type'] == 'VENDA']

            total_buy_qty = sum(b['quantity'] for b in buys)
            total_sell_qty = sum(s['quantity'] for s in sells)

            dt_qty = min(total_buy_qty, total_sell_qty)

            total_buy_fees = sum(b['fees'] for b in buys)
            total_sell_fees = sum(s['fees'] for s in sells)

            # ── Day Trade Processing ──
            if dt_qty > 0:
                # Weighted average prices for day trade matching
                avg_buy_price = sum(b['price'] * b['quantity'] for b in buys) / total_buy_qty
                avg_sell_price = sum(s['price'] * s['quantity'] for s in sells) / total_sell_qty

                buy_dt_fees = total_buy_fees * (dt_qty / total_buy_qty)
                sell_dt_fees = total_sell_fees * (dt_qty / total_sell_qty)

                # Track day trade sell volume (for DARF reporting)
                dt_sell_value = dt_qty * avg_sell_price
                monthly_dt_sales[month_str] += dt_sell_value

                # Day Trade Net Profit
                dt_profit = dt_qty * (avg_sell_price - avg_buy_price) - (buy_dt_fees + sell_dt_fees)
                running_realized_profit += dt_profit

                # Day trade IRRF (Dedo-Duro: 1% on profit)
                if dt_profit > 0:
                    dt_irrf = dt_profit * 0.01
                    monthly_irrf[month_str]["day_trade"] += dt_irrf

                if dt_profit >= 0:
                    monthly_profits[month_str]["day_trade"] += dt_profit
                else:
                    monthly_losses[month_str]["day_trade"] += abs(dt_profit)

            # ── Swing Trade Leftovers ──
            # Determine leftover quantities
            swing_buy_qty = total_buy_qty - dt_qty
            swing_sell_qty = total_sell_qty - dt_qty

            market_type = sub_group[0]['market_type']
            # Normalize ACOES to VISTA for consistent key usage
            if market_type == 'ACOES':
                market_type = 'VISTA'

            # 1. Process Swing Trade Purchase (Long expansion or Short cover)
            if swing_buy_qty > 0:
                avg_buy_price = sum(b['price'] * b['quantity'] for b in buys) / total_buy_qty
                swing_buy_fees = total_buy_fees * (swing_buy_qty / total_buy_qty)

                if ticker not in custody_state:
                    custody_state[ticker] = {"qty": 0, "avg_price": 0.0, "market_type": market_type}

                pos = custody_state[ticker]
                current_qty = pos["qty"]
                current_avg = pos["avg_price"]

                if current_qty >= 0: # Long position
                    total_cost = current_qty * current_avg + (swing_buy_qty * avg_buy_price + swing_buy_fees)
                    pos["qty"] += swing_buy_qty
                    pos["avg_price"] = total_cost / pos["qty"]
                else: # Short position (covering short)
                    abs_qty = abs(current_qty)
                    covered_qty = min(swing_buy_qty, abs_qty)
                    prop_fees = swing_buy_fees * (covered_qty / swing_buy_qty)
                    
                    cost_to_cover = covered_qty * avg_buy_price + prop_fees
                    # Short profit: Sell price (stored as avg_price) - Buy cost
                    st_profit = covered_qty * current_avg - cost_to_cover
                    running_realized_profit += st_profit

                    if market_type == 'FII':
                        if st_profit >= 0:
                            monthly_profits[month_str]["fii"] += st_profit
                        else:
                            monthly_losses[month_str]["fii"] += abs(st_profit)
                    elif market_type in ('ACOES', 'VISTA'):
                        # Short selling Actions is NEVER exempt
                        if st_profit >= 0:
                            monthly_profits[month_str]["common_other"] += st_profit
                        else:
                            monthly_losses[month_str]["common"] += abs(st_profit)
                    else: # BDR or OPCOES
                        if st_profit >= 0:
                            monthly_profits[month_str]["common_other"] += st_profit
                        else:
                            monthly_losses[month_str]["common"] += abs(st_profit)

                    # Update position
                    pos["qty"] += covered_qty
                    if pos["qty"] == 0:
                        pos["avg_price"] = 0.0
                    
                    # If covered more than shorted, open a long position with the remainder
                    rem_qty = swing_buy_qty - covered_qty
                    if rem_qty > 0:
                        rem_fees = swing_buy_fees * (rem_qty / swing_buy_qty)
                        pos["qty"] = rem_qty
                        pos["avg_price"] = (rem_qty * avg_buy_price + rem_fees) / rem_qty

            # 2. Process Swing Trade Sale (Long reduction or Short expansion)
            if swing_sell_qty > 0:
                avg_sell_price = sum(s['price'] * s['quantity'] for s in sells) / total_sell_qty
                swing_sell_fees = total_sell_fees * (swing_sell_qty / total_sell_qty)

                # Dedo-duro IRRF for Swing Trade: 0.005% on sales volume
                sale_value = swing_sell_qty * avg_sell_price
                swing_irrf = sale_value * 0.00005
                monthly_irrf[month_str]["common"] += swing_irrf

                # Add to sales volume
                monthly_sales[month_str][market_type] += sale_value

                if ticker not in custody_state:
                    custody_state[ticker] = {"qty": 0, "avg_price": 0.0, "market_type": market_type}

                pos = custody_state[ticker]
                current_qty = pos["qty"]
                current_avg = pos["avg_price"]

                if current_qty > 0: # Long position (selling long)
                    sold_qty = min(swing_sell_qty, current_qty)
                    prop_fees = swing_sell_fees * (sold_qty / swing_sell_qty)
                    
                    revenue_net = sold_qty * avg_sell_price - prop_fees
                    st_profit = revenue_net - (sold_qty * current_avg)
                    running_realized_profit += st_profit

                    if market_type == 'FII':
                        if st_profit >= 0:
                            monthly_profits[month_str]["fii"] += st_profit
                        else:
                            monthly_losses[month_str]["fii"] += abs(st_profit)
                    elif market_type in ('ACOES', 'VISTA'):
                        if st_profit >= 0:
                            monthly_profits[month_str]["common_acoes"] += st_profit
                        else:
                            monthly_losses[month_str]["common"] += abs(st_profit)
                    else: # BDR or OPCOES
                        if st_profit >= 0:
                            monthly_profits[month_str]["common_other"] += st_profit
                        else:
                            monthly_losses[month_str]["common"] += abs(st_profit)

                    # Update position
                    pos["qty"] -= sold_qty
                    if pos["qty"] == 0:
                        pos["avg_price"] = 0.0

                    # If sold more than long, open short position
                    rem_qty = swing_sell_qty - sold_qty
                    if rem_qty > 0:
                        rem_fees = swing_sell_fees * (rem_qty / swing_sell_qty)
                        pos["qty"] = -rem_qty
                        pos["avg_price"] = (rem_qty * avg_sell_price - rem_fees) / rem_qty
                else: # Short position (expanding short)
                    revenue_net = swing_sell_qty * avg_sell_price - swing_sell_fees
                    total_revenue = abs(current_qty) * current_avg + revenue_net
                    pos["qty"] -= swing_sell_qty
                    pos["avg_price"] = total_revenue / abs(pos["qty"])

        # ── Apply Corporate Actions (Proventos/Bonificações/Splits) ──
        # Check if there are corporate actions on this date
        day_provs = [p for p in provs if p["record_date"] == date_str]
        for p in day_provs:
            t_ticker = p["ticker"].upper().strip()
            e_type = p["event_type"]
            ratio = p["ratio"]
            unit_cost = p["unit_cost"]

            if e_type in ('DIVIDENDO', 'JCP'):
                running_cash_balance += p['amount']

            if t_ticker in custody_state and custody_state[t_ticker]["qty"] != 0:
                pos = custody_state[t_ticker]
                if e_type == 'SPLIT':
                    pos["qty"] = int(pos["qty"] * ratio)
                    pos["avg_price"] = pos["avg_price"] / ratio
                elif e_type == 'INPLIT':
                    pos["qty"] = int(pos["qty"] * ratio)
                    pos["avg_price"] = pos["avg_price"] / ratio
                elif e_type == 'BONIFICACAO':
                    bonus_qty = int(abs(pos["qty"]) * ratio)
                    if pos["qty"] > 0:
                        new_qty = pos["qty"] + bonus_qty
                        total_cost = pos["qty"] * pos["avg_price"] + bonus_qty * unit_cost
                        pos["qty"] = new_qty
                        pos["avg_price"] = total_cost / new_qty
                    else: # Short position bonification
                        new_qty = pos["qty"] - bonus_qty
                        total_liability = abs(pos["qty"]) * pos["avg_price"] + bonus_qty * unit_cost
                        pos["qty"] = new_qty
                        pos["avg_price"] = total_liability / abs(new_qty)

    # 2. Re-save current custody to Database
    for t_ticker, pos in custody_state.items():
        if pos["qty"] != 0:
            update_custody_record(
                user_id, t_ticker, pos["qty"], round(pos["avg_price"], 4), pos["market_type"]
            )
        else:
            delete_custody_record(user_id, t_ticker)

    # 3. Monthly Tax Processing
    # Sort months chronologically
    sorted_months = sorted(list(set(list(monthly_sales.keys()) + list(monthly_profits.keys()) + list(monthly_losses.keys()))))
    
    # Carryover loss trackers
    accum_loss_common = 0.0
    accum_loss_dt = 0.0
    accum_loss_fii = 0.0

    for month in sorted_months:
        sales = monthly_sales[month]
        profits = monthly_profits[month]
        losses = monthly_losses[month]
        irrf = monthly_irrf[month]

        # ── Swing Trade Ações 20k Exemption ──
        acoes_sales_volume = sales["VISTA"]
        
        # If sales <= 20k, Ações profits are exempt.
        if acoes_sales_volume <= 20000.0:
            taxable_common_profit = profits["common_other"]
        else:
            taxable_common_profit = profits["common_other"] + profits["common_acoes"]

        # Losses from common operations
        common_loss_month = losses["common"]

        # Day trade profits and losses
        dt_profit_month = profits["day_trade"]
        dt_loss_month = losses["day_trade"]

        # FII profits and losses
        fii_profit_month = profits["fii"]
        fii_loss_month = losses["fii"]

        # ── Loss Carryover and Netting ──
        # 1. Common
        net_common = taxable_common_profit - common_loss_month
        if net_common < 0:
            accum_loss_common += abs(net_common)
            base_common = 0.0
        else:
            if accum_loss_common >= net_common:
                accum_loss_common -= net_common
                base_common = 0.0
            else:
                base_common = net_common - accum_loss_common
                accum_loss_common = 0.0

        # 2. Day Trade
        net_dt = dt_profit_month - dt_loss_month
        if net_dt < 0:
            accum_loss_dt += abs(net_dt)
            base_dt = 0.0
        else:
            if accum_loss_dt >= net_dt:
                accum_loss_dt -= net_dt
                base_dt = 0.0
            else:
                base_dt = net_dt - accum_loss_dt
                accum_loss_dt = 0.0

        # 3. FII
        net_fii = fii_profit_month - fii_loss_month
        if net_fii < 0:
            accum_loss_fii += abs(net_fii)
            base_fii = 0.0
        else:
            if accum_loss_fii >= net_fii:
                accum_loss_fii -= net_fii
                base_fii = 0.0
            else:
                base_fii = net_fii - accum_loss_fii
                accum_loss_fii = 0.0

        # ── Tax Calculation ──
        tax_common = base_common * 0.15
        tax_dt = base_dt * 0.20
        tax_fii = base_fii * 0.20

        total_tax_due = tax_common + tax_dt + tax_fii
        total_irrf = irrf["common"] + irrf["day_trade"]

        # Deduct IRRF
        final_tax = max(0.0, total_tax_due - total_irrf)

        # Save DARF and Loss Carryover records
        update_losses_carryover(user_id, month, accum_loss_common, accum_loss_dt, accum_loss_fii)
        
        # Check if the user already marked this DARF as paid to keep state
        existing_darfs = get_darfs(user_id)
        existing_paid = 0
        for d in existing_darfs:
            if d["month"] == month:
                existing_paid = d["paid"]
                break

        dt_sales_month = monthly_dt_sales[month]

        update_darf_record(
            user_id=user_id,
            month=month,
            swing_trade_sales=round(acoes_sales_volume + sales["BDR"] + sales["OPCOES"], 2),
            day_trade_sales=round(dt_sales_month, 2),
            fii_sales=round(sales["FII"], 2),
            swing_trade_profit=round(taxable_common_profit, 2),
            day_trade_profit=round(dt_profit_month, 2),
            fii_profit=round(fii_profit_month, 2),
            tax_due=round(final_tax, 2),
            irrf_dedo_duro=round(total_irrf, 2),
            paid=existing_paid
        )

    # Save final snapshot
    if last_month_seen:
        historical_monthly_raw[last_month_seen] = {
            "custody": {t: dict(c) for t, c in custody_state.items() if c["qty"] != 0},
            "realized_profit_accum": running_realized_profit,
            "cash_balance": running_cash_balance,
            "min_cash_balance": min_cash_balance_seen
        }

    return running_realized_profit, historical_monthly_raw
