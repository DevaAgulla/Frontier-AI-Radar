"""
Research publication source configurations.
Pass RESEARCH_PUBLICATION_URLS (or a subset) into crawl_research_papers().
Each entry defines one source: its base URL, type, and source-specific params.
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
        "name": "openalex",
        "url": "https://api.openalex.org/works",
        "type": "openalex",
        "params": {
            "per_page": 200,
            # Maximum total works to fetch before AI-relevance filtering
            "max_fetch": 1000,
        },
    },
    {
        "name": "huggingface_papers",
        "url": "https://huggingface.co/api/daily_papers",
        "type": "huggingface_papers",
        "params": {},
    },
    {
        "name": "pubmed",
        "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        "type": "pubmed",
        "params": {
            "query": (
                "(large language model[tiab] OR LLM[tiab] OR multimodal[tiab] "
                "OR neural network[tiab] OR deep learning[tiab] "
                "OR transformer[tiab] OR AI agent[tiab] "
                "OR alignment[tiab] OR foundation model[tiab])"
            ),
            "max_results": 200,
        },
    },
    {
        "name": "openreview",
        "url": "https://api2.openreview.net/notes",
        "type": "openreview",
        "params": {
            # Most recent available conferences — update as new ones appear
            "venues": [
                "ICLR.cc/2025/Conference",
                "NeurIPS.cc/2025/Conference",
            ],
            "per_page": 200,
            # Max papers to fetch per venue before AI-relevance filtering
            "max_per_venue": 1000,
        },
    },
]
