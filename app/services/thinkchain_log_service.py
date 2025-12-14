from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from app.config import config


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


class ThinkchainLogService:
    """Lightweight JSONL logger for ThinkChain generation steps.

    Each ThinkChain execution session appends to a workspace file:
      workspace/thinkchain_logs/{chain_id}__{session_id}.jsonl
    Records are line-delimited JSON for easy tail/ingestion.
    """

    def __init__(self) -> None:
        self.base_dir: Path = config.workspace_root / "thinkchain_logs"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[Path, Lock] = {}

    def _get_path(self, chain_id: str, session_id: str) -> Path:
        filename = f"{chain_id}__{session_id}.jsonl"
        return self.base_dir / filename

    def _get_lock(self, path: Path) -> Lock:
        if path not in self._locks:
            self._locks[path] = Lock()
        return self._locks[path]

    def _append(self, path: Path, payload: Dict[str, Any]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False)
        lock = self._get_lock(path)
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(serialized + "\n")

    # Public API
    def log_session_start(
        self,
        *,
        chain_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        path = self._get_path(chain_id, session_id)
        record = {
            "type": "session_start",
            "timestamp": _utc_now(),
            "chain_id": chain_id,
            "session_id": session_id,
            "metadata": metadata or {},
        }
        self._append(path, record)
        return path

    def log_step(
        self,
        *,
        chain_id: str,
        session_id: str,
        step_result: Dict[str, Any],
        normalized: Optional[Dict[str, Any]] = None,
    ) -> None:
        path = self._get_path(chain_id, session_id)
        payload = {
            "type": "step",
            "timestamp": _utc_now(),
            "chain_id": chain_id,
            "session_id": session_id,
            "step": step_result.get("step"),
            "step_name": step_result.get("step_name"),
            "status": step_result.get("status"),
            "quality_score": step_result.get("quality_score"),
            "content_type": step_result.get("content_type"),
            "execution_time": step_result.get("execution_time"),
            "content": step_result.get("content"),
        }
        if normalized is not None:
            payload["normalized"] = normalized
        self._append(path, payload)

    def log_session_end(
        self,
        *,
        chain_id: str,
        session_id: str,
        details: Optional[Dict[str, Any]] = None,
        status: str = "completed",
    ) -> None:
        path = self._get_path(chain_id, session_id)
        record = {
            "type": "session_end",
            "timestamp": _utc_now(),
            "chain_id": chain_id,
            "session_id": session_id,
            "status": status,
            "details": details or {},
        }
        self._append(path, record)

    def log_event(
        self,
        *,
        chain_id: str,
        session_id: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a generic event record into the JSONL log."""
        path = self._get_path(chain_id, session_id)
        record = {
            "type": "event",
            "timestamp": _utc_now(),
            "chain_id": chain_id,
            "session_id": session_id,
            "event": event,
            "data": data or {},
        }
        self._append(path, record)

    # -------- Read helpers --------
    def _path_for(self, chain_id: str, session_id: str) -> Path:
        return self._get_path(chain_id, session_id)

    def read_jsonl(self, chain_id: str, session_id: str) -> List[Dict[str, Any]]:
        path = self._path_for(chain_id, session_id)
        recs: List[Dict[str, Any]] = []
        if not path.exists():
            return recs
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            return []
        return recs

    def find_last_event(
        self, chain_id: str, session_id: str, event_names: List[str]
    ) -> Optional[Dict[str, Any]]:
        names = set(event_names)
        for rec in reversed(self.read_jsonl(chain_id, session_id)):
            if rec.get("type") == "event" and rec.get("event") in names:
                return rec
        return None


thinkchain_log_service = ThinkchainLogService()
