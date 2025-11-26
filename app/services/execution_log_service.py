import json
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from app.config import config


execution_log_context: ContextVar[Optional["ExecutionLogSession"]] = ContextVar(
    "execution_log_context", default=None
)


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


class ExecutionLogSession:
    """Encapsulates a single execution log stored as JSONL under the workspace."""

    def __init__(
        self,
        log_dir: Path,
        flow_type: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        attach: bool = False,
    ):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or uuid.uuid4().hex
        self.file_path = self.log_dir / f"{self.session_id}.jsonl"
        self.flow_type = flow_type or "unknown"
        self.metadata = metadata or {}
        self._token = None
        self._lock = Lock()
        self._started = False

        if attach:
            # Try to hydrate flow type / metadata from disk for attached sessions
            self._load_metadata_from_file()
        else:
            self._write_record(
                {
                    "type": "session_start",
                    "session_id": self.session_id,
                    "flow_type": self.flow_type,
                    "metadata": self.metadata,
                    "timestamp": _utc_now(),
                }
            )
            self._started = True

    def activate(self):
        self._token = execution_log_context.set(self)
        return self

    def deactivate(self):
        if self._token is not None:
            execution_log_context.reset(self._token)
            self._token = None

    def log_event(
        self,
        category: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ):
        record = {
            "type": "event",
            "session_id": self.session_id,
            "timestamp": _utc_now(),
            "category": category,
            "message": message,
            "data": data or {},
        }
        self._write_record(record)

    def close(self, status: str = "completed", details: Optional[Dict[str, Any]] = None):
        record = {
            "type": "session_end",
            "session_id": self.session_id,
            "timestamp": _utc_now(),
            "status": status,
            "details": details or {},
        }
        self._write_record(record)
        self.deactivate()

    def _write_record(self, payload: Dict[str, Any]):
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(serialized + "\n")

    def _load_metadata_from_file(self):
        if not self.file_path.exists():
            return
        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return
                header = json.loads(first_line)
                if header.get("flow_type"):
                    self.flow_type = header["flow_type"]
                if header.get("metadata"):
                    self.metadata = header["metadata"]
        except Exception:
            # Fallback to previously provided metadata
            pass


class ExecutionLogService:
    def __init__(self):
        self.log_dir = config.workspace_root / "execution_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def start_session(
        self,
        flow_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionLogSession:
        session = ExecutionLogSession(self.log_dir, flow_type, metadata)
        session.activate()
        return session

    def attach_session(self, session_id: str) -> Optional[ExecutionLogSession]:
        if not session_id:
            return None
        path = self.log_dir / f"{session_id}.jsonl"
        if not path.exists():
            return None
        session = ExecutionLogSession(
            self.log_dir, flow_type=None, metadata=None, session_id=session_id, attach=True
        )
        session.activate()
        return session

    def get_current_session(self) -> Optional[ExecutionLogSession]:
        return execution_log_context.get()

    def log_event(
        self,
        category: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ):
        session = self.get_current_session()
        if not session:
            return
        session.log_event(category, message, data)

    def close_current_session(self, status: str = "completed", details: Optional[Dict[str, Any]] = None):
        session = self.get_current_session()
        if session:
            session.close(status=status, details=details)


execution_log_service = ExecutionLogService()


def start_execution_log(flow_type: str, metadata: Optional[Dict[str, Any]] = None) -> ExecutionLogSession:
    return execution_log_service.start_session(flow_type=flow_type, metadata=metadata)


def attach_execution_log(session_id: str) -> Optional[ExecutionLogSession]:
    return execution_log_service.attach_session(session_id)


def log_execution_event(category: str, message: str, data: Optional[Dict[str, Any]] = None):
    execution_log_service.log_event(category=category, message=message, data=data)


def end_execution_log(status: str = "completed", details: Optional[Dict[str, Any]] = None):
    execution_log_service.close_current_session(status=status, details=details)


def current_execution_log_id() -> Optional[str]:
    session = execution_log_service.get_current_session()
    return session.session_id if session else None
