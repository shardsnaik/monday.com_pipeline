"""
Data Normalization Layer — Real column names from actual data
Deals: 342 rows | Work Orders: 176 rows
Known quality issues:
  - Deal Value missing 51.8%
  - Closure Probability missing 74.9%
  - Close Date missing 20.8%
  - WO: Collected Amount missing 55.7%, Billing Status 84.1%
"""

import re
import json
from datetime import datetime, date
from typing import Optional

# ── Deal Stage → canonical mapping ────────────────────────────────────────────
STAGE_MAP = {
    "a. lead generated": "Lead",
    "b. sales qualified leads": "Qualified",
    "c. demo done": "Demo Done",
    "d. feasibility": "Feasibility",
    "e. proposal/commercials sent": "Proposal Sent",
    "f. negotiations": "Negotiation",
    "g. project won": "Won",
    "h. work order received": "Work Order Received",
    "i. poc": "POC",
    "j. invoice sent": "Invoice Sent",
    "k. amount accrued": "Accrued",
    "l. project lost": "Lost",
    "m. projects on hold": "On Hold",
    "n. not relevant at the moment": "Not Relevant",
    "o. not relevant at all": "Not Relevant",
    "project completed": "Completed",
}

STATUS_MAP = {
    "won": "Won",
    "dead": "Dead",
    "open": "Open",
    "on hold": "On Hold",
}

EXEC_MAP = {
    "completed": "Completed",
    "ongoing": "Ongoing",
    "executed until current month": "Ongoing",
    "not started": "Not Started",
    "pause / struck": "Paused",
    "partial completed": "Partially Completed",
    "partially completed": "Partially Completed",
    "details pending from client": "Pending Client",
}

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y",
                "%Y-%m-%dT%H:%M:%S", "%B %d, %Y", "%b %d, %Y"]


def parse_date(raw) -> Optional[date]:
    if raw is None or (isinstance(raw, float) and str(raw) == 'nan'):
        return None
    raw = str(raw).strip()
    if raw in ('', 'nan', 'NaT', 'None'):
        return None
    if raw.startswith("{"):
        try:
            raw = json.loads(raw).get("date", raw)
        except Exception:
            pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw[:10], fmt[:8] if len(fmt) > 8 else fmt).date()
        except ValueError:
            pass
    return None


def parse_revenue(raw) -> Optional[float]:
    if raw is None or (isinstance(raw, float) and str(raw) == 'nan'):
        return None
    raw = str(raw).strip().replace(",", "").replace("₹", "").replace("$", "").lower()
    if raw in ('', 'nan', 'none'):
        return None
    m = 1
    if raw.endswith("m"):
        m, raw = 1_000_000, raw[:-1]
    elif raw.endswith("k"):
        m, raw = 1_000, raw[:-1]
    try:
        return float(raw) * m
    except ValueError:
        return None


def normalize_stage(raw: str) -> str:
    if not raw:
        return "Unknown"
    return STAGE_MAP.get(raw.lower().strip(), raw.strip())


def normalize_status(raw: str) -> str:
    if not raw:
        return "Unknown"
    return STATUS_MAP.get(raw.lower().strip(), raw.strip())


def normalize_exec_status(raw: str) -> str:
    if not raw:
        return "Unknown"
    return EXEC_MAP.get(raw.lower().strip(), raw.strip())


def item_to_dict(item: dict) -> dict:
    """Convert Monday item (from GraphQL) to flat dict keyed by column title"""
    result = {"id": item["id"], "name": item["name"]}
    for col in item.get("column_values", []):
        title = col["column"]["title"]
        result[title] = col.get("text") or ""
    return result


class DataNormalizer:
    def normalize_deals(self, raw_items: list) -> tuple[list, list]:
        """
        Normalize deal records from Monday API.
        Columns: Deal Name, Owner Code, Client Code, Deal Status, Deal Stage,
                 Sector, Deal Value (INR), Closure Probability, Close Date,
                 Created Date, Product
        """
        notes = []
        records = []
        total = len(raw_items)

        missing_value = 0
        missing_date = 0
        missing_sector = 0
        missing_prob = 0

        for item in raw_items:
            flat = item_to_dict(item)
            deal_value = parse_revenue(
                flat.get("Deal Value (INR)") or flat.get("Masked Deal value") or ""
            )
            close_date = parse_date(
                flat.get("Close Date") or flat.get("Close Date (A)") or
                flat.get("Tentative Close Date") or ""
            )
            sector = (flat.get("Sector") or flat.get("Sector/service") or "").strip()
            prob = (flat.get("Closure Probability") or "").strip()

            if deal_value is None:
                missing_value += 1
            if close_date is None:
                missing_date += 1
            if not sector:
                missing_sector += 1
            if not prob or prob == "Closure Probability":
                missing_prob += 1

            records.append({
                "id": flat.get("id"),
                "deal_name": flat.get("name") or flat.get("Deal Name", ""),
                "owner_code": flat.get("Owner Code") or flat.get("Owner code", ""),
                "client_code": flat.get("Client Code", ""),
                "status": normalize_status(flat.get("Deal Status", "")),
                "stage": normalize_stage(flat.get("Deal Stage", "")),
                "sector": sector or None,
                "deal_value": deal_value,
                "closure_prob": prob if prob not in ("", "Closure Probability") else None,
                "close_date": close_date,
                "created_date": parse_date(flat.get("Created Date", "")),
                "product": flat.get("Product") or flat.get("Product deal") or None,
            })

        if missing_value:
            pct = round(missing_value / total * 100, 1)
            notes.append(f"⚠️ Deal Value missing for {missing_value}/{total} records ({pct}%) — pipeline totals are understated.")
        if missing_date:
            pct = round(missing_date / total * 100, 1)
            notes.append(f"⚠️ Close Date missing for {missing_date}/{total} records ({pct}%) — quarter filters may exclude these deals.")
        if missing_sector:
            notes.append(f"⚠️ {missing_sector} deals have no sector — sector analysis may be incomplete.")
        if missing_prob > total * 0.5:
            notes.append(f"⚠️ Closure Probability unpopulated for {missing_prob}/{total} deals — weighted forecast uses stage-based defaults.")

        return records, notes

    def normalize_work_orders(self, raw_items: list) -> tuple[list, list]:
        """
        Normalize work order records from Monday API.
        Columns: Deal Name, Customer Code, Serial Number, Nature of Work,
                 Execution Status, Sector, Type of Work, BD/KAM Owner, Platform,
                 Amount Excl GST (INR), Billed Excl GST (INR), Collected Amount (INR),
                 Amount Receivable (INR), Invoice Status, WO Status, Billing Status,
                 Start Date, End Date, PO/LOI Date
        """
        notes = []
        records = []
        total = len(raw_items)

        missing_amount = 0
        missing_dates = 0
        missing_collected = 0

        for item in raw_items:
            flat = item_to_dict(item)
            amount = parse_revenue(flat.get("Amount Excl GST (INR)", ""))
            collected = parse_revenue(flat.get("Collected Amount (INR)", ""))
            billed = parse_revenue(flat.get("Billed Excl GST (INR)", ""))
            receivable = parse_revenue(flat.get("Amount Receivable (INR)", ""))
            start = parse_date(flat.get("Start Date", ""))
            end = parse_date(flat.get("End Date", ""))

            if amount is None:
                missing_amount += 1
            if start is None:
                missing_dates += 1
            if collected is None:
                missing_collected += 1

            records.append({
                "id": flat.get("id"),
                "deal_name": flat.get("name") or flat.get("Deal Name", ""),
                "customer_code": flat.get("Customer Code", ""),
                "serial_number": flat.get("Serial Number", ""),
                "nature_of_work": flat.get("Nature of Work", ""),
                "execution_status": normalize_exec_status(flat.get("Execution Status", "")),
                "sector": (flat.get("Sector") or "").strip() or None,
                "type_of_work": flat.get("Type of Work", ""),
                "owner_code": flat.get("BD/KAM Owner", ""),
                "platform": flat.get("Platform", ""),
                "amount": amount,
                "billed": billed,
                "collected": collected,
                "receivable": receivable,
                "invoice_status": flat.get("Invoice Status", ""),
                "wo_status": flat.get("WO Status", ""),
                "billing_status": flat.get("Billing Status", ""),
                "start_date": start,
                "end_date": end,
                "po_date": parse_date(flat.get("PO/LOI Date", "")),
            })

        if missing_amount:
            notes.append(f"⚠️ Contract Amount missing for {missing_amount}/{total} work orders.")
        if missing_collected:
            pct = round(missing_collected / total * 100, 1)
            notes.append(f"⚠️ Collected Amount missing for {missing_collected}/{total} WOs ({pct}%) — collection analysis may be incomplete.")
        if missing_dates:
            notes.append(f"⚠️ Start Date missing for {missing_dates}/{total} work orders — timeline analysis limited.")

        return records, notes