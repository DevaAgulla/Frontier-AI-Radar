"""Claude API summarization utilities (stub - team will implement)."""

from typing import Dict, Any, List
from anthropic import Anthropic


async def summarize_with_claude(
    content: str, system_prompt: str, max_tokens: int = 1000
) -> str:
    """Summarize content using Claude API (stub)."""
    # STUB: Team will implement
    return "Mock summary from Claude"


async def extract_structured_findings(
    content: str, schema: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Extract structured findings from content using Claude (stub)."""
    # STUB: Team will implement
    return []
