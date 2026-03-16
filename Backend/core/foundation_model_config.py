"""
foundation_model_config.py

Central configuration for the foundation model release tracker.
Edit this file to add/remove sources or tweak runtime settings.

Copied from TeammatesTools/foundational_models/config.py and integrated
into the core/ package for use by the Model Intelligence Agent.
"""

# ---------------------------------------------------------------------------
# HTTP settings
# ---------------------------------------------------------------------------

# Seconds before a request is abandoned
REQUEST_TIMEOUT: int = 30

# User-Agent sent with every request
USER_AGENT: str = (
    "Mozilla/5.0 (compatible; FoundationModelTracker/1.0; "
    "+https://github.com/your-org/foundation-model-tracker)"
)

# ---------------------------------------------------------------------------
# Pagination defaults
# ---------------------------------------------------------------------------

# Maximum pages to walk for paginated JSON APIs (HuggingFace, GitHub)
MAX_PAGES: int = 10

# Items per page requested from paginated APIs
PER_PAGE: int = 100

# ---------------------------------------------------------------------------
# Source URLs
# ---------------------------------------------------------------------------

SOURCE_URLS: list[str] = [
    # HuggingFace — one URL per trusted org using sort=lastModified so recently
    # active repos appear first AND both createdAt + lastModified are populated
    # in the response (sort=createdAt leaves lastModified=null).
    # Pages are 0-indexed (&p=0 is most recent).
    "https://huggingface.co/api/models?author=meta-llama&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=mistralai&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=Qwen&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=google&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=microsoft&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=openai&sort=lastModified&limit=100",
    "https://huggingface.co/api/models?author=anthropic&sort=lastModified&limit=100",

    # OpenAI blog RSS (redirects from /blog to /news automatically)
    "https://openai.com/blog/rss.xml",

    # Anthropic: no public RSS feed; use sitemap.xml which carries <lastmod> dates
    "https://www.anthropic.com/sitemap.xml",

    # Google DeepMind blog RSS
    "https://deepmind.google/blog/rss.xml",

    # NVIDIA developer blog RSS — covers NIM / foundation model announcements
    "https://developer.nvidia.com/blog/feed/",

    # GitHub model announcements: openai-cookbook (model-level notes, not SDK bumps)
    "https://api.github.com/repos/openai/openai-cookbook/releases?per_page=100",

    # NOTE — the following providers do not expose a reliable public RSS feed
    # or date-queryable API as of 2026-03:
    #   Meta AI   : https://ai.meta.com/blog/rss/   -> 404
    #   Mistral AI: https://mistral.ai/news/rss.xml  -> 404, sitemap has no <lastmod>
    #   Cohere    : https://cohere.com/blog/rss.xml  -> redirects to HTML
    #   AI21      : https://www.ai21.com/blog/rss    -> unreliable
]

# ---------------------------------------------------------------------------
# Provider mapping
# Map hostname fragment -> human-readable provider label
# ---------------------------------------------------------------------------

PROVIDER_MAP: dict[str, str] = {
    "openai.com":         "OpenAI",
    "anthropic.com":      "Anthropic",
    "deepmind.google":    "Google DeepMind",
    "ai.meta.com":        "Meta AI",
    "mistral.ai":         "Mistral AI",
    "cohere.com":         "Cohere",
    "huggingface.co":     "HuggingFace",
    "developer.nvidia":   "NVIDIA",
    "api.github.com":     "GitHub",
    "github.com":         "GitHub",
}

# ---------------------------------------------------------------------------
# Source label mapping
# Map hostname fragment -> short stable identifier used in the "source" field
# ---------------------------------------------------------------------------

SOURCE_LABELS: dict[str, str] = {
    "openai.com":         "openai_rss",
    "anthropic.com":      "anthropic_sitemap",
    "deepmind.google":    "deepmind_rss",
    "ai.meta.com":        "meta_rss",
    "mistral.ai":         "mistral_rss",
    "cohere.com":         "cohere_rss",
    "huggingface.co":     "huggingface_api",
    "developer.nvidia":   "nvidia_rss",
    "api.github.com":     "github_api",
    "github.com":         "github_api",
}

# ---------------------------------------------------------------------------
# HuggingFace trusted provider allowlist
# Only models whose org/user matches one of these (case-insensitive) are kept.
# Add or remove entries here to control which orgs are tracked.
# ---------------------------------------------------------------------------

HUGGINGFACE_ALLOWED_ORGS: set[str] = {
    "meta-llama",
    "mistralai",
    "qwen",
    "google",
    "deepseek-ai",
    "microsoft",
    "openai",
    "anthropic",
}

# ---------------------------------------------------------------------------
# Well-known GitHub owner -> provider label
# Used when parsing GitHub releases to resolve owner names to provider labels
# ---------------------------------------------------------------------------

GITHUB_OWNER_MAP: dict[str, str] = {
    "openai":      "OpenAI",
    "anthropics":  "Anthropic",
    "mistralai":   "Mistral AI",
    "google":      "Google",
    "meta-llama":  "Meta AI",
    "cohere-ai":   "Cohere",
}

# ---------------------------------------------------------------------------
# Output schema defaults
# Every release record is initialised from this template
# ---------------------------------------------------------------------------

RELEASE_SCHEMA: dict = {
    "model_name":        None,
    "provider":          None,
    "release_date":      None,
    "model_details":     None,
    "modalities":        [],
    "context_length":    None,
    "benchmarks":        {},
    "pricing":           None,
    "api_link":          None,
    "model_page":        None,
    "github_repo":       None,
    "extra_information": None,
    "source":            None,
}
