"""
Dynamic Embedding Provider — reads config from SystemSetting at runtime.

Every RAG operation (ingestion and retrieval) goes through this module to
obtain the correct LangChain Embeddings instance. The provider and model
are configurable from the database without restarts.

Both providers are normalized to a UNIFIED dimension (768) so that a
single Pinecone index works regardless of which provider is active.

    openai  → text-embedding-3-large  (native 3072 → truncated to 768)
    gemini  → models/gemini-embedding-2  (native 768)

OpenAI's text-embedding-3-* models support Matryoshka Representation
Learning, meaning truncated embeddings retain high quality.

Usage:
    from rag.embeddings import EmbeddingProvider

    embedder = await EmbeddingProvider.get_embedder(db)
    vectors  = await embedder.aembed_documents(["Hello world"])
"""

import logging
from typing import Dict, Tuple

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.system import SystemSetting

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_PROVIDERS = ("openai", "gemini")

DEFAULT_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "text-embedding-3-large"
DEFAULT_GEMINI_MODEL = "models/gemini-embedding-2"

# Unified dimension: both providers output this size so a single
# Pinecone index (dimension=768) works for either provider.
# OpenAI achieves this via the `dimensions` parameter (Matryoshka truncation).
# Gemini embedding-2 outputs 768 natively.
UNIFIED_EMBEDDING_DIMENSION = 768


# ── Public API ────────────────────────────────────────────────────────────────

def get_embedding_dimension() -> int:
    """
    Return the unified vector dimension used across all providers.

    This is the value you should use when creating the Pinecone index.
    Both OpenAI and Gemini output vectors of this size.

    Returns:
        768 — the unified embedding dimension.
    """
    return UNIFIED_EMBEDDING_DIMENSION


class EmbeddingProvider:
    """
    Runtime embedding factory that reads config from SystemSetting.

    All providers are normalized to UNIFIED_EMBEDDING_DIMENSION (768)
    so that switching providers does NOT require re-creating the
    Pinecone index or re-ingesting existing documents.

    Caches embedder instances per (provider, model) pair so repeated
    calls within the same process do not re-instantiate the client.
    """

    # Class-level cache:  (provider, model_name) → Embeddings instance
    _cache: Dict[Tuple[str, str], Embeddings] = {}

    @classmethod
    async def get_embedder(cls, db: AsyncSession) -> Embeddings:
        """
        Read the embedding provider and model name from SystemSetting,
        then return the matching LangChain Embeddings instance.

        Args:
            db: Active async database session.

        Returns:
            A LangChain Embeddings instance ready for embed_documents / embed_query.

        Raises:
            ValueError: If the configured provider is not supported.
        """
        # 1. Read SystemSetting (singleton row)
        result = await db.execute(select(SystemSetting).limit(1))
        sys_settings = result.scalar_one_or_none()

        # 2. Resolve provider, model, and API key with safe defaults.
        #    Uses getattr so this works both before and after the
        #    embedding_provider / embedding_model columns are added.
        provider = (
            getattr(sys_settings, "embedding_provider", None) or DEFAULT_PROVIDER
        ).lower()
        model_name = getattr(sys_settings, "embedding_model", None)

        if provider == "openai":
            model_name = model_name or DEFAULT_OPENAI_MODEL
            api_key = getattr(sys_settings, "openai_api_key", None) if sys_settings else None
        elif provider == "gemini":
            model_name = model_name or DEFAULT_GEMINI_MODEL
            api_key = getattr(sys_settings, "gemini_api_key", None) if sys_settings else None
        else:
            raise ValueError(
                f"Unsupported embedding provider '{provider}'. "
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
            )

        # 3. Return cached instance if available
        cache_key = (provider, model_name)
        if cache_key in cls._cache:
            logger.debug("Embedding cache hit: provider=%s model=%s", provider, model_name)
            return cls._cache[cache_key]

        # 4. Instantiate the correct LangChain embeddings class
        embedder = cls._create_embedder(provider, model_name, api_key)

        # 5. Cache and return
        cls._cache[cache_key] = embedder
        logger.info(
            "Created embedding instance: provider=%s model=%s dimensions=%d",
            provider, model_name, UNIFIED_EMBEDDING_DIMENSION,
        )
        return embedder

    @classmethod
    def clear_cache(cls) -> None:
        """Invalidate the embedder cache (e.g. after SystemSetting changes)."""
        cls._cache.clear()
        logger.info("Embedding provider cache cleared.")

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _create_embedder(provider: str, model_name: str, api_key: str | None) -> Embeddings:
        """
        Instantiate the correct LangChain Embeddings class.

        Both providers are configured to output UNIFIED_EMBEDDING_DIMENSION
        (768) vectors, ensuring Pinecone index compatibility.

        Args:
            provider:   "openai" or "gemini".
            model_name: Model identifier (e.g. "text-embedding-3-large").
            api_key:    Provider API key from SystemSetting.

        Returns:
            Configured Embeddings instance outputting 768-dim vectors.
        """
        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            kwargs = {
                "model": model_name,
                "dimensions": UNIFIED_EMBEDDING_DIMENSION,  # Matryoshka truncation
            }
            if api_key:
                kwargs["openai_api_key"] = api_key
            return OpenAIEmbeddings(**kwargs)

        if provider == "gemini":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            kwargs = {"model": model_name}
            if api_key:
                kwargs["google_api_key"] = api_key
            return GoogleGenerativeAIEmbeddings(**kwargs)

        # Should be unreachable — validated in get_embedder
        raise ValueError(f"Unsupported provider: {provider}")
