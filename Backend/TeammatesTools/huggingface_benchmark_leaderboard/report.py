"""
Report formatting for HF Benchmark & Leaderboard Tracker.
Outputs real data fetched from Hugging Face; no LLM (no Claude).
Includes caveats and reproducibility notes where applicable.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_NO_DATA_MSG = "\n(No data.)\n"

# Clean display labels for leaderboard columns (strip emojis / special chars from dataset)
_COL_LABELS = {
    "average": "Average",
    "license": "License",
    "hub": "Hub likes",
    "params": "Params (B)",
    "params (b)": "Params (B)",
    "#params (b)": "Params (B)",
    "co2": "CO2 (kg)",
    "co2 cost (kg)": "CO2 (kg)",
    "available on the hub": "On Hub",
    "moe": "MoE",
    "flagged": "Flagged",
    "chat template": "Chat Template",
}


def _clean_col_label(col: str) -> str:
    """Convert dataset column name to readable label (strip emojis, normalize)."""
    if not col:
        return col
    # Remove emojis and extra spaces
    clean = re.sub(r"[^\w\s#().\-]", "", col).strip()
    lower = clean.lower()
    for key, label in _COL_LABELS.items():
        if key in lower or lower in key:
            return label
    return clean or col


def format_leaderboard_section(data: list[dict[str, Any]], top_n: int = 20) -> str:
    """Format Open LLM Leaderboard data (who's on top, task breakdown)."""
    lines = ["## Open LLM Leaderboard (live from HF dataset open-llm-leaderboard/contents)"]
    if not data:
        return "\n".join(lines) + _NO_DATA_MSG
    err = data[0].get("error")
    if err:
        return "\n".join(lines) + f"\nError: {err}\n"

    lines.append("")
    cols = [k for k in data[0].keys() if k != "error"]
    id_col = "model" if "model" in cols else (cols[0] if cols else "id")
    score_cols = [c for c in cols if c != id_col and isinstance(data[0].get(c), (int, float))]
    if not score_cols and cols:
        score_cols = [c for c in cols if c != id_col]

    for i, row in enumerate(data[:top_n], 1):
        mid = row.get(id_col, row.get("model_id", ""))
        parts = [f"  {i}. {mid}"]
        for sc in score_cols[:8]:
            v = row.get(sc)
            if v is not None:
                parts.append(f"  {sc}={v}")
        lines.append(" | ".join(parts))
    lines.append("")
    lines.append("(Tasks: ARC, HellaSwag, MMLU, TruthfulQA, Winogrande, GSM8k — per Open LLM Leaderboard.)")
    lines.append("Caveat: Compare same model type and precision; leaderboard can have submission timing bias.")
    return "\n".join(lines)


def format_trending_section(data: list[dict[str, Any]], limit: int = 15) -> str:
    """Format trending models (from HF API list_models)."""
    lines = ["## Trending / popular models (live from HF API list_models)"]
    if not data:
        return "\n".join(lines) + _NO_DATA_MSG
    err = data[0].get("error")
    if err:
        return "\n".join(lines) + f"\nError: {err}\n"

    lines.append("")
    for i, row in enumerate(data[:limit], 1):
        mid = row.get("id", "")
        down = row.get("downloads")
        likes = row.get("likes")
        tag = row.get("pipeline_tag", "")
        parts = [f"  {i}. {mid}"]
        if down is not None:
            parts.append(f"downloads={down}")
        if likes is not None:
            parts.append(f"likes={likes}")
        if tag:
            parts.append(f"tag={tag}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_eval_datasets_section(data: list[dict[str, Any]], limit: int = 15) -> str:
    """Format official evaluation datasets (from HF API list_datasets)."""
    lines = ["## Official / benchmark evaluation datasets (live from HF API list_datasets)"]
    if not data:
        return "\n".join(lines) + _NO_DATA_MSG
    err = data[0].get("error")
    if err:
        return "\n".join(lines) + f"\nError: {err}\n"

    lines.append("")
    for i, row in enumerate(data[:limit], 1):
        did = row.get("id", "")
        down = row.get("downloads")
        likes = row.get("likes")
        parts = [f"  {i}. {did}"]
        if down is not None:
            parts.append(f"downloads={down}")
        if likes is not None:
            parts.append(f"likes={likes}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_model_eval_section(data: list[dict[str, Any]], limit: int = 10) -> str:
    """Format model card eval results (when available via API)."""
    lines = ["## Model eval results (from model cards via HF API model_info)"]
    if not data:
        return "\n".join(lines) + _NO_DATA_MSG
    lines.append("")
    for row in data[:limit]:
        mid = row.get("id", "")
        err = row.get("error")
        if err:
            lines.append(f"  {mid}: error — {err}")
            continue
        ev = row.get("eval_results")
        if ev:
            lines.append(f"  {mid}: {json.dumps(ev)[:200]}...")
        else:
            lines.append(f"  {mid}: (no eval_results in response)")
    return "\n".join(lines)


def build_html_report(
    leaderboard_data: list[dict[str, Any]],
    trending_data: list[dict[str, Any]],
    eval_datasets_data: list[dict[str, Any]],
    top_n_leaderboard: int = 20,
    top_n_trending: int = 15,
    top_n_eval: int = 15,
) -> str:
    """Build a single HTML report with readable tables for UI display."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    caveats_html = """
    <section class="caveats">
      <h2>Caveats</h2>
      <ul>
        <li>Leaderboard: compare same category (base vs chat vs merged) and precision.</li>
        <li>Different eval settings and submission times can affect rankings.</li>
        <li>Eval results on model cards may be from different benchmarks than the Open LLM Leaderboard.</li>
      </ul>
    </section>
    """

    # Leaderboard table — only show key columns (skip HTML-rich or redundant fields)
    leaderboard_rows = ""
    if leaderboard_data and not leaderboard_data[0].get("error"):
        cols = [k for k in leaderboard_data[0].keys() if k != "error"]
        # First column in dataset is typically the model row id (e.g. "0-hero_Matter-0.2-7B-DPO_bfloat16")
        id_col = cols[0] if cols else "id"
        # Pick only key columns; avoid duplicates by label so we don't get "Hub likes" 4x
        def _is_usable_col(c: str) -> bool:
            if c == id_col:
                return False
            lower = c.lower()
            if "fullname" in lower or "sha" in lower:
                return False
            if "model" in lower and "average" not in lower and "param" not in lower:
                return False
            return True
        def _col_priority(c: str) -> int:
            l = c.lower()
            if "average" in l:
                return 0
            if "param" in l or c.startswith("#"):
                return 1
            if "license" in l:
                return 2
            if "hub" in l or "like" in l:
                return 3
            if "type" in l and "weight" not in l:
                return 4
            if "arch" in l:
                return 5
            if "precision" in l:
                return 6
            return 7
        candidates = sorted([c for c in cols if _is_usable_col(c)], key=_col_priority)
        seen_labels: set[str] = set()
        display_cols = []
        for c in candidates:
            lab = _clean_col_label(c)
            if lab not in seen_labels:
                seen_labels.add(lab)
                display_cols.append(c)
            if len(display_cols) >= 6:
                break
        header_cells = "<th>Model</th>" + "".join(f"<th>{_clean_col_label(c)}</th>" for c in display_cols)
        for i, row in enumerate(leaderboard_data[:top_n_leaderboard], 1):
            model_id = row.get(id_col, row.get("model_id", ""))
            if isinstance(model_id, str) and "<" in model_id:
                model_id = str(model_id).split(">")[1].split("<")[0] if ">" in model_id else model_id
            model_id = str(model_id).strip()
            if "/" in model_id:
                model_link = f"https://huggingface.co/{model_id}"
            else:
                model_link = f"https://huggingface.co/{model_id.replace('_', '/', 1)}"
            cells = [f'<td><a href="{model_link}" target="_blank" rel="noopener">{_escape(model_id)}</a></td>']
            for c in display_cols:
                v = row.get(c)
                if v is None:
                    cells.append("<td>—</td>")
                elif isinstance(v, str) and ("<" in v or "href=" in v):
                    cells.append("<td>—</td>")
                elif isinstance(v, float):
                    cells.append(f"<td>{v:.2f}</td>")
                elif isinstance(v, bool):
                    cells.append(f"<td>{'Yes' if v else 'No'}</td>")
                else:
                    cells.append(f"<td>{_escape(str(v))}</td>")
            leaderboard_rows += f"<tr><td>{i}</td>{''.join(cells)}</tr>"
        leaderboard_html = f"""
    <section class="section">
      <h2>Open LLM Leaderboard</h2>
      <p class="subtitle">Live from HF dataset <code>open-llm-leaderboard/contents</code></p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>#</th>{header_cells}</tr></thead>
          <tbody>{leaderboard_rows}</tbody>
        </table>
      </div>
      <p class="note">Tasks: ARC, HellaSwag, MMLU, TruthfulQA, Winogrande, GSM8k. Compare same model type and precision.</p>
    </section>
    """
    else:
        err = leaderboard_data[0].get("error", "No data") if leaderboard_data else "No data"
        leaderboard_html = f"""
    <section class="section">
      <h2>Open LLM Leaderboard</h2>
      <p class="error">{_escape(str(err))}</p>
    </section>
    """

    # Trending models table
    trending_rows = ""
    if trending_data and not trending_data[0].get("error"):
        for i, row in enumerate(trending_data[:top_n_trending], 1):
            mid = row.get("id", "")
            link = f"https://huggingface.co/{mid}"
            down = row.get("downloads")
            likes = row.get("likes")
            tag = row.get("pipeline_tag", "") or "—"
            trending_rows += f'<tr><td>{i}</td><td><a href="{link}" target="_blank" rel="noopener">{_escape(mid)}</a></td><td>{down or "—"}</td><td>{likes or "—"}</td><td>{_escape(tag)}</td></tr>'
        trending_html = f"""
    <section class="section">
      <h2>Trending / popular models</h2>
      <p class="subtitle">Live from HF API <code>list_models</code></p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>#</th><th>Model</th><th>Downloads</th><th>Likes</th><th>Task</th></tr></thead>
          <tbody>{trending_rows}</tbody>
        </table>
      </div>
    </section>
    """
    else:
        err = trending_data[0].get("error", "No data") if trending_data else "No data"
        trending_html = f"""
    <section class="section">
      <h2>Trending models</h2>
      <p class="error">{_escape(str(err))}</p>
    </section>
    """

    # Eval datasets table
    eval_rows = ""
    if eval_datasets_data and not eval_datasets_data[0].get("error"):
        for i, row in enumerate(eval_datasets_data[:top_n_eval], 1):
            did = row.get("id", "")
            link = f"https://huggingface.co/datasets/{did}"
            down = row.get("downloads")
            likes = row.get("likes")
            eval_rows += f'<tr><td>{i}</td><td><a href="{link}" target="_blank" rel="noopener">{_escape(did)}</a></td><td>{down or "—"}</td><td>{likes or "—"}</td></tr>'
        eval_html = f"""
    <section class="section">
      <h2>Official benchmark / evaluation datasets</h2>
      <p class="subtitle">Live from HF API <code>list_datasets(benchmark=official)</code></p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>#</th><th>Dataset</th><th>Downloads</th><th>Likes</th></tr></thead>
          <tbody>{eval_rows}</tbody>
        </table>
      </div>
    </section>
    """
    else:
        err = eval_datasets_data[0].get("error", "No data") if eval_datasets_data else "No data"
        eval_html = f"""
    <section class="section">
      <h2>Evaluation datasets</h2>
      <p class="error">{_escape(str(err))}</p>
    </section>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HF Benchmark & Leaderboard Tracker</title>
  <style>
    :root {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; font-size: 16px; line-height: 1.5; color: #1a1a1a; background: #f5f5f5; }}
    body {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; background: #fff; box-shadow: 0 0 20px rgba(0,0,0,.08); }}
    h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; color: #0f172a; }}
    .meta {{ color: #64748b; font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .caveats {{ background: #fef9c3; padding: 1rem 1.25rem; border-radius: 8px; margin-bottom: 2rem; }}
    .caveats ul {{ margin: 0.5rem 0 0 1.25rem; padding: 0; }}
    .section {{ margin-bottom: 2.5rem; }}
    .section h2 {{ font-size: 1.25rem; color: #0f172a; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #64748b; font-size: 0.875rem; margin-bottom: 0.75rem; }}
    .note {{ color: #64748b; font-size: 0.8rem; margin-top: 0.75rem; }}
    .error {{ color: #b91c1c; }}
    .table-wrap {{ overflow-x: auto; }}
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    .data-table th, .data-table td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
    .data-table th {{ background: #f1f5f9; font-weight: 600; color: #334155; }}
    .data-table tbody tr:hover {{ background: #f8fafc; }}
    .data-table a {{ color: #2563eb; text-decoration: none; }}
    .data-table a:hover {{ text-decoration: underline; }}
    code {{ background: #f1f5f9; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85em; }}
  </style>
</head>
<body>
  <header>
    <h1>Hugging Face Benchmark & Leaderboard Tracker</h1>
    <p class="meta">Generated {generated} UTC · All data from Hugging Face APIs (real time, no dummy data)</p>
  </header>
  {caveats_html}
  {leaderboard_html}
  {trending_html}
  {eval_html}
</body>
</html>
"""
    return html


def _escape(s: str) -> str:
    """Escape HTML entities."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_report(sections: dict[str, str], caveats: bool = True) -> str:
    """Build full report text with optional caveats."""
    header = [
        "# Hugging Face Benchmark & Leaderboard Tracker",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "All data is fetched in real time from Hugging Face APIs/datasets (no dummy data).",
        "",
    ]
    if caveats:
        header.extend([
            "## Caveats",
            "- Leaderboard: compare same category (base vs chat vs merged) and precision.",
            "- Different eval settings and submission times can affect rankings.",
            "- Eval results on model cards may be from different benchmarks than the Open LLM Leaderboard.",
            "",
        ])
    return "\n".join(header) + "\n\n" + "\n\n".join(sections.values())


def write_report(report_text: str, out_dir: str, format_type: str = "text") -> Path:
    """Write report to output dir. format_type: 'text' | 'json' (json stores raw sections)."""
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    if format_type == "json":
        out_file = path / "report.txt"
        out_file.write_text(report_text, encoding="utf-8")
        return out_file
    out_file = path / "report.txt"
    out_file.write_text(report_text, encoding="utf-8")
    return out_file


def write_html_report(html_content: str, out_dir: str) -> Path:
    """Write HTML report to output/report.html."""
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    out_file = path / "report.html"
    out_file.write_text(html_content, encoding="utf-8")
    return out_file
