"""
Streamlit Frontend - Monday.com AI Agent
Features: Live query, visible tool traces, data quality alerts, sector dashboard
"""

import streamlit as st
import requests
import json
from datetime import datetime

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Monday.com AI Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0f1117; }
    .main-header {
        background: linear-gradient(135deg, #6C63FF, #3ECFCF);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
    }
    .trace-card {
        background: #1a1d2e;
        border: 1px solid #2d3061;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 6px 0;
        font-family: monospace;
        font-size: 0.82rem;
        color: #a0aec0;
    }
    .trace-tool { color: #6C63FF; font-weight: bold; }
    .quality-warning {
        background: #2d2010;
        border-left: 4px solid #f6ad55;
        padding: 10px 16px;
        border-radius: 4px;
        margin: 6px 0;
        color: #f6ad55;
        font-size: 0.88rem;
    }
    .metric-card {
        background: #1a1d2e;
        border: 1px solid #2d3061;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    .answer-box {
        background: #111827;
        border: 1px solid #374151;
        border-radius: 12px;
        padding: 24px;
        line-height: 1.8;
        color: #e5e7eb;
    }
    .sector-chip {
        display: inline-block;
        background: #6C63FF22;
        border: 1px solid #6C63FF55;
        border-radius: 20px;
        padding: 4px 12px;
        margin: 3px;
        color: #a78bfa;
        font-size: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar - Config ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    api_key = st.text_input("Monday API Key", type="password", placeholder="eyJhbGciOi...")
    deals_board_id = st.text_input("Deals Board ID", placeholder="1234567890")
    work_orders_board_id = st.text_input("Work Orders Board ID", placeholder="9876543210")

    st.divider()
    st.markdown("### 💡 Example Queries")
    examples = [
        "How's our pipeline in Energy this quarter?",
        "What's the conversion rate from won deals to work orders?",
        "Show me execution health across all sectors",
        "Where are we seeing revenue leakage?",
        "Which sector has the most overdue projects?",
        "Overall pipeline health this quarter",
    ]
    for ex in examples:
        if st.button(ex, key=ex, use_container_width=True):
            st.session_state["query"] = ex

    st.divider()
    backend_url = st.text_input("Backend URL", value="http://localhost:8000")
    st.caption("Make sure the FastAPI backend is running")

    st.markdown("---")
    st.markdown("**Agent Architecture**")
    st.code("""Frontend (Streamlit)
    ↓
LLM Agent (Tool-calling)
    ↓
Monday API Tool Layer
    ↓
Data Normalization Layer
    ↓
Response Generator""", language="text")


# ── Main Header ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
  <h1 style="margin:0;font-size:2rem;">📊 Monday.com AI Agent</h1>
  <p style="margin:0.5rem 0 0;opacity:0.85;">Live API · Tool-Call Traces · Founder-Level Intelligence</p>
</div>
""", unsafe_allow_html=True)

# ── Query Input ──────────────────────────────────────────────────────────────
col1, col2 = st.columns([5, 1])
with col1:
    query = st.text_input(
        "Ask a business question",
        value=st.session_state.get("query", ""),
        placeholder="How's our pipeline in Energy this quarter?",
        label_visibility="collapsed"
    )
with col2:
    run = st.button("🔍 Analyze", type="primary", use_container_width=True)

# ── Validation ───────────────────────────────────────────────────────────────
if run:
    if not api_key or not deals_board_id or not work_orders_board_id:
        st.error("Please fill in your Monday API Key and both Board IDs in the sidebar.")
        st.stop()
    if not query.strip():
        st.error("Please enter a question.")
        st.stop()

    # ── Live API Call ─────────────────────────────────────────────────────────
    with st.spinner("🔄 Calling Monday API, normalizing data, running analytics..."):
        try:
            response = requests.post(
                f"{backend_url}/query",
                json={
                    "question": query,
                    "monday_api_key": api_key,
                    "deals_board_id": deals_board_id,
                    "work_orders_board_id": work_orders_board_id
                },
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.ConnectionError:
            st.error("❌ Cannot connect to backend. Make sure FastAPI is running at " + backend_url)
            st.stop()
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.stop()

    # ── Layout: Answer + Traces ───────────────────────────────────────────────
    answer_col, trace_col = st.columns([3, 2])

    with answer_col:
        st.markdown("### 💬 Agent Response")
        st.markdown(
            f'<div class="answer-box">{result["answer"]}</div>',
            unsafe_allow_html=True
        )

        # Data Quality Notes
        if result.get("data_quality_notes"):
            st.markdown("#### ⚠️ Data Quality Notes")
            for note in result["data_quality_notes"]:
                st.markdown(f'<div class="quality-warning">{note}</div>', unsafe_allow_html=True)

    with trace_col:
        st.markdown("### 🔍 Tool Call Traces")
        st.caption("Live API calls — no caching, no preload")
        for trace in result.get("tool_traces", []):
            tool_name = trace.get("tool", "unknown()")
            details = {k: v for k, v in trace.items() if k != "tool"}
            details_str = " · ".join(f"{k}: {v}" for k, v in details.items())
            st.markdown(f"""
<div class="trace-card">
  <span class="trace-tool">▶ {tool_name}</span><br>
  {details_str}
</div>
""", unsafe_allow_html=True)

    # ── Metrics Dashboard ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📈 Key Metrics")

    insights = result.get("raw_insights", {})
    pipeline = insights.get("pipeline", {})
    conversion = insights.get("conversion", {})
    execution = insights.get("execution", {})

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Pipeline Value", f"${pipeline.get('total_pipeline_value', 0):,.0f}")
    with m2:
        st.metric("Expected Close", f"${pipeline.get('expected_close_value', 0):,.0f}")
    with m3:
        st.metric("Conversion Rate", f"{conversion.get('conversion_rate_pct', 0)}%",
                  delta=None if conversion.get('conversion_rate_pct', 0) >= 70 else "Low")
    with m4:
        st.metric("Revenue Leakage", f"${conversion.get('revenue_leakage', 0):,.0f}",
                  delta=None)
    with m5:
        st.metric("Overdue WOs", f"{execution.get('overdue', 0)}",
                  delta=f"{execution.get('overdue_rate_pct', 0)}% rate")

    # ── Sector Performance Matrix ─────────────────────────────────────────────
    sector_matrix = insights.get("sector_matrix", [])
    if sector_matrix:
        st.divider()
        st.markdown("### 🗺️ Sector Performance Matrix")
        st.caption("Cross-board analysis: Pipeline × Execution × Conversion")

        import pandas as pd
        df = pd.DataFrame(sector_matrix)
        df.columns = [
            "Sector", "Pipeline Value ($)", "Deals",
            "Conversion (%)", "Revenue Leakage ($)",
            "Overdue Rate (%)", "Load vs Avg (%)"
        ]

        def color_risk(val):
            if isinstance(val, float) or isinstance(val, int):
                if val > 30:
                    return "color: #fc8181"
                elif val > 15:
                    return "color: #f6ad55"
                else:
                    return "color: #68d391"
            return ""

        st.dataframe(
            df.style.applymap(color_risk, subset=["Overdue Rate (%)", "Load vs Avg (%)"]),
            use_container_width=True,
            hide_index=True
        )

    # ── Stage Distribution ────────────────────────────────────────────────────
    stage_dist = pipeline.get("stage_distribution", {})
    if stage_dist:
        st.divider()
        st.markdown("### 🎯 Pipeline Stage Distribution")
        cols = st.columns(len(stage_dist))
        for i, (stage, data) in enumerate(sorted(stage_dist.items(), key=lambda x: -x[1]["value"])):
            with cols[i]:
                st.metric(
                    label=stage,
                    value=f"${data['value']:,.0f}",
                    delta=f"{data['count']} deals"
                )

# ── Empty State ───────────────────────────────────────────────────────────────
else:
    st.markdown("""
    <div style="text-align:center;padding:4rem;color:#6b7280;">
        <div style="font-size:3rem;margin-bottom:1rem;">📊</div>
        <h3 style="color:#9ca3af;">Ready to analyze your pipeline</h3>
        <p>Configure your Monday credentials in the sidebar, then ask a business question above.</p>
        <p style="font-size:0.85rem;margin-top:1rem;">
            Powered by live Monday API · Zero caching · Visible tool traces
        </p>
    </div>
    """, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#4b5563;font-size:0.8rem;'>"
    "Monday.com AI Agent · Live API · No Caching · Founder-Level Intelligence"
    "</div>",
    unsafe_allow_html=True
)