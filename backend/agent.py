"""
Monday.com AI Agent
Pipeline: Question → Ollama LLM (intent) → Tool calls → Analytics → Ollama LLM (response)

Ollama is used for two things:
  1. Intent extraction  — structured JSON out of the user's free-form question
  2. Response synthesis — founder-level narrative from the raw analytics data

All tool calls (Monday API, analytics) happen between those two LLM calls.
"""

import json
import sys
import os
import time
import requests
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from tools.monday_api_tools import MondayAPITools
from tools.analytics import AnalyticsEngine
from normalizer.normalizer import DataNormalizer


# ── Ollama client ─────────────────────────────────────────────────────────────

class OllamaClient:
    def __init__(self, host: str, model: str):
        self.host  = host.rstrip("/")
        self.model = model

    def chat(self, system: str, user: str, temperature: float = 0.2, timeout: int = 60) -> str:
        """
        Call Ollama /api/chat and return the assistant's reply as a string.
        Falls back gracefully if Ollama is unreachable.
        """
        payload = {
            "model":    self.model,
            "stream":   False,
            "options":  {"temperature": temperature},
            "messages": [
                {"role": "system",    "content": system},
                {"role": "user",      "content": user},
            ],
        }
        try:
            r = requests.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except requests.exceptions.ConnectionError:
            return "__OLLAMA_UNAVAILABLE__"
        except Exception as e:
            return f"__OLLAMA_ERROR__: {e}"

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False


# ── Step 1: LLM Intent Extraction ────────────────────────────────────────────

INTENT_SYSTEM = """You are an intent parser for a business intelligence agent.
Extract structured information from the user's question and return ONLY valid JSON.

Return this exact JSON schema (no extra keys, no markdown fences):
{
  "sector": "<sector name or null>",
  "quarter": "<'current' or 'previous'>",
  "intent": "<one of: pipeline, execution, conversion, collections, sector_comparison, overall_health, general>",
  "clarification_needed": "<null or a short clarifying question to ask the user>"
}

Known sectors (use exact casing): Mining, Renewables, Railways, Powerline, Construction, Others
Intent definitions:
  pipeline         — deals, pipeline value, stage, forecast
  execution        — work orders, delivery, project status, overdue
  conversion       — deal-to-WO conversion rate, revenue leakage, win rate
  collections      — AR, billing, receivables, invoice
  sector_comparison — comparing sectors
  overall_health   — general health, how are we doing
  general          — anything else
"""

def extract_intent_with_llm(llm: OllamaClient, question: str) -> dict:
    """Use Ollama to parse intent from the question. Falls back to keyword matching."""
    raw = llm.chat(INTENT_SYSTEM, question, temperature=0.0, timeout=30)

    if raw.startswith("__OLLAMA"):
        # Fallback: keyword-based parsing
        return _keyword_intent(question)

    # Strip accidental markdown fences
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw)
        # Validate required keys exist
        parsed.setdefault("sector", None)
        parsed.setdefault("quarter", "current")
        parsed.setdefault("intent", "general")
        parsed.setdefault("clarification_needed", None)
        return parsed
    except json.JSONDecodeError:
        return _keyword_intent(question)


def _keyword_intent(question: str) -> dict:
    """Deterministic fallback intent parser (no LLM)"""
    q = question.lower()

    known_sectors = ["mining", "renewables", "railways", "powerline", "construction", "others"]
    sector = next((s.title() for s in known_sectors if s in q), None)

    quarter = "previous" if any(w in q for w in ["last quarter", "previous quarter", "q4", "q3"]) else "current"

    intent = "general"
    if any(w in q for w in ["pipeline", "deals", "forecast", "stage", "revenue"]):
        intent = "pipeline"
    if any(w in q for w in ["work order", "execution", "delivery", "overdue", "project"]):
        intent = "execution"
    if any(w in q for w in ["convert", "conversion", "win rate", "leakage"]):
        intent = "conversion"
    if any(w in q for w in ["ar", "billing", "invoice", "receivable", "collection"]):
        intent = "collections"
    if any(w in q for w in ["sector", "compare", "breakdown", "all sectors"]):
        intent = "sector_comparison"
    if any(w in q for w in ["overall", "health", "how are we", "summary"]):
        intent = "overall_health"

    return {"sector": sector, "quarter": quarter, "intent": intent, "clarification_needed": None}


# ── Step 2: LLM Response Synthesis ───────────────────────────────────────────

RESPONSE_SYSTEM = """You are a senior business intelligence analyst presenting data to a founder.

Rules:
- Lead with the most important number or risk — never bury the headline
- Use Indian Rupee (₹) formatting for all monetary values
- Flag data quality issues inline (e.g. "Note: 51% of deal values are missing")
- Highlight risks with clear labels: 🚨 Critical, ⚠️ Warning, ✅ Healthy
- Keep it under 300 words — founders are busy
- End with a 1-sentence "Bottom Line" recommendation
- Do NOT use generic filler phrases like "great question" or "certainly"
- Respond in plain text with light markdown (headers with ###, bold with **)
"""

def synthesise_response_with_llm(llm: OllamaClient, question: str, analytics: dict, quality_notes: list) -> str:
    """Ask Ollama to write the founder-facing narrative from the analytics payload."""

    context = f"""
User question: {question}

Analytics data (all monetary values in INR):
{json.dumps(analytics, indent=2, default=str)}

Data quality warnings:
{chr(10).join(quality_notes) if quality_notes else 'None'}
"""

    raw = llm.chat(RESPONSE_SYSTEM, context, temperature=0.3, timeout=90)

    if raw.startswith("__OLLAMA"):
        # Fallback: build response programmatically
        return _build_fallback_response(question, analytics, quality_notes)

    return raw


def _build_fallback_response(question: str, analytics: dict, quality_notes: list) -> str:
    """Rule-based response when Ollama is unavailable."""
    p = analytics.get("pipeline", {})
    c = analytics.get("conversion", {})
    e = analytics.get("execution", {})

    lines = [f"### 📊 {p.get('sector','All')} — {p.get('quarter','')}\n"]

    pv = p.get("total_pipeline_value", 0)
    ev = p.get("expected_close_value", 0)
    if pv:
        lines.append(f"**Pipeline:** ₹{pv:,.0f} across {p.get('total_deals',0)} deals. Expected close: **₹{ev:,.0f}**")
        if p.get("early_stage_pct", 0) > 50:
            lines.append(f"⚠️ {p['early_stage_pct']}% of deals in early stage — forecast is uncertain.")

    cr = c.get("conversion_rate_pct", 0)
    leakage = c.get("revenue_leakage", 0)
    if c.get("closed_won_deals", 0):
        icon = "✅" if cr >= 80 else ("⚠️" if cr >= 60 else "🚨")
        lines.append(f"\n{icon} **Conversion:** {cr}% of Won deals have Work Orders. Revenue not yet in execution: ₹{leakage:,.0f}")

    wo = e.get("total_work_orders", 0)
    if wo:
        od = e.get("overdue_rate_pct", 0)
        icon = "✅" if od < 10 else ("⚠️" if od < 20 else "🚨")
        lines.append(f"\n{icon} **Execution:** {wo} WOs — {e.get('completed',0)} completed, {e.get('overdue_count',0)} overdue ({od}%)")
        lines.append(f"   Collection rate: {e.get('collection_rate_pct',0)}% | AR outstanding: ₹{e.get('total_receivable',0):,.0f}")

    if quality_notes:
        lines.append("\n**Data Quality Notes:**")
        for n in quality_notes:
            lines.append(f"  {n}")

    return "\n".join(lines)


# ── Main Agent ────────────────────────────────────────────────────────────────

class MondayAgent:
    def __init__(
        self,
        api_key: str,
        deals_board_id: str,
        work_orders_board_id: str,
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "deepseek-r1:1.5b",
    ):
        self.api        = MondayAPITools(api_key, deals_board_id, work_orders_board_id)
        self.normalizer = DataNormalizer()
        self.llm        = OllamaClient(host=ollama_host, model=ollama_model)

    async def process_query(self, question: str) -> dict:
        tool_traces   = []
        quality_notes = []

        # ── 1. LLM intent extraction ──────────────────────────────────────
        t0 = time.time()
        intent = extract_intent_with_llm(self.llm, question)
        tool_traces.append({
            "tool":    "extract_intent_with_llm()",
            "model":   self.llm.model,
            "input":   question,
            "output":  intent,
            "latency_ms": round((time.time() - t0) * 1000),
        })

        # If the LLM thinks clarification is needed, return early
        if intent.get("clarification_needed"):
            return {
                "answer":             intent["clarification_needed"],
                "tool_traces":        tool_traces,
                "data_quality_notes": [],
                "raw_insights":       {},
            }

        sector  = intent.get("sector")
        quarter = intent.get("quarter", "current")

        # ── 2. Live Monday API calls ──────────────────────────────────────
        raw_deals, deals_trace = self.api.get_deals()
        tool_traces.append(deals_trace)

        raw_wos, wos_trace = self.api.get_work_orders()
        tool_traces.append(wos_trace)

        # ── 3. Normalize ──────────────────────────────────────────────────
        deals, deal_quality = self.normalizer.normalize_deals(raw_deals)
        wos,   wo_quality   = self.normalizer.normalize_work_orders(raw_wos)
        quality_notes.extend(deal_quality)
        quality_notes.extend(wo_quality)

        tool_traces.append({
            "tool":          "normalize_deals()",
            "records_in":    len(raw_deals),
            "records_out":   len(deals),
            "quality_flags": len(deal_quality),
        })
        tool_traces.append({
            "tool":          "normalize_work_orders()",
            "records_in":    len(raw_wos),
            "records_out":   len(wos),
            "quality_flags": len(wo_quality),
        })

        # ── 4. Analytics (tool calls based on intent) ─────────────────────
        engine = AnalyticsEngine(deals, wos)

        pipeline = engine.pipeline_summary(sector=sector, quarter=quarter)
        tool_traces.append({
            "tool":           "pipeline_summary()",
            "filter":         {"sector": sector, "quarter": quarter},
            "deals_analyzed": pipeline["total_deals"],
            "pipeline_value": f"₹{pipeline['total_pipeline_value']:,.0f}",
        })

        conversion = engine.conversion_analysis(sector=sector)
        tool_traces.append({
            "tool":            "conversion_analysis()",
            "filter":          {"sector": sector},
            "closed_won":      conversion["closed_won_deals"],
            "conversion_rate": f"{conversion['conversion_rate_pct']}%",
            "revenue_leakage": f"₹{conversion['revenue_leakage']:,.0f}",
        })

        execution = engine.execution_health(sector=sector)
        tool_traces.append({
            "tool":         "execution_health()",
            "filter":       {"sector": sector},
            "work_orders":  execution["total_work_orders"],
            "overdue_rate": f"{execution['overdue_rate_pct']}%",
            "collection_rate": f"{execution.get('collection_rate_pct', 0)}%",
        })

        collections = engine.collections_analysis(sector=sector)
        tool_traces.append({
            "tool":            "collections_analysis()",
            "filter":          {"sector": sector},
            "total_receivable": f"₹{collections['total_receivable']:,.0f}",
            "stuck_billing":    collections["stuck_billing"],
        })

        sector_matrix = engine.sector_performance_matrix()
        tool_traces.append({
            "tool":             "sector_performance_matrix()",
            "sectors_analyzed": len(sector_matrix),
        })

        analytics_payload = {
            "pipeline":      pipeline,
            "conversion":    conversion,
            "execution":     execution,
            "collections":   collections,
            "sector_matrix": sector_matrix,
        }

        # ── 5. LLM response synthesis ─────────────────────────────────────
        t0 = time.time()
        answer = synthesise_response_with_llm(
            self.llm, question, analytics_payload, quality_notes
        )
        tool_traces.append({
            "tool":       "synthesise_response_with_llm()",
            "model":      self.llm.model,
            "latency_ms": round((time.time() - t0) * 1000),
        })

        return {
            "answer":             answer,
            "tool_traces":        tool_traces,
            "data_quality_notes": quality_notes,
            "raw_insights":       analytics_payload,
        }