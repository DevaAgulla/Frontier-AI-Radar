"""Content change detection utilities — real difflib implementation."""

import hashlib
import difflib
from typing import Dict, Any


def compute_content_hash(content: str) -> str:
    """Compute SHA256 hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()


def detect_changes(old_hash: str, new_content: str, old_content: str = "") -> Dict[str, Any]:
    """Detect changes between old hash and new content.

    Args:
        old_hash: SHA256 hash of the previously seen content.
        new_content: The newly fetched content string.
        old_content: (Optional) The previously seen content for line-level diff.

    Returns:
        Dict with changed (bool), new_hash (str), diff_summary (str).
    """
    new_hash = compute_content_hash(new_content)
    changed = old_hash != new_hash

    diff_summary = "No changes detected."
    if changed and old_content:
        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
            n=1,
        ))
        if diff_lines:
            # Cap output to avoid token overload
            diff_summary = "\n".join(diff_lines[:60])[:1500]
        else:
            diff_summary = "Hash changed but textual diff is empty (whitespace/encoding change)."
    elif changed:
        diff_summary = f"Content changed (hash: {old_hash[:12]}… → {new_hash[:12]}…). Previous content not provided for line-level diff."

    return {
        "changed": changed,
        "new_hash": new_hash,
        "diff_summary": diff_summary,
    }
