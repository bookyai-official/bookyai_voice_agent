"""
Unified document loading for all supported RAG source types.

Single interface — one class handles PDF, DOCX, TXT, Markdown, and URL
sources by dispatching to the correct LangChain loader internally.

Usage:
    from rag.loaders import DocumentLoader

    docs = DocumentLoader.load("pdf", "/tmp/policy.pdf")
    docs = DocumentLoader.load("url", "https://example.com/faq")
"""

import logging
from typing import List, Dict, Callable

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ── Supported source types ────────────────────────────────────────────────────

SUPPORTED_SOURCE_TYPES = ("pdf", "docx", "txt", "markdown", "url")


class DocumentLoaderError(Exception):
    """Raised when document loading fails for any reason."""


class DocumentLoader:
    """
    Unified document loader — selects the correct LangChain loader
    based on source_type and returns a list of Document objects.
    """

    # Maps source_type → loader factory function.
    # Each factory accepts a source_path and returns list[Document].
    _LOADER_MAP: Dict[str, Callable[[str], List[Document]]] = {}

    @classmethod
    def load(cls, source_type: str, source_path: str) -> List[Document]:
        """
        Load a document from the given source.

        Args:
            source_type: One of "pdf", "docx", "txt", "markdown", "url".
            source_path: Filesystem path (for files) or URL (for web sources).

        Returns:
            List of LangChain Document objects with page_content and metadata.

        Raises:
            ValueError:           If source_type is not supported.
            DocumentLoaderError:  If loading fails (file not found, network error, etc.).
        """
        source_type_lower = source_type.lower()

        if source_type_lower not in SUPPORTED_SOURCE_TYPES:
            raise ValueError(
                f"Unsupported source type '{source_type}'. "
                f"Supported: {', '.join(SUPPORTED_SOURCE_TYPES)}"
            )

        loader_fn = cls._LOADER_MAP.get(source_type_lower)
        if loader_fn is None:
            raise ValueError(f"No loader registered for source type '{source_type}'.")

        try:
            documents = loader_fn(source_path)
            logger.info(
                "Loaded %d document(s) from %s source: %s",
                len(documents), source_type_lower, source_path,
            )
            return documents
        except FileNotFoundError:
            raise DocumentLoaderError(
                f"File not found: '{source_path}'. "
                f"Ensure the file exists and the path is correct."
            )
        except Exception as e:
            raise DocumentLoaderError(
                f"Failed to load {source_type_lower} from '{source_path}': {e}"
            ) from e

    # ── Private loader factories ──────────────────────────────────────────────

    @staticmethod
    def _load_pdf(source_path: str) -> List[Document]:
        from langchain_community.document_loaders import PyPDFLoader

        loader = PyPDFLoader(source_path)
        return loader.load()

    @staticmethod
    def _load_docx(source_path: str) -> List[Document]:
        from langchain_community.document_loaders import Docx2txtLoader

        loader = Docx2txtLoader(source_path)
        return loader.load()

    @staticmethod
    def _load_txt(source_path: str) -> List[Document]:
        from langchain_community.document_loaders import TextLoader

        loader = TextLoader(source_path, encoding="utf-8")
        return loader.load()

    @staticmethod
    def _load_markdown(source_path: str) -> List[Document]:
        from langchain_community.document_loaders import UnstructuredMarkdownLoader

        loader = UnstructuredMarkdownLoader(source_path)
        return loader.load()

    @staticmethod
    def _load_url(source_path: str) -> List[Document]:
        from langchain_community.document_loaders import WebBaseLoader

        loader = WebBaseLoader(source_path)
        return loader.load()


# Register loaders on class — done once at import time
DocumentLoader._LOADER_MAP = {
    "pdf":      DocumentLoader._load_pdf,
    "docx":     DocumentLoader._load_docx,
    "txt":      DocumentLoader._load_txt,
    "markdown": DocumentLoader._load_markdown,
    "url":      DocumentLoader._load_url,
}
