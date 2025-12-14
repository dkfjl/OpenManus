"""
SQLite-backed storage for Prompt templates, drop-in replacement for PromptStorage.

Features:
- Personal prompts CRUD with optimistic locking (version).
- Read-only recommended templates (loaded from assets on first run).
- Optional auto-migration from file storage backend on first initialization.

Env controls (read by router; documented here for reference):
- PROMPT_STORAGE_BACKEND=sqlite|fs (router decides which storage to instantiate)
- PROMPT_SQLITE_PATH=/abs/or/relative/path/to/prompt_library.db (optional)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import config
from app.logger import logger
from app.services.prompt_storage import (
    PromptConflictError,
    PromptNotFoundError,
)


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class _DBPaths:
    db_file: Path
    project_root: Path
    assets_recommended: Path


class PromptSQLiteStorage:
    """SQLite storage implementing the same interface as PromptStorage."""

    def __init__(self, db_path: Optional[Path] = None, auto_migrate: bool = True) -> None:
        self.paths = self._resolve_paths(db_path)
        self.paths.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if auto_migrate:
            try:
                # Always sync recommended templates from assets (upsert). Optionally reset by env var.
                self._sync_recommended_prompts()
                self._migrate_personal_from_fs_if_empty()
            except Exception as e:
                logger.warning(f"[PromptSQLite] Auto-migration skipped with error: {e}")

    # -------------- public API (mirrors PromptStorage) --------------
    def create(
        self,
        *,
        name: str,
        prompt: str,
        owner_id: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        pid = uuid.uuid4().hex
        created_at = _now_iso()
        updated_at = created_at
        version = 1
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO personal_prompts(id, owner_id, name, description, version, created_at, updated_at, prompt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pid, owner_id, name, description, version, created_at, updated_at, prompt),
                )
            except sqlite3.IntegrityError as e:
                # likely uniqueness violation for (owner_id, name)
                raise e
        logger.info(f"[PromptSQLite] Created personal prompt: {pid}")
        return {
            "id": pid,
            "ownerId": owner_id,
            "name": name,
            "description": description,
            "version": version,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "prompt": prompt,
        }

    def update(
        self,
        *,
        prompt_id: str,
        owner_id: str,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, owner_id, name, description, version, created_at, updated_at FROM personal_prompts WHERE id=?",
                (prompt_id,),
            ).fetchone()
            if not row:
                raise PromptNotFoundError(f"Prompt {prompt_id} not found")
            if row[1] != owner_id:
                raise PermissionError(f"No permission to update prompt {prompt_id}")
            current_version = int(row[4])
            if version is not None and current_version != version:
                raise PromptConflictError(
                    f"Version conflict: expected {version}, got {current_version}"
                )
            new_name = name if name is not None else row[2]
            new_desc = description if description is not None else row[3]
            new_version = current_version + 1
            now = _now_iso()
            sets: List[str] = ["name=?", "description=?", "version=?", "updated_at=?"]
            params: List[Any] = [new_name, new_desc, new_version, now]
            if prompt is not None:
                sets.append("prompt=?")
                params.append(prompt)
            params.extend([prompt_id])
            conn.execute(
                f"UPDATE personal_prompts SET {', '.join(sets)} WHERE id=?",
                params,
            )
            # fetch final prompt content
            pr = conn.execute(
                "SELECT prompt FROM personal_prompts WHERE id=?",
                (prompt_id,),
            ).fetchone()
            final_prompt = pr[0] if pr else prompt
        logger.info(f"[PromptSQLite] Updated personal prompt: {prompt_id}")
        return {
            "id": prompt_id,
            "ownerId": owner_id,
            "name": new_name,
            "description": new_desc,
            "version": new_version,
            "createdAt": row[5],
            "updatedAt": now,
            "prompt": final_prompt,
        }

    def delete(self, *, prompt_id: str, owner_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT owner_id FROM personal_prompts WHERE id=?",
                (prompt_id,),
            ).fetchone()
            if not row:
                raise PromptNotFoundError(f"Prompt {prompt_id} not found")
            if row[0] != owner_id:
                raise PermissionError(f"No permission to delete prompt {prompt_id}")
            conn.execute("DELETE FROM personal_prompts WHERE id=?", (prompt_id,))
        logger.info(f"[PromptSQLite] Deleted personal prompt: {prompt_id}")
        return True

    def get(self, prompt_id: str, owner_id: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, owner_id, name, description, version, created_at, updated_at, prompt
                FROM personal_prompts WHERE id=?
                """,
                (prompt_id,),
            ).fetchone()
            if not row:
                raise PromptNotFoundError(f"Prompt {prompt_id} not found")
            if owner_id and row[1] != owner_id:
                raise PermissionError(f"No permission to access prompt {prompt_id}")
            return {
                "id": row[0],
                "ownerId": row[1],
                "name": row[2],
                "description": row[3],
                "version": row[4],
                "createdAt": row[5],
                "updatedAt": row[6],
                "prompt": row[7],
            }

    def list_personal(
        self,
        *,
        owner_id: str,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        where = ["owner_id=?"]
        params: List[Any] = [owner_id]
        if name_filter:
            where.append("LOWER(name) LIKE ?")
            params.append(f"%{name_filter.lower()}%")
        where_sql = " AND ".join(where)
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM personal_prompts WHERE {where_sql}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, owner_id, name, description, version, created_at, updated_at
                FROM personal_prompts
                WHERE {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, page_size, offset),
            ).fetchall()
        items = [
            {
                "id": r[0],
                "ownerId": r[1],
                "name": r[2],
                "description": r[3],
                "version": r[4],
                "createdAt": r[5],
                "updatedAt": r[6],
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "pageSize": page_size}

    def list_recommended(
        self,
        *,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        where = []
        params: List[Any] = []
        if name_filter:
            where.append("LOWER(name) LIKE ?")
            params.append(f"%{name_filter.lower()}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM recommended_prompts {where_sql}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, name, description, created_at, updated_at
                FROM recommended_prompts
                {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, page_size, offset),
            ).fetchall()
        items = [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "createdAt": r[3],
                "updatedAt": r[4],
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "pageSize": page_size}

    def get_recommended(self, prompt_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, description, prompt, created_at, updated_at
                FROM recommended_prompts WHERE id=?
                """,
                (prompt_id,),
            ).fetchone()
            if not row:
                raise PromptNotFoundError(f"Recommended prompt {prompt_id} not found")
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "prompt": row[3],
                "createdAt": row[4],
                "updatedAt": row[5],
            }

    def check_name_uniqueness(
        self, owner_id: str, name: str, exclude_id: Optional[str] = None
    ) -> bool:
        with self._connect() as conn:
            if exclude_id:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM personal_prompts
                    WHERE owner_id=? AND name=? AND id != ?
                    """,
                    (owner_id, name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM personal_prompts WHERE owner_id=? AND name=?",
                    (owner_id, name),
                ).fetchone()
        return (row[0] == 0)

    # -------------- internal helpers --------------
    def _resolve_paths(self, db_path: Optional[Path]) -> _DBPaths:
        project_root = config.root_path
        if db_path is None:
            db_dir = project_root / "db"
            db_dir.mkdir(exist_ok=True)
            db_file = db_dir / "prompt_library.db"
        else:
            db_file = Path(db_path)
        assets_recommended = project_root / "assets" / "prompts" / "recommended.json"
        return _DBPaths(db_file=db_file, project_root=project_root, assets_recommended=assets_recommended)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.paths.db_file)
        conn.row_factory = sqlite3.Row
        # Better defaults for concurrent reads
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_prompts (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    UNIQUE(owner_id, name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recommended_prompts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _sync_recommended_prompts(self) -> None:
        """Upsert recommended templates from assets. If env PROMPT_RECOMMENDED_SYNC=reset, clear table first."""
        if not self.paths.assets_recommended.exists():
            logger.warning(
                f"[PromptSQLite] No recommended.json found at {self.paths.assets_recommended}"
            )
            return
        try:
            data = json.loads(self.paths.assets_recommended.read_text("utf-8"))
        except Exception as e:
            logger.warning(f"[PromptSQLite] Failed to parse recommended.json: {e}")
            return

        strategy = (Path(".") and (uuid))  # dummy to silence unused import in static analyzers
        reset = False
        try:
            import os

            reset = (os.getenv("PROMPT_RECOMMENDED_SYNC", "").lower() == "reset")
        except Exception:
            reset = False

        now = _now_iso()
        upserted = 0
        with self._connect() as conn:
            if reset:
                conn.execute("DELETE FROM recommended_prompts")
                logger.info("[PromptSQLite] Reset recommended_prompts table before import")
            for item in data:
                pid = item.get("id") or uuid.uuid4().hex
                name = item.get("name") or ""
                desc = item.get("description")
                prompt = item.get("prompt") or ""
                # SQLite upsert on primary key
                conn.execute(
                    """
                    INSERT INTO recommended_prompts(id, name, description, prompt, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        description=excluded.description,
                        prompt=excluded.prompt,
                        updated_at=excluded.updated_at
                    """,
                    (pid, name, desc, prompt, now, now),
                )
                upserted += 1
        logger.info(f"[PromptSQLite] Synced {upserted} recommended prompts from assets")

    def _migrate_personal_from_fs_if_empty(self) -> None:
        with self._connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM personal_prompts").fetchone()[0]
            if cnt > 0:
                return
        # Try to read from file-based storage
        try:
            from app.services.prompt_storage import PromptStorage

            fs = PromptStorage()
            # Access internal index (migration context)
            index = fs._load_index()
            prompts = index.get("prompts", {})
            if not prompts:
                return
            inserted = 0
            with self._connect() as conn:
                for pid, meta in prompts.items():
                    try:
                        content = fs._load_prompt_content(pid)
                        if content is None:
                            continue
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO personal_prompts
                            (id, owner_id, name, description, version, created_at, updated_at, prompt)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                pid,
                                meta.get("ownerId") or meta.get("owner_id") or "",
                                meta.get("name") or "",
                                meta.get("description"),
                                int(meta.get("version", 1)),
                                meta.get("createdAt") or _now_iso(),
                                meta.get("updatedAt") or _now_iso(),
                                content,
                            ),
                        )
                        inserted += 1
                    except Exception as e:
                        logger.warning(f"[PromptSQLite] Skip migrating prompt {pid}: {e}")
            logger.info(f"[PromptSQLite] Migrated {inserted} personal prompts from file storage")
        except Exception as e:
            logger.info(f"[PromptSQLite] No file storage to migrate or migration failed: {e}")
