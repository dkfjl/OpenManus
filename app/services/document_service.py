import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine, List, Optional

from pydantic import BaseModel, Field

from app.config import config
from app.llm import LLM
from app.logger import logger
from app.schema import Message
from app.tool.word_document import WordDocumentTool


class OutlineSection(BaseModel):
    heading: str
    summary: str = ""
    subtopics: List[str] = Field(default_factory=list)


class DocumentPlan(BaseModel):
    title: str
    sections: List[OutlineSection]


class DocumentGenerator:
    def __init__(self):
        self.settings = config.document_config
        self.llm = LLM()
        self.word_tool = WordDocumentTool()
        self.metadata_dir = config.workspace_root / ".structured_docs"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    async def create_task(
        self,
        topic: str,
        filepath: Optional[str] = None,
        language: Optional[str] = None,
        reference_content: Optional[str] = None,
    ) -> dict:
        language = language or self.settings.default_language
        doc_path = self._resolve_path(filepath or self._default_filename(topic))
        plan = await self._build_outline(topic=topic, language=language)
        await self._write_table_of_contents(
            topic=topic, plan=plan, doc_path=doc_path, language=language
        )
        metadata = self._initialize_metadata(
            topic=topic,
            language=language,
            plan=plan,
            doc_path=doc_path,
            reference_content=reference_content,
        )
        self._save_metadata(metadata)
        logger.info(
            "Structured document task %s created with %d sections",
            metadata["task_id"],
            len(plan.sections),
        )
        return metadata

    async def run_task(self, task_id: str) -> dict:
        metadata = self._load_metadata(task_id)
        if not metadata:
            raise ValueError(f"未找到任务 {task_id}")

        if metadata.get("status") == "completed":
            logger.info("Task %s already completed", task_id)
            return metadata

        doc_path = Path(metadata["filepath"])
        doc_path.parent.mkdir(parents=True, exist_ok=True)

        metadata["status"] = "writing"
        metadata.pop("error", None)
        self._save_metadata(metadata)

        sections = metadata.get("sections", [])
        total_sections = len(sections)
        if total_sections == 0:
            metadata["status"] = "failed"
            metadata["error"] = "任务缺少章节信息"
            self._save_metadata(metadata)
            raise ValueError("文档任务缺少章节信息")

        start_index = metadata.get("next_section_index", 0)
        language = metadata.get("language", self.settings.default_language)
        topic = metadata.get("topic", "")
        reference_material = metadata.get("reference_content", "")

        try:
            for idx in range(start_index, total_sections):
                section_data = sections[idx]
                section = OutlineSection(
                    heading=section_data.get("heading", f"部分 {idx + 1}"),
                    summary=section_data.get("summary", ""),
                    subtopics=section_data.get("subtopics", []),
                )

                content = await self._compose_section_content(
                    topic=topic,
                    section=section,
                    language=language,
                    section_index=idx + 1,
                    total_sections=total_sections,
                    reference_material=reference_material,
                )

                await self.word_tool.execute(
                    filepath=str(doc_path),
                    append=True,
                    sections=[
                        {
                            "heading": section.heading,
                            "content": content,
                        }
                    ],
                )

                metadata["sections"][idx]["status"] = "completed"
                metadata["sections"][idx]["latest_content_length"] = len(
                    content.split()
                )
                metadata["latest_completed_heading"] = section.heading
                metadata["next_section_index"] = idx + 1
                self._save_metadata(metadata)

            metadata["status"] = "completed"
            self._save_metadata(metadata)
            logger.info("Structured document task %s completed", task_id)
        except Exception as exc:
            metadata["status"] = "failed"
            metadata["error"] = str(exc)
            self._save_metadata(metadata)
            logger.exception("Structured document task %s failed", task_id)
            raise

        return metadata

    def get_task(self, task_id: str) -> dict:
        metadata = self._load_metadata(task_id)
        if not metadata:
            raise FileNotFoundError(f"任务 {task_id} 不存在")
        progress = self._build_progress(metadata)
        return self._build_response(metadata, progress)

    async def _build_outline(self, topic: str, language: str) -> DocumentPlan:
        system_text = (
            "You are an expert planning assistant. "
            "Always respond with valid JSON describing a document outline."
        )
        sections_target = self.settings.outline_sections
        user_text = (
            f"为主题《{topic}》设计一份{language}报告的大纲。"
            f"需要 4~{sections_target} 个主要章节，每章包含一句话总结和 2-4 个关键要点。"
            "请严格按照以下 JSON 结构输出：\n"
            '{'
            '"title": "报告标题",'
            '"sections": ['
            '{"heading": "章节名称", "summary": "一句话定位", "subtopics": ["要点1","要点2"]}'
            ']'
            "}"
        )

        response = await self.llm.ask(
            [Message.user_message(user_text)],
            system_msgs=[Message.system_message(system_text)],
            stream=False,
            temperature=0.2,
        )
        plan_dict = self._parse_json_response(response)
        title = plan_dict.get("title") or f"{topic}报告"
        sections_raw = plan_dict.get("sections") or []
        sections = [
            OutlineSection(
                heading=section.get("heading") or section.get("title") or f"部分 {idx+1}",
                summary=section.get("summary") or section.get("description") or "",
                subtopics=section.get("subtopics")
                or section.get("bullets")
                or section.get("key_points")
                or [],
            )
            for idx, section in enumerate(sections_raw)
        ]
        if not sections:
            raise ValueError("生成大纲失败：未返回任何章节。")

        return DocumentPlan(title=title, sections=sections)

    async def _write_table_of_contents(
        self, topic: str, plan: DocumentPlan, doc_path: Path, language: str
    ):
        toc_title = self.settings.table_of_contents_title or "目录"
        lines = [toc_title, ""]
        for idx, section in enumerate(plan.sections, start=1):
            descriptor = section.summary.strip()
            line = f"{idx}. {section.heading}"
            if descriptor:
                line += f" —— {descriptor}"
            lines.append(line)

        body_text = "\n".join(lines)
        await self.word_tool.execute(
            filepath=str(doc_path),
            document_title=plan.title or f"{topic}报告",
            body=body_text,
            append=False,
        )

    async def _compose_section_content(
        self,
        topic: str,
        section: OutlineSection,
        language: str,
        section_index: int,
        total_sections: int,
        reference_material: str = "",
    ) -> str:
        min_words = self.settings.min_section_words
        key_points = "、".join(section.subtopics) if section.subtopics else ""

        system_text = (
            "You are a senior economic planning writer. "
            f"Write in fluent {language}, providing analysis, data references, and actionable suggestions. "
            f"Each section must contain at least {min_words} words, using multiple paragraphs."
        )
        reference_excerpt = self._prepare_reference_excerpt(reference_material)

        user_text = (
            f"总主题：{topic}\n"
            f"当前章节：{section.heading} （第 {section_index} / {total_sections} 部分）\n"
            f"章节定位：{section.summary or '无'}\n"
            f"关键要点：{key_points or '自行补充'}\n"
            "请输出多段落正文，可在结尾给出条列建议。"
        )

        if reference_excerpt:
            user_text += "\n\n以下是上传文档的关键信息，请优先引用并补充：\n"
            user_text += reference_excerpt

        content = await self.llm.ask(
            [Message.user_message(user_text)],
            system_msgs=[Message.system_message(system_text)],
            stream=False,
            temperature=0.35,
        )
        return content.strip()

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _default_filename(topic: str) -> str:
        sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "document"
        return f"{sanitized}.docx"

    @staticmethod
    def _resolve_path(filepath: str) -> Path:
        base = config.workspace_root
        candidate = Path(filepath)
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.suffix.lower() != ".docx":
            candidate = candidate.with_suffix(".docx")
        return candidate

    def _metadata_path(self, task_id: str) -> Path:
        return self.metadata_dir / f"{task_id}.json"

    def _load_metadata(self, task_id: str) -> Optional[dict]:
        meta_path = self._metadata_path(task_id)
        if not meta_path.exists():
            return None
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_metadata(self, data: dict):
        if "task_id" not in data:
            raise ValueError("metadata 缺少 task_id")
        meta_path = self._metadata_path(data["task_id"])
        data.setdefault("created_at", self._now())
        data["updated_at"] = self._now()
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _initialize_metadata(
        self,
        topic: str,
        language: str,
        plan: DocumentPlan,
        doc_path: Path,
        reference_content: Optional[str] = None,
    ) -> dict:
        task_id = uuid.uuid4().hex
        now = self._now()
        return {
            "version": 1,
            "task_id": task_id,
            "topic": topic,
            "language": language,
            "title": plan.title,
            "filepath": str(doc_path),
            "reference_content": reference_content or "",
            "sections": [
                {
                    "heading": section.heading,
                    "summary": section.summary,
                    "subtopics": section.subtopics,
                    "status": "pending",
                }
                for section in plan.sections
            ],
            "next_section_index": 0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }

    def _prepare_reference_excerpt(self, reference_material: str) -> str:
        text = (reference_material or "").strip()
        if not text:
            return ""
        max_chars = getattr(self.settings, "max_reference_chars", 6000)
        if len(text) <= max_chars:
            return text
        logger.warning(
            "Reference material length %d exceeds limit %d, truncating",
            len(text),
            max_chars,
        )
        return text[:max_chars]

    def _build_progress(self, metadata: dict) -> dict:
        sections = metadata.get("sections", [])
        total = len(sections)
        completed = sum(1 for section in sections if section.get("status") == "completed")
        next_index = metadata.get("next_section_index", completed)
        next_heading = (
            sections[next_index]["heading"] if 0 <= next_index < total else None
        )
        return {
            "total_sections": total,
            "completed_sections": completed,
            "next_section_index": next_index if next_heading is not None else None,
            "next_section_heading": next_heading,
            "latest_completed_heading": metadata.get("latest_completed_heading"),
        }

    def _build_response(self, metadata: dict, progress: dict) -> dict:
        return {
            "task_id": metadata.get("task_id"),
            "status": metadata.get("status", "pending"),
            "filepath": metadata.get("filepath"),
            "title": metadata.get("title") or "",
            "sections": [section.get("heading", "") for section in metadata.get("sections", [])],
            "progress": progress,
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "error": metadata.get("error"),
        }

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat() + "Z"


RUNNING_TASKS: set[asyncio.Task] = set()


def _schedule_background(coro: Coroutine[Any, Any, Any]):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)

    def _cleanup(t: asyncio.Task):
        RUNNING_TASKS.discard(t)

    task.add_done_callback(_cleanup)
    return task


async def create_structured_document_task(
    topic: str,
    filepath: Optional[str] = None,
    language: Optional[str] = None,
    reference_content: Optional[str] = None,
) -> dict:
    generator = DocumentGenerator()
    metadata = await generator.create_task(
        topic=topic,
        filepath=filepath,
        language=language,
        reference_content=reference_content,
    )
    progress = generator._build_progress(metadata)
    response = generator._build_response(metadata, progress)
    _schedule_background(generator.run_task(metadata["task_id"]))
    return response


async def get_structured_document_task(task_id: str) -> dict:
    generator = DocumentGenerator()
    return generator.get_task(task_id)
