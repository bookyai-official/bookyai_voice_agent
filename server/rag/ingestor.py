"""
Knowledge Ingestor — orchestrates the full ingestion pipeline for a single document.

Flow:
    KnowledgeDocument (DB)
        → DocumentLoader.load()
        → ChunkSplitter.split()
        → EmbeddingProvider.get_embedder()
        → PineconeVectorStore.add_documents()  (embed + upsert in one step)
        → Update DB status (completed / failed)

Usage:
    from rag.ingestor import KnowledgeIngestor

    await KnowledgeIngestor.ingest(
        document_id=123,
        job_id=456,
        source_path="/tmp/policy.pdf",
        index_name="booky-rag",
    )
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import List

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models.knowledge import KnowledgeBase, KnowledgeDocument, IngestionJob
from rag.loaders import DocumentLoader
from rag.splitter import ChunkSplitter
from rag.embeddings import EmbeddingProvider
from rag.pinecone_client import PineconeClientManager

logger = logging.getLogger(__name__)


from models.subscription import Subscription, SubscriptionPlan

class KnowledgeIngestor:
    """
    Orchestrates the full ingestion pipeline for a single KnowledgeDocument.

    Handles:
        1. Loading the document from its source
        2. Splitting into chunks with tenant metadata
        3. Embedding + upserting into Pinecone via PineconeVectorStore
        4. Updating DB records (status, chunk_count, errors)
    """

    @classmethod
    async def ingest(
        cls,
        document_id: int,
        job_id: int,
        source_path: str,
        index_name: str,
    ) -> None:
        """
        Run the full ingestion pipeline for a document.

        Args:
            document_id: ID of the KnowledgeDocument to ingest.
            job_id:      ID of the IngestionJob tracking this run.
            source_path: File path or URL to load content from.
            index_name:  Pinecone index name (must already exist).
        """
        async with AsyncSessionLocal() as db:
            try:
                # ── 1. Load document and knowledge base from DB ───────────
                document = await cls._get_document(db, document_id)
                kb = await cls._get_knowledge_base(db, document.knowledge_base_id)

                # ── 2. Mark job as processing ─────────────────────────────
                await cls._update_job_status(
                    db, job_id, "processing",
                    started_at=datetime.now(timezone.utc),
                )
                await cls._update_document_status(db, document_id, "processing")

                # ── 3. Load raw documents ─────────────────────────────────
                logger.info(
                    "[INGESTOR] Loading %s from: %s",
                    document.source_type, source_path,
                )
                raw_docs = DocumentLoader.load(document.source_type, source_path)

                if not raw_docs:
                    raise ValueError(f"No content extracted from '{source_path}'.")

                # Save raw text to document.content
                full_content = "\n\n".join(doc.page_content for doc in raw_docs)
                new_chars_count = len(full_content)

                # Fetch active subscription and check KB character limit
                stmt_sub = (
                    select(Subscription)
                    .where(
                        Subscription.business_id == str(kb.business_id),
                        Subscription.status.in_(['active', 'trialing']),
                        Subscription.ended_at == None
                    )
                    .order_by(Subscription.id.desc())
                    .limit(1)
                )
                sub_result = await db.execute(stmt_sub)
                subscription = sub_result.scalar_one_or_none()
                if subscription:
                    plan_stmt = select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
                    plan_result = await db.execute(plan_stmt)
                    plan = plan_result.scalar_one_or_none()
                    if plan:
                        limits = plan.usage_limits or {}
                        if isinstance(limits, dict):
                            kb_chars_limit = limits.get('kb_chars', 0)
                            if kb_chars_limit > 0:
                                # Fetch other documents for this business to calculate current usage
                                stmt_docs = (
                                    select(KnowledgeDocument)
                                    .join(KnowledgeBase)
                                    .where(
                                        KnowledgeBase.business_id == kb.business_id,
                                        KnowledgeDocument.id != document_id
                                    )
                                )
                                docs_result = await db.execute(stmt_docs)
                                docs = docs_result.scalars().all()
                                current_kb_chars = sum(len(d.content) for d in docs if d.content)
                                
                                if (current_kb_chars + new_chars_count) > kb_chars_limit:
                                    raise ValueError(
                                        f"Adding this document would exceed your plan's Knowledge Base limit of {kb_chars_limit} characters. "
                                        f"(Currently using {current_kb_chars} characters, this document has {new_chars_count} characters)."
                                    )

                document.content = full_content
                await db.commit()


                # ── 4. Split into chunks with tenant metadata ─────────────
                chunks = ChunkSplitter.split(
                    documents=raw_docs,
                    business_id=kb.business_id,
                    knowledge_base_id=kb.id,
                    document_id=document_id,
                    source_name=document.source_name,
                    source_type=document.source_type,
                )

                if not chunks:
                    raise ValueError("Splitting produced zero chunks.")

                # ── 5. Get embedder and create PineconeVectorStore ────────
                embedder = await EmbeddingProvider.get_embedder(db)
                namespace = str(kb.business_id)

                pinecone_mgr = PineconeClientManager()
                vector_store = pinecone_mgr.get_vector_store(
                    index_name=index_name,
                    embedder=embedder,
                    namespace=namespace,
                )

                # ── 6. Build vector IDs: "{document_id}_{chunk_index}" ────
                vector_ids = cls._build_vector_ids(document_id, chunks)

                # ── 7. Embed + Upsert via PineconeVectorStore ─────────────
                logger.info(
                    "[INGESTOR] Embedding and upserting %d chunks "
                    "into namespace '%s'...",
                    len(chunks), namespace,
                )
                await vector_store.aadd_documents(chunks, ids=vector_ids)
                total_upserted = len(chunks)

                # ── 8. Mark success in DB ─────────────────────────────────
                now = datetime.now(timezone.utc)
                await cls._update_document_status(
                    db, document_id, "completed",
                    chunk_count=total_upserted,
                    pinecone_namespace=namespace,
                )
                await cls._update_job_status(
                    db, job_id, "completed",
                    chunks_processed=total_upserted,
                    finished_at=now,
                )

                logger.info(
                    "[INGESTOR] ✓ Document %d ingested: %d chunks upserted.",
                    document_id, total_upserted,
                )

            except Exception as e:
                # ── Failure path — update DB and log full traceback ────────
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "[INGESTOR] ✗ Ingestion failed for document %d: %s\n%s",
                    document_id, error_msg, traceback.format_exc(),
                )
                await cls._mark_failed(db, document_id, job_id, error_msg)

    # ── Private: Vector ID generation ─────────────────────────────────────────

    @staticmethod
    def _build_vector_ids(document_id: int, chunks: list) -> List[str]:
        """
        Generate deterministic Pinecone vector IDs.

        Format: "{document_id}_{chunk_index}"
        This enables targeted deletion and re-ingestion.
        """
        return [
            f"{document_id}_{chunk.metadata.get('chunk_index', i)}"
            for i, chunk in enumerate(chunks)
        ]

    # ── Private: DB helpers ───────────────────────────────────────────────────

    @staticmethod
    async def _get_document(db: AsyncSession, document_id: int) -> KnowledgeDocument:
        """Fetch a KnowledgeDocument or raise."""
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError(f"KnowledgeDocument {document_id} not found.")
        return doc

    @staticmethod
    async def _get_knowledge_base(db: AsyncSession, kb_id: int) -> KnowledgeBase:
        """Fetch the parent KnowledgeBase or raise."""
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise ValueError(f"KnowledgeBase {kb_id} not found.")
        return kb

    @staticmethod
    async def _update_document_status(
        db: AsyncSession,
        document_id: int,
        status: str,
        chunk_count: int | None = None,
        error_message: str | None = None,
        pinecone_namespace: str | None = None,
    ) -> None:
        """Update KnowledgeDocument status and optional fields."""
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc:
            doc.status = status
            if chunk_count is not None:
                doc.chunk_count = chunk_count
            if error_message is not None:
                doc.error_message = error_message
            if pinecone_namespace is not None:
                doc.pinecone_namespace = pinecone_namespace
            await db.commit()

    @staticmethod
    async def _update_job_status(
        db: AsyncSession,
        job_id: int,
        status: str,
        chunks_processed: int | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        """Update IngestionJob status and timing fields."""
        result = await db.execute(
            select(IngestionJob).where(IngestionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = status
            if chunks_processed is not None:
                job.chunks_processed = chunks_processed
            if error_message is not None:
                job.error_message = error_message
            if started_at is not None:
                job.started_at = started_at
            if finished_at is not None:
                job.finished_at = finished_at
            await db.commit()

    @classmethod
    async def _mark_failed(
        cls,
        db: AsyncSession,
        document_id: int,
        job_id: int,
        error_msg: str,
    ) -> None:
        """Mark both document and job as failed with the error message."""
        now = datetime.now(timezone.utc)
        try:
            await cls._update_document_status(
                db, document_id, "failed", error_message=error_msg,
            )
            await cls._update_job_status(
                db, job_id, "failed",
                error_message=error_msg, finished_at=now,
            )
        except Exception as db_err:
            logger.error(
                "[INGESTOR] Failed to update DB after ingestion error: %s",
                db_err,
            )
