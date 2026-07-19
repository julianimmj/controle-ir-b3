import sqlite3
import os
import hashlib
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "db.sqlite")

def get_connection():
    """Get connection to the SQLite database. Ensures directories exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Create all tables in database if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Transactions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        operation_type TEXT NOT NULL, -- 'COMPRA' / 'VENDA'
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        fees REAL DEFAULT 0.0,
        trade_date TEXT NOT NULL, -- 'YYYY-MM-DD'
        market_type TEXT NOT NULL, -- 'VISTA', 'OPCOES', 'BDR', 'FII'
        note_number TEXT,
        broker TEXT,
        is_day_trade INTEGER DEFAULT 0, -- 0 = Swing, 1 = Day Trade
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Custody Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custody (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        average_price REAL NOT NULL,
        market_type TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, ticker)
    );
    """)

    # Proventos (Dividends, JCP, splits, bonifications) Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        ticker TEXT NOT NULL,
        event_type TEXT NOT NULL, -- 'DIVIDENDO', 'JCP', 'BONIFICACAO', 'SPLIT', 'INPLIT'
        amount REAL DEFAULT 0.0, -- Total cash paid or bonus qty
        record_date TEXT NOT NULL, -- 'YYYY-MM-DD'
        ratio REAL DEFAULT 1.0, -- split/inplit ratio or bonification ratio
        unit_cost REAL DEFAULT 0.0, -- bonus cost basis
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Loss Carryover (prejuízos acumulados) Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS loss_carryover (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        month TEXT NOT NULL, -- 'YYYY-MM'
        common_loss REAL DEFAULT 0.0,
        day_trade_loss REAL DEFAULT 0.0,
        fii_loss REAL DEFAULT 0.0,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, month)
    );
    """)

    # DARFs & Monthly Tax Reports Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS darfs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        month TEXT NOT NULL, -- 'YYYY-MM'
        swing_trade_sales REAL DEFAULT 0.0,
        day_trade_sales REAL DEFAULT 0.0,
        fii_sales REAL DEFAULT 0.0,
        swing_trade_profit REAL DEFAULT 0.0,
        day_trade_profit REAL DEFAULT 0.0,
        fii_profit REAL DEFAULT 0.0,
        tax_due REAL DEFAULT 0.0,
        irrf_dedo_duro REAL DEFAULT 0.0,
        paid INTEGER DEFAULT 0, -- 0 = Unpaid, 1 = Paid
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, month)
    );
    """)

    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# Security & Hashing Helpers
# ─────────────────────────────────────────

def hash_password(password: str, salt: str) -> str:
    """Return pbkdf2 hash of password."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()

def generate_salt() -> str:
    """Generate dynamic salt."""
    return os.urandom(16).hex()

# ─────────────────────────────────────────
# User CRUD & Authentication
# ─────────────────────────────────────────

def register_user(email: str, password: str) -> int | None:
    """Register a new user. Returns user_id or None if email exists."""
    email = email.lower().strip()
    salt = generate_salt()
    pw_hash = hash_password(password, salt)
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, salt) VALUES (?, ?, ?);",
            (email, pw_hash, salt)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def authenticate_user(email: str, password: str) -> dict | None:
    """Authenticate email and password. Returns user dict or None."""
    email = email.lower().strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, salt FROM users WHERE email = ?;", (email,))
    user = cursor.fetchone()
    conn.close()

    if user:
        user_dict = dict(user)
        pw_hash = hash_password(password, user_dict["salt"])
        if pw_hash == user_dict["password_hash"]:
            return {"id": user_dict["id"], "email": user_dict["email"]}
    return None

# ─────────────────────────────────────────
# Transactions CRUD
# ─────────────────────────────────────────

def add_transaction(user_id: int, ticker: str, operation_type: str, quantity: int, 
                    price: float, fees: float, trade_date: str, market_type: str, 
                    note_number: str = None, broker: str = None, is_day_trade: int = 0) -> int:
    """Insert transaction record."""
    ticker = ticker.upper().strip()
    operation_type = operation_type.upper().strip()
    market_type = market_type.upper().strip()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (user_id, ticker, operation_type, quantity, price, fees, trade_date, market_type, note_number, broker, is_day_trade)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (user_id, ticker, operation_type, quantity, price, fees, trade_date, market_type, note_number, broker, is_day_trade))
    conn.commit()
    t_id = cursor.lastrowid
    conn.close()
    return t_id

def get_transactions(user_id: int):
    """Retrieve all transactions for a user sorted by trade_date and id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM transactions WHERE user_id = ? ORDER BY trade_date ASC, id ASC;
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_transaction(user_id: int, transaction_id: int):
    """Delete a transaction."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?;", (transaction_id, user_id))
    conn.commit()
    conn.close()

def update_transaction(user_id: int, transaction_id: int, ticker: str, operation_type: str, 
                       quantity: int, price: float, fees: float, trade_date: str, 
                       market_type: str, note_number: str = None, broker: str = None, is_day_trade: int = 0):
    """Update an existing transaction."""
    ticker = ticker.upper().strip()
    operation_type = operation_type.upper().strip()
    market_type = market_type.upper().strip()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE transactions
        SET ticker = ?, operation_type = ?, quantity = ?, price = ?, fees = ?, trade_date = ?, 
            market_type = ?, note_number = ?, broker = ?, is_day_trade = ?
        WHERE id = ? AND user_id = ?;
    """, (ticker, operation_type, quantity, price, fees, trade_date, market_type, note_number, broker, is_day_trade, transaction_id, user_id))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# Custody CRUD
# ─────────────────────────────────────────

def get_custody(user_id: int):
    """Retrieve custody (open positions) for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM custody WHERE user_id = ? ORDER BY ticker ASC;", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_custody_record(user_id: int, ticker: str, quantity: int, average_price: float, market_type: str):
    """Upsert custody position."""
    ticker = ticker.upper().strip()
    market_type = market_type.upper().strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custody (user_id, ticker, quantity, average_price, market_type)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, ticker) DO UPDATE SET
            quantity = excluded.quantity,
            average_price = excluded.average_price,
            market_type = excluded.market_type;
    """, (user_id, ticker, quantity, average_price, market_type))
    conn.commit()
    conn.close()

def delete_custody_record(user_id: int, ticker: str):
    """Delete a custody record when quantity reaches zero."""
    ticker = ticker.upper().strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custody WHERE user_id = ? AND ticker = ?;", (user_id, ticker))
    conn.commit()
    conn.close()

def clear_custody(user_id: int):
    """Clear all custody records for a user (used for rebuilding)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custody WHERE user_id = ?;", (user_id,))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# Proventos CRUD
# ─────────────────────────────────────────

def add_provento(user_id: int, ticker: str, event_type: str, amount: float, 
                 record_date: str, ratio: float = 1.0, unit_cost: float = 0.0) -> int:
    """Add a corporate action or provento."""
    ticker = ticker.upper().strip()
    event_type = event_type.upper().strip()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO proventos (user_id, ticker, event_type, amount, record_date, ratio, unit_cost)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """, (user_id, ticker, event_type, amount, record_date, ratio, unit_cost))
    conn.commit()
    p_id = cursor.lastrowid
    conn.close()
    return p_id

def get_proventos(user_id: int):
    """Get all proventos for user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proventos WHERE user_id = ? ORDER BY record_date ASC, id ASC;", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_provento(user_id: int, provento_id: int):
    """Delete a provento record."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM proventos WHERE id = ? AND user_id = ?;", (provento_id, user_id))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# Losses CRUD
# ─────────────────────────────────────────

def update_losses_carryover(user_id: int, month: str, common_loss: float, day_trade_loss: float, fii_loss: float):
    """Upsert losses carryover record for a specific month."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO loss_carryover (user_id, month, common_loss, day_trade_loss, fii_loss)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET
            common_loss = excluded.common_loss,
            day_trade_loss = excluded.day_trade_loss,
            fii_loss = excluded.fii_loss;
    """, (user_id, month, common_loss, day_trade_loss, fii_loss))
    conn.commit()
    conn.close()

def get_losses_carryover(user_id: int):
    """Get all loss records sorted by month."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loss_carryover WHERE user_id = ? ORDER BY month ASC;", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─────────────────────────────────────────
# DARFs & Monthly Tax Reports CRUD
# ─────────────────────────────────────────

def update_darf_record(user_id: int, month: str, swing_trade_sales: float, day_trade_sales: float, fii_sales: float,
                       swing_trade_profit: float, day_trade_profit: float, fii_profit: float,
                       tax_due: float, irrf_dedo_duro: float, paid: int = 0):
    """Upsert monthly tax/DARF report."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO darfs (user_id, month, swing_trade_sales, day_trade_sales, fii_sales,
                           swing_trade_profit, day_trade_profit, fii_profit, tax_due, irrf_dedo_duro, paid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET
            swing_trade_sales = excluded.swing_trade_sales,
            day_trade_sales = excluded.day_trade_sales,
            fii_sales = excluded.fii_sales,
            swing_trade_profit = excluded.swing_trade_profit,
            day_trade_profit = excluded.day_trade_profit,
            fii_profit = excluded.fii_profit,
            tax_due = excluded.tax_due,
            irrf_dedo_duro = excluded.irrf_dedo_duro,
            paid = excluded.paid,
            generated_at = CURRENT_TIMESTAMP;
    """, (user_id, month, swing_trade_sales, day_trade_sales, fii_sales,
          swing_trade_profit, day_trade_profit, fii_profit, tax_due, irrf_dedo_duro, paid))
    conn.commit()
    conn.close()

def get_darfs(user_id: int):
    """Get all monthly DARF/tax reports for user sorted by month."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM darfs WHERE user_id = ? ORDER BY month ASC;", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_darf_paid_status(user_id: int, month: str, paid: int):
    """Mark a monthly DARF as paid (1) or unpaid (0)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE darfs SET paid = ? WHERE user_id = ? AND month = ?;", (paid, user_id, month))
    conn.commit()
    conn.close()
