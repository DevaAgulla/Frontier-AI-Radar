"""Entity memory operations (PostgreSQL entities table in ai_radar schema).

Replaces ChromaDB. Uses ILIKE text search now; pgvector semantic search
will be activated once the Azure admin enables the vector extension.

Table: ai_radar.entities
  id, name, entity_type, description, metadata, source, embedding, updated_at

The EntityStore class interface is identical to the old ChromaDB version.
"""

import json
from typing import List, Dict, Any, Optional

from memory.schemas import EntityProfile


class EntityStore:
    """PostgreSQL-backed entity store with ILIKE text search fallback."""

    def add_entity(self, entity: EntityProfile) -> None:
        """Add or update an entity in the entities table (UPSERT)."""
        from db.connection import get_engine
        from sqlalchemy import text

        core_keys = {"id", "name", "entity_type", "description", "source"}
        meta = {k: v for k, v in entity.items() if k not in core_keys}

        try:
            with get_engine().begin() as conn:
                conn.execute(text("""
                    INSERT INTO entities
                        (id, name, entity_type, description, metadata, source, updated_at)
                    VALUES
                        (:id, :name, :entity_type, :description,
                         CAST(:metadata AS jsonb), :source, NOW())
                    ON CONFLICT (id) DO UPDATE
                        SET name        = EXCLUDED.name,
                            description = EXCLUDED.description,
                            metadata    = EXCLUDED.metadata,
                            updated_at  = NOW()
                """), {
                    "id":          entity.get("id", ""),
                    "name":        entity.get("name", ""),
                    "entity_type": entity.get("entity_type", "unknown"),
                    "description": entity.get("description", ""),
                    "metadata":    json.dumps(meta),
                    "source":      entity.get("source", "agent"),
                })
        except Exception:
            pass  # non-critical — never crash the pipeline

    def search_entities(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search entities by text similarity (ILIKE).
        When pgvector is enabled this can be upgraded to cosine-similarity
        without changing callers.
        """
        from db.connection import get_engine
        from sqlalchemy import text

        if not query or not query.strip():
            return []

        try:
            with get_engine().connect() as conn:
                result = conn.execute(text("""
                    SELECT id, name, entity_type, description, metadata
                    FROM entities
                    WHERE name ILIKE :q OR description ILIKE :q
                    ORDER BY updated_at DESC
                    LIMIT :top_k
                """), {"q": f"%{query}%", "top_k": top_k})
                return [
                    {
                        "id":       row[0],
                        "metadata": row[4] or {},
                        "document": row[3] or "",
                        "distance": 0.0,
                    }
                    for row in result.fetchall()
                ]
        except Exception:
            return []

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific entity by ID."""
        from db.connection import get_engine
        from sqlalchemy import text

        try:
            with get_engine().connect() as conn:
                result = conn.execute(text(
                    "SELECT id, name, entity_type, description, metadata FROM entities WHERE id = :id"
                ), {"id": entity_id})
                row = result.fetchone()
                if row:
                    return {"id": row[0], "metadata": row[4] or {}, "document": row[3] or ""}
                return None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_entity_store: Optional[EntityStore] = None


def get_entity_store() -> EntityStore:
    """Get or create the global entity store instance."""
    global _entity_store
    if _entity_store is None:
        _entity_store = EntityStore()
    return _entity_store
