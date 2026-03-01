"""
Monday.com AI Agent — FastAPI Backend

Config is loaded entirely from .env — the /query endpoint only needs
the user's question. No credentials in the request body.

Required .env keys:
    MONDAY_API_KEY
    DEALS_BOARD_ID
    WORK_ORDERS_BOARD_ID
    OLLAMA_HOST          (default: http://localhost:11434)
    OLLAMA_MODEL         (default: llama3)
"""

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# ── Load .env from the project root (one level above /backend) ───────────────
env_path = ".env"
load_dotenv(dotenv_path=env_path)

# ── Validate required env vars at startup ────────────────────────────────────
# REQUIRED = ["MONDAY_API_KEY", "DEALS_BOARD_ID", "WORK_ORDERS_BOARD_ID"]
# missing = [k for k in REQUIRED if not os.getenv(k, "").strip()]
# if missing:
#     sys.exit(
#         f"\n❌  Missing required environment variables: {', '.join(missing)}\n"
#         f"    Make sure your .env file exists at: {env_path}\n"
#         f"    Run setup_boards.py first if board IDs are missing.\n"
#     )

MONDAY_API_KEY       = os.getenv("MONDAY_API_KEY")
DEALS_BOARD_ID       = os.getenv("DEALS_BOARD_ID")
WORK_ORDERS_BOARD_ID = os.getenv("WORK_ORDERS_BOARD_ID")
OLLAMA_HOST          = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
OLLAMA_MODEL         = os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b").strip()

# ── Add project root to path so backend/ can import tools/ normalizer/ ───────
sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.agent import MondayAgent  # noqa: E402

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Monday.com BI Agent",
    version="1.0.0",
    description="Answers founder-level business questions via live Monday.com API + Ollama LLM",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """Only the question is needed — all credentials come from .env"""
    question: str

    class Config:
        json_schema_extra = {
            "example": {"question": "How's our Mining sector pipeline this quarter?"}
        }


class QueryResponse(BaseModel):
    answer: str
    tool_traces: list
    data_quality_notes: list
    raw_insights: dict


# ── Singleton agent (reused across requests) ─────────────────────────────────
_agent: MondayAgent | None = None

def get_agent() -> MondayAgent:
    global _agent
    if _agent is None:
        _agent = MondayAgent(
            api_key=MONDAY_API_KEY,
            deals_board_id=DEALS_BOARD_ID,
            work_orders_board_id=WORK_ORDERS_BOARD_ID,
            ollama_host=OLLAMA_HOST,
            ollama_model=OLLAMA_MODEL,
        )
    return _agent


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def query_agent(request: QueryRequest):
    """
    Ask a business intelligence question.
    Config is loaded from .env — only send {"question": "..."}.
    """
    try:
        result = await get_agent().process_query(request.question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Check backend + Ollama connectivity"""
    import requests as req
    ollama_ok = False
    try:
        r = req.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "monday_api_key_set": bool(MONDAY_API_KEY),
        "deals_board_id": DEALS_BOARD_ID,
        "work_orders_board_id": WORK_ORDERS_BOARD_ID,
        "ollama_host": OLLAMA_HOST,
        "ollama_model": OLLAMA_MODEL,
        "ollama_reachable": ollama_ok,
    }


@app.get("/config")
async def config():
    """Return non-sensitive config so the frontend can display it"""
    return {
        "deals_board_id": DEALS_BOARD_ID,
        "work_orders_board_id": WORK_ORDERS_BOARD_ID,
        "ollama_model": OLLAMA_MODEL,
        "ollama_host": OLLAMA_HOST,
    }


if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)