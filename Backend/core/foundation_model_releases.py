"""
foundation_model_releases.py

Fetches and aggregates foundation model release information from multiple
provider sources (RSS feeds and JSON APIs), filters by a given date, and
returns a normalized, deduplicated list of releases.

Configuration (URLs, provider maps, timeouts, ...) lives in
core/foundation_model_config.py.

Dependencies:
    pip install httpx feedparser

Originally authored by teammate; integrated into core/ package for use
by the Model Intelligence Agent.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from core.foundation_model_config import (
    GITHUB_OWNER_MAP,
    MAX_PAGES,
    PER_PAGE,
    PROVIDER_MAP,
    RELEASE_SCHEMA,
    REQUEST_TIMEOUT,
    SOURCE_LABELS,
    SOURCE_URLS,
    USER_AGENT,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("foundation_model_releases")

# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------

def _blank_release(**overrides: Any) -> dict[str, Any]:
    """Return a fresh release dict pre-filled with RELEASE_SCHEMA defaults."""
    release = dict(RELEASE_SCHEMA)
    # Lists and dicts must be new instances, not shared references
    release["modalities"] = []
    release["benchmarks"] = {}
    release.update(overrides)
    return release


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _hostname(url: str) -> str:
    """Return the netloc component of *url*."""
    return urlparse(url).netloc.lower()


def _infer_provider(url: str) -> str:
    """Guess the provider name from a URL using PROVIDER_MAP from config."""
    host = _hostname(url)
    for fragment, provider in PROVIDER_MAP.items():
        if fragment in host:
            return provider
    return "Unknown"


def _infer_source_label(url: str) -> str:
    """Return a short stable identifier for the source URL using SOURCE_LABELS from config."""
    host = _hostname(url)
    for fragment, label in SOURCE_LABELS.items():
        if fragment in host:
            return label
    # Fallback: sanitise the hostname
    return re.sub(r"[^a-z0-9]", "_", host)


def _is_rss(url: str, content_type: str) -> bool:
    """Return True when the response looks like an RSS/Atom feed."""
    ct = content_type.lower()
    if any(k in ct for k in ("xml", "rss", "atom")):
        return True
    path = urlparse(url).path.lower()
    return path.endswith((".xml", ".rss", ".atom")) or "rss" in path


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date_value(value: Any) -> date | None:
    """
    Try to extract a ``datetime.date`` from many possible timestamp formats.

    Accepted types / formats:
    * ``datetime.date`` / ``datetime.datetime`` objects
    * ISO-8601 strings  (``2025-03-05``, ``2025-03-05T14:22:00Z``, ...)
    * feedparser ``time.struct_time`` tuples (9-tuple)
    * Unix epoch integers / floats
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    # feedparser time.struct_time -> use calendar.timegm to get UTC epoch
    if isinstance(value, (tuple, list)) and len(value) >= 6:
        try:
            import calendar
            epoch = calendar.timegm(value[:9])  # type: ignore[arg-type]
            return datetime.fromtimestamp(epoch, tz=timezone.utc).date()
        except Exception:
            pass

    # Unix epoch
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except Exception:
            return None

    # String formats
    if isinstance(value, str):
        value = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",     # ISO-8601 with ms + tz  (e.g. HuggingFace)
            "%Y-%m-%dT%H:%M:%S.%fZ",      # ISO-8601 with ms + literal Z
            "%Y-%m-%dT%H:%M:%S%z",        # ISO-8601 no ms + tz
            "%Y-%m-%dT%H:%M:%SZ",         # ISO-8601 no ms + literal Z
            "%Y-%m-%dT%H:%M:%S",          # ISO-8601 no tz
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%a, %d %b %Y %H:%M:%S %z",   # RFC 2822
            "%a, %d %b %Y %H:%M:%S GMT",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt.date()
            except ValueError:
                continue

    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch_url(url: str, client: httpx.Client) -> httpx.Response | None:
    """
    GET *url* and return the response, or ``None`` on error.

    Uses the User-Agent and timeout from config.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/xml, text/xml, */*",
    }
    try:
        response = client.get(url, headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        return response
    except httpx.TimeoutException:
        logger.warning("Timeout fetching %s", url)
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s for %s", exc.response.status_code, url)
    except httpx.RequestError as exc:
        logger.warning("Request error for %s: %s", url, exc)
    return None


def _paginate_json(
    base_url: str,
    client: httpx.Client,
    *,
    page_param: str = "page",
    per_page: int = PER_PAGE,
    max_pages: int = MAX_PAGES,
    page_start: int = 1,
) -> list[dict]:
    """
    Fetch multiple pages of a JSON API that uses page-based pagination.

    Returns the flat list of all items collected across pages.
    Default per_page and max_pages come from config.

    page_start: first page index -- use 0 for HuggingFace (0-indexed), 1 for GitHub.
    """
    results: list[dict] = []
    for page in range(page_start, page_start + max_pages):
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}{page_param}={page}&per_page={per_page}"
        response = _fetch_url(url, client)
        if response is None:
            break
        try:
            data = response.json()
        except Exception:
            logger.warning("Could not decode JSON from %s", url)
            break

        if isinstance(data, list):
            if not data:
                break
            results.extend(data)
        elif isinstance(data, dict):
            items = data.get("items") or data.get("models") or data.get("results") or []
            if not items:
                break
            results.extend(items)
            break  # Usually single-page when wrapped
        else:
            break

    return results


# ---------------------------------------------------------------------------
# RSS / Atom parsing
# ---------------------------------------------------------------------------

def _parse_rss(content: bytes, url: str, target_date: date) -> list[dict[str, Any]]:
    """
    Parse an RSS/Atom feed and return releases matching *target_date*.

    feedparser accepts raw bytes and auto-detects encoding.
    """
    feed = feedparser.parse(content)
    provider = _infer_provider(url)
    source = _infer_source_label(url)
    releases: list[dict[str, Any]] = []

    for entry in feed.entries:
        raw_date = (
            getattr(entry, "published_parsed", None)
            or getattr(entry, "updated_parsed", None)
        )
        entry_date = _parse_date_value(raw_date)
        if entry_date != target_date:
            continue

        title: str = getattr(entry, "title", "") or ""
        link: str = getattr(entry, "link", "") or ""
        summary: str = getattr(entry, "summary", "") or ""

        clean_summary = re.sub(r"<[^>]+>", " ", summary).strip()
        clean_summary = re.sub(r"\s+", " ", clean_summary)

        releases.append(_blank_release(
            model_name=title,
            provider=provider,
            release_date=str(target_date),
            model_details=clean_summary[:500] if clean_summary else None,
            model_page=link or None,
            source=source,
        ))

    return releases


# ---------------------------------------------------------------------------
# XML Sitemap parsing (for providers without RSS, e.g. Anthropic)
# ---------------------------------------------------------------------------

def _parse_sitemap(content: bytes, url: str, target_date: date) -> list[dict[str, Any]]:
    """
    Parse an XML sitemap that contains ``<lastmod>`` timestamps and return
    releases whose lastmod date matches *target_date*.

    Only ``<url>`` entries under a ``/news/`` path (or similar content paths)
    are considered to avoid including static pages like /careers, /about, etc.
    """
    provider = _infer_provider(url)
    source = _infer_source_label(url)
    releases: list[dict[str, Any]] = []

    # Parse using ElementTree; the sitemap namespace varies so strip it
    text = content.decode("utf-8", errors="replace")
    # Remove namespace declarations so tag names are bare
    text = re.sub(r'\sxmlns(?::[^=]+)?="[^"]+"', "", text)

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
    except Exception as exc:
        logger.warning("Could not parse sitemap XML from %s: %s", url, exc)
        return []

    # Content path fragments that indicate editorial/news pages
    content_paths = ("/news/", "/blog/", "/research/", "/press/", "/updates/")

    for url_elem in root.iter("url"):
        loc = (url_elem.findtext("loc") or "").strip()
        lastmod = (url_elem.findtext("lastmod") or "").strip()

        if not loc or not lastmod:
            continue

        # Only keep editorial URLs
        if not any(p in loc for p in content_paths):
            continue

        entry_date = _parse_date_value(lastmod)
        if entry_date != target_date:
            continue

        # Derive a readable title from the URL slug
        slug = loc.rstrip("/").rsplit("/", 1)[-1]
        title = slug.replace("-", " ").title()

        releases.append(_blank_release(
            model_name=title,
            provider=provider,
            release_date=str(target_date),
            model_page=loc,
            source=source,
        ))

    return releases


# ---------------------------------------------------------------------------
# HuggingFace JSON API parsing
# ---------------------------------------------------------------------------

def _parse_huggingface(items: list[dict], target_date: date) -> list[dict[str, Any]]:
    """Normalise a list of HuggingFace model records into the common schema."""
    releases: list[dict[str, Any]] = []

    for item in items:
        raw_date = item.get("lastModified") or item.get("createdAt")
        if _parse_date_value(raw_date) != target_date:
            continue

        model_id: str = item.get("modelId") or item.get("id") or ""
        parts = model_id.split("/", 1)
        provider = parts[0] if len(parts) == 2 else "HuggingFace"
        model_name = parts[-1]

        tags: list[str] = item.get("tags") or []
        pipeline: str = item.get("pipeline_tag") or ""
        modalities = _extract_modalities_from_tags(tags, pipeline)

        config: dict = item.get("config") or {}
        context_length = (
            config.get("max_position_embeddings")
            or config.get("n_positions")
            or config.get("context_length")
        )

        releases.append(_blank_release(
            model_name=model_name,
            provider=provider,
            release_date=str(target_date),
            model_details=pipeline or None,
            modalities=modalities,
            context_length=str(context_length) if context_length else None,
            model_page=f"https://huggingface.co/{model_id}",
            api_link=f"https://huggingface.co/api/models/{model_id}",
            source="huggingface_api",
        ))

    return releases


def _extract_modalities_from_tags(tags: list[str], pipeline: str) -> list[str]:
    """Infer modalities list from HuggingFace tags and pipeline_tag."""
    modalities: list[str] = []
    combined = " ".join(tags + [pipeline]).lower()
    if any(k in combined for k in ("text", "nlp", "causal-lm", "seq2seq", "translation")):
        modalities.append("text")
    if any(k in combined for k in ("image", "vision", "visual", "vqa", "clip")):
        modalities.append("vision")
    if any(k in combined for k in ("audio", "speech", "asr", "tts")):
        modalities.append("audio")
    if any(k in combined for k in ("video",)):
        modalities.append("video")
    return modalities or ["text"]


# ---------------------------------------------------------------------------
# GitHub Releases JSON API parsing
# ---------------------------------------------------------------------------

def _parse_github_releases(items: list[dict], url: str, target_date: date) -> list[dict[str, Any]]:
    """Normalise GitHub releases API items into the common schema."""
    releases: list[dict[str, Any]] = []

    match = re.search(r"/repos/([^/]+/[^/]+)/releases", url)
    repo_path = match.group(1) if match else ""

    for item in items:
        raw_date = item.get("published_at") or item.get("created_at")
        if _parse_date_value(raw_date) != target_date:
            continue

        tag: str = item.get("tag_name") or ""
        name: str = item.get("name") or tag
        body: str = (item.get("body") or "").strip()
        html_url: str = item.get("html_url") or ""

        # Resolve provider from GITHUB_OWNER_MAP (config), fall back to capitalised owner
        owner = repo_path.split("/")[0].lower() if repo_path else ""
        provider = GITHUB_OWNER_MAP.get(owner, owner.capitalize() or "GitHub")

        releases.append(_blank_release(
            model_name=name,
            provider=provider,
            release_date=str(target_date),
            model_details=body[:500] if body else None,
            github_repo=f"https://github.com/{repo_path}" if repo_path else None,
            model_page=html_url or None,
            source="github_api",
        ))

    return releases


# ---------------------------------------------------------------------------
# Generic JSON API fallback
# ---------------------------------------------------------------------------

def _parse_generic_json(data: Any, url: str, target_date: date) -> list[dict[str, Any]]:
    """
    Best-effort parsing of an unknown JSON structure.

    Walks the top-level list (or a common wrapper key) and attempts to
    extract a date and title from common field names.
    """
    releases: list[dict[str, Any]] = []
    items: list[dict] = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("items", "results", "data", "entries", "models", "releases"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    provider = _infer_provider(url)
    source = _infer_source_label(url)

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_date = None
        for field in ("published_at", "created_at", "updated_at", "date", "lastModified", "timestamp"):
            if item.get(field):
                raw_date = item[field]
                break

        if _parse_date_value(raw_date) != target_date:
            continue

        name = item.get("name") or item.get("title") or item.get("id") or "Unknown"
        details = item.get("description") or item.get("summary") or item.get("body")

        releases.append(_blank_release(
            model_name=str(name),
            provider=provider,
            release_date=str(target_date),
            model_details=str(details)[:500] if details else None,
            source=source,
        ))

    return releases


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _fingerprint(release: dict[str, Any]) -> str:
    """Stable SHA-256 fingerprint on (model_name, provider, release_date)."""
    key = "|".join([
        (release.get("model_name") or "").strip().lower(),
        (release.get("provider") or "").strip().lower(),
        (release.get("release_date") or "").strip(),
    ])
    return hashlib.sha256(key.encode()).hexdigest()


def deduplicate_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate releases; richer record (more non-null fields) wins
    when two records share the same (model_name, provider, release_date).
    """
    seen: dict[str, dict[str, Any]] = {}

    for release in releases:
        fp = _fingerprint(release)
        if fp not in seen:
            seen[fp] = release
        else:
            existing_score = sum(1 for v in seen[fp].values() if v not in (None, [], {}))
            new_score = sum(1 for v in release.values() if v not in (None, [], {}))
            if new_score > existing_score:
                seen[fp] = release

    return list(seen.values())


# ---------------------------------------------------------------------------
# Per-URL dispatch
# ---------------------------------------------------------------------------

def _fetch_and_parse(url: str, client: httpx.Client, target_date: date) -> list[dict[str, Any]]:
    """
    Fetch *url* and return normalised releases for *target_date*.

    Dispatch order:
      1. HuggingFace models API  -> paginated JSON -> _parse_huggingface
      2. GitHub releases API     -> paginated JSON -> _parse_github_releases
      3. Everything else         -> single GET, sniff Content-Type:
           RSS/Atom              -> _parse_rss
           JSON                  -> _parse_generic_json
    """
    logger.info("Fetching %s", url)

    # HuggingFace models API -- pages are 0-indexed (p=0 is the first/latest page)
    if "huggingface.co/api/models" in url:
        items = _paginate_json(url, client, page_param="p", page_start=0)
        return _parse_huggingface(items, target_date)

    # GitHub releases API -- 1-indexed pages
    if "api.github.com" in url and "/releases" in url:
        base = re.sub(r"[?&]per_page=\d+", "", url)
        items = _paginate_json(base, client, page_param="page", page_start=1)
        return _parse_github_releases(items, url, target_date)

    response = _fetch_url(url, client)
    if response is None:
        return []

    content_type = response.headers.get("content-type", "")
    path = url.lower()

    # XML sitemap (e.g. Anthropic uses sitemap.xml with <lastmod> instead of RSS)
    if path.endswith("sitemap.xml") or "sitemap" in path:
        return _parse_sitemap(response.content, url, target_date)

    if _is_rss(url, content_type):
        return _parse_rss(response.content, url, target_date)

    try:
        data = response.json()
        return _parse_generic_json(data, url, target_date)
    except Exception:
        logger.warning("Could not parse response from %s as JSON; skipping.", url)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_foundation_model_releases(
    urls: list[str] | None = None,
    current_date: date | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch model release information from the given sources and return only
    releases that occurred on *current_date*.

    Parameters
    ----------
    urls:
        List of feed / API URLs to query. Defaults to SOURCE_URLS from config.
    current_date:
        Only releases whose date matches this value are returned.
        Defaults to today (UTC).

    Returns
    -------
    list[dict]
        Normalised, deduplicated release records sorted by model_name.
        Each record conforms to the schema defined in RELEASE_SCHEMA (config.py).
    """
    if urls is None:
        urls = SOURCE_URLS
    if current_date is None:
        current_date = datetime.now(timezone.utc).date()

    all_releases: list[dict[str, Any]] = []

    with httpx.Client() as client:
        for url in urls:
            try:
                releases = _fetch_and_parse(url, client, current_date)
                logger.info("  -> %d matching release(s) from %s", len(releases), url)
                all_releases.extend(releases)
            except Exception as exc:
                logger.error("Unexpected error processing %s: %s", url, exc, exc_info=True)

    deduplicated = deduplicate_releases(all_releases)
    deduplicated.sort(key=lambda r: (r.get("model_name") or "").lower())

    logger.info(
        "Total releases for %s: %d (from %d raw, across %d source(s))",
        current_date,
        len(deduplicated),
        len(all_releases),
        len(urls),
    )

    return deduplicated
