import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import faiss
import numpy as np

from app.config import KnowledgeBaseSettings, config
from app.logger import logger
from app.services.embedding_service import EmbeddingService


@dataclass
class KnowledgeRecord:
    id: str
    source_id: str
    text: str
    metadata: Dict[str, str]
    vector: List[float]

    def as_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "text": self.text,
            "metadata": self.metadata,
            "vector": self.vector,
        }


class TextChunker:
    """Character-based chunker with configurable overlap."""

    def __init__(self, chunk_size: int, chunk_overlap: int):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> List[str]:
        normalized = (text or "").replace("\r\n", "\n").strip()
        if not normalized:
            return []

        chunks: List[str] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        length = len(normalized)

        while start < length:
            end = min(length, start + self.chunk_size)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= length:
                break
            start += step

        return chunks


class KnowledgeBaseService:
    """Manages FAISS-backed storage plus metadata for document chunks."""

    def __init__(
        self,
        settings: KnowledgeBaseSettings | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        self.settings = settings or config.knowledge_base_config
        self.embedding_service = embedding_service or EmbeddingService(
            self.settings.embedding
        )
        self._chunker = TextChunker(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        self._lock = asyncio.Lock()
        self._storage_dir = (
            config.workspace_root / self.settings.storage_dir
        ).resolve()
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._metadata_path = self._storage_dir / "records.json"
        self._index: faiss.IndexFlatIP | None = None
        self._records: List[KnowledgeRecord] = []
        self._dimension: Optional[int] = None
        self._load_records()

    async def ingest_document(
        self,
        source_id: str,
        text: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        """Parse, embed, and store a document's text."""

        chunks = self._chunker.chunk(text)
        if not chunks:
            raise ValueError("Document has no content after chunking")

        vectors = await self.embedding_service.embed_texts(chunks)
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding service returned unexpected vector count")

        async with self._lock:
            base_offset = len(self._records)
            records = self._build_records(source_id, chunks, vectors, metadata)
            self._append_to_index(vectors)
            self._records.extend(records)
            self._persist_records()
            logger.info(
                "Ingested %d chunks for source %s (total=%d)",
                len(records),
                source_id,
                len(self._records),
            )

        return {
            "source_id": source_id,
            "chunks_ingested": len(records),
            "record_ids": [record.id for record in records],
            "start_offset": base_offset,
        }

    async def ingest_blocks(
        self,
        source_id: str,
        blocks: Sequence[str],
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        """Directly ingest pre-chunked blocks."""

        clean_blocks = [block.strip() for block in blocks if block and block.strip()]
        if not clean_blocks:
            raise ValueError("No valid text blocks to ingest")
        vectors = await self.embedding_service.embed_texts(clean_blocks)
        if len(vectors) != len(clean_blocks):
            raise RuntimeError("Embedding count mismatch")
        async with self._lock:
            base_offset = len(self._records)
            records = self._build_records(source_id, clean_blocks, vectors, metadata)
            self._append_to_index(vectors)
            self._records.extend(records)
            self._persist_records()
        return {
            "source_id": source_id,
            "chunks_ingested": len(records),
            "record_ids": [record.id for record in records],
            "start_offset": base_offset,
        }

    async def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Sequence[str]]] = None,
    ) -> List[Dict[str, object]]:
        vector = await self.embedding_service.embed_query(query)
        if not vector or self._index is None or self._index.ntotal == 0:
            return []

        k = min(self._index.ntotal, top_k or self.settings.top_k)
        if k <= 0:
            return []

        query_array = np.array([vector], dtype="float32")
        scores, indices = self._index.search(query_array, k)

        allowed_sources = None
        if filters and filters.get("source_ids"):
            allowed_sources = set(filters["source_ids"])

        hits: List[Dict[str, object]] = []
        for idx, score in zip(indices[0], scores[0]):
            if idx < 0 or idx >= len(self._records):
                continue
            record = self._records[idx]
            if allowed_sources and record.source_id not in allowed_sources:
                continue
            hits.append(
                {
                    "id": record.id,
                    "source_id": record.source_id,
                    "text": record.text,
                    "metadata": record.metadata,
                    "score": float(score),
                }
            )
        return hits

    async def delete_source(self, source_id: str) -> int:
        async with self._lock:
            before = len(self._records)
            self._records = [
                record for record in self._records if record.source_id != source_id
            ]
            removed = before - len(self._records)
            if removed:
                self._rebuild_index()
                self._persist_records()
                logger.info("Removed {} chunks for source {}", removed, source_id)
            return removed

    def _build_records(
        self,
        source_id: str,
        chunks: Sequence[str],
        vectors: Sequence[Sequence[float]],
        metadata: Optional[Dict[str, str]],
    ) -> List[KnowledgeRecord]:
        base_meta = dict(metadata) if metadata else {}
        records: List[KnowledgeRecord] = []
        for chunk, vector in zip(chunks, vectors):
            records.append(
                KnowledgeRecord(
                    id=uuid.uuid4().hex,
                    source_id=source_id,
                    text=chunk,
                    metadata=base_meta.copy(),
                    vector=[float(v) for v in vector],
                )
            )
        return records

    def _append_to_index(self, vectors: Sequence[Sequence[float]]) -> None:
        if not vectors:
            return
        array = np.array(vectors, dtype="float32")
        if self._index is None:
            self._dimension = array.shape[1]
            self._index = faiss.IndexFlatIP(self._dimension)
            if self._records:
                existing = np.array(
                    [rec.vector for rec in self._records], dtype="float32"
                )
                if existing.size:
                    self._index.add(existing)
        elif array.shape[1] != self._dimension:
            raise ValueError("Vector dimension mismatch for FAISS index")
        self._index.add(array)

    def _rebuild_index(self) -> None:
        if not self._records:
            self._index = None
            self._dimension = None
            return
        vectors = np.array([record.vector for record in self._records], dtype="float32")
        self._dimension = vectors.shape[1]
        self._index = faiss.IndexFlatIP(self._dimension)
        self._index.add(vectors)

    def _load_records(self) -> None:
        if not self._metadata_path.exists():
            return
        with self._metadata_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._records = [KnowledgeRecord(**item) for item in payload]
        if self._records:
            self._rebuild_index()
            logger.info("Loaded {} knowledge base chunks", len(self._records))

    def _persist_records(self) -> None:
        tmp_path = self._metadata_path.with_suffix(".tmp")
        payload = [record.as_dict() for record in self._records]
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self._metadata_path)
