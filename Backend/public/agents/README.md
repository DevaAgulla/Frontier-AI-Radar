# Agent icons

Place the four agent images in this folder with these exact file names so the app can display them:

| File name | Agent |
|-----------|--------|
| `agent-competitor-releases.png` | Competitor releases (magnifying glass + people) |
| `agent-foundation-model.png` | Foundation model provider releases (document with sparkles) |
| `agent-research-publications.png` | Latest research publications (network / LLM) |
| `agent-huggingface-benchmarks.png` | Hugging Face benchmarking results (friendly face) |

**Location:** `frontier-ai-radar/public/agents/`

**Supported formats:** PNG, SVG, or JPG. If you use SVG or JPG, rename the references in `app/components/AgentCards.tsx` (e.g. change `.png` to `.svg` or `.jpg` in the `imagePath` for each agent).

Until these files are added, the UI shows inline SVG placeholders for each agent.
