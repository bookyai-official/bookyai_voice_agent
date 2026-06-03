"""
FastAPI routes for RAG Knowledge Base management.

Provides endpoints for CRUD on knowledge bases, document upload/URL ingestion,
ingestion status monitoring, and re-ingestion triggers.
All ingestion runs asynchronously via FastAPI BackgroundTasks.
"""

import os
import logging
import tempfile
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from core.database import get_db
from api.dependencies import verify_token
from models.knowledge import KnowledgeBase, KnowledgeDocument, IngestionJob
from schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseRead,
    KnowledgeDocumentRead,
    IngestionJobRead,
    URLIngestRequest,
)
from rag.ingestor import KnowledgeIngestor
from rag.pinecone_client import PineconeClientManager

from services.usage_service import UsageService
from core.config import settings

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PINECONE_INDEX_NAME = settings.PINECONE_INDEX_NAME

ALLOWED_FILE_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".docx": "docx",
    ".md": "markdown",
}


# ── Background Task ──────────────────────────────────────────────────────────

async def run_ingestion(
    document_id: int,
    job_id: int,
    source_path: str,
    index_name: str,
    temp_file_path: str | None = None,
) -> None:
    """
    Background task that runs the full ingestion pipeline.

    Error handling is inside KnowledgeIngestor — this function
    just calls it and cleans up any temporary files afterwards.

    Args:
        document_id:    ID of the KnowledgeDocument to ingest.
        job_id:         ID of the IngestionJob tracking this run.
        source_path:    File path or URL to ingest from.
        index_name:     Pinecone index name.
        temp_file_path: Optional path to a temp file to delete after ingestion.
    """
    try:
        await KnowledgeIngestor.ingest(
            document_id=document_id,
            job_id=job_id,
            source_path=source_path,
            index_name=index_name,
        )
    finally:
        # Clean up temp file if one was created for this ingestion
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug("Cleaned up temp file: %s", temp_file_path)
            except OSError as e:
                logger.warning("Failed to clean up temp file %s: %s", temp_file_path, e)


# ── 1. Create Knowledge Base ─────────────────────────────────────────────────

@router.post("/", response_model=KnowledgeBaseRead, dependencies=[Depends(verify_token)])
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseRead:
    """Create a new knowledge base for a business."""
    # Check feature access
    has_feature = await UsageService.has_feature_access(db, payload.business_id, "custom_knowledge_base")
    if not has_feature:
        raise HTTPException(
            status_code=403,
            detail="Custom Knowledge Base feature is not included in your current subscription plan. Please upgrade to use this feature."
        )
    # Check for duplicate name within the business
    existing = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.business_id == payload.business_id,
            KnowledgeBase.name == payload.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Knowledge base '{payload.name}' already exists for this business.",
        )

    kb = KnowledgeBase(**payload.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)

    return KnowledgeBaseRead(
        **{c.name: getattr(kb, c.name) for c in kb.__table__.columns},
        document_count=0,
    )


# ── 2. List Knowledge Bases ──────────────────────────────────────────────────

@router.get("/{business_id}", response_model=List[KnowledgeBaseRead], dependencies=[Depends(verify_token)])
async def list_knowledge_bases(
    business_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[KnowledgeBaseRead]:
    """List all knowledge bases for a business."""
    result = await db.execute(
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(KnowledgeBase.business_id == business_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    bases = result.scalars().all()

    return [
        KnowledgeBaseRead(
            **{c.name: getattr(kb, c.name) for c in kb.__table__.columns},
            document_count=len(kb.documents),
        )
        for kb in bases
    ]


# ── 3. Delete Knowledge Base ─────────────────────────────────────────────────

@router.delete("/{knowledge_base_id}", dependencies=[Depends(verify_token)])
async def delete_knowledge_base(
    knowledge_base_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Soft delete a knowledge base (set is_active=False).
    Also deletes all Pinecone vectors for every document in this KB.
    """
    result = await db.execute(
        select(KnowledgeBase)
        .options(selectinload(KnowledgeBase.documents))
        .where(KnowledgeBase.id == knowledge_base_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")

    # Delete vectors from Pinecone for each document
    namespace = str(kb.business_id)
    try:
        pinecone_mgr = PineconeClientManager()
        for doc in kb.documents:
            pinecone_mgr.delete_vectors(
                index_name=PINECONE_INDEX_NAME,
                namespace=namespace,
                document_id=doc.id,
            )
    except Exception as e:
        logger.warning("[KNOWLEDGE] Pinecone cleanup failed for KB %d: %s", knowledge_base_id, e)

    # Soft delete
    kb.is_active = False
    await db.commit()

    return {"ok": True, "detail": "Knowledge base deactivated and vectors deleted."}


# ── 4. Upload File ────────────────────────────────────────────────────────────

@router.post(
    "/{knowledge_base_id}/documents/upload",
    response_model=KnowledgeDocumentRead,
    dependencies=[Depends(verify_token)],
)
async def upload_document(
    knowledge_base_id: int,
    background_tasks: BackgroundTasks,
    document_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentRead:
    """
    Upload a file (PDF, DOCX, TXT, MD) for ingestion.
    Returns immediately — ingestion runs in the background.
    """
    kb = await _get_knowledge_base_or_404(db, knowledge_base_id)

    # Check feature access
    has_feature = await UsageService.has_feature_access(db, kb.business_id, "custom_knowledge_base")
    if not has_feature:
        raise HTTPException(
            status_code=403,
            detail="Custom Knowledge Base feature is not included in your current subscription plan. Please upgrade to use this feature."
        )

    # Fetch the document created by Django
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document or document.knowledge_base_id != knowledge_base_id:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Validate file extension
    _, ext = os.path.splitext(file.filename or "")
    ext_lower = ext.lower()
    if ext_lower not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext_lower}'. Allowed: {', '.join(ALLOWED_FILE_EXTENSIONS.keys())}",
        )

    # Write uploaded content to a temp file for the loader
    content = await file.read()
    temp_fd, temp_path = tempfile.mkstemp(suffix=ext_lower)
    os.write(temp_fd, content)
    os.close(temp_fd)

    # Fetch the IngestionJob created by Django
    job_result = await db.execute(
        select(IngestionJob).where(IngestionJob.document_id == document.id).order_by(IngestionJob.id.desc()).limit(1)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")

    # Trigger background ingestion
    background_tasks.add_task(
        run_ingestion,
        document_id=document.id,
        job_id=job.id,
        source_path=temp_path,
        index_name=PINECONE_INDEX_NAME,
        temp_file_path=temp_path,
    )

    logger.info(
        "[KNOWLEDGE] Queued file ingestion: doc=%d job=%d file='%s'",
        document.id, job.id, file.filename,
    )

    return KnowledgeDocumentRead.model_validate(document)


# ── 5. Ingest URL ─────────────────────────────────────────────────────────────

@router.post(
    "/{knowledge_base_id}/documents/url",
    response_model=KnowledgeDocumentRead,
    dependencies=[Depends(verify_token)],
)
async def ingest_url(
    knowledge_base_id: int,
    payload: URLIngestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentRead:
    """
    Ingest a website URL into the knowledge base.
    Returns immediately — ingestion runs in the background.
    """
    kb = await _get_knowledge_base_or_404(db, knowledge_base_id)

    # Check feature access
    has_feature = await UsageService.has_feature_access(db, kb.business_id, "custom_knowledge_base")
    if not has_feature:
        raise HTTPException(
            status_code=403,
            detail="Custom Knowledge Base feature is not included in your current subscription plan. Please upgrade to use this feature."
        )

    # Fetch the document created by Django
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == payload.document_id)
    )
    document = result.scalar_one_or_none()
    if not document or document.knowledge_base_id != knowledge_base_id:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Fetch the IngestionJob created by Django
    job_result = await db.execute(
        select(IngestionJob).where(IngestionJob.document_id == document.id).order_by(IngestionJob.id.desc()).limit(1)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")

    # For URLs, source_path IS the URL itself
    background_tasks.add_task(
        run_ingestion,
        document_id=document.id,
        job_id=job.id,
        source_path=payload.url,
        index_name=PINECONE_INDEX_NAME,
    )

    logger.info(
        "[KNOWLEDGE] Queued URL ingestion: doc=%d job=%d url='%s'",
        document.id, job.id, payload.url,
    )

    return KnowledgeDocumentRead.model_validate(document)


# ── 6. List Documents ─────────────────────────────────────────────────────────

@router.get(
    "/{knowledge_base_id}/documents/",
    response_model=List[KnowledgeDocumentRead],
    dependencies=[Depends(verify_token)],
)
async def list_documents(
    knowledge_base_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[KnowledgeDocumentRead]:
    """List all documents in a knowledge base with their status."""
    await _get_knowledge_base_or_404(db, knowledge_base_id)

    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    documents = result.scalars().all()
    return [KnowledgeDocumentRead.model_validate(doc) for doc in documents]


# ── 7. Document Ingestion Status ──────────────────────────────────────────────

@router.get(
    "/{knowledge_base_id}/documents/{document_id}/status",
    response_model=IngestionJobRead,
    dependencies=[Depends(verify_token)],
)
async def get_document_status(
    knowledge_base_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
) -> IngestionJobRead:
    """Get the latest ingestion job status for a document."""
    result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="No ingestion job found for this document.")

    return IngestionJobRead.model_validate(job)


# ── 8. Re-ingest Document ────────────────────────────────────────────────────

@router.post(
    "/{knowledge_base_id}/documents/{document_id}/reingest",
    response_model=KnowledgeDocumentRead,
    dependencies=[Depends(verify_token)],
)
async def reingest_document(
    knowledge_base_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentRead:
    """
    Re-trigger ingestion for a document.
    Deletes existing vectors, resets status, and creates a new ingestion job.
    """
    result = await db.execute(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.knowledge_base))
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Check feature access
    has_feature = await UsageService.has_feature_access(db, document.knowledge_base.business_id, "custom_knowledge_base")
    if not has_feature:
        raise HTTPException(
            status_code=403,
            detail="Custom Knowledge Base feature is not included in your current subscription plan. Please upgrade to use this feature."
        )

    # Delete existing vectors from Pinecone
    namespace = str(document.knowledge_base.business_id)
    try:
        pinecone_mgr = PineconeClientManager()
        pinecone_mgr.delete_vectors(
            index_name=PINECONE_INDEX_NAME,
            namespace=namespace,
            document_id=document.id,
        )
    except Exception as e:
        if "Namespace not found" in str(e):
            logger.info("[KNOWLEDGE] Namespace %s not found in Pinecone during re-ingestion.", namespace)
        else:
            logger.warning("[KNOWLEDGE] Pinecone cleanup failed for doc %d: %s", document_id, e)

    # Reset document status
    document.status = "queued"
    document.error_message = None
    document.chunk_count = 0
    await db.commit()

    # Create new ingestion job
    job = IngestionJob(document_id=document.id, status="queued")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Determine source_path: for URLs it's the source_name, for files re-ingestion
    # requires the original content to still be accessible
    source_path = document.source_name  # URL or original filename

    background_tasks.add_task(
        run_ingestion,
        document_id=document.id,
        job_id=job.id,
        source_path=source_path,
        index_name=PINECONE_INDEX_NAME,
    )

    logger.info("[KNOWLEDGE] Queued re-ingestion: doc=%d job=%d", document.id, job.id)

    await db.refresh(document)
    return KnowledgeDocumentRead.model_validate(document)


# ── 9. Delete Document Vectors ───────────────────────────────────────────────

@router.delete(
    "/{knowledge_base_id}/documents/{document_id}/vectors",
    dependencies=[Depends(verify_token)],
)
async def delete_document_vectors(
    knowledge_base_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete all vectors for a specific document from Pinecone.
    """
    result = await db.execute(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.knowledge_base))
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found or not linked to this knowledge base.",
        )

    namespace = str(document.knowledge_base.business_id)
    try:
        pinecone_mgr = PineconeClientManager()
        pinecone_mgr.delete_vectors(
            index_name=PINECONE_INDEX_NAME,
            namespace=namespace,
            document_id=document.id,
        )
    except Exception as e:
        error_str = str(e)
        if "Namespace not found" in error_str:
            logger.info("[KNOWLEDGE] Namespace %s not found in Pinecone. Nothing to delete.", namespace)
        else:
            logger.error("[KNOWLEDGE] Pinecone cleanup failed for doc %d: %s", document_id, e)
            raise HTTPException(status_code=500, detail=f"Failed to delete vectors: {error_str}")

    return {"ok": True, "detail": f"Vectors for document {document_id} deleted."}


# ── 10. Delete Document ──────────────────────────────────────────────────────

@router.delete(
    "/{knowledge_base_id}/documents/{document_id}",
    dependencies=[Depends(verify_token)],
)
async def delete_document(
    knowledge_base_id: int,
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a document from the database and its vectors from Pinecone.
    """
    result = await db.execute(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.knowledge_base))
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found or not linked to this knowledge base.",
        )

    # 1. Delete from Pinecone
    namespace = str(document.knowledge_base.business_id)
    try:
        pinecone_mgr = PineconeClientManager()
        pinecone_mgr.delete_vectors(
            index_name=PINECONE_INDEX_NAME,
            namespace=namespace,
            document_id=document.id,
        )
    except Exception as e:
        if "Namespace not found" in str(e):
            logger.info("[KNOWLEDGE] Namespace %s not found in Pinecone during document deletion.", namespace)
        else:
            logger.warning("[KNOWLEDGE] Pinecone cleanup failed for doc %d: %s", document_id, e)
        # We continue even if Pinecone fails, to ensure DB stays in sync

    # 2. Delete from DB
    await db.delete(document)
    await db.commit()

    return {"ok": True, "detail": f"Document {document_id} and its vectors deleted."}


# ── Private Helpers ───────────────────────────────────────────────────────────

async def _get_knowledge_base_or_404(
    db: AsyncSession,
    knowledge_base_id: int,
) -> KnowledgeBase:
    """Fetch a knowledge base by ID or raise 404."""
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    if not kb.is_active:
        raise HTTPException(status_code=404, detail="Knowledge base is deactivated.")
    return kb
