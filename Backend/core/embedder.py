"""Embedding utilities for entity memory — real SentenceTransformer implementation."""

from typing import List, Optional
import structlog

logger = structlog.get_logger()

# ── Lazy singleton cache ────────────────────────────────────────────────────
_model_cache: dict = {}  # {model_name: SentenceTransformer} — lazy import avoids torch at startup


def get_embedding_model(model_name: str = "all-MiniLM-L6-v2"):
    """Get or load embedding model (lazy singleton — loads once, reused forever)."""
    from sentence_transformers import SentenceTransformer  # lazy import to avoid loading torch at startup

    if model_name not in _model_cache:
        logger.info("Loading embedding model", model=model_name)
        _model_cache[model_name] = SentenceTransformer(model_name)
        logger.info("Embedding model loaded", model=model_name)
    return _model_cache[model_name]


def embed_text(text: str, model=None) -> List[float]:
    """Generate embedding for text using SentenceTransformer.

    Args:
        text: The text to embed.
        model: Optional pre-loaded model. If None, uses default all-MiniLM-L6-v2.

    Returns:
        List of floats (384-dim for all-MiniLM-L6-v2).
    """
    if model is None:
        model = get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()
