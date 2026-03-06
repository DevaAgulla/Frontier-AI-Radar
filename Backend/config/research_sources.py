"""
Research publication source configurations.
Pass RESEARCH_PUBLICATION_URLS (or a subset) into crawl_research_papers().
Each entry defines one source: its base URL, type, and source-specific params.

Phase 1 (fast subset): arxiv + huggingface_papers only.
Uncomment other sources to enable them — no code changes needed.
"""

RESEARCH_PUBLICATION_URLS = [
    {
        "name": "arxiv",
        "url": "http://export.arxiv.org/api/query",
        "type": "arxiv",
        "params": {
            # Topics and categories used in the ArXiv search query
            "search_topics": (
                "(all:llm OR all:multimodal OR all:agent "
                "OR all:alignment OR all:evaluation)"
            ),
            "categories": "(cat:cs.CL OR cat:cs.LG OR cat:cs.AI)",
            "max_results": 100,
        },
    },
    {
        "name": "huggingface_papers",
        "url": "https://huggingface.co/api/daily_papers",
        "type": "huggingface_papers",
        "params": {},
    },
    # ── Uncomment to enable additional sources ──────────────────────
    # {
    #     "name": "openalex",
    #     "url": "https://api.openalex.org/works",
    #     "type": "openalex",
    #     "params": {
    #         "per_page": 200,
    #         "max_fetch": 1000,
    #     },
    # },
    # {
    #     "name": "pubmed",
    #     "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    #     "type": "pubmed",
    #     "params": {
    #         "query": (
    #             "(large language model[tiab] OR LLM[tiab] OR multimodal[tiab] "
    #             "OR neural network[tiab] OR deep learning[tiab] "
    #             "OR transformer[tiab] OR AI agent[tiab] "
    #             "OR alignment[tiab] OR foundation model[tiab])"
    #         ),
    #         "max_results": 200,
    #     },
    # },
    # {
    #     "name": "openreview",
    #     "url": "https://api2.openreview.net/notes",
    #     "type": "openreview",
    #     "params": {
    #         "venues": [
    #             "ICLR.cc/2025/Conference",
    #             "NeurIPS.cc/2025/Conference",
    #         ],
    #         "per_page": 200,
    #         "max_per_venue": 1000,
    #     },
    # },
]
