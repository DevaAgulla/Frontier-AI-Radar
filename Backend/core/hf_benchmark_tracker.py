"""
hf_benchmark_tracker.py

Fetches and aggregates Hugging Face benchmark & leaderboard data from
official HF APIs and datasets in real time.  No dummy data, no external LLM.

Adapted from TeammatesTools/huggingface_benchmark_leaderboard/ (fetchers.py
+ main.py) for use within the core/ package by the HF Leaderboard
Intelligence Agent.

Configuration lives in core/hf_benchmark_config.py.

Dependencies:
    pip install huggingface_hub datasets
"""

from __future__ import annotations

import logging
from typing import Any

from core.hf_benchmark_config import (
    EVAL_DATASETS_LIMIT,
    EVAL_DATASETS_SEARCH,
    LEADERBOARD_TOP_N,
    TRACK,
    TRENDING_LIMIT,
    TRENDING_SORT,
)

logger = logging.getLogger("hf_benchmark_tracker")

# ---------------------------------------------------------------------------
# Optional: datasets library for Open LLM Leaderboard contents
# ---------------------------------------------------------------------------

try:
    from datasets import load_dataset  # type: ignore[import-untyped]

    HAS_DATASETS = True
except ImportError:
    HAS_DATASETS = False


# ---------------------------------------------------------------------------
# Fetchers (adapted from TeammatesTools fetchers.py)
# ---------------------------------------------------------------------------


def fetch_open_llm_leaderboard(top_n: int = LEADERBOARD_TOP_N) -> list[dict[str, Any]]:
    """
    Fetch Open LLM Leaderboard data from the official HF dataset.
    Dataset: open-llm-leaderboard/contents (real data, updated by HF).
    """
    if not HAS_DATASETS:
        return [{"error": "datasets library required. Install with: pip install datasets"}]

    try:
        ds = load_dataset("open-llm-leaderboard/contents", split="train")
    except Exception as e:
        logger.warning("Failed to load open-llm-leaderboard/contents: %s", e)
        return [{"error": f"Failed to load open-llm-leaderboard/contents: {e}"}]

    rows: list[dict[str, Any]] = []
    cols = ds.column_names
    for i, row in enumerate(ds):
        if i >= top_n:
            break
        r: dict[str, Any] = {}
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

    return rows[:top_n]


def fetch_trending_models(
    sort: str = TRENDING_SORT,
    limit: int = TRENDING_LIMIT,
) -> list[dict[str, Any]]:
    """
    Fetch trending/popular models from Hugging Face API (real time).
    Uses HfApi.list_models() with sort=trending_score, downloads, or likes.
    """
    from huggingface_hub import HfApi  # type: ignore[import-untyped]
    from huggingface_hub.hf_api import ModelInfo  # type: ignore[import-untyped]

    api = HfApi()
    try:
        models = list(api.list_models(sort=sort, limit=limit))
    except Exception as e:
        logger.warning("list_models failed: %s", e)
        return [{"error": f"list_models failed: {e}"}]

    out: list[dict[str, Any]] = []
    for m in models:
        if isinstance(m, ModelInfo):
            out.append(
                {
                    "id": m.id,
                    "author": getattr(m, "author", None),
                    "downloads": getattr(m, "downloads", None),
                    "likes": getattr(m, "likes", None),
                    "pipeline_tag": getattr(m, "pipeline_tag", None),
                    "created_at": str(getattr(m, "created_at", None) or ""),
                    "last_modified": str(getattr(m, "last_modified", None) or ""),
                    "trending_score": getattr(m, "trendingScore", None),
                }
            )
        else:
            out.append({"raw": str(m)})
    return out


def fetch_eval_datasets(
    benchmark: str | bool = "official",
    limit: int = EVAL_DATASETS_LIMIT,
    search: str | None = EVAL_DATASETS_SEARCH,
) -> list[dict[str, Any]]:
    """
    Fetch official/benchmark evaluation datasets from Hugging Face API.
    Uses HfApi.list_datasets(benchmark=...).
    """
    from huggingface_hub import HfApi  # type: ignore[import-untyped]

    api = HfApi()
    try:
        if search:
            it = api.list_datasets(search=search)
        else:
            it = api.list_datasets(benchmark=benchmark)
        datasets_list = list(it)[:limit]
    except Exception as e:
        logger.warning("list_datasets failed: %s", e)
        return [{"error": f"list_datasets failed: {e}"}]

    out: list[dict[str, Any]] = []
    for d in datasets_list:
        out.append(
            {
                "id": d.id,
                "author": getattr(d, "author", None),
                "downloads": getattr(d, "downloads", None),
                "likes": getattr(d, "likes", None),
                "tags": getattr(d, "tags", None) or [],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Public API — single entry point for the LangChain tool
# ---------------------------------------------------------------------------


def fetch_hf_benchmark_data(
    *,
    track_leaderboard: bool | None = None,
    track_trending: bool | None = None,
    track_eval_datasets: bool | None = None,
    leaderboard_top_n: int | None = None,
    trending_sort: str | None = None,
    trending_limit: int | None = None,
    eval_datasets_limit: int | None = None,
    eval_datasets_search: str | None = None,
) -> dict[str, Any]:
    """
    Fetch HF leaderboard, trending models, and eval datasets in one call.

    Returns a structured dict with:
        - leaderboard_data: list of leaderboard rows
        - trending_data: list of trending model dicts
        - eval_datasets_data: list of eval dataset dicts
        - errors: list of any error messages encountered
    """
    track = dict(TRACK)
    if track_leaderboard is not None:
        track["open_llm_leaderboard"] = track_leaderboard
    if track_trending is not None:
        track["trending_models"] = track_trending
    if track_eval_datasets is not None:
        track["eval_datasets"] = track_eval_datasets

    top_n = leaderboard_top_n if leaderboard_top_n is not None else LEADERBOARD_TOP_N
    sort = trending_sort if trending_sort is not None else TRENDING_SORT
    trend_limit = trending_limit if trending_limit is not None else TRENDING_LIMIT
    eval_limit = eval_datasets_limit if eval_datasets_limit is not None else EVAL_DATASETS_LIMIT
    eval_search = eval_datasets_search if eval_datasets_search is not None else EVAL_DATASETS_SEARCH

    leaderboard_data: list[dict[str, Any]] = []
    trending_data: list[dict[str, Any]] = []
    eval_datasets_data: list[dict[str, Any]] = []
    errors: list[str] = []

    if track.get("open_llm_leaderboard"):
        logger.info("Fetching Open LLM Leaderboard (HF dataset)...")
        leaderboard_data = fetch_open_llm_leaderboard(top_n=top_n)
        if leaderboard_data and leaderboard_data[0].get("error"):
            errors.append(leaderboard_data[0]["error"])

    if track.get("trending_models"):
        logger.info("Fetching trending models (HF API list_models)...")
        trending_data = fetch_trending_models(sort=sort, limit=trend_limit)
        if trending_data and trending_data[0].get("error"):
            errors.append(trending_data[0]["error"])

    if track.get("eval_datasets"):
        logger.info("Fetching official benchmark datasets (HF API list_datasets)...")
        eval_datasets_data = fetch_eval_datasets(
            benchmark="official",
            limit=eval_limit,
            search=eval_search or None,
        )
        if eval_datasets_data and eval_datasets_data[0].get("error"):
            errors.append(eval_datasets_data[0]["error"])

    return {
        "leaderboard_data": leaderboard_data,
        "trending_data": trending_data,
        "eval_datasets_data": eval_datasets_data,
        "errors": errors,
    }
