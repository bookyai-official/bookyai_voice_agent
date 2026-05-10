"""
Document chunking with multi-tenant metadata tagging.

Splits LangChain Document objects into smaller chunks using
RecursiveCharacterTextSplitter, and stamps every chunk with
business_id, knowledge_base_id, and document_id for Pinecone
multi-tenant filtering.

Usage:
    from rag.splitter import ChunkSplitter

    chunks = ChunkSplitter.split(
        documents=raw_docs,
        business_id=42,
        knowledge_base_id=7,
        document_id=123,
        source_name="policy.pdf",
        source_type="pdf",
    )
"""

import logging
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# ── Chunking defaults ─────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class ChunkSplitter:
    """
    Splits documents into smaller chunks and tags each chunk with
    multi-tenant metadata required for Pinecone filtering.
    """

    @classmethod
    def split(
        cls,
        documents: List[Document],
        business_id: int,
        knowledge_base_id: int,
        document_id: int,
        source_name: str,
        source_type: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[Document]:
        """
        Split documents into chunks and enrich each chunk's metadata.

        Args:
            documents:         Raw LangChain Document objects from a loader.
            business_id:       Tenant ID — used for Pinecone metadata filtering.
            knowledge_base_id: Parent knowledge base ID.
            document_id:       Parent document record ID.
            source_name:       Original filename or URL.
            source_type:       One of "pdf", "docx", "txt", "markdown", "url".
            chunk_size:        Maximum characters per chunk (default 500).
            chunk_overlap:     Overlap between consecutive chunks (default 50).

        Returns:
            List of Document chunks, each with enriched metadata:
                - source: original filename or URL
                - source_type: pdf / docx / txt / markdown / url
                - business_id: tenant isolation key
                - knowledge_base_id: parent KB ID
                - document_id: parent document ID
                - chunk_index: 0-based position within the document
        """
        if not documents:
            logger.warning("No documents provided to split.")
            return []

        # 1. Create the splitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

        # 2. Split into raw chunks
        raw_chunks = splitter.split_documents(documents)

        # 3. Enrich metadata on every chunk
        enriched_chunks: List[Document] = []
        for index, chunk in enumerate(raw_chunks):
            chunk.metadata.update({
                "source": source_name,
                "source_type": source_type,
                "business_id": business_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
                "chunk_index": index,
            })
            enriched_chunks.append(chunk)

        logger.info(
            "Split %d document(s) into %d chunks "
            "(business_id=%d, document_id=%d, chunk_size=%d, overlap=%d)",
            len(documents), len(enriched_chunks),
            business_id, document_id, chunk_size, chunk_overlap,
        )
        return enriched_chunks
