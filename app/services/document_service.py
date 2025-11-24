import json
import re
from pathlib import Path
from typing import List, Optional

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

    async def generate(
        self,
        topic: str,
        filepath: Optional[str] = None,
        language: Optional[str] = None,
    ) -> dict:
        language = language or self.settings.default_language
        plan = await self._build_outline(topic=topic, language=language)
        doc_path = self._resolve_path(filepath or self._default_filename(topic))

        await self._write_table_of_contents(
            topic=topic, plan=plan, doc_path=doc_path, language=language
        )

        for index, section in enumerate(plan.sections, start=1):
            content = await self._compose_section_content(
                topic=topic,
                section=section,
                language=language,
                section_index=index,
                total_sections=len(plan.sections),
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

        return {
            "filepath": str(doc_path),
            "title": plan.title,
            "sections": [section.heading for section in plan.sections],
        }

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
    ) -> str:
        min_words = self.settings.min_section_words
        key_points = "、".join(section.subtopics) if section.subtopics else ""

        system_text = (
            "You are a senior economic planning writer. "
            f"Write in fluent {language}, providing analysis, data references, and actionable suggestions. "
            f"Each section must contain at least {min_words} words, using multiple paragraphs."
        )
        user_text = (
            f"总主题：{topic}\n"
            f"当前章节：{section.heading} （第 {section_index} / {total_sections} 部分）\n"
            f"章节定位：{section.summary or '无'}\n"
            f"关键要点：{key_points or '自行补充'}\n"
            "请输出多段落正文，可在结尾给出条列建议。"
        )

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


async def generate_structured_document(
    topic: str,
    filepath: Optional[str] = None,
    language: Optional[str] = None,
) -> dict:
    generator = DocumentGenerator()
    result = await generator.generate(topic=topic, filepath=filepath, language=language)
    logger.info(
        "Structured document generated at %s with %d sections",
        result["filepath"],
        len(result["sections"]),
    )
    return result
