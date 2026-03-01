"""
Analytics Engine — Real business logic based on actual Skylark drone data
Sectors: Mining, Renewables, Railways, Powerline, Construction, Others
Deal Stages: A (Lead) → H (Work Order Received) → G (Project Won) → Project Completed
"""

from datetime import date, datetime
from typing import Optional
from collections import defaultdict

STAGE_PROBABILITY = {
    "Lead": 0.05, "Qualified": 0.10, "Demo Done": 0.20, "Feasibility": 0.25,
    "Proposal Sent": 0.40, "Negotiation": 0.70, "POC": 0.50,
    "Work Order Received": 0.90, "Won": 1.0, "Completed": 1.0,
    "Invoice Sent": 0.95, "Accrued": 0.98, "Lost": 0.0,
    "Not Relevant": 0.0, "On Hold": 0.15, "Unknown": 0.10,
}

PROB_OVERRIDE = {"High": 0.75, "Medium": 0.40, "Low": 0.15}


def current_quarter_bounds():
    today = date.today()
    q = (today.month - 1) // 3
    start = date(today.year, q * 3 + 1, 1)
    end = date(today.year, 12, 31) if q == 3 else date(today.year, (q + 1) * 3 + 1, 1)
    return start, end


def previous_quarter_bounds():
    today = date.today()
    q = (today.month - 1) // 3
    if q == 0:
        return date(today.year - 1, 10, 1), date(today.year - 1, 12, 31)
    return date(today.year, (q - 1) * 3 + 1, 1), date(today.year, q * 3 + 1, 1)


def in_quarter(d, start, end):
    return d is not None and start <= d <= end


def expected_value(deal):
    val = deal.get("deal_value") or 0
    if deal.get("closure_prob") in PROB_OVERRIDE:
        prob = PROB_OVERRIDE[deal["closure_prob"]]
    else:
        prob = STAGE_PROBABILITY.get(deal.get("stage", "Unknown"), 0.10)
    return val * prob


class AnalyticsEngine:
    def __init__(self, deals, work_orders):
        self.deals = deals
        self.work_orders = work_orders

    def pipeline_summary(self, sector=None, quarter="current"):
        q_start, q_end = current_quarter_bounds() if quarter == "current" else previous_quarter_bounds()
        deals = self.deals
        if sector:
            deals = [d for d in deals if sector.lower() in (d.get("sector") or "").lower()]

        active_deals = [d for d in deals if d.get("status") in ("Open", "On Hold", "Won")]
        q_deals = [d for d in active_deals if in_quarter(d.get("close_date"), q_start, q_end)]
        target_deals = q_deals if q_deals else active_deals

        total_value = sum(d.get("deal_value") or 0 for d in target_deals)
        ev = sum(expected_value(d) for d in target_deals)

        stage_dist = defaultdict(lambda: {"count": 0, "value": 0})
        for d in target_deals:
            s = d.get("stage", "Unknown")
            stage_dist[s]["count"] += 1
            stage_dist[s]["value"] += d.get("deal_value") or 0

        won_deals = [d for d in deals if d.get("status") == "Won"]
        won_value = sum(d.get("deal_value") or 0 for d in won_deals)

        early_stages = {"Lead", "Qualified", "Demo Done", "Unknown"}
        early_pct = round(
            sum(1 for d in target_deals if d.get("stage") in early_stages)
            / max(len(target_deals), 1) * 100, 1
        )

        return {
            "sector": sector or "All Sectors",
            "quarter": f"Q{(q_start.month-1)//3 + 1} {q_start.year}",
            "total_deals": len(target_deals),
            "total_pipeline_value": total_value,
            "expected_close_value": ev,
            "won_deals": len(won_deals),
            "won_value": won_value,
            "early_stage_pct": early_pct,
            "stage_distribution": dict(stage_dist),
            "has_date_filter": len(q_deals) > 0,
        }

    def conversion_analysis(self, sector=None):
        won_stages = {"Won", "Work Order Received", "Invoice Sent", "Accrued", "Completed"}
        closed_deals = [
            d for d in self.deals
            if d.get("stage") in won_stages or d.get("status") == "Won"
        ]
        if sector:
            closed_deals = [d for d in closed_deals if sector.lower() in (d.get("sector") or "").lower()]

        wo_names = set()
        for wo in self.work_orders:
            name = (wo.get("deal_name") or "").strip().lower()
            if name:
                wo_names.add(name)

        matched = 0
        matched_value = 0
        unmatched_value = 0

        for d in closed_deals:
            name = (d.get("deal_name") or "").strip().lower()
            if name in wo_names:
                matched += 1
                matched_value += d.get("deal_value") or 0
            else:
                unmatched_value += d.get("deal_value") or 0

        total_won = len(closed_deals)
        won_value = sum(d.get("deal_value") or 0 for d in closed_deals)

        return {
            "sector": sector or "All Sectors",
            "closed_won_deals": total_won,
            "converted_to_work_orders": matched,
            "conversion_rate_pct": round(matched / max(total_won, 1) * 100, 1),
            "matched_revenue": matched_value,
            "revenue_leakage": unmatched_value,
            "total_won_revenue": won_value,
            "leakage_pct": round(unmatched_value / max(won_value, 1) * 100, 1),
        }

    def execution_health(self, sector=None):
        wos = self.work_orders
        if sector:
            wos = [wo for wo in wos if sector.lower() in (wo.get("sector") or "").lower()]

        total = len(wos)
        if total == 0:
            return {"sector": sector or "All", "total_work_orders": 0, "overdue_count": 0,
                    "overdue_rate_pct": 0, "collection_rate_pct": 0, "billing_rate_pct": 0,
                    "total_contract_value": 0, "total_collected": 0, "total_receivable": 0,
                    "sector_load_vs_avg_pct": 0, "completed": 0, "ongoing": 0}

        completed = [wo for wo in wos if wo.get("execution_status") == "Completed"]
        ongoing = [wo for wo in wos if wo.get("execution_status") == "Ongoing"]
        not_started = [wo for wo in wos if wo.get("execution_status") == "Not Started"]
        paused = [wo for wo in wos if wo.get("execution_status") == "Paused"]

        total_contract = sum(wo.get("amount") or 0 for wo in wos)
        total_billed = sum(wo.get("billed") or 0 for wo in wos)
        total_collected = sum(wo.get("collected") or 0 for wo in wos)
        total_receivable = sum(wo.get("receivable") or 0 for wo in wos)

        today = date.today()
        overdue = [
            wo for wo in wos
            if wo.get("end_date") and wo["end_date"] < today
            and wo.get("execution_status") not in ("Completed",)
        ]

        sector_counts = defaultdict(int)
        for wo in self.work_orders:
            sector_counts[(wo.get("sector") or "Unknown")] += 1
        avg_load = sum(sector_counts.values()) / max(len(sector_counts), 1)
        overload_pct = round((total - avg_load) / max(avg_load, 1) * 100, 1)

        return {
            "sector": sector or "All Sectors",
            "total_work_orders": total,
            "completed": len(completed),
            "ongoing": len(ongoing),
            "not_started": len(not_started),
            "paused": len(paused),
            "overdue_count": len(overdue),
            "overdue_rate_pct": round(len(overdue) / max(total, 1) * 100, 1),
            "total_contract_value": total_contract,
            "total_billed": total_billed,
            "total_collected": total_collected,
            "total_receivable": total_receivable,
            "collection_rate_pct": round(total_collected / max(total_contract, 1) * 100, 1),
            "billing_rate_pct": round(total_billed / max(total_contract, 1) * 100, 1),
            "sector_load_vs_avg_pct": overload_pct,
        }

    def sector_performance_matrix(self):
        sectors = set()
        for d in self.deals:
            if d.get("sector"): sectors.add(d["sector"])
        for wo in self.work_orders:
            if wo.get("sector"): sectors.add(wo["sector"])

        results = []
        for sector in sorted(sectors):
            p = self.pipeline_summary(sector=sector)
            c = self.conversion_analysis(sector=sector)
            e = self.execution_health(sector=sector)
            results.append({
                "sector": sector,
                "pipeline_value": p["total_pipeline_value"],
                "active_deals": p["total_deals"],
                "won_value": p["won_value"],
                "conversion_rate": c["conversion_rate_pct"],
                "revenue_leakage": c["revenue_leakage"],
                "work_orders": e["total_work_orders"],
                "contract_value": e["total_contract_value"],
                "collection_rate": e["collection_rate_pct"],
                "overdue_rate": e["overdue_rate_pct"],
            })
        return results

    def collections_analysis(self, sector=None):
        wos = self.work_orders
        if sector:
            wos = [wo for wo in wos if sector.lower() in (wo.get("sector") or "").lower()]
        priority = [wo for wo in wos if "priority" in (wo.get("billing_status") or "").lower()]
        not_billed = [wo for wo in wos if "not billed" in (wo.get("invoice_status") or "").lower()]
        stuck = [wo for wo in wos if "stuck" in (wo.get("billing_status") or "").lower()]
        return {
            "sector": sector or "All Sectors",
            "total_receivable": sum(wo.get("receivable") or 0 for wo in wos),
            "priority_ar_accounts": len(priority),
            "not_yet_billed": len(not_billed),
            "stuck_billing": len(stuck),
        }