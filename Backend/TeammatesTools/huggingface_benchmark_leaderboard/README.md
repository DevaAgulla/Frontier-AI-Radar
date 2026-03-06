# Hugging Face Benchmark & Leaderboard Tracker (HFAgent)

Monitor Hugging Face for latest benchmarking results and trends. **All data is fetched in real time from official Hugging Face APIs and datasets** — no dummy data, no external LLM (e.g. no Claude). This agent uses only Hugging Face as the data source.

## Single function: call from your code

Use **one function** to fetch data and generate reports. Import and call it from any Python project.

### Basic call (defaults from `config.py`)

```python
from main import generate_hf_benchmark_report

result = generate_hf_benchmark_report()
# Reports written to output/report.html and output/report.txt
print(result["html_path"])   # Path to report.html
print(result["txt_path"])    # Path to report.txt
```

### With parameters

```python
from main import generate_hf_benchmark_report

result = generate_hf_benchmark_report(
    output_dir="./my_reports",           # where to write files
    track_leaderboard=True,              # fetch Open LLM Leaderboard
    track_trending=True,                 # fetch trending models
    track_eval_datasets=True,            # fetch official eval datasets
    leaderboard_top_n=30,                # max leaderboard models
    trending_sort="trending_score",      # or "downloads", "likes"
    trending_limit=20,
    eval_datasets_limit=15,
    eval_datasets_search=None,           # optional filter, e.g. "reasoning"
    write_txt=True,                      # write report.txt
    write_html=True,                     # write report.html
    verbose=True,                        # print progress (set False when calling from scripts)
)

# Return value
assert result["html_path"] is not None
assert result["txt_path"] is not None
# Raw data for your own use:
leaderboard = result["leaderboard_data"]
trending = result["trending_data"]
datasets = result["eval_datasets_data"]
# Or use the generated content in memory:
html_string = result["html_content"]
txt_string = result["txt_content"]
```

### Parameters reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_dir` | str or Path | `config.OUTPUT_DIR` ("output") | Directory for report files. |
| `track_leaderboard` | bool | from config (True) | Fetch Open LLM Leaderboard. |
| `track_trending` | bool | from config (True) | Fetch trending models. |
| `track_eval_datasets` | bool | from config (True) | Fetch official eval datasets. |
| `leaderboard_top_n` | int | from config (50) | Max leaderboard models to fetch. |
| `trending_sort` | str | from config ("trending_score") | Sort: `"trending_score"`, `"downloads"`, `"likes"`, etc. |
| `trending_limit` | int | from config (30) | Max trending models. |
| `eval_datasets_limit` | int | from config (25) | Max eval datasets. |
| `eval_datasets_search` | str or None | from config (None) | Optional search filter for datasets. |
| `write_txt` | bool | True | Write `report.txt`. |
| `write_html` | bool | True | Write `report.html`. |
| `verbose` | bool | True | Print progress to stdout. |

### Return value

The function returns a **dict** with:

| Key | Type | Description |
|-----|------|-------------|
| `html_path` | Path or None | Path to `report.html` (None if `write_html=False`). |
| `txt_path` | Path or None | Path to `report.txt` (None if `write_txt=False`). |
| `leaderboard_data` | list | Raw leaderboard rows (list of dicts). |
| `trending_data` | list | Raw trending model rows. |
| `eval_datasets_data` | list | Raw eval dataset rows. |
| `html_content` | str or None | Full HTML string (None if `write_html=False`). |
| `txt_content` | str or None | Full text report (None if `write_txt=False`). |

### Call from another project (same machine)

**Option A — HFAgent is a subfolder of your project**

```python
import sys
sys.path.insert(0, "/path/to/parent/of/HFAgent")  # so "HFAgent" package is found

from HFAgent import generate_hf_benchmark_report

result = generate_hf_benchmark_report(output_dir="./reports", verbose=False)
```

**Option B — run or import from inside the HFAgent directory**

```python
# From inside c:\...\HFAgent or with HFAgent on sys.path
from main import generate_hf_benchmark_report

result = generate_hf_benchmark_report(output_dir="./reports", verbose=False)
```

---

## What it tracks (configurable)

- **Open LLM Leaderboard** — Live data from the HF dataset `open-llm-leaderboard/contents` (scores, tasks: ARC, HellaSwag, MMLU, TruthfulQA, Winogrande, GSM8k).
- **Trending models** — From HF API `list_models(sort="trending_score" | "downloads" | "likes")`.
- **Evaluation datasets** — Official benchmark datasets via HF API `list_datasets(benchmark="official")`.

## Output focus

- Who's on top / task breakdown (leaderboard).
- Trending and popular models (engagement metrics).
- Official evaluation datasets of interest.
- Caveats (leaderboard bias, different eval settings, reproducibility notes).

## Design

- Prefer **official HF endpoints**: `huggingface_hub.HfApi` and `datasets.load_dataset`.
- No external LLM: the agent only fetches and formats HF data.

## Setup

```bash
cd HFAgent
pip install -r requirements.txt
```

Optional: log in to Hugging Face for higher rate limits (not required for read-only public data):

```bash
huggingface-cli login
```

## Run from command line

```bash
python main.py
```

This calls `generate_hf_benchmark_report()` with default options. Reports are written to:

- **`output/report.html`** — open in a browser for a readable UI (tables, links to HF, caveats).
- `output/report.txt` — plain text version.

## Configuration (optional)

Edit `config.py` to change defaults used when you don't pass parameters:

- Enable/disable tracks: `TRACK["open_llm_leaderboard"]`, `TRACK["trending_models"]`, `TRACK["eval_datasets"]`.
- Set `LEADERBOARD_TOP_N`, `TRENDING_SORT` (`trending_score`, `downloads`, `likes`, etc.), `TRENDING_LIMIT`, `EVAL_DATASETS_LIMIT`, `EVAL_DATASETS_SEARCH`, `OUTPUT_DIR`.

## Data sources (real-time)

| Source            | API / dataset |
|-------------------|----------------|
| Open LLM Leaderboard | `datasets.load_dataset("open-llm-leaderboard/contents")` |
| Trending models   | `HfApi().list_models(sort="trending_score", limit=N)` |
| Eval datasets     | `HfApi().list_datasets(benchmark="official")` |

No Claude or other external model is used; all displayed data comes from Hugging Face.
