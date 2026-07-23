import re
import pdfplumber
from datetime import datetime

def clean_number(val_str: str) -> float:
    """Convert Brazilian number format (e.g. 1.250,50 or 25,40) to float."""
    if not val_str:
        return 0.0
    val_str = val_str.replace(".", "").replace(",", ".").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def clean_qty(qty_str: str) -> int:
    """Convert quantity string to integer."""
    if not qty_str:
        return 0
    qty_str = qty_str.replace(".", "").replace(",", "").strip()
    try:
        return int(qty_str)
    except ValueError:
        return 0

def parse_sinacor_pdf(pdf_file_path_or_bytes) -> dict | None:
    """
    Parses a B3 Sinacor standard PDF brokerage note.
    Supports file path (str) or file bytes (uploaded file).
    
    Returns a dict with:
      - note_number: str
      - trade_date: str (YYYY-MM-DD)
      - broker: str
      - transactions: list of dicts
      - total_fees: float
      - irrf: float
    """
    full_text = ""
    try:
        if isinstance(pdf_file_path_or_bytes, (str, bytes)) or hasattr(pdf_file_path_or_bytes, "read"):
            with pdfplumber.open(pdf_file_path_or_bytes) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
        else:
            return None
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return None

    if not full_text:
        return None

    # 1. Parse Metadata (Date, Note Number, Broker)
    trade_date = None
    note_number = None
    broker = "B3 Broker"

    # Search for trade date (Data Pregão: DD/MM/YYYY or similar)
    date_matches = re.findall(r'(?:data\s+preg[ãa]o|data\s+do\s+preg[ãa]o|preg[ãa]o)[:\s]+(\d{2}/\d{2}/\d{4})', full_text, re.IGNORECASE)
    if date_matches:
        trade_date = datetime.strptime(date_matches[0], "%d/%m/%Y").strftime("%Y-%m-%d")
    else:
        # Fallback date search
        date_fallback = re.findall(r'\b(\d{2}/\d{2}/\d{4})\b', full_text)
        if date_fallback:
            trade_date = datetime.strptime(date_fallback[0], "%d/%m/%Y").strftime("%Y-%m-%d")

    # Search for note number
    note_matches = re.findall(r'(?:n[oºu]\.?\s+nota|nr\.\s+nota|nota|n[ºo]\s+da\s+nota)[:\s]+(\d+[\d\s]*)', full_text, re.IGNORECASE)
    if note_matches:
        note_number = note_matches[0].replace(" ", "").strip()
    else:
        # Fallback note number
        note_fallback = re.findall(r'\bFolha\s+\d+/\d+\s+(\d+)\b', full_text, re.IGNORECASE)
        if note_fallback:
            note_number = note_fallback[0].strip()

    # Search for Broker Name / CNPJ
    # Standard brokers list to search in header
    brokers_list = ["CLEAR", "XP INVESTIMENTOS", "RICO", "GENIAL", "BTG PACTUAL", "INTER DTVM", "NU INVEST", "EASYINVEST"]
    for b in brokers_list:
        if b in full_text.upper():
            broker = b.title()
            break

    # 2. Parse Transactions
    transactions = []
    
    # Sinacor row pattern:
    # 1-BOVESPA C VISTA TICKER DESCRIPTION QTY PRICE TOTAL D/C
    # Let's search line by line
    lines = full_text.split("\n")
    
    # Broad regex to capture transaction rows
    # Group 1: C/V
    # Group 2: Market type (VISTA, FRACIONARIO, OPCAO, etc.)
    # Group 3: Ticker (4 letters + 1-2 digits, or Options ticker)
    # Group 4: Quantity (e.g. 100 or 1.000)
    # Group 5: Price (e.g. 25,40 or 2.540,00)
    # Group 6: Total (e.g. 2.540,00)
    # Group 7: D/C
    row_pattern = re.compile(
        r'\b([CV])\s+(VISTA|FRACIONARIO|OP[CÇ][AÃ]O|EXERC[IÍ]CIO)\s+([A-Z]{4}\d{1,2}|[A-Z]{5}\d{3})\b.*?(\d+[\d\.]*)\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+([DC])',
        re.IGNORECASE
    )

    for line in lines:
        match = row_pattern.search(line)
        if match:
            op_type = "COMPRA" if match.group(1).upper() == "C" else "VENDA"
            mkt_type_raw = match.group(2).upper()
            
            # Map market type to our standard: 'VISTA', 'OPCOES', 'BDR', 'FII'
            ticker = match.group(3).upper()
            qty = clean_qty(match.group(4))
            price = clean_number(match.group(5))
            total = clean_number(match.group(6))
            dc = match.group(7).upper()

            # Determine standard market type
            # FIIs usually end in 11 and contain FII in name, let's check standard rule:
            # 11 can be FII, BDR (like AAPL34 or similar BDRs end in 34, but some ETFs end in 11).
            # A simple fallback: if ends in 11, we can check a common list or default to VISTA
            # (FII is handled under VISTA rules in yfinance, but tax-wise we need to separate FII).
            # We can identify FII if the name contains "FII" or by typical FII tickers.
            # Let's do a basic ticker classification:
            # Known ETFs that end in 11 but are NOT FIIs
            ETFS_NOT_FII = {
                'BOVA11', 'IVVB11', 'SMAL11', 'HASH11', 'QBTC11', 'QETH11',
                'DIVO11', 'BOVV11', 'PIBB11', 'BRAX11', 'ECOO11', 'FIND11',
                'GOVE11', 'ISUS11', 'MATB11', 'IMAB11', 'FIXA11', 'IRFM11',
                'SMAC11', 'GOLD11', 'SPXI11', 'NASD11', 'EURP11', 'ACWI11',
                'XINA11', 'TECK11', '5GTK11', 'JOGO11', 'GURU11', 'SHOT11',
            }
            if ticker.endswith("11") and ticker not in ETFS_NOT_FII:
                # Tickers ending in 11 are almost always FIIs
                # (ETFs ending in 11 are explicitly excluded above)
                mkt_type = "FII"
            elif ticker.endswith("34") or ticker.endswith("35") or ticker.endswith("39"):
                mkt_type = "BDR"
            elif len(ticker) >= 7:  # e.g. PETRH320 (options)
                mkt_type = "OPCOES"
            elif "OPC" in mkt_type_raw:
                mkt_type = "OPCOES"
            else:
                mkt_type = "VISTA"

            transactions.append({
                "ticker": ticker,
                "operation_type": op_type,
                "quantity": qty,
                "price": price,
                "total": total,
                "market_type": mkt_type,
                "dc": dc
            })

    # 3. Parse Financial Costs (Taxas/Custos)
    # Emolumentos
    emol = 0.0
    emol_match = re.search(r'(?:emolumentos|taxa\s+de\s+emolumentos)[:\s]+(\d+,\d{2})', full_text, re.IGNORECASE)
    if emol_match:
        emol = clean_number(emol_match.group(1))

    # Taxa de liquidação
    liq = 0.0
    liq_match = re.search(r'(?:taxa\s+de\s+liquida[cç][aã]o)[:\s]+(\d+,\d{2})', full_text, re.IGNORECASE)
    if liq_match:
        liq = clean_number(liq_match.group(1))

    # Corretagem
    corr = 0.0
    corr_match = re.search(r'(?:corretagem|taxa\s+operacional)[:\s]+(\d+,\d{2})', full_text, re.IGNORECASE)
    if corr_match:
        corr = clean_number(corr_match.group(1))

    # IRRF (Dedo-Duro)
    irrf = 0.0
    irrf_match = re.search(r'(?:i\.r\.r\.f\.\s+s/\s+opera[cç][oõ]es|irrf|irrf\s+opera[cç][oõ]es)[:\s]+(\d+,\d{2})', full_text, re.IGNORECASE)
    if irrf_match:
        irrf = clean_number(irrf_match.group(1))

    total_fees = emol + liq + corr

    # 4. Proportional Fee Allocation
    # Sum of all transaction values
    total_val = sum(t["total"] for t in transactions)
    if total_val > 0:
        for t in transactions:
            t["fees"] = round((t["total"] / total_val) * total_fees, 2)
    else:
        for t in transactions:
            t["fees"] = 0.0

    return {
        "note_number": note_number or "N/A",
        "trade_date": trade_date or datetime.today().strftime("%Y-%m-%d"),
        "broker": broker,
        "transactions": transactions,
        "total_fees": round(total_fees, 2),
        "irrf": round(irrf, 2)
    }
