# Research Publications Crawler

A reusable Python function that fetches AI/ML research papers from 7 sources and returns a unified JSON result. Designed to be imported into any project.

---

## Files

| File | Purpose |
|---|---|
| `crawler.py` | Main module — contains `crawl_research_papers()` |
| `config.py` | Source URLs and per-source parameters |
| `README.md` | This file |

---

## Installation

```bash
pip install httpx
```

---

## Quick Start

```python
from crawler import crawl_research_papers
from config import RESEARCH_PUBLICATION_URLS

# Fetch all sources with today's date
result = crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)

print(result["total"])                          # e.g. 1847
print(result["sources"]["arxiv"]["count"])      # e.g. 100
print(result["sources"]["arxiv"]["papers"][0])  # first paper dict
```

---

## Function Signature

```python
def crawl_research_papers(
    sources:    list[dict],
    crawl_date: date | None = None,
    start_date: date | None = None,
    end_date:   date | None = None,
) -> dict
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `sources` | `list[dict]` | **required** | List of source configs from `config.py` |
| `crawl_date` | `date` | `date.today()` | Date for daily sources (OpenAlex, HuggingFace, PubMed, ACL) |
| `start_date` | `date` | `crawl_date` | Start of date range for ArXiv and Semantic Scholar |
| `end_date` | `date` | `crawl_date` | End of date range for ArXiv and Semantic Scholar |

---

## Usage Examples

### 1. Fetch everything with today's date
```python
from crawler import crawl_research_papers
from config import RESEARCH_PUBLICATION_URLS

result = crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)
```

### 2. Fetch for a specific date
```python
from datetime import date

result = crawl_research_papers(
    sources=RESEARCH_PUBLICATION_URLS,
    crawl_date=date(2026, 3, 4),
)
```

### 3. Fetch with a date range (ArXiv spans multiple days)
```python
result = crawl_research_papers(
    sources=RESEARCH_PUBLICATION_URLS,
    crawl_date=date(2026, 3, 5),   # used by OpenAlex, HuggingFace, PubMed
    start_date=date(2026, 3, 4),   # ArXiv range start
    end_date=date(2026, 3, 5),     # ArXiv range end
)
```

### 4. Use only specific sources
```python
selected = [s for s in RESEARCH_PUBLICATION_URLS
            if s["name"] in ("arxiv", "huggingface_papers", "pubmed")]

result = crawl_research_papers(sources=selected)
```

### 5. Convert result to JSON string
```python
import json

json_str = json.dumps(result, indent=2, ensure_ascii=False)
print(json_str)
```

### 6. Save to file
```python
with open("papers.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
```

### 7. Use in an API (FastAPI example)
```python
from fastapi import FastAPI
from crawler import crawl_research_papers
from config import RESEARCH_PUBLICATION_URLS

app = FastAPI()

@app.get("/papers")
def get_papers():
    return crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)
```

---

## Return Value (JSON Schema)

```json
{
  "crawl_date":   "2026-03-05",
  "start_date":   "2026-03-05",
  "end_date":     "2026-03-05",
  "generated_at": "2026-03-05T10:00:00.000000+00:00",
  "total":        1847,
  "sources": {
    "arxiv":             { "count": 100,  "papers": [...] },
    "openalex":          { "count": 6,    "papers": [...] },
    "huggingface_papers":{ "count": 16,   "papers": [...] },
    "pubmed":            { "count": 64,   "papers": [...] },
    "openreview":        { "count": 1756, "papers": [...] }
  }
}
```

On source error:
```json
"source_name": { "count": 0, "error": "error message" }
```

---

## Paper Object Schemas

### ArXiv
```json
{
  "id":               "2603.04390v1",
  "title":            "...",
  "abstract":         "...",
  "authors":          ["Author One", "Author Two"],
  "published":        "2026-03-04T18:53:25Z",
  "updated":          "2026-03-04T18:53:25Z",
  "abstract_url":     "https://arxiv.org/abs/2603.04390v1",
  "pdf_url":          "https://arxiv.org/pdf/2603.04390v1",
  "primary_category": "cs.AI",
  "categories":       ["cs.AI", "cs.LG"],
  "doi":              null,
  "comment":          "Submitted to ...",
  "journal_ref":      null,
  "source":           "arxiv"
}
```

### OpenAlex
```json
{
  "id":               "https://openalex.org/W...",
  "doi":              "https://doi.org/...",
  "title":            "...",
  "abstract":         "...",
  "authors":          ["Author One"],
  "institutions":     ["MIT", "Stanford"],
  "published":        "2026-03-05",
  "publication_year": 2026,
  "type":             "article",
  "language":         "en",
  "abstract_url":     "https://...",
  "pdf_url":          "https://...",
  "oa_url":           "https://...",
  "is_open_access":   true,
  "oa_status":        "green",
  "primary_topic": {
    "name":     "Large Language Models",
    "subfield": "Artificial Intelligence",
    "field":    "Computer Science",
    "domain":   "Physical Sciences"
  },
  "topics":           [{ "name": "...", "subfield": "...", "field": "..." }],
  "keywords":         ["llm", "agent"],
  "concepts":         ["Natural language processing"],
  "cited_by_count":   0,
  "referenced_works_count": 42,
  "venue":            "arXiv",
  "venue_type":       "repository",
  "is_retracted":     false,
  "biblio":           { "volume": null, "issue": null, "first_page": null, "last_page": null },
  "updated_date":     "2026-03-05T...",
  "source":           "openalex"
}
```

### HuggingFace Papers
```json
{
  "id":                  "2603.04379",
  "title":               "...",
  "abstract":            "...",
  "ai_summary":          "One-sentence AI-generated summary",
  "ai_keywords":         ["autoregressive", "video generation"],
  "authors":             ["Author One", "Author Two"],
  "organization":        "ByteDance",
  "published":           "2026-03-04T18:45:21.000Z",
  "submitted_on_daily":  "2026-03-05T00:52:45.624Z",
  "abstract_url":        "https://arxiv.org/abs/2603.04379",
  "pdf_url":             "https://arxiv.org/pdf/2603.04379",
  "hf_page":             "https://huggingface.co/papers/2603.04379",
  "thumbnail":           "https://cdn-thumbnails.huggingface.co/...",
  "media_urls":          ["https://cdn-uploads.huggingface.co/...mp4"],
  "upvotes":             89,
  "num_comments":        2,
  "submitted_by":        "taesiri",
  "source":              "huggingface_papers"
}
```

### PubMed
```json
{
  "id":           "41782065",
  "title":        "...",
  "abstract":     "...",
  "authors":      ["First Last"],
  "affiliations": ["Department of ..., University of ..."],
  "published":    "2026-Mar-04",
  "journal":      "Nature Medicine",
  "doi":          "10.xxxx/...",
  "abstract_url": "https://pubmed.ncbi.nlm.nih.gov/41782065",
  "pdf_url":      "https://doi.org/10.xxxx/...",
  "mesh_terms":   ["Deep Learning", "Natural Language Processing"],
  "source":       "pubmed"
}
```

### OpenReview
```json
{
  "id":           "PwxYoMvmvy",
  "title":        "...",
  "abstract":     "...",
  "tldr":         "...",
  "authors":      ["Author One", "Author Two"],
  "keywords":     ["LLM", "alignment", "benchmark"],
  "primary_area": "alignment, fairness, safety, privacy",
  "venue":        "ICLR 2025 Oral",
  "venue_id":     "ICLR.cc/2025/Conference",
  "abstract_url": "https://openreview.net/forum?id=PwxYoMvmvy",
  "pdf_url":      "https://openreview.net/pdf/...",
  "submitted_at": "2024-09-28T11:59:23+00:00",
  "source":       "openreview"
}
```

---

## Config Reference (`config.py`)

Each entry in `RESEARCH_PUBLICATION_URLS`:

```python
{
    "name":   str,   # unique source identifier
    "url":    str,   # base API URL
    "type":   str,   # dispatcher key (see supported types below)
    "params": dict,  # source-specific parameters
}
```

### Supported types and their params

| type | key params |
|---|---|
| `arxiv` | `search_topics`, `categories`, `max_results` |
| `openalex` | `per_page`, `max_fetch` |
| `huggingface_papers` | _(none required)_ |
| `pubmed` | `query`, `max_results` |
| `openreview` | `venues` (list), `per_page`, `max_per_venue` |

---

## Adding a Custom Source

1. Add an entry to `RESEARCH_PUBLICATION_URLS` in `config.py` with `"type": "my_source"`
2. In `crawler.py`, add a fetcher function `_fetch_my_source(base_url, params, crawl_date, start_date, end_date) -> list[dict]`
3. Register it in `_FETCHERS`:
   ```python
   _FETCHERS["my_source"] = lambda cfg, d, s, e: _fetch_my_source(cfg["url"], cfg.get("params", {}), d, s, e)
   ```

---

## Rate Limits & API Keys

| Source | Limit (no key) | How to get a key |
|---|---|---|
| ArXiv | ~3 req/sec | No key needed |
| OpenAlex | Polite pool | No key needed (add `?mailto=you@example.com`) |
| HuggingFace | Generous | No key needed |
| Semantic Scholar | 1 req/sec | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) |
| PubMed | 3 req/sec | No key needed (10/sec with key from NCBI) |
| OpenReview | No stated limit | No key needed |
| ACL Anthology | Uses S2 limits | Same as Semantic Scholar |

Set `api_key` inside `params` in `config.py` for Semantic Scholar / ACL.

---

## Run as Script

```bash
python crawler.py
```

Fetches all sources for today's date and saves `papers_YYYYMMDD_YYYYMMDD.json`.
