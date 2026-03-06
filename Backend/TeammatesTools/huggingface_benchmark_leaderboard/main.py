"""
Hugging Face Benchmark & Leaderboard Tracker — single entry point.
Fetches real data from Hugging Face APIs and datasets only. No external LLM (no Claude).

Call generate_hf_benchmark_report() from your code or run: python main.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["generate_hf_benchmark_report"]

# Lazy imports to allow calling from other code without importing config first
def _get_config():
    from config import (
        EVAL_DATASETS_LIMIT,
        EVAL_DATASETS_SEARCH,
        LEADERBOARD_TOP_N,
        OUTPUT_DIR,
        REPORT_FORMAT,
        TRACK,
        TRENDING_LIMIT,
        TRENDING_SORT,
    )
    return {
        "eval_datasets_limit": EVAL_DATASETS_LIMIT,
        "eval_datasets_search": EVAL_DATASETS_SEARCH,
        "leaderboard_top_n": LEADERBOARD_TOP_N,
        "output_dir": OUTPUT_DIR,
        "report_format": REPORT_FORMAT,
        "track": TRACK,
        "trending_limit": TRENDING_LIMIT,
        "trending_sort": TRENDING_SORT,
    }


def generate_hf_benchmark_report(
    output_dir: str | Path | None = None,
    *,
    track_leaderboard: bool | None = None,
    track_trending: bool | None = None,
    track_eval_datasets: bool | None = None,
    leaderboard_top_n: int | None = None,
    trending_sort: str | None = None,
    trending_limit: int | None = None,
    eval_datasets_limit: int | None = None,
    eval_datasets_search: str | None = None,
    write_txt: bool = True,
    write_html: bool = True,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Fetch Hugging Face leaderboard, trending models, and eval datasets; write reports.
    Call this single function from your own code.

    Parameters
    ----------
    output_dir : str or Path, optional
        Directory for report files. Default: config.OUTPUT_DIR ("output").
    track_leaderboard : bool, optional
        If True, fetch Open LLM Leaderboard. Default: from config (True).
    track_trending : bool, optional
        If True, fetch trending models. Default: from config (True).
    track_eval_datasets : bool, optional
        If True, fetch official eval datasets. Default: from config (True).
    leaderboard_top_n : int, optional
        Max number of leaderboard models to fetch. Default: from config (50).
    trending_sort : str, optional
        Sort for trending: "trending_score", "downloads", "likes", etc. Default: from config.
    trending_limit : int, optional
        Max number of trending models. Default: from config (30).
    eval_datasets_limit : int, optional
        Max number of eval datasets. Default: from config (25).
    eval_datasets_search : str, optional
        Optional search filter for eval datasets. Default: from config (None).
    write_txt : bool
        Write text report (report.txt). Default: True.
    write_html : bool
        Write HTML report (report.html). Default: True.
    verbose : bool
        Print progress messages. Default: True.

    Returns
    -------
    dict with keys:
        - html_path : Path or None — path to report.html if write_html=True
        - txt_path : Path or None — path to report.txt if write_txt=True
        - leaderboard_data : list — raw leaderboard rows (or empty)
        - trending_data : list — raw trending model rows (or empty)
        - eval_datasets_data : list — raw eval dataset rows (or empty)
        - html_content : str or None — HTML string if write_html=True
        - txt_content : str or None — text report if write_txt=True
    """
    cfg = _get_config()
    out_dir = str(output_dir) if output_dir is not None else cfg["output_dir"]
    track = dict(cfg["track"])
    if track_leaderboard is not None:
        track["open_llm_leaderboard"] = track_leaderboard
    if track_trending is not None:
        track["trending_models"] = track_trending
    if track_eval_datasets is not None:
        track["eval_datasets"] = track_eval_datasets
    top_n = leaderboard_top_n if leaderboard_top_n is not None else cfg["leaderboard_top_n"]
    sort = trending_sort if trending_sort is not None else cfg["trending_sort"]
    trend_limit = trending_limit if trending_limit is not None else cfg["trending_limit"]
    eval_limit = eval_datasets_limit if eval_datasets_limit is not None else cfg["eval_datasets_limit"]
    eval_search = eval_datasets_search if eval_datasets_search is not None else cfg["eval_datasets_search"]

    from fetchers import (
        fetch_eval_datasets,
        fetch_open_llm_leaderboard,
        fetch_trending_models,
    )
    from report import (
        build_report,
        build_html_report,
        format_eval_datasets_section,
        format_leaderboard_section,
        format_trending_section,
        write_report,
        write_html_report,
    )

    sections: dict[str, str] = {}
    leaderboard_data: list[dict[str, Any]] = []
    trending_data: list[dict[str, Any]] = []
    eval_datasets_data: list[dict[str, Any]] = []

    if track.get("open_llm_leaderboard"):
        if verbose:
            print("Fetching Open LLM Leaderboard (HF dataset open-llm-leaderboard/contents)...")
        leaderboard_data = fetch_open_llm_leaderboard(top_n=top_n)
        sections["leaderboard"] = format_leaderboard_section(
            leaderboard_data, top_n=min(20, top_n)
        )

    if track.get("trending_models"):
        if verbose:
            print("Fetching trending models (HF API list_models)...")
        trending_data = fetch_trending_models(sort=sort, limit=trend_limit)
        sections["trending"] = format_trending_section(
            trending_data, limit=min(15, trend_limit)
        )

    if track.get("eval_datasets"):
        if verbose:
            print("Fetching official benchmark datasets (HF API list_datasets)...")
        eval_datasets_data = fetch_eval_datasets(
            benchmark="official",
            limit=eval_limit,
            search=eval_search or None,
        )
        sections["eval_datasets"] = format_eval_datasets_section(
            eval_datasets_data, limit=min(15, eval_limit)
        )

    result: dict[str, Any] = {
        "html_path": None,
        "txt_path": None,
        "leaderboard_data": leaderboard_data,
        "trending_data": trending_data,
        "eval_datasets_data": eval_datasets_data,
        "html_content": None,
        "txt_content": None,
    }

    if write_txt:
        report_text = build_report(sections, caveats=True)
        result["txt_content"] = report_text
        result["txt_path"] = write_report(report_text, out_dir, format_type=cfg["report_format"])
        if verbose:
            print(f"Report (text) written to: {result['txt_path']}")

    if write_html:
        html_content = build_html_report(
            leaderboard_data,
            trending_data,
            eval_datasets_data,
            top_n_leaderboard=min(20, top_n),
            top_n_trending=min(15, trend_limit),
            top_n_eval=min(15, eval_limit),
        )
        result["html_content"] = html_content
        result["html_path"] = write_html_report(html_content, out_dir)
        if verbose:
            print(f"Report (HTML) written to: {result['html_path']}")

    if verbose and (write_txt or write_html):
        print("Open the HTML file in a browser for a readable UI view.")

    return result


if __name__ == "__main__":
    generate_hf_benchmark_report()
