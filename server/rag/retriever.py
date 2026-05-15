"""
Knowledge Retriever — fetches relevant context from Pinecone at agent runtime.

Queries the vector store using the user's message, returns formatted
context chunks for injection into the agent's prompt. Retrieval failures
are always silent — the agent continues without RAG context.

Usage:
    from rag.retriever import KnowledgeRetriever

    context = await KnowledgeRetriever.retrieve_with_scores(
        query="What is your cancellation policy?",
        business_id="42",
        db=db_session,
    )
    # context is a formatted string or "" if nothing relevant found
"""

import os
import logging
from typing import List, Tuple

from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession

from rag.embeddings import EmbeddingProvider
from rag.pinecone_client import PineconeClientManager

from core.config import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_INDEX_NAME = settings.PINECONE_INDEX_NAME
DEFAULT_TOP_K = 5
DEFAULT_SCORE_THRESHOLD = 0.3

CONTEXT_SEPARATOR = "\n\n---\n\n"


class KnowledgeRetriever:
    """
    Retrieves relevant knowledge base chunks from Pinecone at agent runtime.

    Both methods return a formatted string (or empty string on failure).
    Errors are logged but never raised — retrieval is best-effort.
    """

    @classmethod
    async def retrieve(
        cls,
        query: str,
        business_id: str,
        db: AsyncSession,
        top_k: int = DEFAULT_TOP_K,
        index_name: str = DEFAULT_INDEX_NAME,
    ) -> str:
        """
        Retrieve top-k relevant chunks without score filtering.

        Args:
            query:      The user's message to search against.
            business_id: Business ID string — used as Pinecone namespace.
            db:         Active async database session (for EmbeddingProvider).
            top_k:      Number of results to return.
            index_name: Pinecone index name.

        Returns:
            Formatted context string, or "" if no results or on error.
        """
        try:
            namespace = str(business_id)
            # Pinecone metadata stores business_id as integer
            pinecone_filter = {"business_id": {"$eq": int(business_id)}}

            logger.info(
                "[RETRIEVER] retrieve() called — "
                "business_id=%s, namespace='%s', filter=%s, "
                "top_k=%d, index='%s', query='%s'",
                business_id, namespace, pinecone_filter,
                top_k, index_name, query[:80],
            )

            vector_store = await cls._get_vector_store(db, business_id, index_name)

            results: List[Document] = await vector_store.asimilarity_search(
                query=query,
                k=top_k,
                filter=pinecone_filter,
            )

            logger.info(
                "[RETRIEVER] retrieve() returned %d results for business_id=%s",
                len(results), business_id,
            )

            if not results:
                logger.warning(
                    "[RETRIEVER] No results for business_id=%s query='%s'",
                    business_id, query[:80],
                )
                return ""

            return cls._format_context(results)

        except Exception as e:
            logger.error(
                "[RETRIEVER] Retrieval failed (business_id=%s): %s",
                business_id, e, exc_info=True,
            )
            return ""

    @classmethod
    async def retrieve_with_scores(
        cls,
        query: str,
        business_id: str,
        db: AsyncSession,
        top_k: int = DEFAULT_TOP_K,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        index_name: str = DEFAULT_INDEX_NAME,
    ) -> str:
        """
        Retrieve top-k chunks, filtering out anything below score_threshold.

        This is the recommended method for agent integration — it avoids
        injecting irrelevant low-confidence context into the prompt.

        Args:
            query:           The user's message to search against.
            business_id:     Business ID string — used as Pinecone namespace.
            db:              Active async database session.
            top_k:           Number of candidate results to fetch.
            score_threshold: Minimum similarity score (0.0–1.0) to include.
            index_name:      Pinecone index name.

        Returns:
            Formatted context string, or "" if no results pass the threshold.
        """
        try:
            namespace = str(business_id)
            # Pinecone metadata stores business_id as integer
            pinecone_filter = {"business_id": {"$eq": int(business_id)}}

            logger.info(
                "[RETRIEVER] retrieve_with_scores() called — "
                "business_id=%s, namespace='%s', filter=%s, "
                "top_k=%d, threshold=%.2f, index='%s', query='%s'",
                business_id, namespace, pinecone_filter,
                top_k, score_threshold, index_name, query[:80],
            )

            vector_store = await cls._get_vector_store(db, business_id, index_name)

            scored_results: List[Tuple[Document, float]] = (
                await vector_store.asimilarity_search_with_score(
                    query=query,
                    k=top_k,
                    filter=pinecone_filter,
                )
            )

            logger.info(
                "[RETRIEVER] Pinecone returned %d raw results for business_id=%s",
                len(scored_results), business_id,
            )

            if not scored_results:
                logger.warning(
                    "[RETRIEVER] No results for business_id=%s query='%s'",
                    business_id, query[:80],
                )
                return ""

            # Log all scores for debugging
            for i, (doc, score) in enumerate(scored_results):
                logger.info(
                    "[RETRIEVER]   Result #%d: score=%.4f, source='%s', "
                    "content_preview='%s'",
                    i + 1, score,
                    doc.metadata.get("source", "unknown"),
                    doc.page_content[:100],
                )

            # Filter by score threshold
            passing = [
                (doc, score) for doc, score in scored_results
                if score >= score_threshold
            ]

            if not passing:
                best_score = max(s for _, s in scored_results)
                logger.warning(
                    "[RETRIEVER] %d results found but NONE above threshold %.2f "
                    "(best=%.4f, business_id=%s). Consider lowering threshold.",
                    len(scored_results), score_threshold,
                    best_score, business_id,
                )
                return ""

            documents = [doc for doc, _ in passing]
            best_score = max(s for _, s in passing)
            logger.info(
                "[RETRIEVER] ✅ Returning %d/%d chunks above threshold %.2f "
                "(best=%.4f, business_id=%s)",
                len(passing), len(scored_results),
                score_threshold, best_score, business_id,
            )
            return cls._format_context(documents)

        except Exception as e:
            logger.error(
                "[RETRIEVER] Retrieval failed (business_id=%s): %s",
                business_id, e, exc_info=True,
            )
            return ""

    # ── Private helpers ───────────────────────────────────────────────────────

    @classmethod
    async def _get_vector_store(
        cls,
        db: AsyncSession,
        business_id: str,
        index_name: str,
    ):
        """Create a PineconeVectorStore for the given business namespace."""
        namespace = str(business_id)
        logger.info(
            "[RETRIEVER] Creating vector store — index='%s', namespace='%s'",
            index_name, namespace,
        )
        embedder = await EmbeddingProvider.get_embedder(db)
        pinecone_mgr = PineconeClientManager()
        return pinecone_mgr.get_vector_store(
            index_name=index_name,
            embedder=embedder,
            namespace=namespace,
        )

    @staticmethod
    def _format_context(documents: List[Document]) -> str:
        """
        Format retrieved chunks into a single context string for prompt injection.

        Each chunk is prefixed with its source metadata for transparency.
        """
        blocks: List[str] = []
        for doc in documents:
            source = doc.metadata.get("source", "unknown")
            source_type = doc.metadata.get("source_type", "")
            label = f"[Source: {source}"
            if source_type:
                label += f" ({source_type})"
            label += "]"

            blocks.append(f"{label}\n{doc.page_content}")

        return CONTEXT_SEPARATOR.join(blocks)
