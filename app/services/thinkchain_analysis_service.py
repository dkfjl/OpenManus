from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.llm import LLM
from app.logger import logger
from app.schema import Message


@dataclass
class LogPointers:
    chain_id: str
    session_id: str
    log_path: Path
    analysis_path: Path


class ThinkchainAnalysisService:
    def __init__(self) -> None:
        self.logs_dir: Path = config.workspace_root / "thinkchain_logs"
        self.uploads_dir: Path = config.workspace_root / "uploads"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    # ---------------
    # File helpers
    # ---------------
    def _resolve_latest_session(self, chain_id: str) -> Optional[Tuple[str, Path]]:
        """Return (session_id, log_path) for the latest log file for a chain.

        Strategy: pick most recently modified `*.jsonl` matching prefix.
        """
        prefix = f"{chain_id}__"
        cand = list(self.logs_dir.glob(f"{prefix}*.jsonl"))
        if not cand:
            return None
        cand.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        path = cand[0]
        name = path.name
        try:
            session_id = name.split("__", 1)[1].rsplit(".jsonl", 1)[0]
        except Exception:
            session_id = name
        return session_id, path

    def _pointers(self, chain_id: str, session_id: Optional[str]) -> Optional[LogPointers]:
        if not session_id:
            latest = self._resolve_latest_session(chain_id)
            if not latest:
                return None
            session_id, log_path = latest
        else:
            log_path = self.logs_dir / f"{chain_id}__{session_id}.jsonl"
            if not log_path.exists():
                return None
        analysis_path = log_path.with_suffix(".analysis.json")
        return LogPointers(chain_id, session_id, log_path, analysis_path)

    # ---------------
    # Log parsing / digest
    # ---------------
    def _load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        # tolerate partial lines
                        continue
        except Exception as e:
            logger.error(f"Failed to read log {path}: {e}")
        return records

    def _summarize_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute lightweight metrics and a compact digest structure."""
        steps: List[Dict[str, Any]] = []
        total_steps = 0
        q_scores: List[float] = []
        meta_topic = None
        meta_lang = None
        meta_task_type = None

        for rec in records:
            rtype = rec.get("type")
            if rtype == "session_start":
                md = rec.get("metadata") or {}
                meta_topic = md.get("topic", meta_topic)
                meta_lang = md.get("language", meta_lang)
                meta_task_type = md.get("task_type", meta_task_type)
            if rtype == "step":
                total_steps += 1
                qs = rec.get("quality_score")
                try:
                    if qs is not None:
                        q_scores.append(float(qs))
                except Exception:
                    pass
                step_num = rec.get("step")
                step_name = rec.get("step_name")
                status = rec.get("status")
                ctype = rec.get("content_type")
                content = rec.get("content") or {}
                norm = rec.get("normalized") or {}

                # Prefer normalized.meta.summary, fallback to content.summary/text
                summary = None
                try:
                    summary = (
                        ((norm.get("meta") or {}).get("summary"))
                        if isinstance(norm, dict)
                        else None
                    )
                except Exception:
                    summary = None
                if not summary and isinstance(content, dict):
                    cs = content.get("summary")
                    if isinstance(cs, str):
                        summary = cs
                if not summary and isinstance(content, str):
                    summary = content[:400]

                steps.append(
                    {
                        "step": step_num,
                        "name": step_name,
                        "status": status,
                        "type": ctype,
                        "summary": (summary or "").strip()[:800],
                    }
                )

        avg_quality = round(sum(q_scores) / max(1, len(q_scores)), 3) if q_scores else None
        return {
            "topic": meta_topic,
            "language": meta_lang,
            "task_type": meta_task_type,
            "total_steps": total_steps,
            "avg_quality": avg_quality,
            "steps": steps,
        }

    def _build_digest_text(self, summary: Dict[str, Any]) -> str:
        topic = summary.get("topic") or ""
        lang = summary.get("language") or "zh"
        hdr = (
            f"[ThinkChain Log Digest]\n"
            f"topic: {topic}\nlanguage: {lang}\n"
            f"total_steps: {summary.get('total_steps')}\n"
            f"avg_quality: {summary.get('avg_quality')}\n\n"
        )
        lines: List[str] = [hdr, "# Steps"]
        for s in summary.get("steps", [])[:60]:  # hard cap
            lines.append(
                f"- step={s.get('step')} name={s.get('name')} type={s.get('type')} status={s.get('status')}\n  summary: {s.get('summary')}"
            )
        return "\n".join(lines)

    # ---------------
    # Public API
    # ---------------
    def resolve_log(self, chain_id: str, session_id: Optional[str]) -> LogPointers:
        ptr = self._pointers(chain_id, session_id)
        if not ptr:
            raise FileNotFoundError("找不到对应的日志文件")
        return ptr

    def build_digest(self, chain_id: str, session_id: Optional[str] = None) -> Tuple[str, LogPointers, Dict[str, Any]]:
        ptr = self.resolve_log(chain_id, session_id)
        records = self._load_jsonl(ptr.log_path)
        summary = self._summarize_records(records)
        digest = self._build_digest_text(summary)
        return digest, ptr, summary

    async def generate_analysis(
        self,
        *,
        chain_id: str,
        session_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """LLM reads the digest and returns structured JSON analysis, persisted to disk."""
        digest, ptr, s = self.build_digest(chain_id, session_id)
        topic = s.get("topic") or ""
        lang = (language or s.get("language") or "zh").lower()

        llm = LLM()
        sys = (
            "你是资深分析师。\n"
            "请基于给定的 ThinkChain 日志摘要，输出结构化 JSON 分析，不要输出任何解释性文本。"
        )
        tmpl = f"""
任务主题: {topic}
目标语言: {('中文' if lang.startswith('zh') else 'English')}

日志摘要如下（仅供分析）：
---BEGIN DIGEST---
{digest}
---END DIGEST---

请仅输出一个 JSON，结构为：
{{
  "overview": "简要说明目标、过程与总体质量（不少于80字）",
  "key_findings": ["... 至少5条"],
  "risks": ["... 风险或问题，至少3条"],
  "recommendations": ["... 对策/后续动作，至少5条，尽量可执行"],
  "timeline": ["Step i - 名称：一句话描述..."],
  "metrics": {{"total_steps": {s.get('total_steps')}, "avg_quality": {json.dumps(s.get('avg_quality'))} }},
  "markdown": "将以上要点转写为可读的Markdown报告（>300字）"
}}
只返回 JSON。若无法解析，也请返回上述键的占位内容。
"""
        resp = await llm.ask(
            [Message.system_message(sys), Message.user_message(tmpl)],
            stream=False,
            temperature=0.2,
        )
        parsed: Dict[str, Any]
        try:
            txt = (resp or "").strip()
            if txt.startswith("{"):
                parsed = json.loads(txt)
            else:
                # best effort: find a JSON block
                import re

                m = re.search(r"(\{[\s\S]*\})", txt)
                parsed = json.loads(m.group(1)) if m else {"overview": txt}
        except Exception:
            parsed = {"overview": resp or ""}

        payload = {
            "chain_id": ptr.chain_id,
            "session_id": ptr.session_id,
            "log_path": str(ptr.log_path),
            "analysis": parsed,
        }

        try:
            ptr.analysis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Write analysis failed: {e}")
        return payload

    def load_cached_analysis(self, chain_id: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ptr = self._pointers(chain_id, session_id)
        if not ptr:
            return None
        if not ptr.analysis_path.exists():
            return None
        try:
            return json.loads(ptr.analysis_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create_digest_upload_file(self, chain_id: str, session_id: Optional[str] = None) -> str:
        """Persist digest as a pseudo uploaded file and return its UUID string."""
        digest, ptr, _ = self.build_digest(chain_id, session_id)
        file_uuid = str(uuid.uuid4())
        filename = f"{file_uuid}_thinkchain_{ptr.chain_id}_{ptr.session_id}_log.txt"
        path = self.uploads_dir / filename
        try:
            path.write_text(digest, encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to write digest upload file: {e}")
            raise
        return file_uuid


thinkchain_analysis_service = ThinkchainAnalysisService()

