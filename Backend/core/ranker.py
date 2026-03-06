"""Impact scoring and ranking utilities (stub - team will implement)."""

from typing import Dict, Any, List
from config.settings import load_scoring_config


def compute_impact_score(finding: Dict[str, Any]) -> float:
    """Compute impact score using formula (stub)."""
    # STUB: Team will implement
    weights = load_scoring_config().get("impact_score_weights", {})
    relevance = finding.get("relevance", 0.0)
    novelty = finding.get("novelty", 0.0)
    credibility = finding.get("credibility", 0.0)
    actionability = finding.get("actionability", 0.0)
    
    score = (
        weights.get("relevance", 0.35) * relevance
        + weights.get("novelty", 0.25) * novelty
        + weights.get("credibility", 0.20) * credibility
        + weights.get("actionability", 0.20) * actionability
    )
    return score


def rank_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank findings by impact score (stub)."""
    # STUB: Team will implement
    for finding in findings:
        finding["impact_score"] = compute_impact_score(finding)
    return sorted(findings, key=lambda x: x.get("impact_score", 0.0), reverse=True)
