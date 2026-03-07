# Frontier AI Radar

A fully automated daily multi-agent intelligence system that tracks competitor releases, foundation model updates, research publications, and HuggingFace benchmark results — and delivers a branded PDF digest to your inbox every day.

Built with Claude + LangGraph. Six pipeline layers. Eleven agents. Real data.

---

## What It Does

- **Competitor Intel** — crawls product blogs and changelogs (OpenAI, Anthropic, Google, and any URL you add) and detects real product/API/pricing changes
- **Foundation Model Intel** — tracks model releases across 8 major AI orgs via HuggingFace API, RSS feeds, and GitHub releases
- **Research Intel** — scans arXiv (cs.CL, cs.LG, stat.ML) and Semantic Scholar for papers that matter
- **Benchmark Intel** — monitors HuggingFace leaderboards for SOTA movements and trending models
- **Digest + PDF** — compiles all findings into a ranked, deduplicated, branded PDF report
- **Email Delivery** — sends the PDF + inline summary to any email, automatically every day at a configured time
- **Web Dashboard** — manage sources, trigger runs, browse findings, download PDFs, compare run diffs

---

## Repository Structure

```
Frontier-AI-Radar/
├── Backend/          # Python FastAPI + LangGraph multi-agent pipeline
├── frontend/         # Next.js 16 web dashboard
└── Dockerfile        # Docker build for the backend (Railway-ready)
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai) API key (Claude access) **or** a Google Gemini API key
- A [Brevo](https://brevo.com) API key for email delivery (free tier: 300 emails/day)

### 1. Clone the repo

```bash
git clone https://github.com/your-org/Frontier-AI-Radar.git
cd Frontier-AI-Radar
```

### 2. Set up the Backend

```bash
cd Backend
cp .env.example .env   # fill in your keys (see Backend/README.md)
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Set up the Frontend

```bash
cd frontend
npm install
# Set NEXT_PUBLIC_BACKEND_URL if needed (defaults to local backend)
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 4. Run via Docker (optional)

```bash
docker build -t frontier-ai-radar .
docker run -p 8000:8000 --env-file Backend/.env frontier-ai-radar
```

---

## Deployment

| Service | Platform |
|---------|----------|
| Backend | [Railway](https://railway.app) — point to the `Dockerfile` at repo root |
| Frontend | [Vercel](https://vercel.com) — point to the `frontend/` directory |

Set all environment variables in each platform's dashboard (same keys as the `.env` file).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph + LangChain |
| LLM | Claude via OpenRouter (or Gemini fallback) |
| Backend API | FastAPI + Uvicorn |
| Database | SQLite (SQLAlchemy ORM) — zero config |
| PDF generation | xhtml2pdf + Jinja2 |
| Email delivery | Brevo (primary), SMTP (fallback) |
| Scheduler | APScheduler |
| Frontend | Next.js 16 + TypeScript + Tailwind CSS |
| Memory | JSON long-term store + ChromaDB entity store |

---

## Detailed Setup

- [Backend README](./Backend/README.md) — API keys, `.env` reference, pipeline overview
- [Frontend README](./frontend/README.md) — environment variables, pages guide, deployment

---

## License

MIT
