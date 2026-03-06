"""Short-term memory operations (LangGraph state)."""

from typing import Any, Optional
from pipeline.state import RadarState


def read_from_state(state: RadarState, key: str, default: Any = None) -> Any:
    """Read a value from short-term memory (LangGraph state)."""
    return state.get(key, default)


def write_to_state(state: RadarState, key: str, value: Any) -> RadarState:
    """Write a value to short-term memory (returns new state, never mutates)."""
    return {**state, key: value}


def get_findings_by_agent(state: RadarState, agent_name: str) -> list:
    """Get findings from state for a specific agent."""
    agent_key_map = {
        "competitor_intel": "competitor_findings",
        "model_intel": "provider_findings",
        "research_intel": "research_findings",
        "benchmark_intel": "hf_findings",
    }
    key = agent_key_map.get(agent_name)
    if not key:
        return []
    return state.get(key, [])


def get_all_findings(state: RadarState) -> list:
    """Get all findings from all agents."""
    findings = []
    findings.extend(state.get("competitor_findings", []))
    findings.extend(state.get("provider_findings", []))
    findings.extend(state.get("research_findings", []))
    findings.extend(state.get("hf_findings", []))
    return findings
