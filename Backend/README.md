# Frontier AI Radar — Backend

FastAPI + LangGraph multi-agent pipeline that crawls AI sources, ranks findings, generates a PDF digest, and emails it automatically.

---

## Architecture

```
START
  └── Mission Controller        (sets run objectives)
        └── Strategy Planner    (plans per-agent instructions)
              ├── Research Intel Agent      (arXiv + Semantic Scholar)
              ├── Competitor Intel Agent    (blogs, changelogs, RSS)
              ├── Model Intel Agent         (HuggingFace API + GitHub)
              └── Benchmark Intel Agent     (HF leaderboards)
                    └── intel_join          (fan-in convergence)
                          └── Verification Agent (optional SOTA checks)
                                └── Ranking Agent   (deterministic scoring)
                                      └── Digest Agent    (executive summary)
                                            └── Report Generator (PDF via Jinja2)
                                                  └── Notification Agent (email)
                                                        └── END
```

Impact scoring formula used by the Ranking Agent:

```
Impact = 0.35 × Relevance + 0.25 × Novelty + 0.20 × Credibility + 0.20 × Actionability
```

All four intelligence agents run **in parallel** via LangGraph fan-out. One agent failing never blocks the digest.

---

## Prerequisites

- Python 3.12+
- pip

---

## Setup

### 1. Install dependencies

```bash
cd Backend
pip install -r requirements.txt
```

### 2. Create your `.env` file

Copy the template below, save it as `Backend/.env`, and fill in your keys:

```env
# ── LLM (pick one backend) ─────────────────────────────────────────────────

# Option A: OpenRouter (recommended — gives access to Claude)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
LLM_BACKEND=openrouter

# Option B: Google Gemini
# GEMINI_API_KEY=AIza...
# GEMINI_MODEL=gemini-2.0-flash
# LLM_BACKEND=gemini

# ── Email delivery ──────────────────────────────────────────────────────────

# Brevo (recommended — 300 free emails/day, works with any recipient)
BREVO_API_KEY=xkeysib-...

# The "From" address (must be verified in Brevo)
EMAIL_FROM=your-email@example.com

# Default recipients for scheduled runs (comma-separated)
EMAIL_RECIPIENTS=you@example.com,teammate@example.com

# ── API security ────────────────────────────────────────────────────────────

# Any long random string — used to sign JWT tokens
API_SECRET_KEY=change-me-to-a-long-random-secret

# ── Optional enrichment APIs ────────────────────────────────────────────────

# HuggingFace — needed for Model Intel and Benchmark Intel agents
HF_API_TOKEN=hf_...

# Tavily — web search fallback (free tier available)
TAVILY_API_KEY=tvly-...

# Semantic Scholar — research paper search (free, no key required for basic use)
SEMANTIC_SCHOLAR_API_KEY=

# ── Scheduler ───────────────────────────────────────────────────────────────

# Time of daily automated run (24-hour format)
DAILY_RUN_TIME=17:00
TIMEZONE=Asia/Kolkata

# ── LangSmith observability (optional) ─────────────────────────────────────

LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=frontier-ai-radar

# ── Storage paths (defaults work out of the box) ───────────────────────────

DATABASE_URL=sqlite:///db/frontier_ai_radar.db
LONG_TERM_MEMORY_PATH=data/long_term
ENTITY_STORE_PATH=data/entity_store
REPORTS_OUTPUT_PATH=data/reports

# ── PDF branding ─────────────────────────────────────────────────────────────

PDF_BRAND_NAME=Frontier AI Radar
PDF_BRAND_COLOR=#2563eb

# ── SMTP fallback (only if not using Brevo) ──────────────────────────────────

# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your@gmail.com
# SMTP_PASSWORD=your-app-password
```

### 3. Start the API server

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is now live at `http://localhost:8000`.

Interactive API docs: `http://localhost:8000/docs`

---

## Running the Pipeline

### Manual trigger via API

```bash
# Full pipeline — all 4 intelligence agents
curl -X POST http://localhost:8000/api/v1/pipeline/run/async \
  -H "Content-Type: application/json" \
  -d '{"mode": "full", "since_days": 1}'

# Competitor-only run on a specific URL
curl -X POST http://localhost:8000/api/v1/pipeline/run/async \
  -H "Content-Type: application/json" \
  -d '{"mode": "competitor", "urls": ["https://openai.com/blog"], "url_mode": "custom"}'
```

### Scheduled automatic run

The scheduler starts automatically with the API server. It fires the full pipeline at `DAILY_RUN_TIME` every day and emails all subscribed users.

To subscribe an email:

```bash
curl -X POST http://localhost:8000/api/v1/scheduler/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "name": "Your Name"}'
```

---

## Project Structure

```
Backend/
├── agents/                  # All LangGraph agent nodes
│   ├── base_agent.py        # Shared ReAct agent builder + helpers
│   ├── mission_controller.py
│   ├── strategy_planner.py
│   ├── research_intel.py    # arXiv + Semantic Scholar
│   ├── competitor_intel.py  # Blogs, changelogs, RSS feeds
│   ├── model_intel.py       # HuggingFace API + GitHub releases
│   ├── benchmark_intel.py   # HF leaderboards
│   ├── verification.py      # SOTA claim checker
│   ├── ranking.py           # Deterministic impact scoring
│   ├── digest.py            # Executive summary compiler
│   ├── report_generator.py  # Jinja2 → PDF (deterministic, no LLM)
│   └── notification.py      # Email delivery (deterministic send)
│
├── api/
│   └── main.py              # FastAPI app — all endpoints
│
├── pipeline/
│   ├── graph.py             # LangGraph StateGraph definition
│   ├── runner.py            # run_radar() entry point
│   ├── scheduler.py         # APScheduler daily cron job
│   ├── router.py            # Conditional edge functions
│   └── state.py             # RadarState TypedDict + Finding schema
│
├── core/
│   ├── tools.py             # All LangChain @tool definitions
│   ├── fetcher.py           # HTTP + headless fetch utilities
│   ├── extractor.py         # HTML/RSS → text extraction
│   ├── research_crawler.py  # arXiv + Semantic Scholar crawler
│   ├── foundation_model_releases.py  # HF API + GitHub release fetcher
│   ├── hf_benchmark_tracker.py       # HF leaderboard tracker
│   ├── ranker.py            # Impact score math
│   └── change_detector.py  # Content fingerprinting + diff
│
├── memory/
│   ├── long_term.py         # JSON file-based persistent memory
│   ├── short_term.py        # LangGraph state read/write helpers
│   └── entity_store.py      # ChromaDB vector store
│
├── db/
│   ├── models.py            # SQLAlchemy ORM (User, Run, Finding, etc.)
│   ├── persist.py           # DB read/write helpers
│   └── connection.py        # SQLite session factory
│
├── config/
│   ├── settings.py          # Pydantic Settings (loads .env)
│   ├── sources.yaml         # Default source URLs per agent
│   └── scoring.yaml         # Scoring weights
│
├── templates/
│   └── digest.html          # Jinja2 PDF template
│
├── requirements.txt
└── .env                     # Your secrets (never commit this)
```

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/pipeline/run` | Synchronous run (waits for completion) |
| `POST` | `/api/v1/pipeline/run/async` | Async run (returns immediately, poll `/runs`) |
| `GET` | `/api/v1/runs` | List all past runs |
| `GET` | `/api/v1/runs/{id}` | Get a single run with status |
| `GET` | `/api/v1/findings` | Query findings (filter by agent, category, entity) |
| `GET` | `/api/v1/digests` | List digests |
| `GET` | `/api/v1/digests/{id}/pdf` | Download a PDF |
| `POST` | `/api/v1/scheduler/subscribe` | Subscribe email for daily delivery |
| `GET` | `/api/v1/scheduler/subscribers` | List all subscribers |
| `GET` | `/api/v1/sources/competitors` | List competitor sources |
| `POST` | `/api/v1/sources/competitors` | Add a competitor source |
| `POST` | `/api/v1/auth/register` | Register a user account |
| `POST` | `/api/v1/auth/login` | Login and receive JWT token |

Full interactive docs at `http://localhost:8000/docs` once the server is running.

---

## Docker

```bash
# From the repo root
docker build -t frontier-ai-radar .
docker run -p 8000:8000 --env-file Backend/.env frontier-ai-radar
```

---

## Deploying to Railway

1. Push repo to GitHub
2. Create a new Railway project → **Deploy from GitHub repo**
3. Set the **Root Directory** to `/` (uses the `Dockerfile` at repo root)
4. Add all `.env` variables in Railway's **Variables** tab
5. Railway auto-assigns a public URL — copy it into the frontend's environment as `NEXT_PUBLIC_BACKEND_URL`

---

## Minimum Required Keys to Get Started

| Key | Where to get it | Required? |
|-----|----------------|-----------|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) | Yes (or use Gemini) |
| `BREVO_API_KEY` | [brevo.com](https://brevo.com) | Yes (for email) |
| `EMAIL_FROM` | Your verified Brevo sender | Yes |
| `EMAIL_RECIPIENTS` | Any email address | Yes |
| `API_SECRET_KEY` | Any random string | Yes |
| `HF_API_TOKEN` | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | Recommended |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) | Optional |
