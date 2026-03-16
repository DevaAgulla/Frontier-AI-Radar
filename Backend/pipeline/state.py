"""LangGraph state definition for Frontier AI Radar."""

from typing import Annotated, TypedDict, Optional
from operator import add
from datetime import datetime
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class Finding(TypedDict):
    """Output schema for every intelligence agent."""

    id: str  # uuid
    title: str
    source_url: str
    publisher: str
    date_detected: str  # ISO format
    category: str  # "release"|"research"|"benchmark"|"pricing"|"safety"|"tooling"
    what_changed: str  # max 50 words
    why_it_matters: str  # max 60 words
    confidence: str  # "HIGH"|"MEDIUM"|"LOW" — output label only, never loop controller
    actionability: float  # 0.0-1.0
    novelty: float  # 0.0-1.0
    credibility: float  # 0.0-1.0
    relevance: float  # 0.0-1.0
    impact_score: float  # computed by Ranking Agent
    entities: list[str]  # companies, models, datasets mentioned
    evidence_snippet: str  # direct quote from source, max 40 words
    needs_verification: bool  # True if SOTA/benchmark claim detected
    tags: list[str]
    markdown_summary: str  # formatted for PDF rendering
    agent_source: str  # which agent produced this finding


class VerificationTask(TypedDict):
    """Task created by Model Intelligence Agent for Verification Agent."""

    claim: str  # e.g., "GPT-5 claims SOTA on MMLU"
    model: str  # model name
    benchmark: str  # benchmark name
    source_url: str  # where the claim was found
    finding_id: str  # ID of the finding that triggered this


class VerificationVerdict(TypedDict):
    """Result from Verification Agent checking a claim."""

    task_id: str  # reference to VerificationTask
    verified: bool  # True if claim is confirmed
    verdict: str  # "confirmed"|"contradicted"|"unclear"
    evidence_url: str  # URL to HuggingFace leaderboard or other evidence
    notes: str  # explanation of verdict


class AgentError(TypedDict):
    """Error captured during agent execution."""

    agent_name: str
    error_type: str
    error_message: str
    timestamp: str  # ISO format
    context: dict  # additional context about the error


class RadarState(TypedDict):
    """Shared state for all agents in the LangGraph pipeline."""

    # Run metadata
    run_id: str
    run_mode: str  # "full" | "competitor" | "research" | "model" | "benchmark"
    selected_agents: list[str]
    mission_goal: str
    strategy_plan: dict
    since_timestamp: str  # ISO format datetime
    config: dict

    # Custom URL support
    custom_urls: list[str]  # user-provided URLs for targeted crawling
    url_mode: str  # "default" | "append" | "custom"

    # Database tracking (set by runner, used by downstream agents)
    extraction_db_id: int  # FK to extractions table
    run_db_id: int  # FK to runs table

    # Discovery outputs (Layer 3)
    discovered_sources: Annotated[list[dict], add]
    trend_signals: Annotated[list[dict], add]

    # Intelligence outputs (Layer 4 - each agent writes to its slice)
    competitor_findings: Annotated[list[Finding], add]
    provider_findings: Annotated[list[Finding], add]
    research_findings: Annotated[list[Finding], add]
    hf_findings: Annotated[list[Finding], add]

    # Cross-agent communication
    verification_tasks: Annotated[list[VerificationTask], add]
    verification_verdicts: Annotated[list[VerificationVerdict], add]

    # Post-processing (Layer 5)
    merged_findings: list[Finding]
    ranked_findings: list[Finding]

    # Email recipients (resolved by API layer before pipeline starts)
    email_recipients: list[str]  # populated from users table or single user

    # Final outputs (Layer 6)
    digest_json: dict
    digest_markdown: str
    digest_needs_rewrite: bool  # self-correction flag for digest retry loop
    pdf_path: str
    email_status: str
    errors: Annotated[list[AgentError], add]

    # Persona (loaded by API layer from persona_templates table)
    persona_id: Optional[str]       # UUID of active persona_template (None = default)
    persona_prompt: Optional[str]   # digest_system_prompt from persona_templates
    suggested_questions: Optional[list]  # pre-seeded questions for the active persona

    # ReAct loop tracking
    agent_iterations: dict  # {agent_name: current_iteration}

    # ── Chat node (shared channel with chat_agent subgraph) ────────────────
    # Adding `messages` with add_messages reducer is the LangGraph-documented
    # pattern for embedding a create_react_agent subgraph directly as a node
    # in a parent graph with a different state schema.  LangGraph passes only
    # the shared keys to the subgraph (messages) and merges the output back.
    #
    # Chat fields are Optional — they are None during every digest pipeline run
    # and only populated when the API routes a chat request through this graph.
    messages:        Annotated[list[BaseMessage], add_messages]  # shared with chat subgraph
    chat_query:      Optional[str]   # set by API → triggers route_from_start → chat_agent
    chat_session_id: Optional[str]   # chat session UUID (used as thread_id suffix)
    chat_mode:       Optional[str]   # "text" | "voice"
