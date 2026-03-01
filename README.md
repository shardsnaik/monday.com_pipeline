# Monday.com BI Agent 🚀

An AI agent that answers founder-level business intelligence queries against live
Monday.com boards — powered by Ollama (self-hosted LLM), FastAPI, and Streamlit.

No credentials in API requests. No caching. Every answer comes from a fresh live
query with full tool-call traces visible in the UI.

---

## Architecture

```
┌─────────────────────────────────────────┐
│           Streamlit Frontend            │  ← conversational UI + trace panel
└────────────────────┬────────────────────┘
                     │ POST /query  {"question": "..."}
┌────────────────────▼────────────────────┐
│           FastAPI Backend               │  ← reads all config from .env
│           backend/main.py               │
└────────────────────┬────────────────────┘
                     │
┌────────────────────▼────────────────────┐
│           MondayAgent  (agent.py)       │
│                                         │
│  1. Ollama LLM  — intent extraction     │  ← question → {sector, quarter, intent}
│  2. Monday GraphQL API  (live, no cache)│  ← get_deals() + get_work_orders()
│  3. Data Normalization Layer            │  ← dates, revenue, status, encoding
│  4. Analytics Engine                   │  ← pipeline, conversion, execution, AR
│  5. Ollama LLM  — response synthesis   │  ← analytics JSON → founder narrative
└─────────────────────────────────────────┘
```

**LLM is used twice per query:**
- First call extracts `{sector, quarter, intent}` from the free-form question
- Second call writes the founder-facing narrative from the raw analytics payload

Both calls fall back gracefully if Ollama is unavailable — the agent still works
using keyword-based intent parsing and rule-based response templates.

---

## Project Structure

```
monday-agent/
│
├── agent.py                   # Core agent: Ollama + tools + analytics
│
├── backend/
│   └── main.py                # FastAPI — loads all config from .env
│
├── frontend/
│   └── app.py                 # Streamlit UI + tool traces + sector dashboard
│
├── tools/
│   ├── monday_tools.py        # Live Monday GraphQL API calls (no cache)
│   └── analytics.py           # Cross-board analytics engine
│
├── normalizer/
│   └── normalizer.py          # Data cleaning, encoding, quality reporting
│
├── setup_boards.py            # One-time: creates Monday boards + imports data
│
├── deals_clean.csv            # Preprocessed deals data (342 rows)
├── work_orders_clean.csv      # Preprocessed work orders (176 rows)
│
├── .env.example               # Config template — copy to .env
├── requirements.txt
└── README.md
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.11 or 3.12 recommended |
| Ollama | latest | Self-hosted LLM runtime |
| Monday.com account | any plan | Free plan works for setup |

---

## Step 1 — Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## Step 2 — Install and start Ollama

Ollama runs the LLM locally. No OpenAI key needed.

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows — download the installer from:
# https://ollama.com/download/windows
```

Start the server (leave this terminal open):
```bash
ollama serve
```

Pull a model (one-time download, ~4 GB):
```bash
ollama pull llama3          # recommended
# alternatives:
# ollama pull mistral       # slightly faster
# ollama pull llama3.1      # stronger reasoning, 8 GB
# ollama pull phi3          # lightweight, good for low-RAM machines
```

Verify Ollama is running:
```bash
curl http://localhost:11434/api/tags
# Returns JSON listing available models
```

---

## Step 3 — Get your Monday API key

1. Log into [monday.com](https://monday.com)
2. Click your **profile picture** (top-right corner)
3. Go to **Developers**
4. Click **My Access Tokens** → **Show** → **Copy**

---

## Step 4 — Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# ── REQUIRED ──────────────────────────────────────────────────────
MONDAY_API_KEY=your_monday_api_key_here

# ── Data files (.csv or .xlsx both work) ─────────────────────────
# Paths are relative to setup_boards.py
# On Windows: forward slashes, backslashes, and absolute paths all work
DEALS_CSV=deals_clean.csv
WORK_ORDERS_CSV=work_orders_clean.csv

# ── AUTO-FILLED by setup_boards.py — leave blank for now ─────────
DEALS_BOARD_ID=
WORK_ORDERS_BOARD_ID=

# ── Ollama ────────────────────────────────────────────────────────
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3

# ── Optional ──────────────────────────────────────────────────────
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
```

> **Windows path examples — all valid:**
> ```
> DEALS_CSV=deals_clean.csv
> DEALS_CSV=resources/deals_clean.csv
> DEALS_CSV=resources\deals_clean.csv
> DEALS_CSV=C:/Users/You/data/deals_clean.csv
> ```

---

## Step 5 — Create Monday boards and import data

Run this **once**. It creates both boards, adds all columns with the correct types,
imports your data, and writes the board IDs back into `.env` automatically.

```bash
python setup_boards.py
```

Expected output:
```
=======================================================
  Monday.com Board Setup — AI Agent
=======================================================
  API Key         : **********abc123
  Deals file      : C:\project\deals_clean.csv
  Work Orders file: C:\project\work_orders_clean.csv
=======================================================

📋 Creating Deals board...
   Board ID: 5026904196
   + Owner Code (text)
   + Deal Status (status)
   + Deal Value (INR) (numbers)
   + Close Date (date)
   ...

🗂  Creating Work Orders board...
   Board ID: 5026904198
   + Execution Status (status)
   + Amount Excl GST (INR) (numbers)
   ...

📥 Importing Deals data...
   Importing 342 rows ...
   ... 25/342 rows done
   ✅ 342 imported, 0 errors

📥 Importing Work Orders data...
   Importing 176 rows ...
   ✅ 176 imported, 0 errors

✅  Board IDs written back to .env automatically.

🎉  Setup Complete!
  DEALS_BOARD_ID       = 5026904196
  WORK_ORDERS_BOARD_ID = 5026904198
```

> **Already ran setup and boards exist?** Skip this step. Just add the board IDs
> directly to `.env`. Find them in the Monday URL when you open a board:
> `https://yourorg.monday.com/boards/5026904196`

---

## Step 6 — Start the backend

From the project root:
```bash
cd backend
uvicorn main:app --reload --port 8000
```

The server reads `.env` on startup and exits immediately with a clear error if
any required variable is missing.

Confirm it is healthy:
```bash
curl http://localhost:8000/health
```
```json
{
  "status": "ok",
  "monday_api_key_set": true,
  "deals_board_id": "5026904196",
  "work_orders_board_id": "5026904198",
  "ollama_host": "http://localhost:11434",
  "ollama_model": "llama3",
  "ollama_reachable": true
}
```

---

## Step 7 — Start the frontend

Open a **new terminal**:
```bash
cd frontend
streamlit run app.py
```

Browser opens at `http://localhost:8501`.

---

## Using the Agent

### Send a query (API)

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How is our Mining sector pipeline this quarter?"}'
```

The request body is just `{"question": "..."}` — no API keys, no board IDs.
All credentials live in `.env` on the server.

### Example questions

| Question | What the agent computes |
|---|---|
| `How's our Mining pipeline this quarter?` | Pipeline value, stage distribution, weighted expected close, early-stage risk % |
| `What's our deal-to-work-order conversion rate?` | Cross-board join: Won deals → WO matches, conversion %, revenue leakage in ₹ |
| `Show execution health for Renewables` | WO count, completed/ongoing/overdue, collection rate, sector load vs average |
| `Which sectors have AR problems?` | Receivables by sector, stuck billing, priority accounts |
| `Compare all sectors` | Full matrix: pipeline × conversion × collection × overdue rate |
| `Overall summary — how are we doing?` | Complete health report across both boards |

### Visible tool-call traces

Every response in the UI shows exactly what ran:

```
▶ extract_intent_with_llm()       model=llama3 · latency=340ms
▶ get_deals()                     boards(ids=5026904196) · 342 records · 180ms
▶ get_work_orders()               boards(ids=5026904198) · 176 records · 162ms
▶ normalize_deals()               342 in → 342 out · 3 quality flags
▶ normalize_work_orders()         176 in → 176 out · 2 quality flags
▶ pipeline_summary()              sector=Mining · Q1 2026 · ₹45,48,38,416
▶ conversion_analysis()           163 Closed Won · 14.7% conversion · ₹leakage
▶ execution_health()              100 WOs · 0% overdue · 68% collection rate
▶ collections_analysis()          ₹4,82,19,188 receivable · 0 stuck
▶ sector_performance_matrix()     6 sectors analyzed
▶ synthesise_response_with_llm()  model=llama3 · latency=2840ms
```

---

## Data Quality Notes

The normalizer detects and reports these issues inline with every answer:

| Issue in source data | How it is handled |
|---|---|
| Deal Value missing — 51.8% of deals | Flagged every response: "pipeline totals understated" |
| Closure Probability missing — 74.9% | Falls back to stage-based probability model |
| Close Date missing — 20.8% after merge | `Close Date (A)` merged with `Tentative Close Date` |
| WO Collected Amount missing — 55.7% | Flagged in AR analysis |
| Billing Status missing — 84.1% | Excluded from aggregations |
| Deal Stage uses coded labels (A–O) | Mapped: `"G. Project Won"` → `"Won"`, etc. |
| Execution Status has 7 raw variants | Normalised to 5: Completed / Ongoing / Not Started / Paused / Partially Completed |
| `.xlsx` Work Orders file | Auto-detected, read via pandas |
| CSV BOM / Windows encoding | Tries utf-8-sig → utf-8 → latin-1 → cp1252 automatically |

---

## Cross-Board Intelligence

The key feature is the **Deals → Work Orders join**. Both boards share masked
deal names (e.g. "Naruto", "Scooby-Doo") as the linking key.

```
Deals board                  Work Orders board
────────────────             ──────────────────
Deal Name  ─────────────────→ Deal Name
Deal Status = Won             Execution Status
Deal Value (INR)              Amount Excl GST (INR)
Sector                        Sector
Close Date                    Start Date / End Date
```

From this join the agent computes:

- **Conversion rate** — % of Won deals that have a matching Work Order
- **Revenue leakage** — Won deal value with no corresponding Work Order (₹)
- **Execution backlog** — WO load per sector vs cross-sector average
- **Collection gap** — contract value vs amount actually collected

---

## Troubleshooting

**`MONDAY_API_KEY is not set` on startup**
→ `.env` file is missing or not in the project root. The script prints the exact
path it looked at — verify the file is there, not `.env.example`.

**`File not found: resources\deals_clean.csv`**
→ The path in `DEALS_CSV` is resolved relative to `setup_boards.py`. The script
prints the full resolved path at startup — compare it to where your file actually is.

**`UnicodeDecodeError` when reading CSV**
→ The script auto-tries four encodings. If it still fails, open the CSV in
Notepad and **Save As → Encoding: UTF-8**.

**`Rate limited — waiting 10s` during import**
→ Normal on Monday's free tier (~60 requests/min). The script retries automatically
with exponential back-off. Just let it run.

**`Ollama not reachable` in `/health`**
→ Run `ollama serve` in a separate terminal. If Ollama is on another machine,
set `OLLAMA_HOST=http://<ip>:11434` in `.env`.

**Responses look template-based, not LLM-generated**
→ Ollama is not running or the model is not pulled. Run:
```bash
ollama serve          # in one terminal
ollama pull llama3    # in another terminal
```

**`GraphQL Error: column_title_taken`**
→ That column already exists on the board. The script skips it automatically.

**Backend exits immediately at startup**
→ A required `.env` variable is missing. The exit message names exactly which one.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `MONDAY_API_KEY` | ✅ Yes | — | Monday.com personal API token |
| `DEALS_BOARD_ID` | ✅ Yes | — | Auto-written by `setup_boards.py` |
| `WORK_ORDERS_BOARD_ID` | ✅ Yes | — | Auto-written by `setup_boards.py` |
| `DEALS_CSV` | Setup only | `deals_clean.csv` | Path to deals file (.csv or .xlsx) |
| `WORK_ORDERS_CSV` | Setup only | `work_orders_clean.csv` | Path to work orders file |
| `OLLAMA_HOST` | No | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | No | `llama3` | Model name (must be pulled first) |
| `BACKEND_HOST` | No | `0.0.0.0` | FastAPI bind host |
| `BACKEND_PORT` | No | `8000` | FastAPI bind port |

---

## API Reference

### `POST /query`
```json
// Request — only the question
{"question": "How is our Renewables pipeline?"}

// Response
{
  "answer": "### Renewables — Q1 2026\n...",
  "tool_traces": [
    {"tool": "extract_intent_with_llm()", "latency_ms": 340, ...},
    {"tool": "get_deals()", "records_retrieved": 342, ...},
    ...
  ],
  "data_quality_notes": [
    "⚠️ 51.8% of deal values are missing — pipeline totals understated."
  ],
  "raw_insights": {
    "pipeline": {...},
    "conversion": {...},
    "execution": {...},
    "collections": {...},
    "sector_matrix": [...]
  }
}
```

### `GET /health`
Returns connectivity status for Monday API, Ollama, and loaded board IDs.

### `GET /config`
Returns non-sensitive runtime config (board IDs, model, host) for the frontend.