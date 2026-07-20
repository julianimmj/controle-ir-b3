import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

def format_yf_ticker(ticker: str) -> str:
    """Format ticker for Yahoo Finance (Brazilian stocks end in .SA)."""
    ticker = ticker.upper().strip()
    if ".SA" in ticker:
        return ticker
    # Options usually have 8 characters (e.g. PETRI240), we don't query them on yf
    if len(ticker) in [5, 6]:
        return f"{ticker}.SA"
    return ticker

@st.cache_data(ttl=900)
def get_current_prices(tickers: list[str]) -> dict:
    """
    Fetch the latest close price for a list of B3 tickers using yfinance.
    Returns a dictionary of ticker -> price.
    """
    prices = {}
    if not tickers:
        return prices

    # Format tickers
    yf_tickers = [format_yf_ticker(t) for t in tickers]
    # Filter out options (usually len != 5/6 and does not contain .SA)
    valid_tickers = [t for t in yf_tickers if ".SA" in t]

    if not valid_tickers:
        return prices

    try:
        # Download 5 days of data to handle weekends/holidays reliably
        data = yf.download(valid_tickers, period="5d", group_by="ticker", progress=False)
        
        for t in tickers:
            yf_t = format_yf_ticker(t)
            if yf_t not in valid_tickers:
                prices[t] = 0.0 # Option or invalid
                continue
                
            try:
                # Handle single vs multiple tickers structure in yfinance output
                if len(valid_tickers) == 1:
                    ticker_data = data
                else:
                    ticker_data = data[yf_t]
                
                # Get the last non-null close price
                close_series = ticker_data['Close'].dropna()
                if not close_series.empty:
                    prices[t] = float(close_series.iloc[-1])
                else:
                    prices[t] = 0.0
            except Exception:
                prices[t] = 0.0
    except Exception as e:
        print(f"Error fetching prices: {e}")
        # Fallback to single fetch
        for t in tickers:
            yf_t = format_yf_ticker(t)
            if ".SA" in yf_t:
                try:
                    ticker_obj = yf.Ticker(yf_t)
                    hist = ticker_obj.history(period="5d")
                    if not hist.empty:
                        prices[t] = float(hist['Close'].dropna().iloc[-1])
                    else:
                        prices[t] = 0.0
                except Exception:
                    prices[t] = 0.0
            else:
                prices[t] = 0.0

    return prices

@st.cache_data(ttl=3600)
def suggest_corporate_events(ticker: str, start_date: str) -> list[dict]:
    """
    Fetch corporate actions (dividends and splits) from yfinance for a ticker
    since start_date. Returns a list of dicts representing suggested actions.
    """
    events = []
    yf_ticker = format_yf_ticker(ticker)
    if ".SA" not in yf_ticker:
        return events

    try:
        tk = yf.Ticker(yf_ticker)
        # Dividends
        divs = tk.dividends
        if not divs.empty:
            divs = divs[divs.index >= start_date]
            for date, val in divs.items():
                events.append({
                    "ticker": ticker,
                    "event_type": "DIVIDENDO",
                    "amount": float(val),
                    "record_date": date.strftime("%Y-%m-%d"),
                    "ratio": 1.0,
                    "unit_cost": 0.0,
                    "description": f"Dividendo/JCP de R$ {val:.4f} por cota"
                })
        
        # Splits/Consolidations
        splits = tk.splits
        if not splits.empty:
            splits = splits[splits.index >= start_date]
            for date, ratio in splits.items():
                event_type = "SPLIT" if ratio > 1.0 else "INPLIT"
                events.append({
                    "ticker": ticker,
                    "event_type": event_type,
                    "amount": 0.0,
                    "record_date": date.strftime("%Y-%m-%d"),
                    "ratio": float(ratio),
                    "unit_cost": 0.0,
                    "description": f"Desdobramento/Grupamento de {ratio:.4f}"
                })
    except Exception as e:
        print(f"Error fetching corporate actions for {ticker}: {e}")

    return events

@st.cache_data(ttl=86400)
def get_ibov_cdi_history(start_date_str: str, end_date_str: str) -> dict:
    """
    Fetch monthly IBOVESPA index and CDI accumulated values between start_date and end_date.
    Returns a dict with 'months' list, 'ibov' list (normalized to 100), and 'cdi' list (normalized to 100).
    """
    import urllib.request
    import json
    
    # 1. Parse start and end dates
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    except Exception:
        start_date = datetime.today() - timedelta(days=365)
        end_date = datetime.today()

    # Generate list of YYYY-MM months
    months = []
    curr = datetime(start_date.year, start_date.month, 1)
    target_end = datetime(end_date.year, end_date.month, 1)
    while curr <= target_end:
        months.append(curr.strftime("%Y-%m"))
        # advance 32 days and reset to day 1 to move to next month safely
        next_m = curr + timedelta(days=32)
        curr = datetime(next_m.year, next_m.month, 1)

    if not months:
        months = [datetime.today().strftime("%Y-%m")]

    # 2. Fetch IBOVESPA (^BVSP) monthly close
    ibov_prices = {}
    try:
        # Download data slightly before start_date to ensure we get a baseline price
        hist_start = (start_date - timedelta(days=60)).strftime("%Y-%m-%d")
        data = yf.download("^BVSP", start=hist_start, end=(end_date + timedelta(days=5)).strftime("%Y-%m-%d"), interval="1mo", progress=False)
        if not data.empty:
            for timestamp, row in data.iterrows():
                m_str = timestamp.strftime("%Y-%m")
                close_val = float(row['Close']) if 'Close' in row else float(row['Close'].iloc[0])
                ibov_prices[m_str] = close_val
    except Exception as e:
        print(f"Error downloading IBOV data: {e}")

    # 3. Fetch CDI accumulated monthly rate from BCB API (Series 4391)
    cdi_monthly_rates = {}
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados?formato=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode())
            for item in res_data:
                # BCB date format is dd/mm/yyyy
                raw_date = item['data']
                rate_val = float(item['valor']) / 100.0 # convert percentage to decimal
                try:
                    dt = datetime.strptime(raw_date, "%d/%m/%Y")
                    m_str = dt.strftime("%Y-%m")
                    cdi_monthly_rates[m_str] = rate_val
                except Exception:
                    continue
    except Exception as e:
        print(f"Error fetching CDI from BCB: {e}. Using fallback rates.")

    # 4. Construct normalized historical values starting at 100.0
    ibov_normalized = []
    cdi_normalized = []
    
    # Base baseline values
    first_month = months[0]
    first_ibov_price = ibov_prices.get(first_month, 120000.0) # default fallback if not found
    
    curr_ibov_norm = 100.0
    curr_cdi_norm = 100.0
    
    last_ibov_price = first_ibov_price
    
    for i, m in enumerate(months):
        if i == 0:
            ibov_normalized.append(100.0)
            cdi_normalized.append(100.0)
        else:
            # Calculate IBOV relative change
            price_today = ibov_prices.get(m, last_ibov_price)
            change = (price_today / last_ibov_price) if last_ibov_price > 0 else 1.0
            curr_ibov_norm = curr_ibov_norm * change
            ibov_normalized.append(round(curr_ibov_norm, 2))
            last_ibov_price = price_today
            
            # Calculate CDI accumulated growth
            # Fallback to monthly 0.85% (about 10.7% a.y.) if API failed or month not found
            rate = cdi_monthly_rates.get(m, 0.0085)
            curr_cdi_norm = curr_cdi_norm * (1.0 + rate)
            cdi_normalized.append(round(curr_cdi_norm, 2))

    return {
        "months": months,
        "ibov": ibov_normalized,
        "cdi": cdi_normalized
    }

@st.cache_data(ttl=86400)
def get_ticker_historical_monthly_closes(tickers: tuple, start_date_str: str, end_date_str: str) -> dict:
    """
    Fetch monthly closes for a list of tickers between start_date and end_date.
    Returns a dict: ticker -> { YYYY-MM -> float }
    """
    closes = {}
    if not tickers:
        return closes

    # Format dates
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d") - timedelta(days=60) # buffer
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=5)
        start_fmt = start_date.strftime("%Y-%m-%d")
        end_fmt = end_date.strftime("%Y-%m-%d")
    except Exception:
        start_fmt = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")
        end_fmt = datetime.today().strftime("%Y-%m-%d")

    for t in tickers:
        closes[t] = {}
        # Ignore custom codes or short option names
        if len(t) > 7 or any(c.isdigit() for c in t) and not t.endswith('3') and not t.endswith('4') and not t.endswith('11') and not t.endswith('34'):
            # Probably an option or something invalid for standard monthly yahoo quotes
            continue
            
        yf_ticker = f"{t}.SA"
        try:
            data = yf.download(yf_ticker, start=start_fmt, end=end_fmt, interval="1mo", progress=False)
            if not data.empty:
                for timestamp, row in data.iterrows():
                    m_str = timestamp.strftime("%Y-%m")
                    close_val = float(row['Close']) if 'Close' in row else float(row['Close'].iloc[0])
                    closes[t][m_str] = close_val
        except Exception as e:
            print(f"Error downloading history for {t}: {e}")

    return closes

