"""All tools for Frontier AI Radar agents.

REAL implementations:
  - crawl_research_sources  (wraps teammate's multi-source research crawler)
  - search_arxiv            (wraps _fetch_arxiv from research crawler)
  - read_memory             (wired to memory/long_term.py JSON storage)
  - write_memory            (wired to memory/long_term.py JSON storage)

STUBS (team will provide):
  All other tools remain placeholders with correct signatures.

Every tool uses Pydantic BaseModel input schemas with Field(description=...)
so the LLM gets rich metadata for autonomous tool selection.
"""

from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from datetime import datetime, date, timezone
import asyncio
import json
import os
import re
import hashlib

from memory.long_term import (
    read_memory as _lt_read,
    write_memory as _lt_write,
)
from core.research_crawler import crawl_research_papers, _fetch_arxiv
from config.research_sources import RESEARCH_PUBLICATION_URLS
from config.settings import settings


# ============================================================================
# LINK SCORING HELPER (used by crawl_page & fetch_headless)
# ============================================================================

# Common nav/utility paths that are never articles
_NAV_PATHS = frozenset([
    "/about", "/careers", "/business", "/pricing", "/foundation",
    "/login", "/signup", "/sign-up", "/sign-in", "/contact",
    "/api", "/docs", "/safety", "/privacy", "/terms", "/legal",
    "/help", "/support", "/faq", "/settings", "/account",
    "/team", "/press", "/investors", "/partners", "/enterprise",
    "/download", "/install", "/status", "/sitemap",
])

# URL path fragments that signal article / blog-post pages
_ARTICLE_PATH_PATTERNS = ("/index/", "/blog/", "/news/", "/post/",
                          "/research/", "/article/", "/updates/",
                          "/announcements/", "/releases/")

# Slug keywords that suggest newsworthy content
_ARTICLE_SLUG_KEYWORDS = ("introducing", "announcing", "update", "release",
                          "launch", "new-", "how-we", "gpt-", "llama",
                          "gemini", "claude", "mistral", "benchmark",
                          "safety", "system-card")


def _score_link(url: str, text: str) -> int:
    """Return a priority score for a discovered link.

    -1  → skip entirely (navigation / utility page)
     0  → neutral
    >0  → likely an article; higher = more likely
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()

    # ── Skip obvious nav pages ───────────────────────────────────────
    if path in _NAV_PATHS or any(path.startswith(p + "/") and path.count("/") <= 2
                                  for p in _NAV_PATHS):
        return -1

    # Also skip very short paths like "/" or "/en"
    if len(path) <= 3:
        return -1

    score = 0

    # ── Article-like URL patterns ────────────────────────────────────
    if any(pat in path for pat in _ARTICLE_PATH_PATTERNS):
        score += 3

    # ── Deep paths (3+ segments → /blog/introducing-gpt-5-4) ────────
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 3:
        score += 2

    # ── Descriptive link text (>20 chars, likely an article title) ───
    if len(text) > 20:
        score += 2

    # ── Slug keywords suggesting news / releases ─────────────────────
    slug = segments[-1] if segments else ""
    if any(kw in slug for kw in _ARTICLE_SLUG_KEYWORDS):
        score += 1

    return score


# ============================================================================
# WEB FETCHING TOOLS
# ============================================================================


class CrawlPageInput(BaseModel):
    url: str = Field(description="The full URL of the webpage to fetch and parse")


@tool(args_schema=CrawlPageInput)
async def crawl_page(url: str) -> Dict[str, Any]:
    """
    Fetch and parse HTML content from a webpage using httpx + BeautifulSoup.
    USE THIS FOR: Primary method for fetching HTML content from any URL.
    DO NOT USE FOR: JavaScript-rendered pages that require browser execution (use fetch_headless instead).
    RETURNS: {
        "url": str,
        "title": str,
        "content": str,
        "date": str (ISO format or None),
        "status_code": int,
        "content_length": int
    }
    """
    import httpx
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    loop = asyncio.get_running_loop()

    def _fetch() -> Dict[str, Any]:
        try:
            from urllib.parse import urlparse, urljoin

            with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
                resp = client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # ── Extract internal links BEFORE stripping noise ─────────
            base_parsed = urlparse(url)
            base_domain = base_parsed.netloc
            discovered_links = []
            seen_hrefs = set()
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                full_url = urljoin(url, href)
                parsed = urlparse(full_url)
                if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean not in seen_hrefs and clean != url.rstrip("/"):
                        skip_patterns = ("/cdn-cgi/", "/static/", "/assets/", "/api/", "#", ".png", ".jpg", ".css", ".js")
                        if not any(pat in clean.lower() for pat in skip_patterns):
                            seen_hrefs.add(clean)
                            link_text = a_tag.get_text(strip=True)[:120]
                            score = _score_link(clean, link_text)
                            if score >= 0:  # skip nav pages (score == -1)
                                discovered_links.append({"url": clean, "text": link_text, "_score": score})

            # Sort by score descending so articles come first
            discovered_links.sort(key=lambda x: x.pop("_score", 0), reverse=True)

            # Remove script/style/nav/footer noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            title = soup.title.get_text(strip=True) if soup.title else ""

            # Try to extract main content area
            main = soup.find("main") or soup.find("article") or soup.find("body")
            text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

            # Collapse whitespace and cap at 8000 chars to avoid token overload
            text = re.sub(r"\n{3,}", "\n\n", text)[:8000]

            # Try to find a publication date
            date_found = None
            for meta in soup.find_all("meta"):
                prop = meta.get("property", "") or meta.get("name", "")
                if "date" in prop.lower() or "published" in prop.lower():
                    date_found = meta.get("content")
                    break
            if not date_found:
                time_el = soup.find("time")
                if time_el:
                    date_found = time_el.get("datetime") or time_el.get_text(strip=True)

            return {
                "url": url,
                "title": title,
                "content": text,
                "date": date_found,
                "status_code": resp.status_code,
                "content_length": len(text),
                "links": discovered_links[:50],
            }
        except Exception as exc:
            return {
                "url": url,
                "title": "",
                "content": f"Error fetching page: {exc}",
                "date": None,
                "status_code": 0,
                "content_length": 0,
                "links": [],
            }

    return await loop.run_in_executor(None, _fetch)


class FetchRssFeedInput(BaseModel):
    url: str = Field(description="The full URL of the RSS or Atom feed to parse")


@tool(args_schema=FetchRssFeedInput)
async def fetch_rss_feed(url: str) -> List[Dict[str, Any]]:
    """
    Parse RSS or Atom feed and return list of entries.
    USE THIS FOR: RSS/Atom feeds from blogs, news sites, product changelogs.
    DO NOT USE FOR: HTML pages (use crawl_page instead).
    RETURNS: List of {
        "title": str,
        "link": str,
        "published": str (ISO format),
        "summary": str,
        "author": str (optional)
    }
    """
    import httpx
    import feedparser as _feedparser

    loop = asyncio.get_event_loop()

    def _fetch_and_parse() -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": "FrontierAIRadar/1.0"},
                timeout=30,
                follow_redirects=True,
            )
            resp.raise_for_status()
            feed = _feedparser.parse(resp.content)
        except Exception as exc:
            return [{"error": f"Failed to fetch RSS feed: {exc}", "url": url}]

        entries: List[Dict[str, Any]] = []
        for entry in feed.entries[:50]:  # cap at 50 entries
            # Extract published date
            raw_date = getattr(entry, "published", None) or getattr(entry, "updated", None)
            if raw_date is None:
                # Try struct_time variants
                parsed_time = (
                    getattr(entry, "published_parsed", None)
                    or getattr(entry, "updated_parsed", None)
                )
                if parsed_time:
                    try:
                        import calendar
                        epoch = calendar.timegm(parsed_time[:9])
                        raw_date = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
                    except Exception:
                        raw_date = ""

            # Clean summary HTML
            summary = getattr(entry, "summary", "") or ""
            summary = re.sub(r"<[^>]+>", " ", summary).strip()
            summary = re.sub(r"\s+", " ", summary)

            entries.append({
                "title": getattr(entry, "title", "") or "",
                "link": getattr(entry, "link", "") or "",
                "published": raw_date or "",
                "summary": summary[:500],
                "author": getattr(entry, "author", "") or "",
            })

        return entries

    return await loop.run_in_executor(None, _fetch_and_parse)


class FetchHeadlessInput(BaseModel):
    url: str = Field(description="The full URL of the JS-rendered page to fetch via headless browser")


@tool(args_schema=FetchHeadlessInput)
async def fetch_headless(url: str) -> Dict[str, Any]:
    """
    Fetch webpage content using headless browser (Playwright) for JavaScript-rendered pages.
    USE THIS FOR: Pages that require JavaScript execution to render content.
    DO NOT USE FOR: Static HTML pages (use crawl_page instead - it's faster).
    RETURNS: {
        "url": str,
        "title": str,
        "content": str,
        "date": str (ISO format or None),
        "status_code": int,
        "content_length": int
    }
    """
    from bs4 import BeautifulSoup

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "url": url,
            "title": "",
            "content": "Error: playwright not installed. Run: pip install playwright && playwright install chromium",
            "date": None,
            "status_code": 0,
            "content_length": 0,
        }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # Navigate — use domcontentloaded (fires fast) then wait for JS to render.
            # "networkidle" hangs on sites with continuous background requests (e.g. OpenAI blog).
            response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status_code = response.status if response else 0

            # Give JS 3-4 seconds to hydrate/render the page content
            await page.wait_for_timeout(4000)

            # Extract rendered HTML
            html = await page.content()
            title = await page.title()

            await browser.close()

        # Parse with BeautifulSoup just like crawl_page
        soup = BeautifulSoup(html, "html.parser")

        # ── Extract internal links BEFORE stripping nav/footer ────────
        from urllib.parse import urlparse, urljoin
        base_parsed = urlparse(url)
        base_domain = base_parsed.netloc
        discovered_links = []
        seen_hrefs = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            full_url = urljoin(url, href)
            parsed = urlparse(full_url)
            # Keep only same-domain, http(s), non-anchor, non-asset links
            if parsed.netloc == base_domain and parsed.scheme in ("http", "https"):
                clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean not in seen_hrefs and clean != url.rstrip("/"):
                    # Skip obvious non-article paths
                    skip_patterns = ("/cdn-cgi/", "/static/", "/assets/", "/api/", "#", ".png", ".jpg", ".css", ".js")
                    if not any(pat in clean.lower() for pat in skip_patterns):
                        seen_hrefs.add(clean)
                        link_text = a_tag.get_text(strip=True)[:120]
                        score = _score_link(clean, link_text)
                        if score >= 0:  # skip nav pages (score == -1)
                            discovered_links.append({"url": clean, "text": link_text, "_score": score})

        # Sort by score descending so articles come first
        discovered_links.sort(key=lambda x: x.pop("_score", 0), reverse=True)

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Extract main content
        main = soup.find("main") or soup.find("article") or soup.find("body")
        text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)[:8000]

        # Try to find publication date
        date_found = None
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "") or meta.get("name", "")
            if "date" in prop.lower() or "published" in prop.lower():
                date_found = meta.get("content")
                break
        if not date_found:
            time_el = soup.find("time")
            if time_el:
                date_found = time_el.get("datetime") or time_el.get_text(strip=True)

        return {
            "url": url,
            "title": title,
            "content": text,
            "date": date_found,
            "status_code": status_code,
            "content_length": len(text),
            "links": discovered_links[:50],  # cap at 50 links
        }

    except Exception as exc:
        return {
            "url": url,
            "title": "",
            "content": f"Headless fetch error: {exc}",
            "date": None,
            "status_code": 0,
            "content_length": 0,
        }


class ExtractPdfDoclingInput(BaseModel):
    url: str = Field(description="The URL of the PDF document to extract structured content from")


@tool(args_schema=ExtractPdfDoclingInput)
async def extract_pdf_docling(url: str) -> Dict[str, Any]:
    """
    Extract structured content from PDF using pdfplumber (tables, sections, text).
    USE THIS FOR: PDF documents that need structured extraction (tables, sections).
    DO NOT USE FOR: HTML pages or when PDF extraction is disabled globally.
    RETURNS: {
        "url": str,
        "sections": List[Dict],
        "tables": List[Dict],
        "figures": List[Dict],
        "text": str
    }
    """
    import httpx
    import tempfile

    loop = asyncio.get_running_loop()

    def _extract():
        try:
            import pdfplumber
        except ImportError:
            return {
                "url": url,
                "sections": [],
                "tables": [],
                "figures": [],
                "text": "Error: pdfplumber not installed. Run: pip install pdfplumber",
            }

        try:
            # Download PDF to a temp file
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "FrontierAIRadar/1.0"})
                resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            sections = []
            tables = []
            all_text_parts = []

            with pdfplumber.open(tmp_path) as pdf:
                for i, page in enumerate(pdf.pages[:30]):  # cap at 30 pages
                    text = page.extract_text() or ""
                    all_text_parts.append(text)

                    # Extract tables from the page
                    page_tables = page.extract_tables() or []
                    for t_idx, table in enumerate(page_tables):
                        if table and len(table) > 1:
                            headers = [str(c or "") for c in table[0]]
                            rows = [[str(c or "") for c in row] for row in table[1:]]
                            tables.append({
                                "page": i + 1,
                                "table_index": t_idx,
                                "headers": headers,
                                "rows": rows[:20],  # cap rows
                            })

                    # Treat each page as a section
                    if text.strip():
                        first_line = text.strip().split("\n")[0][:120]
                        sections.append({
                            "title": first_line,
                            "content": text[:2000],
                            "page": i + 1,
                        })

            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

            full_text = "\n\n".join(all_text_parts)[:10000]

            return {
                "url": url,
                "sections": sections,
                "tables": tables,
                "figures": [],  # pdfplumber doesn't extract figures
                "text": full_text,
            }
        except Exception as exc:
            return {
                "url": url,
                "sections": [],
                "tables": [],
                "figures": [],
                "text": f"PDF extraction failed: {exc}",
            }

    return await loop.run_in_executor(None, _extract)


class DiffContentInput(BaseModel):
    old_hash: str = Field(description="SHA-256 hash of the previously crawled content")
    new_content: str = Field(description="The new page content to compare against the old hash")


@tool(args_schema=DiffContentInput)
async def diff_content(old_hash: str, new_content: str) -> Dict[str, Any]:
    """
    Detect real content changes by comparing hash of old content with new content.
    USE THIS FOR: Detecting if a webpage actually changed since last crawl.
    DO NOT USE FOR: Comparing two different URLs (use separate crawl_page calls).
    RETURNS: {
        "changed": bool,
        "new_hash": str,
        "diff_summary": str
    }
    """
    import difflib

    new_hash = hashlib.sha256(new_content.encode()).hexdigest()
    changed = old_hash != new_hash

    diff_summary = "No changes detected."
    if changed:
        # Try to retrieve old content from long-term memory for a textual diff
        old_content = _lt_read(f"content_cache:{old_hash}")
        if old_content and isinstance(old_content, str):
            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile="previous",
                tofile="current",
                lineterm="",
                n=1,
            ))
            if diff_lines:
                # Cap at 1500 chars to avoid token overload
                diff_summary = "\n".join(diff_lines[:60])[:1500]
            else:
                diff_summary = "Content hash changed but textual diff is empty (whitespace or encoding change)."
        else:
            diff_summary = f"Content changed (old hash: {old_hash[:12]}… → new hash: {new_hash[:12]}…). Previous content not cached for line-level diff."

        # Cache new content for future diffs
        _lt_write(f"content_cache:{new_hash}", new_content[:10000])

    return {
        "changed": changed,
        "new_hash": new_hash,
        "diff_summary": diff_summary,
    }


# ============================================================================
# SEARCH & DISCOVERY TOOLS
# ============================================================================


class SearchWebInput(BaseModel):
    query: str = Field(description="The search query string for Tavily web search")


@tool(args_schema=SearchWebInput)
async def search_web(query: str) -> List[Dict[str, Any]]:
    """
    General web search using Tavily API.
    USE THIS FOR: Discovering new sources, finding relevant web pages, fallback search.
    DO NOT USE FOR: Academic paper search (use search_arxiv or search_semantic_scholar instead).
    RETURNS: List of {
        "title": str,
        "url": str,
        "snippet": str,
        "score": float
    }
    """
    if not settings.tavily_api_key:
        return [{"title": "Web search unavailable", "url": "", "snippet": "TAVILY_API_KEY is not configured.", "score": 0.0}]
    try:
        from tavily import AsyncTavilyClient  # type: ignore
        client = AsyncTavilyClient(api_key=settings.tavily_api_key)
        results = await client.search(query, max_results=5)
        hits = results.get("results", [])
        return [
            {
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "snippet": h.get("content", ""),
                "score": h.get("score", 0.0),
            }
            for h in hits
        ]
    except Exception as exc:
        return [{"title": "Search error", "url": "", "snippet": str(exc), "score": 0.0}]


class CrawlResearchSourcesInput(BaseModel):
    source_names: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional list of source names to crawl, e.g. ['arxiv', 'huggingface_papers']. "
            "If None or empty, crawls ALL configured sources."
        ),
    )
    crawl_date: Optional[str] = Field(
        default=None,
        description="ISO date string (YYYY-MM-DD) for daily sources. Defaults to today.",
    )


@tool(args_schema=CrawlResearchSourcesInput)
async def crawl_research_sources(
    source_names: Optional[List[str]] = None,
    crawl_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Crawl configured research paper sources and return a unified result dict.
    Currently enabled: arxiv, huggingface_papers (fast subset).
    USE THIS FOR: Bulk paper fetching across multiple academic sources in one call.
    DO NOT USE FOR: Targeted single-source follow-up (use search_arxiv instead).
    RETURNS: {
        "crawl_date": str,
        "start_date": str,
        "end_date": str,
        "generated_at": str,
        "total": int,
        "sources": {
            "arxiv": {"count": int, "papers": [...]},
            "huggingface_papers": {"count": int, "papers": [...]}
        }
    }
    Each paper has: id, title, abstract, authors, published, abstract_url, pdf_url, source.
    """
    sources = RESEARCH_PUBLICATION_URLS
    if source_names:
        sources = [s for s in sources if s["name"] in source_names]

    cd = date.fromisoformat(crawl_date) if crawl_date else date.today()

    # The teammate's crawler uses synchronous httpx.Client — run in executor
    # so we don't block the async event loop.
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: crawl_research_papers(sources=sources, crawl_date=cd),
    )
    return result


class SearchArxivInput(BaseModel):
    query: str = Field(description="Search query with OR/AND operators, e.g. 'evaluation OR benchmark'")
    categories: List[str] = Field(description="arXiv categories to search, e.g. ['cs.CL', 'cs.LG', 'stat.ML']")
    since_date: str = Field(description="ISO date string (YYYY-MM-DD). Only return papers published after this date.")


@tool(args_schema=SearchArxivInput)
async def search_arxiv(
    query: str, categories: List[str], since_date: str
) -> List[Dict[str, Any]]:
    """
    Search arXiv for AI/ML papers matching a query and category filter.
    USE THIS FOR: Targeted follow-up arXiv searches when bulk results are thin.
    DO NOT USE FOR: Non-academic content (use search_web) or citation data (use search_semantic_scholar).
    RETURNS: List of paper dicts with: id, title, abstract, authors, published,
             abstract_url, pdf_url, primary_category, categories, source.
    """
    # Build arXiv search params from the tool's inputs
    cat_expr = "(" + " OR ".join(f"cat:{c}" for c in categories) + ")"
    topic_parts = [kw.strip() for kw in query.replace(" OR ", "|").replace(" AND ", "|").split("|") if kw.strip()]
    topic_expr = "(" + " OR ".join(f"all:{t}" for t in topic_parts) + ")" if topic_parts else f"(all:{query})"

    params = {
        "search_topics": topic_expr,
        "categories": cat_expr,
        "max_results": 50,
    }

    try:
        start = date.fromisoformat(since_date[:10]) if since_date else date.today()
    except ValueError:
        start = date.today()
    end = date.today()

    loop = asyncio.get_event_loop()
    papers = await loop.run_in_executor(
        None,
        lambda: _fetch_arxiv("http://export.arxiv.org/api/query", params, start, end),
    )
    return papers


class SearchSemanticScholarInput(BaseModel):
    query: str = Field(description="Search query for academic papers on Semantic Scholar")


@tool(args_schema=SearchSemanticScholarInput)
async def search_semantic_scholar(query: str) -> List[Dict[str, Any]]:
    """
    Search Semantic Scholar for academic papers with citation data.
    USE THIS FOR: Finding papers with citation counts, related papers, when arXiv results are thin.
    DO NOT USE FOR: Primary paper discovery (use search_arxiv first - it's faster).
    RETURNS: List of {
        "paper_id": str,
        "title": str,
        "authors": List[str],
        "abstract": str,
        "year": int,
        "citation_count": int,
        "url": str
    }
    """
    import httpx

    api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": 20,
        "fields": "paperId,title,authors,abstract,year,citationCount,url",
    }
    headers = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    return [{"error": f"Semantic Scholar API returned {resp.status_code}"}]
                data = resp.json()
                results = []
                for paper in data.get("data", []):
                    authors = [a.get("name", "") for a in (paper.get("authors") or [])]
                    results.append({
                        "paper_id": paper.get("paperId", ""),
                        "title": paper.get("title", ""),
                        "authors": authors,
                        "abstract": (paper.get("abstract") or "")[:1000],
                        "year": paper.get("year") or 0,
                        "citation_count": paper.get("citationCount") or 0,
                        "url": paper.get("url") or f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
                    })
                return results if results else [{"error": "No papers found", "query": query}]
        except Exception as exc:
            return [{"error": f"Semantic Scholar search failed: {exc}"}]

    return await loop.run_in_executor(None, _fetch)


class SearchGithubTrendingInput(BaseModel):
    """No required inputs — fetches current trending AI/ML repos."""
    pass


@tool(args_schema=SearchGithubTrendingInput)
async def search_github_trending() -> List[Dict[str, Any]]:
    """
    Get trending AI/ML repositories from GitHub.
    USE THIS FOR: Discovering new AI tools, libraries, or research codebases.
    DO NOT USE FOR: Searching specific repositories (use GitHub API directly).
    RETURNS: List of {
        "name": str,
        "full_name": str,
        "description": str,
        "stars": int,
        "url": str,
        "language": str
    }
    """
    import httpx
    from datetime import timedelta

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            # Search for AI/ML repos created or pushed in the last 7 days, sorted by stars
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            params = {
                "q": f"topic:machine-learning OR topic:deep-learning OR topic:llm pushed:>={week_ago}",
                "sort": "stars",
                "order": "desc",
                "per_page": 20,
            }
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get("https://api.github.com/search/repositories", params=params, headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "FrontierAIRadar/1.0",
                })
                if resp.status_code != 200:
                    return [{"error": f"GitHub API returned {resp.status_code}"}]
                data = resp.json()
                results = []
                for repo in data.get("items", [])[:20]:
                    results.append({
                        "name": repo.get("name", ""),
                        "full_name": repo.get("full_name", ""),
                        "description": (repo.get("description") or "")[:300],
                        "stars": repo.get("stargazers_count", 0),
                        "url": repo.get("html_url", ""),
                        "language": repo.get("language") or "Unknown",
                    })
                return results if results else [{"error": "No trending repos found"}]
        except Exception as exc:
            return [{"error": f"GitHub trending search failed: {exc}"}]

    return await loop.run_in_executor(None, _fetch)


class SearchHackernewsInput(BaseModel):
    query: str = Field(description="Search query for Hacker News stories, e.g. 'AI OR LLM'")


@tool(args_schema=SearchHackernewsInput)
async def search_hackernews(query: str) -> List[Dict[str, Any]]:
    """
    Search Hacker News for top AI stories using Firebase API.
    USE THIS FOR: Community signals, trending AI discussions, early signal detection.
    DO NOT USE FOR: Academic research (use search_arxiv instead).
    RETURNS: List of {
        "title": str,
        "url": str,
        "score": int,
        "comments": int,
        "time": str (ISO format)
    }
    """
    import httpx

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            params = {
                "query": query,
                "tags": "story",
                "hitsPerPage": 20,
            }
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get("https://hn.algolia.com/api/v1/search", params=params)
                if resp.status_code != 200:
                    return [{"error": f"HN API returned {resp.status_code}"}]
                data = resp.json()
                results = []
                for hit in data.get("hits", []):
                    created_ts = hit.get("created_at_i")
                    time_iso = (
                        datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
                        if created_ts else datetime.now(timezone.utc).isoformat()
                    )
                    results.append({
                        "title": hit.get("title", ""),
                        "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                        "score": hit.get("points") or 0,
                        "comments": hit.get("num_comments") or 0,
                        "time": time_iso,
                    })
                return results if results else [{"error": "No HN stories found", "query": query}]
        except Exception as exc:
            return [{"error": f"Hacker News search failed: {exc}"}]

    return await loop.run_in_executor(None, _fetch)


class SearchRedditInput(BaseModel):
    subreddit: str = Field(description="Subreddit name without r/ prefix, e.g. 'MachineLearning'")
    query: str = Field(description="Search query within the subreddit")


@tool(args_schema=SearchRedditInput)
async def search_reddit(subreddit: str, query: str) -> List[Dict[str, Any]]:
    """
    Search Reddit subreddit for posts using JSON API (no auth required).
    USE THIS FOR: Community discussions, trending topics in AI subreddits.
    DO NOT USE FOR: Academic content or official announcements.
    RETURNS: List of {
        "title": str,
        "url": str,
        "score": int,
        "comments": int,
        "subreddit": str,
        "created": str (ISO format)
    }
    """
    import httpx

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            search_url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q": query,
                "sort": "relevance",
                "t": "week",
                "limit": 20,
                "restrict_sr": "on",
            }
            headers = {"User-Agent": "FrontierAIRadar/1.0"}
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(search_url, params=params, headers=headers)
                if resp.status_code != 200:
                    return [{"error": f"Reddit API returned {resp.status_code}"}]
                data = resp.json()
                results = []
                children = data.get("data", {}).get("children", [])
                for child in children:
                    post = child.get("data", {})
                    created_utc = post.get("created_utc")
                    created_iso = (
                        datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                        if created_utc else datetime.now(timezone.utc).isoformat()
                    )
                    results.append({
                        "title": post.get("title", ""),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "score": post.get("score", 0),
                        "comments": post.get("num_comments", 0),
                        "subreddit": post.get("subreddit", subreddit),
                        "created": created_iso,
                    })
                return results if results else [{"error": "No Reddit posts found", "query": query}]
        except Exception as exc:
            return [{"error": f"Reddit search failed: {exc}"}]

    return await loop.run_in_executor(None, _fetch)


# ============================================================================
# HUGGINGFACE TOOLS
# ============================================================================


class FetchHfLeaderboardInput(BaseModel):
    leaderboard_name: str = Field(description="HuggingFace leaderboard ID, e.g. 'open_llm_leaderboard'")


@tool(args_schema=FetchHfLeaderboardInput)
async def fetch_hf_leaderboard(leaderboard_name: str) -> Dict[str, Any]:
    """
    Fetch structured leaderboard data from HuggingFace using Datasets API.
    USE THIS FOR: Getting current benchmark rankings, SOTA claims, model comparisons.
    DO NOT USE FOR: Individual model details (use fetch_hf_model_card instead).
    RETURNS: {
        "leaderboard": str,
        "models": List[Dict with model_id, scores, rank, etc.],
        "last_updated": str (ISO format)
    }
    """
    import httpx

    # Map friendly names to actual HF dataset paths
    LEADERBOARD_MAP = {
        "open_llm": "open-llm-leaderboard/results",
        "open_llm_leaderboard": "open-llm-leaderboard/results",
        "chatbot_arena": "lmsys/chatbot_arena_leaderboard",
        "bigcode": "bigcode/bigcode-models-leaderboard",
    }

    dataset_id = LEADERBOARD_MAP.get(leaderboard_name.lower().replace("-", "_"), leaderboard_name)
    api_url = f"https://huggingface.co/api/datasets/{dataset_id}"

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                # Get dataset info
                resp = client.get(api_url)
                if resp.status_code != 200:
                    return {
                        "leaderboard": leaderboard_name,
                        "models": [],
                        "last_updated": datetime.utcnow().isoformat(),
                        "error": f"Dataset API returned {resp.status_code}",
                    }
                data = resp.json()

                # Try to get a sample of rows from the dataset
                rows_url = f"https://datasets-server.huggingface.co/first-rows?dataset={dataset_id}&config=default&split=train"
                rows_resp = client.get(rows_url)
                models = []
                if rows_resp.status_code == 200:
                    rows_data = rows_resp.json()
                    for i, row in enumerate(rows_data.get("rows", [])[:30]):
                        row_data = row.get("row", {})
                        models.append({
                            "rank": i + 1,
                            "model_id": row_data.get("model_name_for_query") or row_data.get("model") or row_data.get("Model") or str(row_data.get("id", f"model_{i}")),
                            "scores": {k: v for k, v in row_data.items()
                                       if isinstance(v, (int, float)) and k.lower() not in ("rank", "index")},
                        })

                return {
                    "leaderboard": leaderboard_name,
                    "models": models,
                    "last_updated": data.get("lastModified", datetime.utcnow().isoformat()),
                }
        except Exception as exc:
            return {
                "leaderboard": leaderboard_name,
                "models": [],
                "last_updated": datetime.utcnow().isoformat(),
                "error": str(exc),
            }

    return await loop.run_in_executor(None, _fetch)


class SearchHfModelsInput(BaseModel):
    query: str = Field(description="Search query for HuggingFace models")
    sort: str = Field(default="trending", description="Sort order: 'trending', 'downloads', 'likes', 'recent'")


@tool(args_schema=SearchHfModelsInput)
async def search_hf_models(query: str, sort: str = "trending") -> List[Dict[str, Any]]:
    """
    Search HuggingFace for models using HF API.
    USE THIS FOR: Finding trending models, recent model releases, model discovery.
    DO NOT USE FOR: Leaderboard data (use fetch_hf_leaderboard instead).
    RETURNS: List of {
        "model_id": str,
        "author": str,
        "downloads": int,
        "likes": int,
        "tags": List[str],
        "url": str
    }
    """
    import httpx

    SORT_MAP = {
        "trending": "trending",
        "downloads": "downloads",
        "likes": "likes",
        "recent": "lastModified",
    }
    sort_param = SORT_MAP.get(sort, "trending")
    api_url = "https://huggingface.co/api/models"

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(api_url, params={
                    "search": query,
                    "sort": sort_param,
                    "direction": -1,
                    "limit": 20,
                })
                if resp.status_code != 200:
                    return [{"error": f"HF API returned {resp.status_code}"}]
                results = []
                for m in resp.json():
                    model_id = m.get("modelId") or m.get("id", "")
                    author = model_id.split("/")[0] if "/" in model_id else ""
                    results.append({
                        "model_id": model_id,
                        "author": author,
                        "downloads": m.get("downloads", 0),
                        "likes": m.get("likes", 0),
                        "tags": (m.get("tags") or [])[:10],
                        "url": f"https://huggingface.co/{model_id}",
                    })
                return results
        except Exception as exc:
            return [{"error": str(exc)}]

    return await loop.run_in_executor(None, _fetch)


class FetchHfModelCardInput(BaseModel):
    model_id: str = Field(description="HuggingFace model ID in 'org/model-name' format")


@tool(args_schema=FetchHfModelCardInput)
async def fetch_hf_model_card(model_id: str) -> Dict[str, Any]:
    """
    Fetch full model details from HuggingFace model card.
    USE THIS FOR: Getting complete model information, architecture details, usage examples.
    DO NOT USE FOR: Leaderboard rankings (use fetch_hf_leaderboard instead).
    RETURNS: {
        "model_id": str,
        "author": str,
        "description": str,
        "tags": List[str],
        "metrics": Dict,
        "config": Dict,
        "url": str
    }
    """
    import httpx

    api_url = f"https://huggingface.co/api/models/{model_id}"

    loop = asyncio.get_running_loop()

    def _fetch():
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(api_url)
                if resp.status_code != 200:
                    return {
                        "model_id": model_id,
                        "error": f"HF API returned {resp.status_code}",
                        "url": f"https://huggingface.co/{model_id}",
                    }
                data = resp.json()
                mid = data.get("modelId") or data.get("id", model_id)
                author = mid.split("/")[0] if "/" in mid else data.get("author", "")

                # Extract card text (README) if available
                card_data = data.get("cardData") or {}
                description = card_data.get("description") or ""
                if not description:
                    # Fallback: try siblings for README
                    readme_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
                    try:
                        r2 = client.get(readme_url)
                        if r2.status_code == 200:
                            description = r2.text[:3000]
                    except Exception:
                        pass

                # Extract safetensors / config info
                config = {}
                if data.get("config"):
                    config = {k: v for k, v in data["config"].items()
                              if k in ("model_type", "hidden_size", "num_hidden_layers",
                                       "num_attention_heads", "vocab_size", "max_position_embeddings")}

                return {
                    "model_id": mid,
                    "author": author,
                    "description": description[:3000],
                    "tags": (data.get("tags") or [])[:15],
                    "metrics": {
                        "downloads": data.get("downloads", 0),
                        "likes": data.get("likes", 0),
                        "pipeline_tag": data.get("pipeline_tag", ""),
                        "library_name": data.get("library_name", ""),
                    },
                    "config": config,
                    "url": f"https://huggingface.co/{mid}",
                }
        except Exception as exc:
            return {
                "model_id": model_id,
                "error": str(exc),
                "url": f"https://huggingface.co/{model_id}",
            }

    return await loop.run_in_executor(None, _fetch)


class DiffLeaderboardSnapshotsInput(BaseModel):
    today: Dict[str, Any] = Field(description="Today's leaderboard snapshot from fetch_hf_leaderboard")
    yesterday: Dict[str, Any] = Field(description="Yesterday's leaderboard snapshot from memory")


@tool(args_schema=DiffLeaderboardSnapshotsInput)
async def diff_leaderboard_snapshots(
    today: Dict[str, Any], yesterday: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compare two leaderboard snapshots to detect rank movements and new entries.
    USE THIS FOR: Detecting SOTA changes, rank shifts, new model entries.
    DO NOT USE FOR: Comparing different leaderboards (use same leaderboard_name for both snapshots).
    RETURNS: {
        "new_models": List[str],
        "rank_changes": List[Dict with model_id, old_rank, new_rank],
        "sota_changes": List[Dict]
    }
    """
    def _normalize(entries: list) -> dict:
        """Coerce each entry to a dict. Handles plain strings (LLM hallucination guard)."""
        result = {}
        for i, m in enumerate(entries):
            if isinstance(m, str):
                m = {"model_id": m, "rank": i + 1, "scores": {}}
            mid = m.get("model_id") or m.get("model") or f"model_{i}"
            result[mid] = m
        return result

    today_models    = _normalize(today.get("models", []))
    yesterday_models = _normalize(yesterday.get("models", []))

    new_models = [mid for mid in today_models if mid not in yesterday_models]

    rank_changes = []
    sota_changes = []
    for mid, tm in today_models.items():
        if mid in yesterday_models:
            ym = yesterday_models[mid]
            old_rank = ym.get("rank")
            new_rank = tm.get("rank")
            if old_rank is not None and new_rank is not None and old_rank != new_rank:
                rank_changes.append({
                    "model_id": mid,
                    "old_rank": old_rank,
                    "new_rank": new_rank,
                    "delta": old_rank - new_rank,  # positive = improved
                })
            # Check for SOTA changes (any score improved significantly)
            t_scores = tm.get("scores", {})
            y_scores = ym.get("scores", {})
            for bench, t_val in t_scores.items():
                y_val = y_scores.get(bench)
                if y_val is not None and isinstance(t_val, (int, float)) and isinstance(y_val, (int, float)):
                    if t_val > y_val * 1.01:  # >1% improvement
                        sota_changes.append({
                            "model_id": mid,
                            "benchmark": bench,
                            "old_score": y_val,
                            "new_score": t_val,
                        })

    # If a new model is rank 1, that is also a SOTA change
    for mid in new_models:
        tm = today_models[mid]
        if tm.get("rank") == 1:
            sota_changes.append({
                "model_id": mid,
                "event": "new_model_at_rank_1",
                "scores": tm.get("scores", {}),
            })

    return {
        "new_models": new_models,
        "rank_changes": sorted(rank_changes, key=lambda x: abs(x.get("delta", 0)), reverse=True),
        "sota_changes": sota_changes,
    }


# ============================================================================
# MEMORY TOOLS
# ============================================================================


class ReadMemoryInput(BaseModel):
    type: str = Field(description="Memory type: 'short_term', 'long_term', or 'entity'")
    key: str = Field(description="The memory key to read, e.g. 'seen_arxiv_ids', 'last_digest_summary'")


@tool(args_schema=ReadMemoryInput)
async def read_memory(type: str, key: str) -> Dict[str, Any]:
    """
    Read from memory system (short-term, long-term, or entity store).
    USE THIS FOR: Checking seen content, entity context, historical data before processing.
    DO NOT USE FOR: Writing data (use write_memory instead).
    RETURNS: {
        "type": str,
        "key": str,
        "value": Any,
        "found": bool
    }
    """
    if type == "long_term":
        value = _lt_read(key)
        return {
            "type": type,
            "key": key,
            "value": value,
            "found": value is not None,
        }
    if type == "entity":
        # key is treated as a search query for entity memory
        from memory.entity_store import get_entity_store
        results = get_entity_store().search_entities(key, top_k=5)
        return {
            "type": type,
            "key": key,
            "value": results,
            "found": bool(results),
        }
    # short_term: read directly from memory_kv with st_ prefix
    if type == "short_term":
        value = _lt_read(f"st_{key}")
        return {
            "type": type,
            "key": key,
            "value": value,
            "found": value is not None,
        }
    return {
        "type": type,
        "key": key,
        "value": None,
        "found": False,
    }


class WriteMemoryInput(BaseModel):
    type: str = Field(description="Memory type: 'short_term', 'long_term', or 'entity'")
    key: str = Field(description="The memory key to write to, e.g. 'seen_arxiv_ids'")
    value: Any = Field(description="The value to store (will be JSON-serialized)")


@tool(args_schema=WriteMemoryInput)
async def write_memory(type: str, key: str, value: Any) -> Dict[str, Any]:
    """
    Write to memory system (short-term, long-term, or entity store).
    USE THIS FOR: Saving findings, seen IDs, entity profiles after processing.
    DO NOT USE FOR: Reading data (use read_memory instead).
    RETURNS: {
        "type": str,
        "key": str,
        "success": bool
    }
    """
    if type == "long_term":
        # Deserialise if caller passed a JSON string
        real_value = value
        if isinstance(value, str):
            try:
                real_value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        _lt_write(key, real_value)
        return {"type": type, "key": key, "success": True}

    if type == "entity":
        # value must be a dict (EntityProfile) or JSON string of one
        from memory.entity_store import get_entity_store
        entity_data = value
        if isinstance(value, str):
            try:
                entity_data = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                entity_data = {"id": key, "name": key}
        if not isinstance(entity_data, dict):
            entity_data = {"id": key, "name": str(value)}
        # Ensure required fields have defaults
        entity_data.setdefault("id", key)
        entity_data.setdefault("name", key)
        entity_data.setdefault("entity_type", "unknown")
        entity_data.setdefault("description", "")
        entity_data.setdefault("source", "agent")
        get_entity_store().add_entity(entity_data)
        return {"type": type, "key": key, "success": True}

    if type == "short_term":
        # Persist short_term data to memory_kv with st_ prefix for cross-run access
        real_value = value
        if isinstance(value, str):
            try:
                real_value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        _lt_write(f"st_{key}", real_value)
        return {"type": type, "key": key, "success": True}

    return {"type": type, "key": key, "success": True}


class SearchEntityMemoryInput(BaseModel):
    query: str = Field(description="Semantic search query for entities, e.g. 'OpenAI GPT model'")
    top_k: int = Field(default=5, description="Number of top results to return (default 5)")


@tool(args_schema=SearchEntityMemoryInput)
async def search_entity_memory(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Semantic search in entity memory (ChromaDB) for organizations, models, benchmarks.
    USE THIS FOR: Getting context about known entities before summarizing findings.
    DO NOT USE FOR: General web search (use search_web instead).
    RETURNS: List of {
        "id": str,
        "name": str,
        "type": str,
        "description": str,
        "distance": float
    }
    """
    from memory.entity_store import get_entity_store

    loop = asyncio.get_running_loop()

    def _search():
        try:
            store = get_entity_store()
            raw_results = store.search_entities(query, top_k=top_k)
            results = []
            for item in raw_results:
                meta = item.get("metadata", {})
                results.append({
                    "id": item.get("id", ""),
                    "name": meta.get("name", ""),
                    "type": meta.get("type", "unknown"),
                    "description": item.get("document", ""),
                    "distance": item.get("distance", 1.0),
                })
            return results if results else [{
                "id": "",
                "name": "",
                "type": "none",
                "description": f"No entities found matching '{query}'.",
                "distance": 1.0,
            }]
        except Exception as exc:
            return [{
                "id": "",
                "name": "",
                "type": "error",
                "description": f"Entity memory search failed: {exc}",
                "distance": 1.0,
            }]

    return await loop.run_in_executor(None, _search)


# ============================================================================
# CROSS-AGENT TOOLS
# ============================================================================


class FlagVerificationTaskInput(BaseModel):
    claim: str = Field(description="The SOTA or benchmark claim to verify, e.g. 'GPT-5 claims SOTA on MMLU'")
    model: str = Field(description="The model name making the claim")
    benchmark: str = Field(description="The benchmark name being claimed, e.g. 'MMLU', 'HellaSwag'")
    source_url: str = Field(description="URL where the claim was originally found")


@tool(args_schema=FlagVerificationTaskInput)
async def flag_verification_task(
    claim: str, model: str, benchmark: str, source_url: str
) -> Dict[str, Any]:
    """
    Create a verification task for the Verification Agent to check a SOTA/benchmark claim.
    USE THIS FOR: When Model Intelligence Agent detects a SOTA claim that needs independent verification.
    DO NOT USE FOR: Research papers or non-benchmark claims.
    RETURNS: {
        "task_id": str,
        "claim": str,
        "model": str,
        "benchmark": str,
        "source_url": str,
        "created": str (ISO format)
    }
    """
    # STUB: Team will provide real implementation
    # This will write to state["verification_tasks"]
    return {
        "task_id": "mock-task-id",
        "claim": claim,
        "model": model,
        "benchmark": benchmark,
        "source_url": source_url,
        "created": datetime.utcnow().isoformat(),
    }


# ============================================================================
# SCORING & DELIVERY TOOLS
# ============================================================================


class ComputeImpactScoreInput(BaseModel):
    finding: Dict[str, Any] = Field(
        description="A Finding dict with relevance, novelty, credibility, actionability fields (each 0.0-1.0)"
    )


@tool(args_schema=ComputeImpactScoreInput)
async def compute_impact_score(finding: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute impact score using formula: 0.35*Relevance + 0.25*Novelty + 0.20*Credibility + 0.20*Actionability.
    USE THIS FOR: Ranking findings by impact after all intelligence agents have emitted.
    DO NOT USE FOR: Individual component scores (those are computed by agents).
    RETURNS: {
        "impact_score": float (0.0-1.0),
        "breakdown": {
            "relevance": float,
            "novelty": float,
            "credibility": float,
            "actionability": float
        }
    }
    """
    def _clamp(val, lo=0.0, hi=1.0):
        try:
            return max(lo, min(hi, float(val)))
        except (TypeError, ValueError):
            return 0.5  # safe default

    r = _clamp(finding.get("relevance", 0.5))
    n = _clamp(finding.get("novelty", 0.5))
    c = _clamp(finding.get("credibility", 0.5))
    a = _clamp(finding.get("actionability", 0.5))

    score = 0.35 * r + 0.25 * n + 0.20 * c + 0.20 * a

    return {
        "impact_score": round(score, 3),
        "breakdown": {
            "relevance": round(r, 3),
            "novelty": round(n, 3),
            "credibility": round(c, 3),
            "actionability": round(a, 3),
        },
    }


class RenderPdfInput(BaseModel):
    html_content: str = Field(description="Complete branded HTML content to render as PDF")


@tool(args_schema=RenderPdfInput)
async def render_pdf(html_content: str) -> Dict[str, Any]:
    """
    Render HTML content to a real PDF file on disk using xhtml2pdf.
    USE THIS FOR: Generating final PDF digest from compiled HTML template.
    DO NOT USE FOR: Raw HTML from web pages (use crawl_page for that).
    RETURNS: {
        "pdf_path": str,
        "size_bytes": int,
        "pages": int
    }
    """
    from xhtml2pdf import pisa  # lazy import to keep startup fast

    output_dir = settings.reports_output_path
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"digest-{timestamp}.pdf"
    pdf_path = str(output_dir / filename)

    # pisa.CreatePDF is synchronous – run in executor to avoid blocking
    loop = asyncio.get_running_loop()

    def _generate() -> dict:
        with open(pdf_path, "wb") as fh:
            pisa_status = pisa.CreatePDF(html_content, dest=fh)

        if pisa_status.err:
            return {
                "pdf_path": "",
                "size_bytes": 0,
                "pages": 0,
                "error": f"xhtml2pdf reported {pisa_status.err} error(s)",
            }

        size_bytes = os.path.getsize(pdf_path)
        # xhtml2pdf doesn't expose page count easily; estimate from file
        return {
            "pdf_path": pdf_path,
            "size_bytes": size_bytes,
            "pages": max(1, size_bytes // 5000),  # rough estimate
        }

    result = await loop.run_in_executor(None, _generate)
    return result


class SendEmailMcpInput(BaseModel):
    to: List[str] = Field(description="List of recipient email addresses")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body content (HTML or plain text)")
    pdf_path: str = Field(description="Absolute or relative path to PDF attachment")


@tool(args_schema=SendEmailMcpInput)
async def send_email_mcp(
    to: List[str], subject: str, body: str, pdf_path: str
) -> Dict[str, Any]:
    """
    Send email with PDF attachment.
    Priority: Brevo HTTP API → Resend HTTP API → SMTP fallback.
    USE THIS FOR: All email delivery in the notification agent.
    DO NOT USE FOR: Direct API calls to external services.
    RETURNS: {
        "status": str ("sent"|"failed"),
        "message_id": str,
        "error": str (optional)
    }
    """
    import os
    import base64
    import httpx
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from pathlib import Path

    brevo_api_key = os.environ.get("BREVO_API_KEY", "") or (settings.brevo_api_key or "")
    resend_api_key = os.environ.get("RESEND_API_KEY", "")

    # Determine which provider to use (priority order)
    if brevo_api_key:
        provider = "Brevo"
    elif resend_api_key:
        provider = "Resend"
    else:
        provider = "SMTP"

    try:
        # ── LOG: Entry ──────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"[EMAIL] send_email_mcp called")
        print(f"[EMAIL] To: {to}")
        print(f"[EMAIL] Subject: {subject}")
        print(f"[EMAIL] PDF path: {pdf_path}")
        print(f"[EMAIL] Provider: {provider}")
        print(f"[EMAIL] From: {settings.email_from}")
        print(f"{'='*60}")

        # ── Helper: read PDF for attachment ────────────────────────
        pdf_file = Path(pdf_path)
        pdf_b64 = None
        pdf_filename = "report.pdf"
        if pdf_file.exists():
            pdf_size = pdf_file.stat().st_size
            pdf_b64 = base64.b64encode(pdf_file.read_bytes()).decode("utf-8")
            pdf_filename = pdf_file.name
            print(f"[EMAIL] PDF attached: {pdf_filename} ({pdf_size} bytes)")
        else:
            print(f"[EMAIL] WARNING: PDF file NOT found at {pdf_path}")

        # ════════════════════════════════════════════════════════════
        # 1. BREVO HTTP API (primary — 300 free emails/day, any recipient)
        # ════════════════════════════════════════════════════════════
        if provider == "Brevo":
            print("[EMAIL] Using Brevo HTTP API (port 443 — never blocked)")

            # Parse sender: support "Name <email>" or plain email
            from_email = settings.email_from
            from_name = "Frontier AI Radar"
            if "<" in from_email and ">" in from_email:
                parts = from_email.split("<")
                from_name = parts[0].strip()
                from_email = parts[1].replace(">", "").strip()

            brevo_payload: Dict[str, Any] = {
                "sender": {
                    "name": from_name,
                    "email": from_email,
                },
                "to": [{"email": addr.strip()} for addr in to],
                "subject": subject,
                "htmlContent": body,
            }

            # Attach PDF if available
            if pdf_b64:
                brevo_payload["attachment"] = [{
                    "content": pdf_b64,
                    "name": pdf_filename,
                }]

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": brevo_api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=brevo_payload,
                    timeout=30.0,
                )

            if resp.status_code in (200, 201):
                resp_data = resp.json()
                message_id = resp_data.get("messageId", "brevo-ok")
                print(f"\n[EMAIL] *** EMAIL SENT SUCCESSFULLY via Brevo ***")
                print(f"[EMAIL] Message-ID: {message_id}")
                print(f"[EMAIL] Recipients: {to}")
                print(f"[EMAIL] Subject: {subject}")
                print(f"{'='*60}\n")
                return {"status": "sent", "message_id": str(message_id), "error": None}
            else:
                error_msg = f"Brevo API error {resp.status_code}: {resp.text}"
                print(f"\n[EMAIL] *** BREVO SEND FAILED ***")
                print(f"[EMAIL] Error: {error_msg}")
                print(f"{'='*60}\n")
                return {"status": "failed", "message_id": "", "error": error_msg}

        # ════════════════════════════════════════════════════════════
        # 2. RESEND HTTP API (fallback — kept for backward compat)
        # ════════════════════════════════════════════════════════════
        if provider == "Resend":
            print("[EMAIL] Using Resend HTTP API (port 443 — never blocked)")
            from_addr = settings.email_from or "Frontier AI Radar <onboarding@resend.dev>"

            resend_payload: Dict[str, Any] = {
                "from": from_addr,
                "to": to,
                "subject": subject,
                "html": body,
            }

            if pdf_b64:
                resend_payload["attachments"] = [{
                    "filename": pdf_filename,
                    "content": pdf_b64,
                }]

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=resend_payload,
                    timeout=30.0,
                )

            if resp.status_code in (200, 201):
                resp_data = resp.json()
                message_id = resp_data.get("id", "resend-ok")
                print(f"\n[EMAIL] *** EMAIL SENT SUCCESSFULLY via Resend ***")
                print(f"[EMAIL] Message-ID: {message_id}")
                print(f"[EMAIL] Recipients: {to}")
                print(f"[EMAIL] Subject: {subject}")
                print(f"{'='*60}\n")
                return {"status": "sent", "message_id": str(message_id), "error": None}
            else:
                error_msg = f"Resend API error {resp.status_code}: {resp.text}"
                print(f"\n[EMAIL] *** RESEND SEND FAILED ***")
                print(f"[EMAIL] Error: {error_msg}")
                print(f"{'='*60}\n")
                return {"status": "failed", "message_id": "", "error": error_msg}

        # ════════════════════════════════════════════════════════════
        # 3. SMTP FALLBACK (for local development only)
        # ════════════════════════════════════════════════════════════
        print(f"[EMAIL] Using SMTP fallback ({settings.smtp_host}:{settings.smtp_port})")

        msg = MIMEMultipart()
        msg["From"] = settings.email_from
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        if pdf_file.exists():
            with open(pdf_file, "rb") as f:
                attachment = MIMEApplication(f.read(), _subtype="pdf")
                attachment.add_header(
                    "Content-Disposition", "attachment",
                    filename=pdf_filename,
                )
                msg.attach(attachment)

        smtp_port = settings.smtp_port
        print(f"[EMAIL] Connecting to SMTP {settings.smtp_host}:{smtp_port}...")
        loop = asyncio.get_event_loop()

        def _send():
            if smtp_port == 465:
                with smtplib.SMTP_SSL(settings.smtp_host, smtp_port) as server:
                    server.ehlo()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, smtp_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)
            return msg.get("Message-ID", "sent-ok")

        message_id = await loop.run_in_executor(None, _send)

        print(f"\n[EMAIL] *** EMAIL SENT SUCCESSFULLY via SMTP ***")
        print(f"[EMAIL] Message-ID: {message_id}")
        print(f"[EMAIL] Recipients: {to}")
        print(f"[EMAIL] Subject: {subject}")
        print(f"{'='*60}\n")

        return {
            "status": "sent",
            "message_id": str(message_id),
            "error": None,
        }
    except Exception as e:
        print(f"\n[EMAIL] *** EMAIL SEND FAILED ***")
        print(f"[EMAIL] Error: {type(e).__name__}: {e}")
        print(f"[EMAIL] Recipients: {to}")
        print(f"[EMAIL] Provider: {provider}")
        print(f"{'='*60}\n")

        return {
            "status": "failed",
            "message_id": "",
            "error": str(e),
        }


# ============================================================================
# FOUNDATION MODEL RELEASE TRACKING TOOL
# ============================================================================


class FetchFoundationModelReleasesInput(BaseModel):
    target_date: str = Field(
        default="",
        description=(
            "End date for release window (YYYY-MM-DD format). "
            "Leave empty to use today's date (UTC)."
        ),
    )
    since_days: int = Field(
        default=7,
        description=(
            "Number of days to look back from target_date (inclusive). "
            "1 = today only, 7 = last 7 days (default)."
        ),
    )


@tool(args_schema=FetchFoundationModelReleasesInput)
async def fetch_foundation_model_releases_tool(target_date: str = "", since_days: int = 7) -> List[Dict[str, Any]]:
    """
    Fetch foundation model releases from 12+ provider sources within a date window.
    USE THIS FOR: Getting real-time model release data from OpenAI, Anthropic,
        Google DeepMind, Meta, Mistral, HuggingFace, xAI, NVIDIA, and GitHub.
    DO NOT USE FOR: Historical research papers (use crawl_research_sources).
    SOURCES QUERIED:
        - HuggingFace API (8 orgs: meta-llama, mistralai, Qwen, google, deepseek-ai, microsoft, openai, anthropic)
        - OpenAI blog RSS feed
        - Anthropic sitemap.xml
        - Google DeepMind blog RSS feed
        - xAI (Grok) blog RSS feed
        - NVIDIA developer blog RSS feed
        - GitHub releases API (openai-cookbook)
    RETURNS: List of normalized release dicts, each with:
        model_name, provider, release_date, model_details, modalities,
        context_length, benchmarks, pricing, api_link, model_page,
        github_repo, source.
    Returns empty list if no releases found for the target date window.
    """
    from core.foundation_model_releases import fetch_foundation_model_releases

    loop = asyncio.get_event_loop()

    # Parse target_date or default to today (UTC)
    if target_date and target_date.strip():
        try:
            td = date.fromisoformat(target_date.strip())
        except ValueError:
            td = datetime.now(timezone.utc).date()
    else:
        td = datetime.now(timezone.utc).date()

    since = max(1, since_days)

    # Run the synchronous httpx-based fetcher in a thread pool
    def _fetch() -> List[Dict[str, Any]]:
        return fetch_foundation_model_releases(current_date=td, since_days=since)

    return await loop.run_in_executor(None, _fetch)


# ============================================================================
# HF BENCHMARK & LEADERBOARD TRACKING TOOL
# ============================================================================


class FetchHfBenchmarkDataInput(BaseModel):
    leaderboard_top_n: int = Field(
        default=20,
        description=(
            "Max number of Open LLM Leaderboard models to fetch (default 20)."
        ),
    )
    trending_limit: int = Field(
        default=15,
        description=(
            "Max number of trending models to fetch (default 15)."
        ),
    )
    eval_datasets_limit: int = Field(
        default=15,
        description=(
            "Max number of eval benchmark datasets to fetch (default 15)."
        ),
    )


@tool(args_schema=FetchHfBenchmarkDataInput)
async def fetch_hf_benchmark_data_tool(
    leaderboard_top_n: int = 20,
    trending_limit: int = 15,
    eval_datasets_limit: int = 15,
) -> Dict[str, Any]:
    """
    Fetch HuggingFace benchmark leaderboard data, trending models, and eval datasets.
    USE THIS FOR: Getting real-time Open LLM Leaderboard rankings, trending AI models,
        and official benchmark/evaluation datasets from HuggingFace.
    DO NOT USE FOR: Foundation model releases (use fetch_foundation_model_releases_tool).
    DATA SOURCES:
        - Open LLM Leaderboard (HF dataset: open-llm-leaderboard/contents)
        - Trending models (HfApi.list_models sorted by trending_score)
        - Official benchmark/eval datasets (HfApi.list_datasets)
    RETURNS: Dict with keys:
        leaderboard_data: List of model ranking rows (model name, scores, etc.)
        trending_data: List of trending models (id, downloads, likes, pipeline_tag)
        eval_datasets_data: List of eval datasets (id, downloads, likes, tags)
        errors: List of error messages (if any)
    Returns empty lists if no data available.
    """
    from core.hf_benchmark_tracker import fetch_hf_benchmark_data

    loop = asyncio.get_event_loop()

    def _fetch() -> Dict[str, Any]:
        return fetch_hf_benchmark_data(
            leaderboard_top_n=leaderboard_top_n,
            trending_limit=trending_limit,
            eval_datasets_limit=eval_datasets_limit,
        )

    return await loop.run_in_executor(None, _fetch)
