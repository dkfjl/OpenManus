from __future__ import annotations

from typing import Optional

from app.config import config
from app.llm import LLM
from app.logger import logger
from app.schema import Message


class DocumentSummaryService:
    """Use the LLM to produce concise summaries of parsed upload content."""

    def __init__(self, max_chars: int = 8000):
        self.llm = LLM()
        self.max_chars = max_chars

    async def summarize(self, content: str, language: Optional[str] = None) -> str:
        text = (content or "").strip()
        if not text:
            return ""

        prepared = self._trim(text)
        target_language = language or config.document_config.default_language

        system_prompt = (
            "You are a senior analyst who condenses supporting materials into"
            " faithful summaries. Capture the main thesis, key arguments,"
            " quantitative facts, and recommended actions."
        )
        user_prompt = (
            f"请使用{target_language}总结以下资料，输出 3-5 条要点，每条不超过两句话，"
            "可以补充关键数据或结论。若资料存在多主题，请按主题分组。\n\n"
            f"资料内容：\n{prepared}"
        )

        summary = await self.llm.ask(
            [Message.user_message(user_prompt)],
            system_msgs=[Message.system_message(system_prompt)],
            stream=False,
            temperature=0.2,
        )
        result = summary.strip()
        logger.info("Generated upload summary (%d chars)", len(result))
        return result

    def _trim(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        logger.warning(
            "Upload content exceeds %d chars; truncating for summarization", self.max_chars
        )
        return text[: self.max_chars]
