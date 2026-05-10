# RAG Knowledge Base API Documentation

This document provides detailed API documentation for the Knowledge Base endpoints defined in `api/routes/knowledge.py`.

## Base Path
`[PREFIX]/api/knowledge-bases`

## Authentication
All endpoints require authentication via the `verify_token` dependency. Requests must include the internal API secret token as configured by `API_SECRET_TOKEN` in `.env`.

---

## 1. Create Knowledge Base

Create a new knowledge base for a specific business. 
A business cannot have multiple active knowledge bases with the exact same name.

**Endpoint:** `POST /`

**Request Body (`KnowledgeBaseCreate`):**
```json
{
  "business_id": 123,
  "name": "Customer Support FAQ",
  "description": "Standard operating procedures and FAQs for support agents."
}
```

**Response (`KnowledgeBaseRead`):**
```json
{
  "id": 1,
  "business_id": 123,
  "name": "Customer Support FAQ",
  "description": "Standard operating procedures and FAQs for support agents.",
  "is_active": true,
  "created_at": "2026-05-09T18:00:00Z",
  "updated_at": "2026-05-09T18:00:00Z",
  "document_count": 0
}
```

**Status Codes:**
- `200 OK`: Created successfully.
- `409 Conflict`: A knowledge base with this name already exists for the given business.

---

## 2. List Knowledge Bases

List all knowledge bases belonging to a specific business. Results are ordered by creation date (newest first).

**Endpoint:** `GET /{business_id}`

**Path Parameters:**
- `business_id` (int): The ID of the business.

**Response (`List[KnowledgeBaseRead]`):**
```json
[
  {
    "id": 1,
    "business_id": 123,
    "name": "Customer Support FAQ",
    "description": "Standard operating procedures and FAQs for support agents.",
    "is_active": true,
    "created_at": "2026-05-09T18:00:00Z",
    "updated_at": "2026-05-09T18:00:00Z",
    "document_count": 5
  }
]
```

---

## 3. Delete Knowledge Base

Soft-deletes a knowledge base by setting `is_active=False`. 
This operation also explicitly deletes all associated Pinecone vectors from the vector database to prevent deleted knowledge from appearing in RAG contexts.

**Endpoint:** `DELETE /{knowledge_base_id}`

**Path Parameters:**
- `knowledge_base_id` (int): The ID of the knowledge base to delete.

**Response:**
```json
{
  "ok": true,
  "detail": "Knowledge base deactivated and vectors deleted."
}
```

**Status Codes:**
- `200 OK`: Deleted successfully.
- `404 Not Found`: Knowledge base does not exist.

---

## 4. Upload File Document

Upload a local file (PDF, DOCX, TXT, or Markdown) for ingestion into the knowledge base.
The file is saved temporarily, database records are created, and the chunking/embedding pipeline is triggered asynchronously in the background.

**Endpoint:** `POST /{knowledge_base_id}/documents/upload`

**Path Parameters:**
- `knowledge_base_id` (int): The target knowledge base ID.

**Request Body (`multipart/form-data`):**
- `file` (UploadFile): The file to ingest. Allowed extensions: `.pdf`, `.docx`, `.txt`, `.md`.

**Response (`KnowledgeDocumentRead`):**
```json
{
  "id": 42,
  "knowledge_base_id": 1,
  "source_type": "pdf",
  "source_name": "company_policy.pdf",
  "pinecone_namespace": "123",
  "status": "queued",
  "error_message": null,
  "chunk_count": 0,
  "created_at": "2026-05-09T18:05:00Z",
  "updated_at": "2026-05-09T18:05:00Z"
}
```

**Status Codes:**
- `200 OK`: File accepted and ingestion queued.
- `400 Bad Request`: Unsupported file type.
- `404 Not Found`: Knowledge base does not exist or is deactivated.

---

## 5. Ingest URL Document

Ingest content directly from a website URL. The URL is scraped, processed, and embedded asynchronously in the background.

**Endpoint:** `POST /{knowledge_base_id}/documents/url`

**Path Parameters:**
- `knowledge_base_id` (int): The target knowledge base ID.

**Request Body (`URLIngestRequest`):**
```json
{
  "url": "https://example.com/pricing"
}
```

**Response (`KnowledgeDocumentRead`):**
```json
{
  "id": 43,
  "knowledge_base_id": 1,
  "source_type": "url",
  "source_name": "https://example.com/pricing",
  "pinecone_namespace": "123",
  "status": "queued",
  "error_message": null,
  "chunk_count": 0,
  "created_at": "2026-05-09T18:10:00Z",
  "updated_at": "2026-05-09T18:10:00Z"
}
```

**Status Codes:**
- `200 OK`: URL accepted and ingestion queued.
- `404 Not Found`: Knowledge base does not exist or is deactivated.

---

## 6. List Documents

List all documents (files and URLs) associated with a specific knowledge base, including their current ingestion status. Ordered by creation date (newest first).

**Endpoint:** `GET /{knowledge_base_id}/documents/`

**Path Parameters:**
- `knowledge_base_id` (int): The target knowledge base ID.

**Response (`List[KnowledgeDocumentRead]`):**
```json
[
  {
    "id": 42,
    "knowledge_base_id": 1,
    "source_type": "pdf",
    "source_name": "company_policy.pdf",
    "pinecone_namespace": "123",
    "status": "completed",
    "error_message": null,
    "chunk_count": 15,
    "created_at": "2026-05-09T18:05:00Z",
    "updated_at": "2026-05-09T18:06:00Z"
  }
]
```

**Status Codes:**
- `200 OK`: Success.
- `404 Not Found`: Knowledge base does not exist or is deactivated.

---

## 7. Get Document Ingestion Status

Retrieve the real-time status of the latest ingestion job for a specific document. Use this endpoint for polling progress on the frontend.

**Endpoint:** `GET /{knowledge_base_id}/documents/{document_id}/status`

**Path Parameters:**
- `knowledge_base_id` (int): The target knowledge base ID.
- `document_id` (int): The target document ID.

**Response (`IngestionJobRead`):**
```json
{
  "id": 105,
  "document_id": 42,
  "status": "completed",
  "error_message": null,
  "chunks_processed": 15,
  "started_at": "2026-05-09T18:05:05Z",
  "finished_at": "2026-05-09T18:06:00Z",
  "created_at": "2026-05-09T18:05:00Z"
}
```

**Status Codes:**
- `200 OK`: Success.
- `404 Not Found`: No ingestion job exists for this document.

---

## 8. Re-ingest Document

Force a document to be re-ingested. This operation:
1. Deletes all existing Pinecone vectors for the document.
2. Resets the document's status to `queued`.
3. Triggers a new asynchronous ingestion pipeline.

*Note: For files, the file must still be accessible on disk at the original `source_name` path. For URLs, it will re-scrape the live URL.*

**Endpoint:** `POST /{knowledge_base_id}/documents/{document_id}/reingest`

**Path Parameters:**
- `knowledge_base_id` (int): The target knowledge base ID.
- `document_id` (int): The target document ID.

**Response (`KnowledgeDocumentRead`):**
```json
{
  "id": 42,
  "knowledge_base_id": 1,
  "source_type": "pdf",
  "source_name": "company_policy.pdf",
  "pinecone_namespace": "123",
  "status": "queued",
  "error_message": null,
  "chunk_count": 0,
  "created_at": "2026-05-09T18:05:00Z",
  "updated_at": "2026-05-09T18:15:00Z"
}
```

**Status Codes:**
- `200 OK`: Vectors cleared and re-ingestion queued successfully.
- `404 Not Found`: Document does not exist.
