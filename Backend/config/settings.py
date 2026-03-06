"""Configuration management using Pydantic Settings."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import yaml
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from .env and YAML configs."""

    # Google Gemini
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", env="GEMINI_MODEL")

    # OpenRouter (Claude via OpenRouter — preferred for speed)
    openrouter_api_key: Optional[str] = Field(default=None, env="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="anthropic/claude-3.5-sonnet",
        env="OPENROUTER_MODEL",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        env="OPENROUTER_BASE_URL",
    )
    # LLM backend: "openrouter" or "gemini"
    llm_backend: str = Field(default="openrouter", env="LLM_BACKEND")

    # LangSmith
    langchain_tracing_v2: bool = Field(default=False, env="LANGCHAIN_TRACING_V2")
    langchain_api_key: Optional[str] = Field(default=None, env="LANGCHAIN_API_KEY")
    langchain_project: str = Field(default="frontier-ai-radar", env="LANGCHAIN_PROJECT")

    # Web Search
    tavily_api_key: Optional[str] = Field(default=None, env="TAVILY_API_KEY")

    # HuggingFace
    hf_api_token: Optional[str] = Field(default=None, env="HF_API_TOKEN")

    # Semantic Scholar
    semantic_scholar_api_key: Optional[str] = Field(default=None, env="SEMANTIC_SCHOLAR_API_KEY")

    # MCP Email (legacy config — kept for backward compatibility)
    mcp_server: str = Field(default="gmail", env="MCP_SERVER")
    mcp_email_server_url: Optional[str] = Field(default=None, env="MCP_EMAIL_SERVER_URL")
    mcp_email_api_key: Optional[str] = Field(default=None, env="MCP_EMAIL_API_KEY")

    # SMTP (email delivery — local dev fallback)
    smtp_host: str = Field(default="smtp.gmail.com", env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, env="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, env="SMTP_PASSWORD")

    # Brevo (primary email provider — 300 free emails/day, any recipient)
    brevo_api_key: Optional[str] = Field(default=None, env="BREVO_API_KEY")

    # Email
    email_from: str = Field(..., env="EMAIL_FROM")
    email_recipients: str = Field(..., env="EMAIL_RECIPIENTS")  # comma-separated

    # Database (SQLite – local file, no external server needed)
    database_url: str = Field(
        default="sqlite:///db/frontier_ai_radar.db", env="DATABASE_URL"
    )

    # Memory/Storage
    long_term_memory_path: Path = Field(default=Path("data/long_term"), env="LONG_TERM_MEMORY_PATH")
    entity_store_path: Path = Field(default=Path("data/entity_store"), env="ENTITY_STORE_PATH")
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL"
    )

    # PDF/Reports
    reports_output_path: Path = Field(default=Path("data/reports"), env="REPORTS_OUTPUT_PATH")
    pdf_brand_name: str = Field(default="Frontier AI Radar", env="PDF_BRAND_NAME")
    pdf_brand_color: str = Field(default="#2563eb", env="PDF_BRAND_COLOR")

    # Arxiv
    arxiv_rate_limit_seconds: int = Field(default=3, env="ARXIV_RATE_LIMIT_SECONDS")

    # Playwright
    playwright_browser: str = Field(default="chromium", env="PLAYWRIGHT_BROWSER")

    # Docling
    enable_pdf_globally: bool = Field(default=False, env="ENABLE_PDF_GLOBALLY")
    docling_table_extraction: bool = Field(default=True, env="DOCLING_TABLE_EXTRACTION")

    # Scheduler
    daily_run_time: str = Field(default="17:00", env="DAILY_RUN_TIME")
    timezone: str = Field(default="Asia/Kolkata", env="TIMEZONE")

    # FastAPI
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    api_secret_key: str = Field(..., env="API_SECRET_KEY")



    # Streamlit
    streamlit_port: int = Field(default=8501, env="STREAMLIT_PORT")

    # Rate Limiting
    max_pages_per_domain: int = Field(default=10, env="MAX_PAGES_PER_DOMAIN")
    default_crawl_rate_seconds: int = Field(default=2, env="DEFAULT_CRAWL_RATE_SECONDS")
    max_concurrent_agents: int = Field(default=4, env="MAX_CONCURRENT_AGENTS")

    # Agent Iteration Caps
    max_iterations_competitor: int = Field(default=6, env="MAX_ITERATIONS_COMPETITOR")
    max_iterations_research: int = Field(default=6, env="MAX_ITERATIONS_RESEARCH")
    max_iterations_model: int = Field(default=7, env="MAX_ITERATIONS_MODEL")
    max_iterations_benchmark: int = Field(default=6, env="MAX_ITERATIONS_BENCHMARK")
    min_content_length_chars: int = Field(default=300, env="MIN_CONTENT_LENGTH_CHARS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def load_sources_config() -> dict:
    """Load sources.yaml configuration."""
    config_path = Path(__file__).parent / "sources.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_scoring_config() -> dict:
    """Load scoring.yaml configuration."""
    config_path = Path(__file__).parent / "scoring.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Global settings instance
settings = Settings()
