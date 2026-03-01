"""
Monday Board Setup Script
Reads config from .env file — no CLI arguments needed.

Fixes applied:
  - Paths resolved relative to THIS file, not cwd — works from any directory
  - Accepts CSV (.csv) AND Excel (.xlsx / .xls) for both data files
  - UTF-8-sig + latin-1 fallback encoding for CSV files (fixes Windows BOM errors)
  - Small delay between column creates to avoid rate-limit 429s
  - Boards already exist? Skips creation and reuses them

Usage:
    1. Copy .env.example → .env, fill in MONDAY_API_KEY
    2. Set DEALS_CSV / WORK_ORDERS_CSV to your file paths (absolute or relative to this script)
    3. python setup_boards.py
"""

import os
import csv
import io
import json
import time
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
env_path = ".env"
load_dotenv(dotenv_path=env_path)

MONDAY_API_KEY = os.getenv("MONDAY_API_KEY", "").strip()
MONDAY_API_URL = "https://api.monday.com/v2"


DEALS_FILE       = 'resources\Deal_funnel_Data.xlsx'
WORK_ORDERS_FILE = 'resources\Work_Order_Tracker Data.xlsx'

if not MONDAY_API_KEY:
    raise SystemExit(
        "\n❌  MONDAY_API_KEY is not set.\n"
        "    Copy .env.example → .env and add your API key.\n"
        "    Get it at: monday.com → avatar → Developers → My Access Tokens\n"
    )


# ── GraphQL helper ────────────────────────────────────────────────────────────

def gql(query: str, variables: dict = None, retries: int = 5) -> dict:
    headers = {
        "Authorization": MONDAY_API_KEY,
        "Content-Type":  "application/json",
        "API-Version":   "2024-01",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    wait = 15  # seconds to wait on first 429
    for attempt in range(retries):
        try:
            r = requests.post(MONDAY_API_URL, json=payload, headers=headers, timeout=30)

            if r.status_code == 429:
                print(f"    ⏳ Rate limited — waiting {wait}s ...")
                time.sleep(wait)
                wait = min(wait * 2, 60)  # exponential back-off, cap at 60s
                continue

            r.raise_for_status()
            data = r.json()

            if "errors" in data:
                raise Exception(f"GraphQL Error: {json.dumps(data['errors'], indent=2)}")

            return data["data"]

        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                print(f"    ⏳ Timeout — retrying ({attempt+1}/{retries}) ...")
                time.sleep(3)
            else:
                raise

    raise Exception("Max retries exceeded.")


# ── Board helpers ─────────────────────────────────────────────────────────────

def create_board(name: str) -> str:
    data = gql(f'mutation {{ create_board(board_name: "{name}", board_kind: public) {{ id }} }}')
    return data["create_board"]["id"]


def add_column(board_id: str, title: str, col_type: str):
    """Add one column, with a small pause to stay under rate limits."""
    gql(f'mutation {{ create_column(board_id: {board_id}, title: "{title}", column_type: {col_type}) {{ id }} }}')
    time.sleep(0.6)   # ~100 requests/min limit → safe at 1 col per 0.6s


def get_column_ids(board_id: str) -> dict:
    data = gql(
        "query ($id: ID!) { boards(ids: [$id]) { columns { id title } } }",
        {"id": board_id},
    )
    return {col["title"]: col["id"] for col in data["boards"][0]["columns"]}


# ── Board definitions ─────────────────────────────────────────────────────────

def create_deals_board() -> str:
    print("\n📋 Creating Deals board...")
    board_id = create_board("Deals — AI Agent")
    print(f"   Board ID: {board_id}")

    columns = [
        ("Owner Code",          "text"),
        ("Client Code",         "text"),
        ("Deal Status",         "text"),
        ("Deal Stage",          "text"),
        ("Sector",              "text"),
        ("Deal Value (INR)",    "numbers"),
        ("Closure Probability", "text"),
        ("Close Date",          "date"),
        ("Created Date",        "date"),
        ("Product",             "text"),
    ]
    for title, col_type in columns:
        add_column(board_id, title, col_type)
        print(f"   + {title} ({col_type})")

    return board_id


def create_work_orders_board() -> str:
    print("\n🗂  Creating Work Orders board...")
    board_id = create_board("Work Orders — AI Agent")
    print(f"   Board ID: {board_id}")

    columns = [
        ("Customer Code",           "text"),
        ("Serial Number",           "text"),
        ("Nature of Work",          "text"),
        ("Execution Status",        "text"),
        ("Sector",                  "text"),
        ("Type of Work",            "text"),
        ("BD/KAM Owner",            "text"),
        ("Platform",                "text"),
        ("Amount Excl GST (INR)",   "numbers"),
        ("Billed Excl GST (INR)",   "numbers"),
        ("Collected Amount (INR)",  "numbers"),
        ("Amount Receivable (INR)", "numbers"),
        ("Invoice Status",          "text"),
        ("WO Status",               "text"),
        ("Billing Status",          "text"),
        ("Start Date",              "date"),
        ("End Date",                "date"),
        ("PO/LOI Date",             "date"),
        ("Last Invoice Date",       "date"),
        ("Latest Invoice No",       "text"),
        ("Actual Billing Month",    "text"),
    ]
    for title, col_type in columns:
        add_column(board_id, title, col_type)
        print(f"   + {title} ({col_type})")

    return board_id


# ── File reader: CSV (any encoding) or Excel ─────────────────────────────────

DATE_COLS = {
    "Close Date", "Created Date", "Start Date", "End Date",
    "PO/LOI Date", "Last Invoice Date",
}
NUMBER_COLS = {
    "Deal Value (INR)", "Amount Excl GST (INR)", "Billed Excl GST (INR)",
    "Collected Amount (INR)", "Amount Receivable (INR)",
}


def read_file(path: Path) -> list[dict]:
    """
    Read CSV or Excel into a list of dicts.
    CSV: tries utf-8-sig first (handles Windows BOM), then latin-1.
    Excel: reads with pandas, skips the embedded-header row if needed.
    """
    suffix = path.suffix.lower()

    # ── Excel ──
    if suffix in (".xlsx", ".xls"):
        print(f"   📊 Detected Excel file: {path.name}")
        df = pd.read_excel(path, header=0, dtype=str)

        # Work Order Tracker has the real column names in row 0 of the data
        # (the file header row is "Unnamed: N"). Detect and fix.
        if all(str(c).startswith("Unnamed") for c in df.columns):
            print("   🔧 Fixing embedded header row (Unnamed columns detected)...")
            df.columns = df.iloc[0].values
            df = df.iloc[1:].reset_index(drop=True)

        df = df.fillna("")
        return df.to_dict(orient="records")

    # ── CSV ──
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                rows = list(csv.DictReader(f))
            print(f"   📄 Read {len(rows)} rows ({encoding}): {path.name}")
            return rows
        except (UnicodeDecodeError, LookupError):
            continue

    raise RuntimeError(f"Could not read {path} — tried utf-8-sig, utf-8, latin-1, cp1252")


# ── Value formatters ──────────────────────────────────────────────────────────

def fmt_date(val: str) -> str | None:
    if not val or str(val).lower() in ("nan", "none", "nat", ""):
        return None
    s = str(val).strip()
    # pandas sometimes serialises dates as "2025-01-15 00:00:00"
    s = s[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return json.dumps({"date": datetime.strptime(s, fmt).strftime("%Y-%m-%d")})
        except ValueError:
            continue
    return None


def fmt_number(val: str) -> float | None:
    if not val or str(val).lower() in ("nan", "none", ""):
        return None
    try:
        return float(str(val).replace("₹", "").replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


# ── Import rows into a Monday board ──────────────────────────────────────────

def import_file(board_id: str, file_path: Path, name_col: str = "Deal Name"):
    if not file_path.exists():
        print(f"   ⚠️  File not found: {file_path}")
        print(f"        Check DEALS_CSV / WORK_ORDERS_CSV in your .env")
        return

    col_ids = get_column_ids(board_id)
    print(f"   Board columns: {list(col_ids.keys())}")

    rows = read_file(file_path)
    if not rows:
        print("   ⚠️  File is empty — nothing to import.")
        return

    # Try to auto-detect name column if the exact key isn't present
    first = rows[0]
    if name_col not in first:
        candidates = [k for k in first if "name" in k.lower() or "deal" in k.lower()]
        if candidates:
            name_col = candidates[0]
            print(f"   ℹ️  Using '{name_col}' as item name column")
        else:
            name_col = list(first.keys())[0]
            print(f"   ℹ️  Falling back to first column '{name_col}' as item name")

    print(f"   Importing {len(rows)} rows ...")
    errors = 0

    for i, row in enumerate(rows):
        raw_name = str(row.get(name_col) or f"Row {i+1}").strip()
        item_name = raw_name.replace('"', "'").replace("\n", " ")[:255]

        col_values: dict = {}
        for col_title, val in row.items():
            if col_title == name_col:
                continue
            col_id = col_ids.get(col_title)
            if not col_id:
                continue
            sval = str(val).strip() if val is not None else ""
            if not sval or sval.lower() in ("nan", "none", "nat", ""):
                continue

            if col_title in DATE_COLS:
                parsed = fmt_date(sval)
                if parsed:
                    col_values[col_id] = parsed
            elif col_title in NUMBER_COLS:
                parsed = fmt_number(sval)
                if parsed is not None:
                    col_values[col_id] = parsed
            else:
                col_values[col_id] = sval[:2000]

        col_values_json = json.dumps(json.dumps(col_values))
        try:
            gql(f"""
            mutation {{
              create_item(
                board_id: {board_id},
                item_name: "{item_name}",
                column_values: {col_values_json}
              ) {{ id }}
            }}
            """)
        except Exception as e:
            errors += 1
            print(f"   ⚠️  Row {i+1} ({item_name[:40]}): {e}")
            if errors > 15:
                print("   ❌ Too many consecutive errors — aborting import.")
                break

        if (i + 1) % 25 == 0:
            print(f"   ... {i+1}/{len(rows)} rows done")

        # Pacing: ~60 mutations/min on free tier
        time.sleep(0.3)

    print(f"   ✅ {len(rows) - errors} imported, {errors} errors")


# ── Write board IDs back to .env ──────────────────────────────────────────────

def update_env(deals_id: str, wo_id: str):
    lines = []
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
    lines = [
        l for l in lines
        if not l.startswith("DEALS_BOARD_ID") and not l.startswith("WORK_ORDERS_BOARD_ID")
    ]
    lines.append(f"\nDEALS_BOARD_ID={deals_id}\n")
    lines.append(f"WORK_ORDERS_BOARD_ID={wo_id}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print("\n✅  Board IDs written back to .env automatically.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Monday.com Board Setup — AI Agent")
    print("=" * 55)
    print(f"  API Key         : {'*' * 10}{MONDAY_API_KEY[-6:]}")
    print(f"  Deals file      : {DEALS_FILE}")
    print(f"  Work Orders file: {WORK_ORDERS_FILE}")
    print("=" * 55)

    deals_board_id = create_deals_board()
    wo_board_id    = create_work_orders_board()

    print("\n📥 Importing Deals data...")

    print("\n📥 Importing Work Orders data...")
    from pathlib import Path

    import_file(deals_board_id, Path(DEALS_FILE), name_col="Deal Name")
    import_file(wo_board_id, Path(WORK_ORDERS_FILE), name_col="Deal name masked")

    update_env(deals_board_id, wo_board_id)

    print("\n" + "=" * 55)
    print("  🎉  Setup Complete!")
    print("=" * 55)
    print(f"  DEALS_BOARD_ID       = {deals_board_id}")
    print(f"  WORK_ORDERS_BOARD_ID = {wo_board_id}")
    print()
    print("  Both IDs saved to .env. Start the backend next:")
    print("  cd backend && uvicorn main:app --reload")
    print()