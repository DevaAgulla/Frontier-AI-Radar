# Foundation Model Release Tracker

A Python tool that aggregates **foundation model release information** from multiple AI provider sources, filters results by a given date, and returns a normalized, deduplicated JSON list.

## What it tracks

- New model launches
- API updates and SDK releases
- Blog announcements (pricing, benchmarks, evaluations)
- GitHub SDK/library releases

## Sources monitored

| Provider | Source Type | URL |
|---|---|---|
| HuggingFace | JSON API (paginated) | `huggingface.co/api/models` |
| OpenAI | RSS feed | `openai.com/blog/rss.xml` |
| Anthropic | RSS feed | `anthropic.com/news/rss.xml` |
| Google DeepMind | RSS feed | `deepmind.google/blog/rss.xml` |
| Meta AI | RSS feed | `ai.meta.com/blog/rss/` |
| Mistral AI | RSS feed | `mistral.ai/news/rss.xml` |
| Cohere | RSS feed | `cohere.com/blog/rss.xml` |
| GitHub (openai-python) | JSON API (paginated) | `api.github.com/repos/openai/openai-python/releases` |

---

## Project structure

```
Foundation_models_script/
├── config.py                    # All configuration: URLs, maps, timeouts, schema
├── foundation_model_releases.py # Core logic: fetch, parse, normalize, deduplicate
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## Setup

### 1. Clone / download the project

```bash
git clone <your-repo-url>
cd Foundation_models_script
```

### 2. Create and activate a virtual environment

```bash
# Create
python -m venv venv

# Activate — Git Bash / macOS / Linux
source venv/Scripts/activate       # Windows Git Bash
source venv/bin/activate           # macOS / Linux

# Activate — Windows native
venv\Scripts\activate.bat          # Command Prompt
venv\Scripts\Activate.ps1          # PowerShell
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Running the script

### From the command line

```bash
# Fetch releases for today
python foundation_model_releases.py

# Fetch releases for a specific date (YYYY-MM-DD)
python foundation_model_releases.py 2026-03-05
```

Output is printed as a formatted JSON array to stdout.

### As a Python module

```python
from datetime import date
from foundation_model_releases import fetch_foundation_model_releases
from config import SOURCE_URLS

# Use the default configured sources
results = fetch_foundation_model_releases(SOURCE_URLS, date.today())

# Or pass a custom list of URLs
results = fetch_foundation_model_releases(
    ["https://www.anthropic.com/news/rss.xml"],
    date(2026, 3, 5),
)

for release in results:
    print(release["model_name"], "-", release["provider"])
```

---

## Configuration

All tunable settings live in **`config.py`** — no changes to the main module are needed.

| Setting | Default | Description |
|---|---|---|
| `SOURCE_URLS` | 8 provider URLs | List of feed / API URLs to query |
| `REQUEST_TIMEOUT` | `30` | HTTP timeout in seconds |
| `USER_AGENT` | tracker bot string | User-Agent header for requests |
| `MAX_PAGES` | `10` | Max pages to walk for paginated APIs |
| `PER_PAGE` | `100` | Items per page for paginated APIs |
| `PROVIDER_MAP` | see config | hostname fragment → provider name |
| `SOURCE_LABELS` | see config | hostname fragment → source identifier |
| `GITHUB_OWNER_MAP` | see config | GitHub owner → provider name |
| `RELEASE_SCHEMA` | see config | Default field template for each release |

### Adding a new source

1. Add the URL to `SOURCE_URLS` in `config.py`
2. Add a hostname entry to `PROVIDER_MAP` and `SOURCE_LABELS`
3. That's it — the script auto-detects RSS vs JSON

---

## Output format

The function returns a **JSON array**. Each item has the following fields:

```json
[
  {
    "model_name": "Claude 4",
    "provider": "Anthropic",
    "release_date": "2026-03-05",
    "model_details": "Next generation reasoning model with improved coding capabilities",
    "modalities": ["text", "vision"],
    "context_length": "200000",
    "benchmarks": {
      "MMLU": "90.2",
      "GPQA": "65.3"
    },
    "pricing": "$3 / 1M input tokens",
    "api_link": "https://docs.anthropic.com",
    "model_page": "https://www.anthropic.com/news/claude-4",
    "github_repo": null,
    "extra_information": "Supports extended thinking and tool use",
    "source": "anthropic_rss"
  }
]
```

### Field reference

| Field | Type | Description |
|---|---|---|
| `model_name` | `string` | Name of the model or release |
| `provider` | `string` | AI company / provider |
| `release_date` | `string` | Date in `YYYY-MM-DD` format |
| `model_details` | `string \| null` | Summary or description of the release |
| `modalities` | `array` | Supported input types: `text`, `vision`, `audio`, `video` |
| `context_length` | `string \| null` | Max token context window (e.g. `"200000"`) |
| `benchmarks` | `object` | Key/value benchmark scores, e.g. `{"MMLU": "90.2"}` |
| `pricing` | `string \| null` | Pricing information if available |
| `api_link` | `string \| null` | Link to API or SDK documentation |
| `model_page` | `string \| null` | Link to the announcement or model page |
| `github_repo` | `string \| null` | GitHub repository URL if applicable |
| `extra_information` | `string \| null` | Any additional details |
| `source` | `string` | Identifier of the source (e.g. `anthropic_rss`, `huggingface_api`) |

Fields not available from a source will be `null` (or `[]` / `{}` for arrays/objects).

---

## How it works

```
fetch_foundation_model_releases(urls, date)
        │
        ├── for each URL
        │       │
        │       ├── huggingface.co/api/models  →  paginated JSON  →  _parse_huggingface()
        │       ├── api.github.com/.../releases →  paginated JSON  →  _parse_github_releases()
        │       └── everything else
        │               ├── Content-Type: XML/RSS  →  _parse_rss()
        │               └── Content-Type: JSON     →  _parse_generic_json()
        │
        ├── filter:  keep only entries where date == current_date
        ├── normalize: map all fields to RELEASE_SCHEMA
        ├── deduplicate: SHA-256 on (model_name, provider, release_date)
        └── sort: alphabetically by model_name
```

---

## Error handling

- A failure on any single source is logged and skipped — other sources continue
- HTTP errors, timeouts, and malformed responses are all caught and warned
- Timestamps in any format (ISO-8601, RFC-2822, Unix epoch, feedparser struct_time) are handled

---

## Dependencies

| Package | Purpose |
|---|---|
| `httpx` | HTTP client for fetching feeds and APIs |
| `feedparser` | Parsing RSS and Atom feeds |

Both are listed in `requirements.txt`. All other imports are Python standard library.
