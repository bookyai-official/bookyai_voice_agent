"""
SQLAlchemy models for the RAG Knowledge Base system — mirrors Django's ai_agent app.

KnowledgeBase: A named collection of documents scoped to a single business.
KnowledgeDocument: Tracks each ingested source (file or URL) within a knowledge base.
IngestionJob: Async job tracker for the document ingestion pipeline.
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from models.base import Base


class KnowledgeBase(Base):
    """
    A named collection of documents belonging to a single business.
    Business isolation: all downstream models (documents, vectors) inherit
    tenant scoping through the KnowledgeBase.business_id FK chain.
    """
    __tablename__ = "ai_agent_knowledgebase"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(
        Integer,
        ForeignKey("business_business.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    documents = relationship(
        "KnowledgeDocument",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_kb_business_name"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, business_id={self.business_id}, name='{self.name}')>"


class KnowledgeDocument(Base):
    """
    Tracks a single ingested source (file or URL) within a knowledge base.
    The actual file content is NOT stored — only metadata and ingestion status.
    Vectors are stored in Pinecone under the pinecone_namespace.
    """
    __tablename__ = "ai_agent_knowledgedocument"

    id = Column(Integer, primary_key=True, index=True)
    knowledge_base_id = Column(
        Integer,
        ForeignKey("ai_agent_knowledgebase.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Source metadata
    source_type = Column(String(20), nullable=False)  # pdf, txt, docx, markdown, url
    source_name = Column(String(500), nullable=False)  # Original filename or URL

    content = Column(Text, nullable=True)

    # Pinecone vector location
    pinecone_namespace = Column(String(100), nullable=False)

    # Ingestion tracking
    status = Column(String(20), nullable=False, default="queued", index=True)  # queued, processing, completed, failed
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    ingestion_jobs = relationship(
        "IngestionJob",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="IngestionJob.created_at.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<KnowledgeDocument(id={self.id}, source_type='{self.source_type}', "
            f"source_name='{self.source_name}', status='{self.status}')>"
        )


class IngestionJob(Base):
    """
    Async job tracker for the document ingestion pipeline.
    One job is created per ingestion attempt (initial or re-ingestion).
    """
    __tablename__ = "ai_agent_ingestionjob"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("ai_agent_knowledgedocument.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(String(20), nullable=False, default="queued", index=True)  # queued, processing, completed, failed
    error_message = Column(Text, nullable=True)
    chunks_processed = Column(Integer, default=0)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("KnowledgeDocument", back_populates="ingestion_jobs")

    def __repr__(self) -> str:
        return f"<IngestionJob(id={self.id}, document_id={self.document_id}, status='{self.status}')>"
