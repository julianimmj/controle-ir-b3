import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import os

from src.database import (
    init_db, register_user, authenticate_user,
    add_transaction, get_transactions, delete_transaction,
    get_custody, add_provento, get_proventos, delete_provento,
    get_darfs, set_darf_paid_status, get_losses_carryover,
    update_transaction, update_provento
)
from src.tax_engine import compute_portfolio
from src.parser import parse_sinacor_pdf
from src.market_data import get_current_prices, suggest_corporate_events

# Initialize Database
init_db()

# ─────────────────────────────────────────
# Page Setup
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Controle de Carteira & IR B3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto"
)

# Custom Premium Styling & Mobile Responsiveness
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .stApp {
        background: #060613;
        background-image:
            radial-gradient(circle at 10% 20%, rgba(124, 77, 255, 0.05) 0%, transparent 40%),
            radial-gradient(circle at 90% 80%, rgba(0, 200, 255, 0.04) 0%, transparent 40%);
    }

    /* Cards */
    .kpi-card {
        background: rgba(13, 13, 33, 0.6);
        border: 1px solid rgba(124, 77, 255, 0.15);
        border-radius: 16px;
        padding: 1.25rem 1.5rem;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        margin-bottom: 1rem;
        min-height: 140px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .kpi-label {
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.55);
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .kpi-value {
        font-size: 1.8rem;
        font-weight: 800;
        color: #ffffff;
        margin-top: 0.2rem;
    }
    .kpi-diff {
        font-size: 0.85rem;
        font-weight: 600;
        margin-top: 0.4rem;
    }
    
    /* Tables styling */
    .styled-table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
        font-size: 0.9rem;
    }
    .styled-table th {
        background-color: rgba(124, 77, 255, 0.15);
        color: #ffffff;
        text-align: left;
        padding: 12px 15px;
        font-weight: 700;
        border-bottom: 2px solid rgba(124, 77, 255, 0.3);
    }
    .styled-table td {
        padding: 10px 15px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        color: rgba(255, 255, 255, 0.85);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0c0c1d !important;
        border-right: 1px solid rgba(124, 77, 255, 0.1) !important;
    }
    
    /* Premium Sidebar Navigation styling */
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
        font-size: 1.15rem !important;
        font-weight: 800 !important;
        color: #7c4dff !important;
        margin-bottom: 12px !important;
        letter-spacing: 0.5px;
    }
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 10px !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        background: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(124, 77, 255, 0.08) !important;
        border-radius: 10px !important;
        padding: 12px 16px !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        width: 100% !important;
        margin-bottom: 2px !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(124, 77, 255, 0.07) !important;
        border-color: rgba(124, 77, 255, 0.3) !important;
        transform: translateY(-1px);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] {
        background: rgba(124, 77, 255, 0.14) !important;
        border-color: rgba(124, 77, 255, 0.55) !important;
        box-shadow: 0 4px 12px rgba(124, 77, 255, 0.15) !important;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label div[data-testid="stMarkdownContainer"] p {
        font-size: 1.05rem !important;
        font-weight: 600 !important;
        color: #ffffff !important;
    }

    /* 📱 Mobile Responsive Media Queries */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
            padding-top: 1rem !important;
        }
        .kpi-card {
            padding: 1rem !important;
            min-height: 110px !important;
            margin-bottom: 0.6rem !important;
        }
        .kpi-value {
            font-size: 1.4rem !important;
        }
        .kpi-label {
            font-size: 0.75rem !important;
        }
        .kpi-diff {
            font-size: 0.75rem !important;
        }
        h1 {
            font-size: 1.6rem !important;
        }
        h2 {
            font-size: 1.3rem !important;
        }
        h3 {
            font-size: 1.1rem !important;
        }
    }

    /* Scrollable tables on mobile screens */
    .stDataFrame, [data-testid="stTable"], .styled-table {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

# ─────────────────────────────────────────
# AUTHENTICATION SCREEN
# ─────────────────────────────────────────
if not st.session_state.logged_in:
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center; font-weight:900;'>📈 B3 Portfolio & IR</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: rgba(255,255,255,0.6);'>Controle tributário completo e custódia inteligente</p>", unsafe_allow_html=True)
        
        tab_login, tab_register = st.tabs(["🔑 Acessar Conta", "📝 Criar Conta"])
        
        with tab_login:
            email_log = st.text_input("E-mail", key="log_email")
            pass_log = st.text_input("Senha", type="password", key="log_pass")
            if st.button("Entrar", use_container_width=True):
                user = authenticate_user(email_log, pass_log)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user["id"]
                    st.session_state.user_email = user["email"]
                    st.toast(f"Bem-vindo, {user['email']}!")
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos.")
                    
        with tab_register:
            email_reg = st.text_input("E-mail", key="reg_email")
            pass_reg = st.text_input("Senha", type="password", key="reg_pass")
            pass_reg_conf = st.text_input("Confirmar Senha", type="password", key="reg_pass_conf")
            
            if st.button("Registrar", use_container_width=True):
                if not email_reg or not pass_reg:
                    st.error("Preencha todos os campos.")
                elif pass_reg != pass_reg_conf:
                    st.error("As senhas não coincidem.")
                else:
                    user_id = register_user(email_reg, pass_reg)
                    if user_id:
                        st.success("Conta criada com sucesso! Faça login na aba acima.")
                    else:
                        st.error("Este e-mail já está cadastrado.")
    st.stop()

# ─────────────────────────────────────────
# PORTAL SIDEBAR NAVIGATION
# ─────────────────────────────────────────
user_id = st.session_state.user_id

st.sidebar.markdown(f"<h3 style='margin-bottom:0;'>👨‍💻 {st.session_state.user_email}</h3>", unsafe_allow_html=True)
st.sidebar.markdown("<span style='font-size:0.8rem; color:rgba(255,255,255,0.4);'>Tenant Isolado</span>", unsafe_allow_html=True)
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navegação",
    ["📊 Dashboard", "📝 Lançamentos", "📂 Upload Notas PDF", "🧮 Apuração de IR", "📅 Declaração IRPF"]
)

st.sidebar.markdown("---")
st.sidebar.markdown("### ℹ️ Guia do Menu")
st.sidebar.markdown("""
<div style='font-size:0.8rem; color:rgba(255,255,255,0.45); line-height:1.35; padding: 2px;'>
    <b>📊 Dashboard</b>:<br>Custódia ativa, P&L estimado/realizado e gráfico comparativo com CDI/IBOV.<br><br>
    <b>📝 Lançamentos</b>:<br>Inclusão manual de ativos ou proventos. Permite corrigir ou excluir registros.<br><br>
    <b>📂 Upload Notas PDF</b>:<br>Importação rápida e automática via leitura de notas Sinacor/B3.<br><br>
    <b>🧮 Apuração de IR</b>:<br>Demonstrativo tributário mensal, compensações e emissão de DARF (6015).<br><br>
    <b>📅 Declaração IRPF</b>:<br>Auxiliar consolidado com quantidade e custo histórico em 31/12.
</div>
""", unsafe_allow_html=True)
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Sair", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user_id = None
    st.session_state.user_email = ""
    st.rerun()

# Rebuild database calculations once per session to ensure correct values
if "recalculated" not in st.session_state:
    res = compute_portfolio(user_id)
    if res:
        st.session_state.total_realized_profit = res[0]
        st.session_state.historical_monthly_data = res[1]
    else:
        st.session_state.total_realized_profit = 0.0
        st.session_state.historical_monthly_data = {}
    st.session_state.recalculated = True

# Helper to trigger recalculation
def trigger_rebuild():
    res = compute_portfolio(user_id)
    if res:
        st.session_state.total_realized_profit = res[0]
        st.session_state.historical_monthly_data = res[1]
    else:
        st.session_state.total_realized_profit = 0.0
        st.session_state.historical_monthly_data = {}
    st.toast("Custódia e impostos recalculados com sucesso!")

# ─────────────────────────────────────────
# 1. DASHBOARD VIEW
# ─────────────────────────────────────────
if menu == "📊 Dashboard":
    st.title("📊 Painel de Controle de Custódia")
    st.markdown("Visão geral dos ativos e valuation atualizados da carteira.")
    
    # Load custody positions
    pos = get_custody(user_id)
    
    # ── Auto-Apply Corporate Actions in Background ──
    if pos:
        applied_proventos = get_proventos(user_id)
        applied_keys = {
            (p["ticker"].upper().strip(), p["event_type"].upper().strip(), p["record_date"])
            for p in applied_proventos
        }
        
        new_events_applied = False
        for p in pos:
            # We look back 90 days
            sug_events = suggest_corporate_events(p["ticker"], (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
            for e in sug_events:
                key = (e["ticker"].upper().strip(), e["event_type"].upper().strip(), e["record_date"])
                if key not in applied_keys:
                    add_provento(user_id, e['ticker'], e['event_type'], e['amount'], e['record_date'], e['ratio'], e['unit_cost'])
                    new_events_applied = True
                    applied_keys.add(key)
        
        if new_events_applied:
            # Recompute portfolio with new corporate events
            res = compute_portfolio(user_id)
            if res:
                st.session_state.total_realized_profit = res[0]
                st.session_state.historical_monthly_data = res[1]
            st.session_state.recalculated = True
            st.toast("⚡ Novos eventos corporativos aplicados automaticamente!")
            # Reload custody
            pos = get_custody(user_id)

    if not pos:
        st.info("Nenhum ativo sob custódia atualmente. Vá em 'Upload Notas PDF' ou 'Lançamentos' para começar.")
    else:
        # Fetch current market prices via yfinance
        tickers = [p["ticker"] for p in pos]
        with st.spinner("Atualizando preços de fechamento com Yahoo Finance..."):
            prices = get_current_prices(tickers)
            
        # Calculate valuation metrics
        total_cost = 0.0
        total_value = 0.0
        
        pos_rows = []
        for p in pos:
            t = p["ticker"]
            qty = p["quantity"]
            avg_price = p["average_price"]
            curr_price = prices.get(t, 0.0)
            
            # If current price fetch failed, fallback to average price for valuation
            if curr_price <= 0.0:
                curr_price = avg_price
                
            cost_basis = qty * avg_price
            curr_value = qty * curr_price
            
            # Profit/Loss calculation (works for both long and short since short has negative cost/value)
            if qty < 0:
                profit_loss = cost_basis - curr_value
            else:
                profit_loss = curr_value - cost_basis
                
            # Accumulate metrics ONLY for purchased assets (long positions, qty > 0)
            if qty > 0:
                total_cost += cost_basis
                total_value += curr_value
            
            pos_rows.append({
                "Ativo": t,
                "Tipo": p["market_type"],
                "Qtd": qty,
                "Preço Médio": f"R$ {avg_price:,.2f}",
                "Custo Total": cost_basis,
                "Preço Atual": f"R$ {curr_price:,.2f}",
                "Valor Atual": curr_value,
                "Lucro/Prejuízo": profit_loss,
                "Retorno %": (profit_loss / abs(cost_basis) * 100) if cost_basis != 0 else 0.0
            })
            
        net_profit_loss = total_value - total_cost
        ret_pct = (net_profit_loss / abs(total_cost) * 100) if total_cost != 0 else 0.0
        
        # KPI Cards Row (4 columns)
        kpi_cols = st.columns(4)
        with kpi_cols[0]:
            st.markdown(f"""
            <div class="kpi-card" title="Custo total de aquisição acumulado apenas para as posições compradas (comprados, qty > 0).">
                <div class="kpi-label">Patrimônio Investido (Custo)</div>
                <div class="kpi-value">R$ {total_cost:,.2f}</div>
                <div class="kpi-diff" style="color: rgba(255,255,255,0.4);">Apenas posições compradas</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_cols[1]:
            st.markdown(f"""
            <div class="kpi-card" title="Valuation de mercado atual das posições compradas (comprados, qty > 0) baseadas na última cotação do Yahoo Finance.">
                <div class="kpi-label">Valuation da Carteira</div>
                <div class="kpi-value">R$ {total_value:,.2f}</div>
                <div class="kpi-diff" style="color: rgba(255,255,255,0.4);">Valor de mercado atual</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_cols[2]:
            color = "#00e676" if net_profit_loss >= 0 else "#ff1744"
            sign = "+" if net_profit_loss >= 0 else ""
            st.markdown(f"""
            <div class="kpi-card" title="Resultado estimado (não realizado) dos ativos comprados em relação ao preço médio de aquisição. Exclui venda a descoberto.">
                <div class="kpi-label">Lucro/Prejuízo Estimado</div>
                <div class="kpi-value" style="color: {color};">{sign}R$ {net_profit_loss:,.2f}</div>
                <div class="kpi-diff" style="color: {color};">{sign}{ret_pct:.2f}% de valorização</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_cols[3]:
            realized_profit = st.session_state.total_realized_profit
            color_r = "#00e676" if realized_profit >= 0 else "#ff1744"
            sign_r = "+" if realized_profit >= 0 else ""
            st.markdown(f"""
            <div class="kpi-card" title="Resultado financeiro líquido de todas as operações fechadas e liquidadas (Day Trade, Swing Trade e FIIs) ao longo do histórico.">
                <div class="kpi-label">Lucro Realizado Histórico</div>
                <div class="kpi-value" style="color: {color_r};">{sign_r}R$ {realized_profit:,.2f}</div>
                <div class="kpi-diff" style="color: {color_r};">Operações encerradas</div>
            </div>
            """, unsafe_allow_html=True)

        # ── Chart: Evolução Patrimonial vs CDI vs IBOV ──
        hist_data = st.session_state.historical_monthly_data
        if hist_data and len(hist_data) >= 1:
            st.markdown("### 📈 Evolução do Patrimônio vs. Benchmarks (IBOV e CDI)")
            st.markdown("<p style='font-size:0.95rem; color:rgba(255,255,255,0.6); margin-top:-0.5rem;'>Evolução percentual acumulada do patrimônio em relação aos aportes, CDI e IBOVESPA alinhados na mesma data inicial de investimento:</p>", unsafe_allow_html=True)
            
            sorted_months = sorted(hist_data.keys())
            first_month_date = sorted_months[0] + "-01"
            last_month_date = datetime.today().strftime("%Y-%m-%d")
            
            col_chart1, col_chart2 = st.columns([4, 1])
            with col_chart2:
                st.markdown("<br>", unsafe_allow_html=True)
                period_opt = st.selectbox("Período do Histórico", ["Histórico Completo", "Últimos 12 Meses"], key="chart_period_opt")
            
            all_tickers = set()
            for m, m_data in hist_data.items():
                for t in m_data["custody"].keys():
                    all_tickers.add(t)
            
            from src.market_data import get_ibov_cdi_history, get_ticker_historical_monthly_closes
            benchmarks = get_ibov_cdi_history(first_month_date, last_month_date)
            closes = get_ticker_historical_monthly_closes(tuple(all_tickers), first_month_date, last_month_date)
            
            months_list = benchmarks["months"]
            
            # Forward-fill gaps
            user_series = {}
            last_valid_state = None
            for m in months_list:
                if m in hist_data:
                    last_valid_state = hist_data[m]
                
                if last_valid_state:
                    custody = last_valid_state["custody"]
                    cash = last_valid_state["cash_balance"]
                    min_cash = last_valid_state["min_cash_balance"]
                    capital = max(0.0, -min_cash)
                    
                    valuation = 0.0
                    for ticker, c in custody.items():
                        qty = c["qty"]
                        if qty > 0:
                            price = closes.get(ticker, {}).get(m, c["avg_price"])
                            valuation += qty * price
                    
                    patrimony = capital + valuation + cash
                    user_series[m] = {
                        "capital": capital,
                        "patrimony": patrimony
                    }
                else:
                    user_series[m] = {
                        "capital": 0.0,
                        "patrimony": 0.0
                    }
            
            portfolio_norm = []
            first_valid_cap = 0.0
            first_valid_pat = 0.0
            for m in months_list:
                state = user_series[m]
                if state["capital"] > 0 and first_valid_cap == 0.0:
                    first_valid_cap = state["capital"]
                    first_valid_pat = state["patrimony"]
                
                if first_valid_cap > 0:
                    relative_growth = (state["patrimony"] / first_valid_pat) * 100.0 if first_valid_pat > 0 else 100.0
                    portfolio_norm.append(round(relative_growth, 2))
                else:
                    portfolio_norm.append(100.0)
            
            # Align IBOV and CDI index lines starting at start_idx
            ibov_norm = []
            cdi_norm = []
            start_idx = 0
            for idx, m in enumerate(months_list):
                if user_series[m]["capital"] > 0:
                    start_idx = idx
                    break
            
            ibov_base = benchmarks["ibov"][start_idx] if start_idx < len(benchmarks["ibov"]) else 100.0
            cdi_base = benchmarks["cdi"][start_idx] if start_idx < len(benchmarks["cdi"]) else 100.0
            
            for idx, m in enumerate(months_list):
                if idx < start_idx:
                    ibov_norm.append(100.0)
                    cdi_norm.append(100.0)
                else:
                    ib_val = (benchmarks["ibov"][idx] / ibov_base) * 100.0 if ibov_base > 0 else 100.0
                    cd_val = (benchmarks["cdi"][idx] / cdi_base) * 100.0 if cdi_base > 0 else 100.0
                    ibov_norm.append(round(ib_val, 2))
                    cdi_norm.append(round(cd_val, 2))
            
            plot_df = pd.DataFrame({
                "Mês": months_list,
                "Minha Carteira (%)": portfolio_norm,
                "IBOV (%)": ibov_norm,
                "CDI (%)": cdi_norm
            })
            
            if period_opt == "Últimos 12 Meses":
                plot_df = plot_df.tail(12)
            
            plot_df = plot_df.set_index("Mês")
            
            with col_chart1:
                st.line_chart(plot_df, use_container_width=True)

        # Assets Table
        st.subheader("📋 Posições Ativas")
        df_pos = pd.DataFrame(pos_rows)
        
        # Format styling for visualization
        df_disp = df_pos.copy()
        df_disp["Custo Total"] = df_disp["Custo Total"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Valor Atual"] = df_disp["Valor Atual"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Lucro/Prejuízo"] = df_disp["Lucro/Prejuízo"].apply(lambda x: f"R$ {x:,.2f}")
        df_disp["Retorno %"] = df_disp["Retorno %"].apply(lambda x: f"{x:.2f}%")
        
        # Centralize text using style and adjust width
        df_styled = df_disp.style.set_properties(**{'text-align': 'center'})
        st.dataframe(df_styled, use_container_width=True, hide_index=True)
        
        # Auto-applied Corporate Actions Informational Panel
        st.subheader("⚡ Eventos Corporativos Aplicados Automaticamente")
        st.markdown("<p style='font-size:0.9rem; color:rgba(255,255,255,0.6); margin-top:-0.5rem;'>Os eventos corporativos e proventos do Yahoo Finance abaixo são aplicados à custódia de forma 100% automatizada e sem necessidade de clique:</p>", unsafe_allow_html=True)
        
        applied_provs = get_proventos(user_id)
        if not applied_provs:
            st.info("Nenhum evento corporativo aplicado até o momento.")
        else:
            recent_provs = sorted(applied_provs, key=lambda x: x["record_date"], reverse=True)[:10]
            for p in recent_provs:
                if p["event_type"] in ("DIVIDENDO", "JCP"):
                    desc = f"R$ {p['amount']:,.2f} recebidos"
                elif p["event_type"] in ("SPLIT", "INPLIT"):
                    desc = f"Desdobramento/Grupamento fator {p['ratio']:.4f}"
                elif p["event_type"] == "BONIFICACAO":
                    desc = f"Bonificação de {p['ratio']*100:.1f}% com custo unitário R$ {p['unit_cost']:.2f}"
                else:
                    desc = f"Evento do tipo {p['event_type']}"
                st.write(f"🔹 **{p['ticker']}**: {p['event_type']} — {desc} em {p['record_date']}")

# ─────────────────────────────────────────
# 2. LANÇAMENTOS (TRANSACTIONS CRUD)
# ─────────────────────────────────────────
elif menu == "📝 Lançamentos":
    st.title("📝 Gestão Manual de Transações & Proventos")
    st.markdown("Adicione, edite ou remova transações manuais ou eventos corporativos de sua carteira.")
    
    # Unified guide expander at the top
    with st.expander("💡 Guia Prático de Lançamentos & Exemplos"):
        st.markdown("""
        ### Como lançar operações e eventos corretamente:
        
        #### 💸 Operações Comuns:
        * **Compra Ordinária**: Selecione `COMPRA`, insira o ticker do ativo (ex: `VALE3`, `MXRF11`), a quantidade e o preço unitário pago.
        * **Venda Ordinária**: Selecione `VENDA`, insira o ticker do ativo, a quantidade vendida e o preço unitário obtido.
        * **Venda a Descoberto (Short)**: Lance uma operação de `VENDA` comum. O sistema identificará que você abriu uma posição vendida automaticamente e calculará o lucro/prejuízo quando você realizar a cobertura (compra).
        * **Opções B3**: Lance com o ticker de 8 caracteres da opção (ex: `PETRE320`) e escolha o tipo de mercado `OPCOES`.
        
        #### 🏛️ Eventos e Proventos:
        * **Dividendos/JCP**: Selecione o evento, insira o ticker e o **valor financeiro total** líquido creditado na conta de proventos.
        * **Desdobramentos (Splits)**: Selecione `SPLIT` e informe o fator de proporção da mudança (ex: se cada ação virou duas, informe `2.0`).
        * **Grupamentos (Inplits)**: Selecione `INPLIT` e informe o fator divisor (ex: se cada dez ações viraram uma, informe `0.10`).
        * **Bonificações**: Selecione `BONIFICACAO`, informe a proporção (ex: 10% de ganho = `0.10`) e o **custo unitário** atribuído pela Receita Federal na data com (disponível no aviso da B3).
        """)

    tab_txs, tab_provs = st.tabs(["💸 Transações de Compra/Venda", "🏛️ Proventos & Eventos Corporativos"])
    
    with tab_txs:
        st.subheader("➕ Inserir Nova Operação Manual")
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            ticker = st.text_input("Ativo (ex: PETR4, MXRF11)", key="add_tx_ticker").upper().strip()
            op_type = st.selectbox("Operação", ["COMPRA", "VENDA"], key="add_tx_op")
            mkt_type = st.selectbox("Tipo de Mercado", ["VISTA", "OPCOES", "BDR", "FII"], key="add_tx_mkt")
        with f_col2:
            qty = st.number_input("Quantidade", min_value=1, step=1, key="add_tx_qty")
            price = st.number_input("Preço Unitário (R$)", min_value=0.01, step=0.01, key="add_tx_price")
            fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, step=0.01, key="add_tx_fees")
        with f_col3:
            trade_date = st.date_input("Data do Pregão", key="add_tx_date")
            broker = st.text_input("Corretora", key="add_tx_broker")
            is_day_trade = st.checkbox("Operação Day Trade?", key="add_tx_dt")
            
        if st.button("Gravar Operação", use_container_width=True, key="btn_save_tx"):
            if not ticker:
                st.error("Digite o código do ativo.")
            else:
                add_transaction(
                    user_id=user_id,
                    ticker=ticker,
                    operation_type=op_type,
                    quantity=qty,
                    price=price,
                    fees=fees,
                    trade_date=trade_date.strftime("%Y-%m-%d"),
                    market_type=mkt_type,
                    broker=broker or "Manual",
                    is_day_trade=1 if is_day_trade else 0
                )
                trigger_rebuild()
                st.rerun()

        # Display transactions list
        st.subheader("📋 Registro de Operações")
        txs = get_transactions(user_id)
        if not txs:
            st.info("Nenhuma operação registrada.")
        else:
            df_txs = pd.DataFrame(txs)
            df_txs_disp = df_txs.copy().drop(columns=["user_id"])
            df_styled = df_txs_disp.style.set_properties(**{'text-align': 'center'})
            st.dataframe(df_styled, use_container_width=True, hide_index=True)
            
            # Row correction and deletion management
            st.markdown("### 🛠️ Corrigir ou Excluir Lançamentos")
            tx_options = {
                f"ID {t['id']} | {t['trade_date']} | {t['ticker']} | {t['operation_type']} ({t['quantity']} a R$ {t['price']:,.2f})": t
                for t in txs
            }
            sel_tx_key = st.selectbox("Selecione a operação para alteração", list(tx_options.keys()), key="sel_tx_alter")
            
            if sel_tx_key:
                selected_tx = tx_options[sel_tx_key]
                
                # Render editing form fields
                st.markdown(f"**Editando Lançamento ID {selected_tx['id']}**")
                e_col1, e_col2, e_col3 = st.columns(3)
                with e_col1:
                    edit_ticker = st.text_input("Ativo", value=selected_tx["ticker"], key=f"e_tx_ticker_{selected_tx['id']}").upper().strip()
                    edit_op = st.selectbox("Operação", ["COMPRA", "VENDA"], index=0 if selected_tx["operation_type"] == "COMPRA" else 1, key=f"e_tx_op_{selected_tx['id']}")
                    edit_mkt = st.selectbox("Tipo de Mercado", ["VISTA", "OPCOES", "BDR", "FII"], index=["VISTA", "OPCOES", "BDR", "FII"].index(selected_tx["market_type"]), key=f"e_tx_mkt_{selected_tx['id']}")
                with e_col2:
                    edit_qty = st.number_input("Quantidade", min_value=1, step=1, value=int(selected_tx["quantity"]), key=f"e_tx_qty_{selected_tx['id']}")
                    edit_price = st.number_input("Preço Unitário (R$)", min_value=0.01, step=0.01, value=float(selected_tx["price"]), key=f"e_tx_price_{selected_tx['id']}")
                    edit_fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, step=0.01, value=float(selected_tx["fees"]), key=f"e_tx_fees_{selected_tx['id']}")
                with e_col3:
                    try:
                        parsed_date = datetime.strptime(selected_tx["trade_date"], "%Y-%m-%d")
                    except Exception:
                        parsed_date = datetime.today()
                    edit_date = st.date_input("Data do Pregão", value=parsed_date, key=f"e_tx_date_{selected_tx['id']}")
                    edit_broker = st.text_input("Corretora", value=selected_tx["broker"], key=f"e_tx_broker_{selected_tx['id']}")
                    edit_dt = st.checkbox("Operação Day Trade?", value=bool(selected_tx["is_day_trade"]), key=f"e_tx_dt_{selected_tx['id']}")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Salvar Alterações", use_container_width=True, key=f"btn_edit_save_{selected_tx['id']}", type="primary"):
                        update_transaction(
                            user_id=user_id,
                            tx_id=selected_tx["id"],
                            ticker=edit_ticker,
                            operation_type=edit_op,
                            quantity=edit_qty,
                            price=edit_price,
                            fees=edit_fees,
                            trade_date=edit_date.strftime("%Y-%m-%d"),
                            market_type=edit_mkt,
                            broker=edit_broker,
                            is_day_trade=1 if edit_dt else 0
                        )
                        trigger_rebuild()
                        st.rerun()
                with col_btn2:
                    if st.button("🗑️ Excluir Registro", use_container_width=True, key=f"btn_edit_del_{selected_tx['id']}"):
                        delete_transaction(user_id, selected_tx["id"])
                        trigger_rebuild()
                        st.rerun()
                        
    with tab_provs:
        st.subheader("➕ Inserir Novo Evento Corporativo Manual")
        e_col1, e_col2, e_col3 = st.columns(3)
        with e_col1:
            e_ticker = st.text_input("Ativo (ex: PETR4, MXRF11)", key="add_e_ticker").upper().strip()
            e_type = st.selectbox("Evento", ["DIVIDENDO", "JCP", "BONIFICACAO", "SPLIT", "INPLIT"], key="add_e_type")
            e_amount = st.number_input("Valor Recebido (Total R$) / Qtd Bonif.", min_value=0.0, step=0.01, key="add_e_amount")
        with e_col2:
            e_record_date = st.date_input("Data com/registro", key="add_e_date")
            e_ratio = st.number_input("Proporção / Fator multiplicador (para Splits/Bonif)", min_value=0.0, value=1.0, step=0.0001, key="add_e_ratio")
        with e_col3:
            e_unit_cost = st.number_input("Custo Unitário da Bonificação", min_value=0.0, step=0.01, key="add_e_unit")
            
        if st.button("Gravar Evento", use_container_width=True, key="btn_save_prov"):
            if not e_ticker:
                st.error("Digite o código do ativo.")
            else:
                add_provento(
                    user_id=user_id,
                    ticker=e_ticker,
                    event_type=e_type,
                    amount=e_amount,
                    record_date=e_record_date.strftime("%Y-%m-%d"),
                    ratio=e_ratio,
                    unit_cost=e_unit_cost
                )
                trigger_rebuild()
                st.rerun()

        # Display proventos list
        st.subheader("📋 Registro de Eventos e Proventos")
        provs = get_proventos(user_id)
        if not provs:
            st.info("Nenhum evento corporativo registrado.")
        else:
            df_provs = pd.DataFrame(provs)
            df_provs_disp = df_provs.copy().drop(columns=["user_id"])
            df_styled_p = df_provs_disp.style.set_properties(**{'text-align': 'center'})
            st.dataframe(df_styled_p, use_container_width=True, hide_index=True)
            
            # Row correction and deletion management for proventos
            st.markdown("### 🛠️ Corrigir ou Excluir Eventos")
            prov_options = {
                f"ID {p['id']} | {p['record_date']} | {p['ticker']} | {p['event_type']}": p
                for p in provs
            }
            sel_prov_key = st.selectbox("Selecione o evento para alteração", list(prov_options.keys()), key="sel_prov_alter")
            
            if sel_prov_key:
                selected_prov = prov_options[sel_prov_key]
                
                st.markdown(f"**Editando Evento ID {selected_prov['id']}**")
                edit_col1, edit_col2, edit_col3 = st.columns(3)
                with edit_col1:
                    e_edit_ticker = st.text_input("Ativo", value=selected_prov["ticker"], key=f"e_prov_ticker_{selected_prov['id']}").upper().strip()
                    e_edit_type = st.selectbox("Evento", ["DIVIDENDO", "JCP", "BONIFICACAO", "SPLIT", "INPLIT"], index=["DIVIDENDO", "JCP", "BONIFICACAO", "SPLIT", "INPLIT"].index(selected_prov["event_type"]), key=f"e_prov_type_{selected_prov['id']}")
                    e_edit_amount = st.number_input("Valor Recebido (Total R$) / Qtd Bonif.", min_value=0.0, step=0.01, value=float(selected_prov["amount"]), key=f"e_prov_amount_{selected_prov['id']}")
                with edit_col2:
                    try:
                        p_parsed_date = datetime.strptime(selected_prov["record_date"], "%Y-%m-%d")
                    except Exception:
                        p_parsed_date = datetime.today()
                    e_edit_date = st.date_input("Data com/registro", value=p_parsed_date, key=f"e_prov_date_{selected_prov['id']}")
                    e_edit_ratio = st.number_input("Proporção / Fator multiplicador", min_value=0.0, step=0.0001, value=float(selected_prov["ratio"]), key=f"e_prov_ratio_{selected_prov['id']}")
                with edit_col3:
                    e_edit_unit = st.number_input("Custo Unitário da Bonificação", min_value=0.0, step=0.01, value=float(selected_prov["unit_cost"]), key=f"e_prov_unit_{selected_prov['id']}")
                
                col_ebtn1, col_ebtn2 = st.columns(2)
                with col_ebtn1:
                    if st.button("💾 Salvar Alterações", use_container_width=True, key=f"btn_edit_prov_save_{selected_prov['id']}", type="primary"):
                        update_provento(
                            user_id=user_id,
                            prov_id=selected_prov["id"],
                            ticker=e_edit_ticker,
                            event_type=e_edit_type,
                            amount=e_edit_amount,
                            record_date=e_edit_date.strftime("%Y-%m-%d"),
                            ratio=e_edit_ratio,
                            unit_cost=e_edit_unit
                        )
                        trigger_rebuild()
                        st.rerun()
                with col_ebtn2:
                    if st.button("🗑️ Excluir Evento", use_container_width=True, key=f"btn_edit_prov_del_{selected_prov['id']}"):
                        delete_provento(user_id, selected_prov["id"])
                        trigger_rebuild()
                        st.rerun()er=ticker,
                        event_type=event_type,
                        amount=amount,
                        record_date=record_date.strftime("%Y-%m-%d"),
                        ratio=ratio,
                        unit_cost=unit_cost
                    )
                    trigger_rebuild()
                    st.rerun()

        st.subheader("📋 Registro de Eventos e Proventos")
        provs = get_proventos(user_id)
        if not provs:
            st.info("Nenhum evento corporativo registrado.")
        else:
            df_provs = pd.DataFrame(provs)
            df_provs_disp = df_provs.copy().drop(columns=["user_id"])
            st.dataframe(df_provs_disp, use_container_width=True, hide_index=True)

            st.markdown("### 🗑️ Excluir Evento")
            del_p_id = st.number_input("ID do Evento para Exclusão", min_value=1, step=1)
            if st.button("Excluir Evento", type="primary"):
                delete_provento(user_id, del_p_id)
                trigger_rebuild()
                st.rerun()

# ─────────────────────────────────────────
# 3. UPLOAD NOTAS PDF (SINACOR PARSER)
# ─────────────────────────────────────────
elif menu == "📂 Upload Notas PDF":
    st.title("📂 Processamento Automatizado de Notas de Corretagem")
    st.markdown("Carregue suas Notas de Corretagem no padrão B3 / Sinacor em formato PDF para importação automatizada.")
    
    uploaded_files = st.file_uploader("Selecione um ou mais PDFs de notas de corretagem", type="pdf", accept_multiple_files=True)
    
    if uploaded_files:
        st.subheader("🔍 Pré-visualização dos dados extraídos")
        
        parsed_notes = []
        for f in uploaded_files:
            # Parse note content
            note_data = parse_sinacor_pdf(f)
            if note_data:
                parsed_notes.append((f.name, note_data))
                st.write(f"📄 **Nota nº {note_data['note_number']}** ({note_data['broker']}) — Pregão: **{note_data['trade_date']}**")
                
                # Show parsed transactions
                df_parsed_t = pd.DataFrame(note_data["transactions"])
                if not df_parsed_t.empty:
                    df_parsed_t["fees"] = df_parsed_t["fees"].apply(lambda x: f"R$ {x:.2f}")
                    df_parsed_t["price"] = df_parsed_t["price"].apply(lambda x: f"R$ {x:.2f}")
                    df_parsed_t["total"] = df_parsed_t["total"].apply(lambda x: f"R$ {x:.2f}")
                    df_styled_u = df_parsed_t.style.set_properties(**{'text-align': 'center'})
                    st.dataframe(df_styled_u, use_container_width=True, hide_index=True)
                else:
                    st.warning("Nenhuma transação identificada na nota.")
                st.markdown("---")
            else:
                st.error(f"Não foi possível extrair dados estruturados de {f.name}.")
                
        if parsed_notes:
            if st.button("📥 Salvar Todas as Transações no Banco de Dados", use_container_width=True):
                success_count = 0
                for fname, nd in parsed_notes:
                    for t in nd["transactions"]:
                        add_transaction(
                            user_id=user_id,
                            ticker=t["ticker"],
                            operation_type=t["operation_type"],
                            quantity=t["quantity"],
                            price=t["price"],
                            fees=t["fees"],
                            trade_date=nd["trade_date"],
                            market_type=t["market_type"],
                            note_number=nd["note_number"],
                            broker=nd["broker"],
                            is_day_trade=0 # Calculated dynamically during portfolio rebuilding
                        )
                        success_count += 1
                
                # Recalculate portfolio calculations immediately
                trigger_rebuild()
                st.success(f"{success_count} operações importadas com sucesso!")
                st.rerun()

# ─────────────────────────────────────────
# 4. APURAÇÃO DE IR (MONTHLY TAX / DARF)
# ─────────────────────────────────────────
elif menu == "🧮 Apuração de IR":
    st.title("🧮 Demonstrativo Mensal e Apuração de DARF")
    st.markdown("Acompanhe o volume de vendas, lucros isentos, prejuízos compensados e guias DARF calculadas.")
    
    darfs = get_darfs(user_id)
    losses = get_losses_carryover(user_id)
    
    if not darfs:
        st.info("Nenhuma apuração tributária gerada ainda. Registre operações em 'Lançamentos' para ver impostos.")
    else:
        # Month selector dropdown
        months = [d["month"] for d in darfs]
        selected_month = st.selectbox("Selecione o mês de competência", months)
        
        darf_info = next(d for d in darfs if d["month"] == selected_month)
        loss_info = next((l for l in losses if l["month"] == selected_month), {"common_loss": 0, "day_trade_loss": 0, "fii_loss": 0})
        
        # Details layout
        st.markdown(f"## Competência: {selected_month}")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("#### 📦 Volume de Vendas")
            st.write(f"🔹 Operações Comuns: **R$ {darf_info['swing_trade_sales']:.2f}**")
            st.write(f"🔹 Fundos Imobiliários: **R$ {darf_info['fii_sales']:.2f}**")
            
        with c2:
            st.markdown("#### 💰 Resultado Líquido")
            st.write(f"🔹 Lucro Comum: **R$ {darf_info['swing_trade_profit']:.2f}**")
            st.write(f"🔹 Lucro Day Trade: **R$ {darf_info['day_trade_profit']:.2f}**")
            st.write(f"🔹 Lucro FII: **R$ {darf_info['fii_profit']:.2f}**")
            
        with c3:
            st.markdown("#### 📉 Prejuízo Acumulado (Próximo Mês)")
            st.write(f"🔹 Swing Trade (Comum): **R$ {loss_info['common_loss']:.2f}**")
            st.write(f"🔹 Day Trade: **R$ {loss_info['day_trade_loss']:.2f}**")
            st.write(f"🔹 Fundos Imobiliários: **R$ {loss_info['fii_loss']:.2f}**")

        st.markdown("---")
        
        # DARF guidance details
        st.subheader("💵 Imposto Devido (DARF)")
        
        tax_due = darf_info["tax_due"]
        if tax_due <= 0.0:
            st.success("🎉 Não há imposto a pagar para este mês.")
        else:
            st.warning(f"⚠️ DARF calculada para pagamento: **R$ {tax_due:.2f}** (IRRF dedo-duro abatido: R$ {darf_info['irrf_dedo_duro']:.2f})")
            
            # Print DARF Details fields
            st.markdown(f"""
            <div class="kpi-card" style="max-width: 500px;">
                <h3 style="margin-top:0; color:#7c4dff;">Guia DARF de Pagamento</h3>
                <table style="width:100%; border:none;">
                    <tr><td><b>Código da Receita:</b></td><td>6015 (Pessoa Física B3)</td></tr>
                    <tr><td><b>Mês de Referência:</b></td><td>{selected_month}</td></tr>
                    <tr><td><b>Valor Total:</b></td><td>R$ {tax_due:.2f}</td></tr>
                    <tr><td><b>Vencimento Limite:</b></td><td>Último dia útil do mês subsequente</td></tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
            
            # Payment toggler
            is_paid = darf_info["paid"]
            if is_paid:
                st.success("✅ Esta DARF foi marcada como PAGA.")
                if st.button("Marcar como Não Paga"):
                    set_darf_paid_status(user_id, selected_month, 0)
                    trigger_rebuild()
                    st.rerun()
            else:
                if st.button("Confirmar Pagamento da DARF"):
                    set_darf_paid_status(user_id, selected_month, 1)
                    trigger_rebuild()
                    st.rerun()

# ─────────────────────────────────────────
# 5. DECLARAÇÃO IRPF (ANNUAL DECLARATION)
# ─────────────────────────────────────────
elif menu == "📅 Declaração IRPF":
    st.title("📅 Auxiliar para Declaração Anual de IRPF")
    st.markdown("Dados consolidados para preenchimento fácil da declaração de ajuste anual do Imposto de Renda.")
    
    darfs = get_darfs(user_id)
    if not darfs:
        st.info("Nenhuma transação para consolidar relatórios anuais.")
    else:
        # Extract years from database months
        years = sorted(list(set([d["month"][:4] for d in darfs])))
        selected_year = st.selectbox("Selecione o ano fiscal", years)
        
        # 1. Bens e Direitos (Assets custody on 31/12)
        st.subheader("💼 Ficha de Bens e Direitos (B3)")
        st.markdown(f"Custódia em **31/12/{selected_year}** com quantidade e custo médio histórico (com taxas inclusas).")
        
        cust = get_custody(user_id)
        if not cust:
            st.info("Nenhum ativo em custódia no final do ano.")
        else:
            cust_rows = []
            for c in cust:
                ticker = c["ticker"]
                qty = c["quantity"]
                avg_p = c["average_price"]
                cost_basis = qty * avg_p
                
                # FII mapping or stocks group codes
                group_code = "03 (Participações societárias)" if c["market_type"] != "FII" else "07 (Fundos)"
                
                cust_rows.append({
                    "Código": group_code,
                    "Ativo": ticker,
                    "Quantidade": qty,
                    "Preço Médio": f"R$ {avg_p:,.2f}",
                    "Situação em 31/12 (Custo Total)": f"R$ {cost_basis:,.2f}"
                })
            df_styled_c = pd.DataFrame(cust_rows).style.set_properties(**{'text-align': 'center'})
            st.dataframe(df_styled_c, use_container_width=True, hide_index=True)
            
        st.markdown("---")
        
        # 2. Resumo Mensal para Ficha de Renda Variável
        st.subheader("📊 Ficha de Renda Variável (Operações Comuns / Day Trade)")
        st.markdown(f"Consolidação mensal de resultados líquidos do ano de **{selected_year}**:")
        
        year_darfs = [d for d in darfs if d["month"].startswith(selected_year)]
        
        var_rows = []
        for y_d in year_darfs:
            month = y_d["month"]
            
            var_rows.append({
                "Mês": month,
                "Resultado Comum (R$)": y_d["swing_trade_profit"],
                "Resultado Day Trade (R$)": y_d["day_trade_profit"],
                "Resultado FII (R$)": y_d["fii_profit"],
                "Dedo-Duro Retido (R$)": y_d["irrf_dedo_duro"],
                "Imposto Devido (R$)": y_d["tax_due"],
                "DARF Paga": "Sim" if y_d["paid"] else "Não"
            })
            
        if var_rows:
            df_styled_v = pd.DataFrame(var_rows).style.set_properties(**{'text-align': 'center'})
            st.dataframe(df_styled_v, use_container_width=True, hide_index=True)
        else:
            st.info(f"Nenhuma apuração mensal disponível para o ano fiscal {selected_year}.")
