"""
Pydantic schemas for RAG Knowledge Base API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ── KnowledgeBase Schemas ─────────────────────────────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    """Request body for creating a new knowledge base."""
    business_id: int
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None


class KnowledgeBaseUpdate(BaseModel):
    """Request body for updating an existing knowledge base."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class KnowledgeBaseRead(BaseModel):
    """Response schema for a knowledge base."""
    id: int
    business_id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    document_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── KnowledgeDocument Schemas ─────────────────────────────────────────────────

class KnowledgeDocumentRead(BaseModel):
    """Response schema for a knowledge document."""
    id: int
    knowledge_base_id: int
    source_type: str
    source_name: str
    pinecone_namespace: str
    status: str
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class URLIngestRequest(BaseModel):
    """Request body for ingesting a URL into a knowledge base."""
    document_id: int
    url: str = Field(..., min_length=1, max_length=2000)


# ── IngestionJob Schemas ──────────────────────────────────────────────────────

class IngestionJobRead(BaseModel):
    """Response schema for an ingestion job."""
    id: int
    document_id: int
    status: str
    error_message: Optional[str] = None
    chunks_processed: int
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Composite Response Schemas ────────────────────────────────────────────────

class KnowledgeBaseDetailRead(KnowledgeBaseRead):
    """Extended response with nested documents list."""
    documents: List[KnowledgeDocumentRead] = []


class KnowledgeDocumentDetailRead(KnowledgeDocumentRead):
    """Extended response with nested ingestion jobs list."""
    ingestion_jobs: List[IngestionJobRead] = []
