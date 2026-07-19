import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def format_yf_ticker(ticker: str) -> str:
    """Format ticker for Yahoo Finance (Brazilian stocks end in .SA)."""
    ticker = ticker.upper().strip()
    if ".SA" in ticker:
        return ticker
    # Options usually have 8 characters (e.g. PETRI240), we don't query them on yf
    if len(ticker) in [5, 6]:
        return f"{ticker}.SA"
    return ticker

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
