"""HTTP fetching utilities (stub - team will implement)."""

from typing import Dict, Any
import httpx


async def fetch_http(url: str, timeout: int = 30) -> Dict[str, Any]:
    """Fetch URL using httpx (stub)."""
    # STUB: Team will implement
    return {"url": url, "status_code": 200, "content": "mock content"}


async def fetch_with_retry(url: str, max_retries: int = 3) -> Dict[str, Any]:
    """Fetch with exponential backoff retry (stub)."""
    # STUB: Team will implement
    return await fetch_http(url)
