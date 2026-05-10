"""
Pinecone client manager — factory for PineconeVectorStore instances.

Uses langchain_pinecone for all vector operations (upsert, search, delete),
backed by the Pinecone v3+ SDK for index management.

Usage:
    from rag.pinecone_client import PineconeClientManager

    manager = PineconeClientManager()
    store   = manager.get_vector_store(
        index_name="booky-rag",
        embedder=embedder,
        namespace="42",
    )

    store.add_documents(chunks, ids=["123_0", "123_1", ...])
    results = store.similarity_search("query", k=5, filter={...})
"""

import os
import logging
from typing import Any

from pinecone import Pinecone
from langchain_core.embeddings import Embeddings
from langchain_pinecone import PineconeVectorStore

logger = logging.getLogger(__name__)


from core.config import settings

class PineconeClientManager:
    """
    Manages the Pinecone client lifecycle and provides convenience
    methods for creating LangChain PineconeVectorStore instances
    and performing targeted vector deletion.
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Initialize the Pinecone client.

        Args:
            api_key: Pinecone API key. If not provided, reads from
                     settings.PINECONE_API_KEY.

        Raises:
            ValueError: If no API key is available.
        """
        resolved_key = api_key or settings.PINECONE_API_KEY
        if not resolved_key:
            raise ValueError(
                "Pinecone API key not found. Set PINECONE_API_KEY in your "
                ".env file or pass it explicitly."
            )

        self._client = Pinecone(api_key=resolved_key)
        logger.info("Pinecone client initialized.")

    def get_index(self, index_name: str) -> Any:
        """
        Return a raw Pinecone Index handle.

        Args:
            index_name: Name of the Pinecone index (must already exist).

        Returns:
            Pinecone Index instance.
        """
        return self._client.Index(index_name)

    def get_vector_store(
        self,
        index_name: str,
        embedder: Embeddings,
        namespace: str,
    ) -> PineconeVectorStore:
        """
        Create a LangChain PineconeVectorStore bound to a specific
        index, embedding model, and namespace.

        Args:
            index_name: Name of the Pinecone index.
            embedder:   LangChain Embeddings instance.
            namespace:  Pinecone namespace (business_id as string).

        Returns:
            PineconeVectorStore ready for add_documents / similarity_search.
        """
        index = self.get_index(index_name)
        store = PineconeVectorStore(
            embedding=embedder,
            index=index,
            namespace=namespace,
        )
        logger.debug(
            "PineconeVectorStore created: index=%s, namespace=%s",
            index_name, namespace,
        )
        return store

    def delete_vectors(
        self,
        index_name: str,
        namespace: str,
        document_id: int,
    ) -> None:
        """
        Delete all vectors belonging to a specific document.

        Uses metadata filter to target only vectors with the matching
        document_id, leaving other documents in the namespace untouched.

        Args:
            index_name:  Name of the Pinecone index.
            namespace:   Pinecone namespace (business_id as string).
            document_id: ID of the KnowledgeDocument whose vectors to delete.
        """
        index = self.get_index(index_name)
        index.delete(
            namespace=namespace,
            filter={"document_id": {"$eq": int(document_id)}},
        )
        logger.info(
            "Deleted vectors for document_id=%d from namespace '%s'",
            document_id, namespace,
        )
