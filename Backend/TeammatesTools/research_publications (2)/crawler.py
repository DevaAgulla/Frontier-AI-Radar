"""
crawler.py — Research Publications Crawler
==========================================
A single reusable function `crawl_research_papers()` that fetches AI/ML
research papers from multiple sources and returns a unified JSON-serializable dict.

Supported sources (driven by config):
  - arxiv
  - openalex
  - huggingface_papers
  - semantic_scholar
  - pubmed
  - openreview
  - acl_anthology

Quick usage:
    from crawler import crawl_research_papers
    from config import RESEARCH_PUBLICATION_URLS

    result = crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)
    print(result["total"])          # total papers across all sources
    print(result["sources"])        # per-source results
"""

import httpx
import re
import time
import xml.etree.ElementTree as ET
import json
from datetime import datetime, date, timezone
from urllib.parse import urlencode


# =============================================================================
# Shared AI relevance filter
# =============================================================================

_AI_PATTERN = re.compile(
    r"\b("
    r"large language model|language model|llm|llms"
    r"|multimodal|multi.modal"
    r"|vision.language|text.to.image|text.to.video"
    r"|diffusion model|generative model|foundation model"
    r"|self.attention|attention mechanism"
    r"|deep learning|neural network|reinforcement learning"
    r"|in.context learning|instruction.tun|fine.tun|rlhf|sft"
    r"|chain.of.thought|retrieval.augmented|rag"
    r"|agentic|multi.agent|autonomous agent|ai agent"
    r"|model alignment|safety alignment|reward model"
    r"|hallucination|jailbreak|red.team"
    r"|gpt|bert|llama|mistral|gemini|qwen|deepseek|falcon|phi.?"
    r"|transformer model|pre.trained model|vision transformer"
    r")\b",
    re.IGNORECASE,
)

_CS_AI_FIELDS = {"computer science", "mathematics"}
_CS_AI_SUBFIELDS = {
    "artificial intelligence", "computer vision and pattern recognition",
    "human-computer interaction", "computational theory and mathematics",
    "computer networks and communications", "software",
    "information systems", "natural language processing",
}


def _ai_match(text: str) -> bool:
    return bool(_AI_PATTERN.search(text))


# =============================================================================
# HTTP helper with retry / backoff
# =============================================================================

def _get(client: httpx.Client, url: str, params: dict | None = None,
         retries: int = 4, backoff: float = 2.0) -> httpx.Response:
    for attempt in range(retries):
        r = client.get(url, params=params)
        if r.status_code == 429:
            wait = backoff * (2 ** attempt)
            print(f"  [rate-limit] 429 — retrying in {wait:.0f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


# =============================================================================
# Source fetchers
# =============================================================================

# ── 1. ArXiv ─────────────────────────────────────────────────────────────────

_ARXIV_NS = {
    "atom":       "http://www.w3.org/2005/Atom",
    "arxiv":      "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _fetch_arxiv(base_url: str, params: dict,
                 start: date, end: date) -> list[dict]:
    search_topics = params.get(
        "search_topics",
        "(all:llm OR all:multimodal OR all:agent OR all:alignment OR all:evaluation)"
    )
    categories = params.get("categories", "(cat:cs.CL OR cat:cs.LG OR cat:cs.AI)")
    max_results = params.get("max_results", 100)

    date_range   = f"submittedDate:[{start.strftime('%Y%m%d')}0000 TO {end.strftime('%Y%m%d')}2359]"
    search_query = f"{search_topics} AND {categories} AND {date_range}"

    url = base_url + "?" + urlencode({
        "search_query": search_query,
        "sortBy": "submittedDate", "sortOrder": "descending",
        "max_results": max_results,
    })
    print(f"[arxiv] GET {url}")

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = _get(client, url)

    entries = ET.fromstring(r.text).findall("atom:entry", _ARXIV_NS)
    print(f"[arxiv] {len(entries)} papers found")

    results = []
    for entry in entries:
        def text(tag, ns="atom"):
            el = entry.find(f"{ns}:{tag}", _ARXIV_NS)
            return el.text.strip() if el is not None and el.text else None

        links = {}
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("rel") == "alternate": links["abstract_url"] = link.get("href")
            elif link.get("title") == "pdf":   links["pdf_url"]      = link.get("href")

        authors    = [a.findtext("atom:name", namespaces=_ARXIV_NS).strip()
                      for a in entry.findall("atom:author", _ARXIV_NS)
                      if a.findtext("atom:name", namespaces=_ARXIV_NS)]
        primary    = entry.find("arxiv:primary_category", _ARXIV_NS)
        categories_list = [c.get("term") for c in entry.findall("atom:category", _ARXIV_NS)]
        arxiv_id   = text("id")

        results.append({
            "id":               arxiv_id.split("/abs/")[-1] if arxiv_id else None,
            "title":            text("title"),
            "abstract":         text("summary"),
            "authors":          authors,
            "published":        text("published"),
            "updated":          text("updated"),
            "abstract_url":     links.get("abstract_url", arxiv_id),
            "pdf_url":          links.get("pdf_url"),
            "primary_category": primary.get("term") if primary is not None else None,
            "categories":       categories_list,
            "doi":              text("doi", "arxiv"),
            "comment":          text("comment", "arxiv"),
            "journal_ref":      text("journal_ref", "arxiv"),
            "source":           "arxiv",
        })
    return results


# ── 2. OpenAlex ──────────────────────────────────────────────────────────────

def _reconstruct_abstract(inv: dict | None) -> str | None:
    if not inv: return None
    return " ".join(w for _, w in sorted(
        [(pos, w) for w, ps in inv.items() for pos in ps]
    ))


def _openalex_relevant(work: dict) -> bool:
    title    = (work.get("display_name") or "").lower()
    abstract = (_reconstruct_abstract(work.get("abstract_inverted_index")) or "").lower()
    pt       = work.get("primary_topic") or {}
    field    = (pt.get("field", {}) or {}).get("display_name", "").lower()
    subfield = (pt.get("subfield", {}) or {}).get("display_name", "").lower()
    return (field in _CS_AI_FIELDS or subfield in _CS_AI_SUBFIELDS) and \
           _ai_match(title + " " + abstract)


def _fetch_openalex(base_url: str, params: dict, for_date: date) -> list[dict]:
    per_page  = params.get("per_page", 200)
    max_fetch = params.get("max_fetch", 1000)
    date_str  = for_date.isoformat()
    all_works, page = [], 1

    print(f"[openalex] Fetching works on {date_str} ...")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        while len(all_works) < max_fetch:
            url = base_url + "?" + urlencode({
                "filter": f"from_publication_date:{date_str},to_publication_date:{date_str}",
                "per_page": per_page, "page": page, "sort": "publication_date:desc",
            })
            print(f"[openalex] GET page {page}")
            r = _get(client, url)
            data    = r.json()
            results = data.get("results", [])
            if not results: break
            all_works.extend(results)
            total = data.get("meta", {}).get("count", 0)
            print(f"[openalex] page {page}: {len(results)} works (total: {total})")
            if len(all_works) >= total: break
            page += 1

    filtered = [w for w in all_works if _openalex_relevant(w)]
    print(f"[openalex] {len(filtered)} AI-relevant (from {len(all_works)} total)")

    out = []
    for work in filtered:
        authors      = [a["author"]["display_name"] for a in work.get("authorships", [])
                        if a.get("author", {}).get("display_name")]
        institutions = list({inst["display_name"]
                             for a in work.get("authorships", [])
                             for inst in a.get("institutions", [])
                             if inst.get("display_name")})
        ploc = work.get("primary_location") or {}
        oa   = work.get("best_oa_location") or {}
        src  = ploc.get("source") or {}
        pt   = work.get("primary_topic") or {}
        out.append({
            "id":           work.get("id"),
            "doi":          work.get("doi"),
            "title":        work.get("display_name") or work.get("title"),
            "abstract":     _reconstruct_abstract(work.get("abstract_inverted_index")),
            "authors":      authors,
            "institutions": institutions,
            "published":    work.get("publication_date"),
            "publication_year": work.get("publication_year"),
            "type":         work.get("type"),
            "language":     work.get("language"),
            "abstract_url": ploc.get("landing_page_url") or work.get("doi"),
            "pdf_url":      ploc.get("pdf_url") or oa.get("pdf_url"),
            "oa_url":       work.get("open_access", {}).get("oa_url"),
            "is_open_access": work.get("open_access", {}).get("is_oa"),
            "oa_status":    work.get("open_access", {}).get("oa_status"),
            "primary_topic": {
                "name":     pt.get("display_name"),
                "subfield": (pt.get("subfield") or {}).get("display_name"),
                "field":    (pt.get("field") or {}).get("display_name"),
                "domain":   (pt.get("domain") or {}).get("display_name"),
            } if pt else None,
            "topics":  [{"name": t.get("display_name"),
                         "subfield": (t.get("subfield") or {}).get("display_name"),
                         "field": (t.get("field") or {}).get("display_name")}
                        for t in work.get("topics", [])],
            "keywords":  [k.get("display_name") for k in work.get("keywords", [])],
            "concepts":  [c.get("display_name") for c in work.get("concepts", [])],
            "cited_by_count": work.get("cited_by_count"),
            "referenced_works_count": work.get("referenced_works_count"),
            "venue":      src.get("display_name"),
            "venue_type": src.get("type"),
            "is_retracted": work.get("is_retracted"),
            "biblio":     work.get("biblio"),
            "updated_date": work.get("updated_date"),
            "source":     "openalex",
        })
    return out


# ── 3. Hugging Face Daily Papers ─────────────────────────────────────────────

def _fetch_hf_papers(base_url: str, params: dict, for_date: date) -> list[dict]:
    url = f"{base_url}?date={for_date.isoformat()}"
    print(f"[hf_papers] GET {url}")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = _get(client, url)
    items = r.json()
    print(f"[hf_papers] {len(items)} papers found")

    out = []
    for item in items:
        paper = item.get("paper", {})
        aid   = paper.get("id")
        org   = paper.get("organization") or item.get("organization") or {}
        sub   = item.get("submittedBy") or {}
        out.append({
            "id":            aid,
            "title":         item.get("title") or paper.get("title"),
            "abstract":      item.get("summary") or paper.get("summary"),
            "ai_summary":    paper.get("ai_summary"),
            "ai_keywords":   paper.get("ai_keywords", []),
            "authors":       [a.get("name") for a in paper.get("authors", [])
                              if a.get("name") and not a.get("hidden")],
            "organization":  org.get("fullname") or org.get("name"),
            "published":     paper.get("publishedAt"),
            "submitted_on_daily": paper.get("submittedOnDailyAt"),
            "abstract_url":  f"https://arxiv.org/abs/{aid}" if aid else None,
            "pdf_url":       f"https://arxiv.org/pdf/{aid}" if aid else None,
            "hf_page":       f"https://huggingface.co/papers/{aid}" if aid else None,
            "thumbnail":     item.get("thumbnail"),
            "media_urls":    item.get("mediaUrls", []),
            "upvotes":       paper.get("upvotes"),
            "num_comments":  item.get("numComments"),
            "submitted_by":  sub.get("fullname") or sub.get("name"),
            "source":        "huggingface_papers",
        })
    return out


# ── 4. PubMed ────────────────────────────────────────────────────────────────

def _fetch_pubmed(base_url: str, params: dict, for_date: date) -> list[dict]:
    date_str    = for_date.strftime("%Y/%m/%d")
    query       = params.get("query", "")
    max_results = params.get("max_results", 200)
    search_url  = f"{base_url}/esearch.fcgi"
    fetch_url   = f"{base_url}/efetch.fcgi"

    print(f"[pubmed] Searching on {date_str} ...")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = _get(client, search_url, params={
            "db": "pubmed", "term": query,
            "datetype": "edat", "mindate": date_str, "maxdate": date_str,
            "retmode": "json", "retmax": max_results,
        })
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        print(f"[pubmed] {len(ids)} IDs found")
        if not ids: return []

        all_articles = []
        for i in range(0, len(ids), 20):
            batch = ",".join(ids[i:i+20])
            r = _get(client, fetch_url, params={
                "db": "pubmed", "id": batch,
                "retmode": "xml", "rettype": "abstract",
            })
            all_articles.extend(_parse_pubmed_xml(r.text))
            time.sleep(0.4)

    print(f"[pubmed] {len(all_articles)} AI-relevant articles")
    return all_articles


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    root, articles = ET.fromstring(xml_text), []
    for article in root.findall(".//PubmedArticle"):
        mc  = article.find("MedlineCitation")
        art = mc.find("Article") if mc is not None else None
        if art is None: continue

        pmid  = (mc.findtext("PMID") or "").strip()
        title = (art.findtext("ArticleTitle") or "").strip()

        abstract_parts = [
            (el.get("Label", "") + ": " if el.get("Label") else "") + (el.text or "")
            for el in art.findall(".//AbstractText")
        ]
        abstract = " ".join(abstract_parts).strip() or None

        authors = []
        for author in art.findall(".//Author"):
            name = f"{author.findtext('ForeName') or ''} {author.findtext('LastName') or ''}".strip()
            if name: authors.append(name)

        doi = next((e.text for e in art.findall("ELocationID")
                    if e.get("EIdType") == "doi"), None)

        pub   = art.find(".//Journal/JournalIssue/PubDate")
        published = (f"{pub.findtext('Year') or ''}-{pub.findtext('Month') or ''}"
                     f"-{pub.findtext('Day') or ''}".strip("-") if pub else None)

        affiliations = list({aff.text.strip()
                             for aff in art.findall(".//AffiliationInfo/Affiliation")
                             if aff.text})
        mesh = [m.findtext("DescriptorName") for m in mc.findall(".//MeshHeading")
                if m.findtext("DescriptorName")]

        if not _ai_match((title + " " + (abstract or "")).lower()):
            continue

        articles.append({
            "id":           pmid,
            "title":        title,
            "abstract":     abstract,
            "authors":      authors,
            "affiliations": affiliations,
            "published":    published,
            "journal":      art.findtext(".//Journal/Title"),
            "doi":          doi,
            "abstract_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}" if pmid else None,
            "pdf_url":      f"https://doi.org/{doi}" if doi else None,
            "mesh_terms":   mesh,
            "source":       "pubmed",
        })
    return articles


# ── 6. OpenReview ─────────────────────────────────────────────────────────────

_OR_AI_AREAS = {
    "language", "llm", "multimodal", "agent", "alignment", "evaluation",
    "nlp", "natural language", "vision", "generative", "reinforcement",
    "foundation model", "deep learning", "neural", "transformer",
}


def _or_relevant(note: dict) -> bool:
    c = note.get("content", {})
    text = " ".join([
        (c.get("title", {}).get("value") or ""),
        (c.get("abstract", {}).get("value") or ""),
        (c.get("primary_area", {}).get("value") or ""),
        " ".join(c.get("keywords", {}).get("value") or []),
    ]).lower()
    return _ai_match(text) or any(a in text for a in _OR_AI_AREAS)


def _fetch_openreview(base_url: str, params: dict) -> list[dict]:
    venues        = params.get("venues", [])
    per_page      = params.get("per_page", 200)
    max_per_venue = params.get("max_per_venue", 1000)
    all_papers    = []

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for venue_id in venues:
            offset, venue_notes = 0, []
            print(f"[openreview] Fetching {venue_id} ...")
            while len(venue_notes) < max_per_venue:
                r = _get(client, base_url, params={
                    "content.venueid": venue_id,
                    "limit": per_page, "offset": offset,
                })
                data  = r.json()
                notes = data.get("notes", [])
                if not notes: break
                venue_notes.extend(notes)
                total = data.get("count") or 0
                print(f"[openreview] {venue_id}: {len(venue_notes)}/{total}")
                if len(venue_notes) >= total: break
                offset += per_page
                time.sleep(0.5)

            filtered = [n for n in venue_notes if _or_relevant(n)]
            print(f"[openreview] {venue_id}: {len(filtered)} AI-relevant (from {len(venue_notes)})")

            for note in filtered:
                c       = note.get("content", {})
                pdf_rel = c.get("pdf", {}).get("value") or ""
                all_papers.append({
                    "id":           note.get("id"),
                    "title":        (c.get("title", {}).get("value") or "").strip(),
                    "abstract":     (c.get("abstract", {}).get("value") or "").strip() or None,
                    "tldr":         (c.get("TLDR", {}).get("value") or "").strip() or None,
                    "authors":      c.get("authors", {}).get("value") or [],
                    "keywords":     c.get("keywords", {}).get("value") or [],
                    "primary_area": c.get("primary_area", {}).get("value"),
                    "venue":        c.get("venue", {}).get("value"),
                    "venue_id":     venue_id,
                    "abstract_url": f"https://openreview.net/forum?id={note.get('forum')}",
                    "pdf_url":      (f"https://openreview.net{pdf_rel}"
                                     if pdf_rel.startswith("/") else pdf_rel or None),
                    "submitted_at": (datetime.fromtimestamp(note["cdate"] / 1000, tz=timezone.utc).isoformat()
                                     if note.get("cdate") else None),
                    "source":       "openreview",
                })

    print(f"[openreview] {len(all_papers)} total AI papers across all venues")
    return all_papers


# =============================================================================
# Source dispatcher
# =============================================================================

_FETCHERS = {
    "arxiv":              lambda cfg, d, s, e: _fetch_arxiv(cfg["url"], cfg.get("params", {}), s, e),
    "openalex":           lambda cfg, d, s, e: _fetch_openalex(cfg["url"], cfg.get("params", {}), d),
    "huggingface_papers": lambda cfg, d, s, e: _fetch_hf_papers(cfg["url"], cfg.get("params", {}), d),
    "pubmed":             lambda cfg, d, s, e: _fetch_pubmed(cfg["url"], cfg.get("params", {}), d),
    "openreview":         lambda cfg, d, s, e: _fetch_openreview(cfg["url"], cfg.get("params", {})),
}


# =============================================================================
# Main public function
# =============================================================================

def crawl_research_papers(
    sources: list[dict],
    crawl_date: date | None = None,
    start_date: date | None = None,
    end_date:   date | None = None,
) -> dict:
    """
    Fetch AI/ML research papers from multiple sources and return a unified dict.

    Parameters
    ----------
    sources : list[dict]
        List of source config dicts (from config.py → RESEARCH_PUBLICATION_URLS).
        Each dict must have:
          - "name"   : str  — unique label (e.g. "arxiv")
          - "url"    : str  — base URL for the source API
          - "type"   : str  — one of: arxiv | openalex | huggingface_papers |
                                       semantic_scholar | pubmed | openreview | acl_anthology
          - "params" : dict — source-specific parameters (see config.py for all options)

    crawl_date : date, optional
        The date used for all date-based sources (openalex, huggingface_papers,
        pubmed, acl_anthology). Defaults to today (date.today()).

    start_date : date, optional
        Start of the ArXiv and Semantic Scholar date range.
        Defaults to crawl_date.

    end_date : date, optional
        End of the ArXiv and Semantic Scholar date range.
        Defaults to crawl_date.

    Returns
    -------
    dict with keys:
        "crawl_date"       : str   — ISO date used for daily sources
        "start_date"       : str   — ISO start date used for range sources
        "end_date"         : str   — ISO end date used for range sources
        "generated_at"     : str   — UTC ISO timestamp of when the crawl ran
        "total"            : int   — total paper count across all sources
        "sources"          : dict  — per-source results, keyed by source name:
            {
              "count"  : int        — number of papers returned
              "papers" : list[dict] — list of paper objects (schema below)
            }
            On error:
            {
              "count"  : 0
              "error"  : str        — error message
            }

    Paper object keys (varies slightly by source):
        id, title, abstract, authors, published, abstract_url, pdf_url, source
        + source-specific extras (see README.md for full schema per source)

    Examples
    --------
    # Fetch everything with today's date:
    from crawler import crawl_research_papers
    from config import RESEARCH_PUBLICATION_URLS

    result = crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)

    # Fetch only arxiv and huggingface for a specific date:
    from datetime import date
    result = crawl_research_papers(
        sources=[s for s in RESEARCH_PUBLICATION_URLS if s["name"] in ("arxiv", "huggingface_papers")],
        crawl_date=date(2026, 3, 4),
    )

    # Convert to JSON string:
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
    """
    today = date.today()
    crawl_date = crawl_date or today
    start_date = start_date or crawl_date
    end_date   = end_date   or crawl_date

    result: dict = {
        "crawl_date":   crawl_date.isoformat(),
        "start_date":   start_date.isoformat(),
        "end_date":     end_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources":      {},
    }

    for cfg in sources:
        name    = cfg.get("name", "unknown")
        src_type = cfg.get("type", "")
        fetcher  = _FETCHERS.get(src_type)

        if not fetcher:
            result["sources"][name] = {
                "count": 0,
                "error": f"Unknown source type '{src_type}'",
            }
            continue

        try:
            papers = fetcher(cfg, crawl_date, start_date, end_date)
            result["sources"][name] = {"count": len(papers), "papers": papers}
        except Exception as exc:
            print(f"[{name}] ERROR: {exc}")
            result["sources"][name] = {"count": 0, "error": str(exc)}

    result["total"] = sum(v.get("count", 0) for v in result["sources"].values())
    print(result)
    return result


# =============================================================================
# CLI entry point  (python crawler.py)
# =============================================================================

if __name__ == "__main__":
    from config import RESEARCH_PUBLICATION_URLS

    data        = crawl_research_papers(sources=RESEARCH_PUBLICATION_URLS)
    output_file = f"papers_{data['start_date']}_{data['end_date']}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"Date        : {data['crawl_date']}")
    print(f"Generated   : {data['generated_at']}")
    for src, v in data["sources"].items():
        status = f"{v['count']} papers" if not v.get("error") else f"ERROR: {v['error'][:60]}"
        print(f"  {src:25s}: {status}")
    print(f"  {'-'*40}")
    print(f"  {'TOTAL':25s}: {data['total']}")
    print(f"\nSaved -> {output_file}")
