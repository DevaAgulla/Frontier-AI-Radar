"""Report Generator Agent — Deterministic Jinja2 template renderer (Layer 6 Delivery).

No LLM call. Reads ranked_findings and digest_json from state, groups findings
by agent_source, and renders them into a branded Jinja2 HTML template.
Then deterministically calls render_pdf to produce the final PDF.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline.state import RadarState
from agents.base_agent import handle_agent_error
from core.tools import render_pdf, write_memory
from config.settings import settings
from db.persist import save_report as db_save_report
import structlog

logger = structlog.get_logger()


def _md_to_html(text: str) -> str:
    """Convert simple markdown to styled HTML for PDF rendering.

    Handles: ## headings, **bold**, - bullet lists, bare paragraphs.
    """
    if not text:
        return ""

    lines = text.split("\n")
    parts: list[str] = []
    in_list = False

    def _bold(s: str) -> str:
        return re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", s)

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            heading = _bold(stripped[3:].strip())
            parts.append(
                f'<p style="font-weight:700;color:#1e3a5f;margin:7px 0 2px;font-size:9.5pt;">'
                f"{heading}</p>"
            )

        elif stripped.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            heading = _bold(stripped[4:].strip())
            parts.append(
                f'<p style="font-weight:600;color:#2d4a7a;margin:5px 0 1px;font-size:9pt;">'
                f"{heading}</p>"
            )

        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                parts.append('<ul style="margin:3px 0 3px 14px;padding:0;">')
                in_list = True
            content = _bold(stripped[2:].strip())
            parts.append(
                f'<li style="margin:1px 0;font-size:9pt;color:#374151;">{content}</li>'
            )

        elif not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False

        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            content = _bold(stripped)
            parts.append(
                f'<p style="margin:2px 0;font-size:9pt;color:#374151;">{content}</p>'
            )

    if in_list:
        parts.append("</ul>")

    return "\n".join(parts)


# ── Load Jinja2 template once at import ───────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

try:
    from jinja2 import Environment, FileSystemLoader
    _jinja_env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,  # we output raw HTML
        auto_reload=True,
    )
    _jinja_env.filters["md"] = _md_to_html
    _digest_template = _jinja_env.get_template("digest.html")
except Exception:
    _digest_template = None


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def report_generator_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Report Generator Agent (deterministic — no LLM).

    1. Read ranked_findings and digest_json from state.
    2. Group findings by agent_source into 4 domain buckets.
    3. Render everything via the Jinja2 template.
    4. Call render_pdf to produce the final PDF.
    5. Write report metadata to memory.
    """
    try:
        run_id = state.get("run_id", "unknown")
        findings = state.get("ranked_findings", [])
        digest = state.get("digest_json", {})
        digest_md = state.get("digest_markdown", "")

        logger.info("Report Generator: starting (deterministic mode)",
                     run_id=run_id, findings_count=len(findings))

        brand_name = settings.pdf_brand_name
        brand_colour = settings.pdf_brand_color
        gen_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

        # ── Group findings by agent_source ─────────────────────────────
        grouped = {
            "research_intel": [],
            "competitor_intel": [],
            "model_intel": [],
            "benchmark_intel": [],
        }
        for f in findings:
            key = f.get("agent_source", "research_intel")
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(f)

        # ── Extract digest sections ────────────────────────────────────
        sections = digest.get("sections", {})
        executive_summary = digest.get("executive_summary", "")

        # Fallback: if digest_json was empty, use digest_markdown
        if not executive_summary and digest_md:
            executive_summary = digest_md

        # ── Render via Jinja2 template ─────────────────────────────────
        digest_template = _digest_template
        if _jinja_env is not None:
            # Reload template every run so style/content edits are reflected immediately.
            digest_template = _jinja_env.get_template("digest.html")

        if digest_template:
            html_content = digest_template.render(
                brand_name=brand_name,
                brand_color=brand_colour,
                generation_date=gen_date,
                run_id=run_id,
                audience="AI/ML Leadership Team",
                total_findings=len(findings),
                executive_summary=executive_summary,
                findings=findings,
                grouped_findings=grouped,
                sections=sections,
            )
        else:
            # Fallback if Jinja2 template could not be loaded
            logger.warning("Report Generator: Jinja2 template not available, using inline fallback")
            # Build a minimal but valid HTML document
            cards_html = ""
            for f in findings:
                title = f.get("title", "Untitled")
                what = f.get("what_changed", "")
                why = f.get("why_it_matters", "")
                score = f.get("impact_score", 0.0)
                conf = f.get("confidence", "MEDIUM")
                cards_html += (
                    f"<div style='border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:12px 0;'>"
                    f"<strong>{title}</strong> "
                    f"<span style='font-size:9pt;color:#64748b;'>[{conf}]</span><br>"
                    f"<span>What changed: {what}</span><br>"
                    f"<span style='font-style:italic;'>Why it matters: {why}</span><br>"
                    f"<span style='font-size:9pt;'>Impact: {score:.2f}</span>"
                    f"</div>\n"
                )

            html_content = (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>{brand_name} Digest</title>"
                f"<style>body{{font-family:'Segoe UI',Arial,sans-serif;margin:40px;color:#1e293b;}}"
                f"h1{{color:{brand_colour};}}"
                f"h2{{color:{brand_colour};border-bottom:2px solid {brand_colour};padding-bottom:4px;}}"
                f"</style></head><body>"
                f"<h1>{brand_name} - Daily Intelligence Digest</h1>"
                f"<p style='color:#64748b;'>{gen_date} | Run: {run_id} | "
                f"Findings: {len(findings)}</p><hr>"
                f"<h2>Executive Summary</h2>"
                f"<p>{executive_summary}</p>"
                f"<h2>Findings</h2>"
                f"{cards_html}"
                f"<hr><p style='color:#94a3b8;text-align:center;font-size:9pt;'>"
                f"Powered by <strong style='color:{brand_colour};'>{brand_name}</strong></p>"
                f"</body></html>"
            )

        logger.info("Report Generator: HTML ready, calling render_pdf",
                     html_length=len(html_content))

        # ── Deterministic render_pdf call ──────────────────────────────
        pdf_result = await render_pdf.ainvoke({"html_content": html_content})

        pdf_path = pdf_result.get("pdf_path", "")
        if not pdf_path:
            logger.error("Report Generator: render_pdf failed",
                         error=pdf_result.get("error", "unknown"))

        # ── Write report metadata to memory ────────────────────────────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_report_metadata",
            "value": json.dumps({
                "pdf_path": pdf_path,
                "run_id": run_id,
                "size_bytes": pdf_result.get("size_bytes", 0),
                "pages": pdf_result.get("pages", 0),
                "findings_count": len(findings),
            }),
        })

        # ── DB: save HTML + PDF to database ────────────────────────────
        extraction_db_id = state.get("extraction_db_id", 0)
        run_db_id = state.get("run_db_id", 0)
        if extraction_db_id and run_db_id:
            db_save_report(
                html_content=html_content,
                pdf_path=pdf_path,
                extraction_id=extraction_db_id,
                run_db_id=run_db_id,
            )

        logger.info("Report Generator: complete", pdf_path=pdf_path,
                     size_bytes=pdf_result.get("size_bytes", 0))
        return {"pdf_path": pdf_path}

    except Exception as e:
        logger.exception("Report Generator error", error=str(e))
        return handle_agent_error("report_generator", e)
