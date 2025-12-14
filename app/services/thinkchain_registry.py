"""
In-memory registry for ThinkChain overviews (planning chains).
Stores chain steps and metadata for a limited time (TTL) for execution use.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.logger import logger


@dataclass
class ChainRecord:
    chain_id: str
    topic: str
    task_type: str
    language: str
    steps: List[Dict[str, Any]]
    reference_sources: List[str] = field(default_factory=list)
    reference_file_uuids: List[str] = field(default_factory=list)  # 新增：保存文件UUID
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ThinkchainRegistry:
    """Lightweight in-memory chain registry with TTL cleanup."""

    def __init__(self) -> None:
        self._chains: Dict[str, ChainRecord] = {}
        self._lock = asyncio.Lock()
        self.ttl: timedelta = timedelta(hours=1)

    async def create_chain(
        self,
        *,
        topic: str,
        task_type: str,
        language: str,
        steps: List[Dict[str, Any]],
        reference_sources: Optional[List[str]] = None,
        reference_file_uuids: Optional[List[str]] = None,
    ) -> str:
        await self.cleanup()
        chain_id = f"chain_{uuid.uuid4().hex[:12]}"
        record = ChainRecord(
            chain_id=chain_id,
            topic=topic,
            task_type=task_type,
            language=language,
            steps=steps,
            reference_sources=reference_sources or [],
            reference_file_uuids=reference_file_uuids or [],
        )
        async with self._lock:
            self._chains[chain_id] = record
        logger.info(f"Created chain {chain_id}: topic={topic[:40]} type={task_type}")
        return chain_id

    async def get_chain(self, chain_id: str) -> Optional[ChainRecord]:
        await self.cleanup()
        async with self._lock:
            rec = self._chains.get(chain_id)
            if rec:
                rec.updated_at = datetime.now().isoformat()
            return rec

    async def delete_chain(self, chain_id: str) -> bool:
        async with self._lock:
            if chain_id in self._chains:
                del self._chains[chain_id]
                return True
            return False

    async def cleanup(self) -> int:
        now = datetime.now()
        to_delete: List[str] = []
        async with self._lock:
            for cid, rec in self._chains.items():
                ts = datetime.fromisoformat(rec.updated_at)
                if now - ts > self.ttl:
                    to_delete.append(cid)
            for cid in to_delete:
                try:
                    del self._chains[cid]
                except Exception:
                    pass
        if to_delete:
            logger.info(f"Cleaned {len(to_delete)} expired chains from registry")
        return len(to_delete)


# Global instance
thinkchain_registry = ThinkchainRegistry()
