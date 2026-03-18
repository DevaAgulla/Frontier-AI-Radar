"""Pydantic output schemas for LangGraph create_react_agent response_format parameter.

Used by: build_react_agent(response_format=SomeSchema)
Result stored in: result["structured_response"]

Benefits vs manual JSON parsing:
  - Eliminates code-fence stripping, truncation repair, boundary detection
  - Type-safe, validated output from every LLM call
  - Compatible with OpenRouter (Claude) and Google Gemini via .with_structured_output()

When response_format is set, LangGraph adds a final "generate_structured_response" node
that calls model.with_structured_output(Schema) on the accumulated messages.
The result is stored as result["structured_response"] (a Pydantic model instance).

Fallback pattern (always kept for safety):
    structured = result.get("structured_response")
    if structured is not None:
        output = structured.model_dump()   # or .findings, etc.
    else:
        # legacy JSON parsing path
        final_text = extract_agent_output(result["messages"])
        output = parse_json_output(final_text)
"""

from typing import List, Optional

from pydantic import BaseModel, Field


# ── SHARED: Single Finding ──────────────────────────────────────────────────

class FindingOutput(BaseModel):
    """Pydantic version of the Finding TypedDict defined in pipeline/state.py.

    All float scores are 0.0–1.0.  The Ranking Agent overwrites impact_score
    deterministically after this output is parsed.
    """

    id: str = Field(description="Unique UUID for this finding")
    title: str = Field(description="Short, descriptive title of the finding")
    source_url: str = Field(description="Primary source URL")
    publisher: str = Field(description="Organization or site that published this")
    date_detected: str = Field(description="ISO-8601 date string")
    category: str = Field(
        description="One of: release | research | benchmark | pricing | safety | tooling"
    )
    what_changed: str = Field(description="What happened — max 50 words")
    why_it_matters: str = Field(description="Business or research impact — max 60 words")
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    actionability: float = Field(default=0.5, description="0.0–1.0")
    novelty: float = Field(default=0.5, description="0.0–1.0")
    credibility: float = Field(default=0.5, description="0.0–1.0")
    relevance: float = Field(default=0.5, description="0.0–1.0")
    impact_score: float = Field(default=0.0, description="Computed by Ranking Agent — leave 0.0")
    entities: List[str] = Field(
        default_factory=list,
        description="Companies, models, or datasets mentioned",
    )
    evidence_snippet: str = Field(description="Direct quote from source — max 40 words")
    needs_verification: bool = Field(
        default=False,
        description="True when a SOTA or benchmark claim requires independent verification",
    )
    tags: List[str] = Field(default_factory=list)
    markdown_summary: str = Field(description="Plain-text summary for rendering — no markdown symbols, no asterisks, no hashes")
    agent_source: str = Field(
        description="Which agent produced this — e.g. research_intel, competitor_intel"
    )


# ── INTEL AGENTS (research, competitor, model, benchmark) ──────────────────

class FindingsOutput(BaseModel):
    """Output schema for all four Layer 4 intelligence agents.

    Each intel agent emits a list of findings; the Ranking Agent collects
    all four lists and merges/deduplicates them.
    """

    findings: List[FindingOutput] = Field(
        description="Intelligence findings ordered by relevance descending"
    )


# ── MISSION CONTROLLER ─────────────────────────────────────────────────────

class MissionPlanOutput(BaseModel):
    """Output schema for Mission Controller Agent (Layer 1)."""

    mission_goal: str = Field(description="One-sentence mission statement for this run")
    selected_agents: List[str] = Field(
        default_factory=list,
        description="Agent names to activate for this run",
    )
    focus_keywords: str = Field(
        description="Search keywords for intelligence agents, OR-joined"
    )
    priority_areas: List[str] = Field(
        default_factory=list,
        description="Topic priority areas for this run",
    )
    reasoning: str = Field(description="Why this focus and these agents were chosen")


# ── STRATEGY PLANNER ───────────────────────────────────────────────────────

class AgentInstructionsOutput(BaseModel):
    """Per-agent execution guidance from the Strategy Planner."""

    research_intel: Optional[str] = None
    competitor_intel: Optional[str] = None
    model_intel: Optional[str] = None
    benchmark_intel: Optional[str] = None


class StrategyPlanOutput(BaseModel):
    """Output schema for Strategy Planner Agent (Layer 2)."""

    focus_keywords: str = Field(description="Optimised search query for intelligence agents")
    priority_areas: List[str] = Field(default_factory=list)
    agent_instructions: Optional[AgentInstructionsOutput] = None
    reasoning: str = Field(description="Why this strategy was chosen")


# ── VERIFICATION AGENT ─────────────────────────────────────────────────────

class VerificationVerdictOutput(BaseModel):
    """Pydantic version of VerificationVerdict TypedDict in pipeline/state.py."""

    task_id: str
    finding_id: str = ""
    verified: bool
    verdict: str = Field(description="confirmed | contradicted | unclear")
    evidence_url: str = ""
    notes: str = ""
    actual_score: Optional[float] = None
    claimed_score: Optional[float] = None


class VerificationOutput(BaseModel):
    """Output schema for Verification Agent (Layer 5)."""

    verdicts: List[VerificationVerdictOutput] = Field(
        description="One verdict per verification task"
    )


# ── RANKING AGENT (LLM dedup pass) ─────────────────────────────────────────

class DeduplicationOutput(BaseModel):
    """Output schema for the Ranking Agent's optional LLM dedup pass.

    The agent returns only the IDs it wants to keep, not the full findings.
    Deterministic scoring happens before the LLM pass and is preserved.
    """

    ids_to_keep: List[str] = Field(
        description="Finding IDs to retain after deduplication, highest impact first"
    )


# ── DIGEST AGENT ───────────────────────────────────────────────────────────

class DigestSectionsOutput(BaseModel):
    """Topic-level deep-dive sections in the digest."""

    research: str = Field(default="", description="HTML paragraphs deep-dive for research/paper findings — NO markdown")
    models: str = Field(default="", description="HTML paragraphs deep-dive for model provider findings — NO markdown")
    benchmarks: str = Field(default="", description="HTML paragraphs deep-dive for benchmark/leaderboard findings — NO markdown")
    competitors: str = Field(default="", description="HTML paragraphs deep-dive for competitor findings — NO markdown")


class DigestOutput(BaseModel):
    """Output schema for Digest Compiler Agent (Layer 6)."""

    executive_summary: str = Field(description="Clean HTML paragraphs executive summary with top 7 items — NO markdown")
    sections: DigestSectionsOutput = Field(default_factory=DigestSectionsOutput)
    top_findings: List[FindingOutput] = Field(
        default_factory=list,
        description="Top 7 finding objects (subset of ranked_findings)",
    )
    total_findings: int = Field(default=0)
    digest_date: str = Field(description="ISO date string, e.g. 2026-03-13")


# ── NOTIFICATION AGENT ─────────────────────────────────────────────────────

class NotificationOutput(BaseModel):
    """Output schema for Notification Agent (Layer 6)."""

    subject: str = Field(description="Email subject line")
    html_body: str = Field(description="Full HTML email body — plain HTML, no embedded CSS")
    preview: str = Field(description="One-line summary of the top finding for preview text")
