"""
Fetchers for Hugging Face data — all real-time from official HF APIs and datasets.
No dummy data. No external LLM (e.g. Claude); this agent only uses HF as the data source.
"""

from __future__ import annotations

from typing import Any

from huggingface_hub import HfApi, list_models, list_datasets
from huggingface_hub.hf_api import ModelInfo

# Optional: datasets library for Open LLM Leaderboard contents
try:
    from datasets import load_dataset
    HAS_DATASETS = True
except ImportError:
    HAS_DATASETS = False


def fetch_open_llm_leaderboard(top_n: int = 50) -> list[dict[str, Any]]:
    """
    Fetch Open LLM Leaderboard data from the official HF dataset.
    Dataset: open-llm-leaderboard/contents (real data, updated by HF).
    """
    if not HAS_DATASETS:
        return [{"error": "datasets library required. Install with: pip install datasets"}]  # type: ignore[return-value]

    try:
        ds = load_dataset("open-llm-leaderboard/contents", split="train")
    except Exception as e:
        return [{"error": f"Failed to load open-llm-leaderboard/contents: {e}"}]  # type: ignore[return-value]

    rows = []
    cols = ds.column_names
    # Normalize: dataset may use different column names (e.g. model_id, average, arc, etc.)
    for i, row in enumerate(ds):
        if i >= top_n:
            break
        r = {}
        for c in cols:
            val = row.get(c)
            if val is not None:
                r[c] = val
        rows.append(r)

    # Sort by average if present
    avg_key = None
    for k in ("average", "Average", "score", "Score"):
        if k in cols:
            avg_key = k
            break
    if avg_key and rows and isinstance(rows[0].get(avg_key), (int, float)):
        rows.sort(key=lambda x: float(x.get(avg_key) or 0), reverse=True)
    elif "model" in cols:
        # Keep order as from dataset (often already ranked)
        pass

    return rows[:top_n]


def fetch_trending_models(
    sort: str = "trending_score",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """
    Fetch trending/popular models from Hugging Face API (real time).
    Uses HfApi.list_models() with sort=trending_score, downloads, or likes.
    """
    api = HfApi()
    # sort: "created_at" | "downloads" | "last_modified" | "likes" | "trending_score"
    try:
        models = list(api.list_models(sort=sort, limit=limit))
    except Exception as e:
        return [{"error": f"list_models failed: {e}"}]  # type: ignore[return-value]

    out = []
    for m in models:
        if isinstance(m, ModelInfo):
            out.append({
                "id": m.id,
                "author": getattr(m, "author", None),
                "downloads": getattr(m, "downloads", None),
                "likes": getattr(m, "likes", None),
                "pipeline_tag": getattr(m, "pipeline_tag", None),
                "created_at": getattr(m, "created_at", None),
                "last_modified": getattr(m, "last_modified", None),
                "trending_score": getattr(m, "trendingScore", None),
            })
        else:
            out.append({"raw": str(m)})
    return out


def fetch_eval_datasets(
    benchmark: str | bool = "official",
    limit: int = 25,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch official/benchmark evaluation datasets from Hugging Face API.
    Uses HfApi.list_datasets(benchmark=...).
    """
    api = HfApi()
    try:
        if search:
            it = api.list_datasets(search=search)
        else:
            it = api.list_datasets(benchmark=benchmark)
        datasets = list(it)[:limit]
    except Exception as e:
        return [{"error": f"list_datasets failed: {e}"}]  # type: ignore[return-value]

    out = []
    for d in datasets:
        out.append({
            "id": d.id,
            "author": getattr(d, "author", None),
            "downloads": getattr(d, "downloads", None),
            "likes": getattr(d, "likes", None),
            "tags": getattr(d, "tags", None) or [],
        })
    return out


def fetch_model_eval_results(model_ids: list[str], expand: list[str] | None = None) -> list[dict[str, Any]]:
    """
    Fetch model info including eval results from model cards (when available).
    Uses HfApi.model_info() with expand=["evalResults", ...].
    """
    api = HfApi()
    expand = expand or ["evalResults", "likes", "downloads", "trendingScore"]
    out = []
    for mid in model_ids[:20]:  # cap to avoid rate limits
        try:
            info = api.model_info(mid, expand=expand)
            d = {
                "id": info.id,
                "author": getattr(info, "author", None),
                "eval_results": getattr(info, "evalResults", None),
                "likes": getattr(info, "likes", None),
                "downloads": getattr(info, "downloads", None),
                "trending_score": getattr(info, "trendingScore", None),
            }
            out.append(d)
        except Exception as e:
            out.append({"id": mid, "error": str(e)})
    return out
