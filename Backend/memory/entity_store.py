"""Entity memory operations (ChromaDB vector store)."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.config import Settings as ChromaSettings
from config.settings import settings
from memory.schemas import EntityProfile


class EntityStore:
    """ChromaDB vector store for entity embeddings."""

    def __init__(self):
        """Initialize ChromaDB client and embedding model."""
        self.client = chromadb.PersistentClient(
            path=str(settings.entity_store_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="entities", metadata={"hnsw:space": "cosine"}
        )
        # Lazy load embedding model (stub for now - team will provide real implementation)
        self._embedding_model = None

    @property
    def embedding_model(self):
        """Lazy load embedding model via core.embedder."""
        if self._embedding_model is None:
            from core.embedder import get_embedding_model
            self._embedding_model = get_embedding_model()
        return self._embedding_model

    def _embed(self, text: str) -> List[float]:
        """Generate embedding for text using real SentenceTransformer."""
        from core.embedder import embed_text
        return embed_text(text, model=self.embedding_model)

    def add_entity(self, entity: EntityProfile) -> None:
        """Add or update an entity in the vector store."""
        # Create embedding from entity description
        embedding = self._embed(f"{entity['name']} {entity['description']}")

        # Check if entity exists
        existing = self.collection.get(ids=[entity["id"]])
        if existing["ids"]:
            # Update
            self.collection.update(
                ids=[entity["id"]],
                embeddings=[embedding],
                documents=[entity["description"]],
                metadatas=[entity],
            )
        else:
            # Add new
            self.collection.add(
                ids=[entity["id"]],
                embeddings=[embedding],
                documents=[entity["description"]],
                metadatas=[entity],
            )

    def search_entities(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for entities by semantic similarity."""
        query_embedding = self._embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["metadatas", "documents", "distances"],
        )

        entities = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i, entity_id in enumerate(results["ids"][0]):
                entities.append(
                    {
                        "id": entity_id,
                        "metadata": results["metadatas"][0][i],
                        "document": results["documents"][0][i],
                        "distance": results["distances"][0][i],
                    }
                )
        return entities

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific entity by ID."""
        results = self.collection.get(ids=[entity_id], include=["metadatas", "documents"])
        if results["ids"]:
            return {
                "id": results["ids"][0],
                "metadata": results["metadatas"][0],
                "document": results["documents"][0],
            }
        return None


# Global instance
_entity_store: Optional[EntityStore] = None


def get_entity_store() -> EntityStore:
    """Get or create global entity store instance."""
    global _entity_store
    if _entity_store is None:
        _entity_store = EntityStore()
    return _entity_store
