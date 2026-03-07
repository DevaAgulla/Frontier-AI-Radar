# Frontier AI Radar — Frontend

Next.js 16 web dashboard for Frontier AI Radar. Manage intelligence sources, trigger pipeline runs, explore findings, download PDF digests, and configure scheduled email delivery.

---

## Prerequisites

- Node.js 18+
- npm
- A running Frontier AI Radar backend (see [Backend README](../Backend/README.md))

---

## Setup

### 1. Install dependencies

```bash
cd frontend
npm install
```

### 2. Configure the backend URL

By default the frontend proxies all API calls through its own Next.js API routes, which point to the deployed Railway backend.

To point at your **local** backend instead, open `lib/backend.ts` and swap the `configured` variable:

```ts
// lib/backend.ts
const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8000/api/v1";

export function getBackendBaseUrl(): string {
  const configured = DEFAULT_BACKEND_BASE;  // <-- change this line
  ...
}
```

### 3. Start the development server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard — last run status + top 10 findings today |
| `/run` | Build Report — drag agents into the pipeline and trigger a run |
| `/config` | Competitor Report — submit any URL for instant competitor intelligence |
| `/runs` | Run History — live status tracking for every pipeline run |
| `/findings` | Findings Explorer — filter by agent, category, entity, or run |
| `/sources` | Sources — manage competitor URLs (add, toggle active, delete) |
| `/archive` | Digest Archive — browse and download past PDF reports |
| `/scheduler` | Scheduler — subscribe your email for daily automated delivery |
| `/compare` | Compare — diff findings between two runs or dates |
| `/benchmarks` | Benchmarks — HuggingFace leaderboard movements |
| `/reports` | Reports — PDF report viewer |
| `/auth` | Login / Register |
| `/profile` | User profile |
| `/settings` | App settings |

---

## Project Structure

```
frontend/
├── app/
│   ├── page.tsx              # Dashboard
│   ├── layout.tsx            # Root layout (sidebar + nav)
│   ├── globals.css           # Global styles + CSS variables
│   │
│   ├── run/page.tsx          # Build Report (drag-and-drop agents)
│   ├── config/page.tsx       # Competitor Report (custom URL)
│   ├── runs/page.tsx         # Run History
│   ├── findings/page.tsx     # Findings Explorer
│   ├── sources/page.tsx      # Sources management
│   ├── archive/page.tsx      # Digest Archive
│   ├── scheduler/page.tsx    # Scheduler subscription
│   ├── compare/page.tsx      # Run comparison / diff view
│   ├── benchmarks/page.tsx   # HF Benchmark leaderboard
│   │
│   ├── components/           # Shared UI components
│   │   ├── Sidebar.tsx
│   │   ├── AgentPipelineDragDrop.tsx
│   │   ├── EmailRecipients.tsx
│   │   ├── URLInput.tsx
│   │   └── ...
│   │
│   ├── context/              # React contexts
│   │   ├── AuthContext.tsx   # JWT auth (login, register, user state)
│   │   ├── RunConfigContext.tsx
│   │   └── ToastContext.tsx
│   │
│   └── api/                  # Next.js API route proxies to backend
│       ├── runs/route.ts     # POST trigger run, GET list runs
│       ├── sources/[id]/route.ts
│       ├── dashboard/route.ts
│       └── ...
│
├── lib/
│   ├── api.ts                # Frontend API client (all fetch calls)
│   ├── backend.ts            # Backend base URL + fetchBackend()
│   └── types.ts              # Shared TypeScript types
│
├── package.json
├── next.config.ts
└── tsconfig.json
```

---

## Triggering a Run

### Full pipeline run

1. Go to **Build Report** (`/run`)
2. Drag one or more agents into the pipeline (Research, Competitor, Model, Benchmark)
3. Click **Run agents** — fires asynchronously
4. Redirected to **Runs** (`/runs`) for live status

### Competitor-only run on a custom URL

1. Go to **Competitor Report** (`/config`)
2. Paste any competitor URL (e.g. `https://openai.com/blog`)
3. Optionally add extra recipient emails to CC on the report
4. Click **Submit**

---

## Authentication

The app has optional user accounts backed by the backend's JWT auth.

- **Register** at `/auth` — name, email, password
- Once logged in, your email is automatically used as the PDF recipient when you trigger any run
- Extra emails entered in the run form are CC'd on top of your account email
- Without an account, you can still trigger runs by entering recipient emails manually

---

## Deploying to Vercel

1. Push your repo to GitHub
2. Go to [vercel.com](https://vercel.com) → **New Project** → Import your repo
3. Set the **Root Directory** to `frontend`
4. Deploy — no additional environment variables required (backend URL is set in `lib/backend.ts`)

To override the backend URL at deploy time, add this variable in Vercel's project settings and update `lib/backend.ts` to read from it:

```
NEXT_PUBLIC_BACKEND_URL=https://your-railway-backend.up.railway.app/api/v1
```

---

## Available Scripts

```bash
npm run dev      # Start development server at http://localhost:3000
npm run build    # Production build (type-check + compile)
npm run start    # Start production server (after build)
npm run lint     # Run ESLint
```

---

## Tech Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| Next.js | 16 | App framework + API route proxies |
| React | 19 | UI |
| TypeScript | 5 | Type safety |
| Tailwind CSS | 4 | Styling |
