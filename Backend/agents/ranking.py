"""Ranking Agent — DETERMINISTIC scoring + LLM dedup (Layer 5 Validation).

Computes impact scores for ALL findings using pure Python math:
Impact = 0.35*Relevance + 0.25*Novelty + 0.20*Credibility + 0.20*Actionability

Then uses LLM (optional, with fallback) for deduplication and clustering.
If the LLM step fails, the deterministically-scored findings are still returned.
"""

import json
from langchain_core.messages import HumanMessage

from pipeline.state import RadarState
from agents.base_agent import (
    build_react_agent,
    get_recursion_limit,
    extract_agent_output,
    parse_json_output,
    handle_agent_error,
)
from core.tools import read_memory, write_memory, search_entity_memory
from config.settings import settings, load_scoring_config
from db.persist import update_scores as db_update_scores
import structlog

logger = structlog.get_logger()


# ── DETERMINISTIC SCORING (no LLM needed) ─────────────────────────────────

def _clamp(val, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(val)))
    except (TypeError, ValueError):
        return 0.5

def _compute_score(finding: dict) -> float:
    """Pure Python impact score computation."""
    r = _clamp(finding.get("relevance", 0.5))
    n = _clamp(finding.get("novelty", 0.5))
    c = _clamp(finding.get("credibility", 0.5))
    a = _clamp(finding.get("actionability", 0.5))
    return round(0.35 * r + 0.25 * n + 0.20 * c + 0.20 * a, 4)


def _score_and_rank(findings: list) -> list:
    """Score all findings deterministically, sort by impact descending."""
    for f in findings:
        f["impact_score"] = _compute_score(f)
    ranked = sorted(findings, key=lambda x: x.get("impact_score", 0), reverse=True)
    for i, f in enumerate(ranked, 1):
        f["rank"] = i
    return ranked


def _assign_confidence(findings: list) -> list:
    """Deterministic confidence assignment using impact_score + rank position.

    Guarantees a realistic spread of HIGH / MEDIUM / LOW for visual variety,
    regardless of what the LLM originally emitted.

    Strategy (rank-based tiers after sorting by impact descending):
      - Top ~30 %  → HIGH   (only if impact_score >= 0.40)
      - Bottom ~30 %  → LOW    (or any finding with impact < 0.35)
      - Middle          → MEDIUM
    """
    n = len(findings)
    if n == 0:
        return findings

    high_cutoff = max(1, int(n * 0.30))       # first N items → HIGH
    low_start = max(high_cutoff + 1, n - int(n * 0.30))  # last N items → LOW

    for idx, f in enumerate(findings):
        score = f.get("impact_score", 0.5)
        if idx < high_cutoff and score >= 0.40:
            f["confidence"] = "HIGH"
        elif idx >= low_start or score < 0.35:
            f["confidence"] = "LOW"
        else:
            f["confidence"] = "MEDIUM"

    return findings


def _deduplicate(findings: list) -> list:
    """Simple deterministic dedup: same source_url = duplicate, keep higher score."""
    seen_urls = {}
    deduped = []
    for f in findings:
        url = f.get("source_url", "")
        if url and url in seen_urls:
            # Keep the one with higher impact_score
            existing = seen_urls[url]
            if f.get("impact_score", 0) > existing.get("impact_score", 0):
                deduped.remove(existing)
                deduped.append(f)
                seen_urls[url] = f
        else:
            deduped.append(f)
            if url:
                seen_urls[url] = f
    return deduped


# ── SYSTEM PROMPT (for optional LLM dedup pass) ──────────────────────────

RANKING_SYSTEM_PROMPT = """You are the Ranking Agent for Frontier AI Radar.

GOAL: Review the pre-scored findings and deduplicate/cluster them.
Impact scores have ALREADY been computed — do NOT recompute them.

DEDUPLICATION RULES:
- Same URL → duplicate (keep higher score)
- Same event described differently → duplicate (keep more detailed version)
- Same model/paper from different sources → duplicate (keep primary source)

CLUSTERING:
- Group by topic: research, models, benchmarks, competitors

OUTPUT FORMAT: Return ONLY a valid JSON array of the Finding objects.
Keep the existing impact_score and rank fields unchanged.
Order by impact_score descending (highest first).

CRITICAL JSON RULES:
- Output ONLY the JSON. No text before or after.
- Do NOT wrap in markdown code fences.
- Ensure the JSON is COMPLETE — every [ has a ], every { has a }.
- Keep string values concise to avoid hitting token limits.
"""


# ── AGENT CONFIGURATION ───────────────────────────────────────────────────

RANKING_CONFIG = {
    "tools": [
        read_memory,
        search_entity_memory,
    ],
    "system_prompt": RANKING_SYSTEM_PROMPT,
    "state": RadarState,
    "config": {
        "max_iterations": 3,
    },
}

_react_agent = build_react_agent(
    system_prompt=RANKING_CONFIG["system_prompt"],
    tools=RANKING_CONFIG["tools"],
)


# ── LANGGRAPH NODE FUNCTION ───────────────────────────────────────────────

async def ranking_agent(state: RadarState) -> RadarState:
    """
    LangGraph node: Ranking Agent.

    Phase 1 (DETERMINISTIC): Collect all findings, compute scores, rank, dedup
    Phase 2 (LLM, OPTIONAL): Claude deduplicates/clusters (with fallback)
    Phase 3: Write to state
    """
    try:
        # ── PHASE 1: COLLECT + SCORE (pure Python, no LLM) ────────
        logger.info("Ranking Agent: Phase 1 — collecting all findings")

        all_findings = []
        all_findings.extend(state.get("competitor_findings", []))
        all_findings.extend(state.get("provider_findings", []))
        all_findings.extend(state.get("research_findings", []))
        all_findings.extend(state.get("hf_findings", []))

        if not all_findings:
            logger.info("Ranking Agent: no findings to rank")
            return {"merged_findings": [], "ranked_findings": []}

        # Deterministic scoring + ranking
        scored = _score_and_rank(list(all_findings))
        deduped = _deduplicate(scored)
        # Re-rank after dedup
        deduped.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        for i, f in enumerate(deduped, 1):
            f["rank"] = i

        # ── Deterministic confidence tiers (HIGH/MEDIUM/LOW) ─────
        deduped = _assign_confidence(deduped)

        # ── Topic clustering (FR4: cluster by topic) ──────────────
        TOPIC_MAP = {
            "release": "Models", "model": "Models", "models": "Models",
            "api": "APIs", "apis": "APIs", "endpoint": "APIs",
            "pricing": "Pricing", "cost": "Pricing",
            "benchmark": "Benchmarks", "benchmarks": "Benchmarks", "eval": "Benchmarks",
            "safety": "Safety", "alignment": "Safety", "policy": "Safety",
            "tooling": "Tooling", "tool": "Tooling", "library": "Tooling", "framework": "Tooling",
            "research": "Research", "paper": "Research",
        }
        for f in deduped:
            cat = (f.get("category") or "").lower().strip()
            f["topic_cluster"] = TOPIC_MAP.get(cat, "Research")

        logger.info(
            "Ranking Agent: Phase 1 complete — scored deterministically",
            total=len(all_findings),
            after_dedup=len(deduped),
        )

        # ── PHASE 2: LLM DEDUP (optional, with fallback) ─────────
        final_ranked = deduped  # fallback: use deterministic results

        try:
            if len(deduped) > 2:
                # Only use LLM if we have enough findings to dedup
                logger.info("Ranking Agent: Phase 2 — LLM dedup pass")

                # Send compact version to LLM (only key fields)
                compact = []
                for f in deduped:
                    compact.append({
                        "id": f.get("id"),
                        "title": f.get("title", "")[:100],
                        "agent_source": f.get("agent_source"),
                        "impact_score": f.get("impact_score"),
                        "rank": f.get("rank"),
                        "source_url": f.get("source_url", "")[:100],
                        "what_changed": f.get("what_changed", "")[:100],
                    })

                user_prompt = (
                    f"Pre-scored and ranked findings ({len(compact)} total):\n"
                    f"{json.dumps(compact, indent=2)}\n\n"
                    "Review for duplicates. Remove any that cover the same event. "
                    "Return the FULL list of finding IDs to KEEP (not remove), "
                    "as a JSON array of strings: [\"id1\", \"id2\", ...]"
                )

                result = await _react_agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": get_recursion_limit(
                        RANKING_CONFIG["config"]["max_iterations"]
                    )},
                )

                final_text = extract_agent_output(result["messages"])
                keep_ids = parse_json_output(final_text)

                # If LLM returned a list of IDs to keep, filter
                if keep_ids and isinstance(keep_ids[0], str):
                    keep_set = set(keep_ids)
                    filtered = [f for f in deduped if f.get("id") in keep_set]
                    if filtered:
                        final_ranked = filtered
                        # Re-rank
                        final_ranked.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
                        for i, f in enumerate(final_ranked, 1):
                            f["rank"] = i
                        logger.info("Ranking Agent: LLM dedup applied", kept=len(final_ranked))
                    else:
                        logger.warning("Ranking Agent: LLM returned empty keep list, using full list")
                else:
                    # LLM might have returned the full findings array — use it if valid
                    if keep_ids and isinstance(keep_ids[0], dict):
                        final_ranked = keep_ids
                        logger.info("Ranking Agent: LLM returned full findings")
            else:
                logger.info("Ranking Agent: skipping LLM pass (too few findings)")

        except Exception as llm_err:
            logger.warning(
                "Ranking Agent: LLM dedup failed, using deterministic results",
                error=str(llm_err),
            )
            # fallback already set: final_ranked = deduped

        # ── PHASE 3: WRITE TO STATE ──────────────────────────────
        await write_memory.ainvoke({
            "type": "long_term",
            "key": "last_ranking_findings",
            "value": json.dumps(final_ranked),
        })

        # ── DB: update findings with impact scores ───────────────
        extraction_db_id = state.get("extraction_db_id", 0)
        if extraction_db_id:
            db_update_scores(final_ranked, extraction_db_id)

        logger.info("Ranking Agent: complete", count=len(final_ranked))
        return {
            "merged_findings": all_findings,
            "ranked_findings": final_ranked,
        }

    except Exception as e:
        logger.exception("Ranking Agent error", error=str(e))
        # CRITICAL FALLBACK: Even if everything fails, try to pass through unranked findings
        try:
            all_findings = []
            all_findings.extend(state.get("competitor_findings", []))
            all_findings.extend(state.get("provider_findings", []))
            all_findings.extend(state.get("research_findings", []))
            all_findings.extend(state.get("hf_findings", []))
            if all_findings:
                scored = _score_and_rank(list(all_findings))
                scored = _assign_confidence(scored)
                logger.info("Ranking Agent: fallback — passing through scored findings", count=len(scored))
                return {
                    "merged_findings": all_findings,
                    "ranked_findings": scored,
                    "errors": [{"agent_name": "ranking", "error_type": type(e).__name__,
                                "error_message": str(e)}],
                }
        except Exception:
            pass
        return handle_agent_error("ranking", e)
