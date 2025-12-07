from typing import Optional, List

from pydantic import Field, model_validator

from app.agent.base import BaseAgent
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.schema import TOOL_CHOICE_TYPE, AgentState, ToolChoice
from app.tool import (CreateChatCompletion, ToolCollection, WebSearch,
                      WordDocumentTool)


class ReportResearchAgent(ToolCallAgent):
    """Research agent for reasoning, synthesis and drafting bullet findings."""

    name: str = "research"
    description: str = "Research and synthesis agent for planning and content drafting"

    # Keep tools lightweight; no Terminate to avoid finishing the whole flow
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(CreateChatCompletion(), WebSearch())
    )

    max_steps: int = 1
    next_step_prompt: str = (
        "根据当前任务，必要时调用 web_search 检索，并用简洁要点总结发现。"
        "不要写入文档，不要调用 terminate。"
    )


class ReportSearchAgent(ToolCallAgent):
    """Focused web search agent to gather facts and sources."""

    name: str = "search"
    description: str = "Web search specialist that returns concise findings with sources"

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(WebSearch())
    )

    max_steps: int = 1
    next_step_prompt: str = (
        "使用 web_search 工具检索与任务高度相关的信息，输出3-5条事实及来源。"
        "不要写入文档，不要调用 terminate。"
    )


class ReportWriterAgent(ToolCallAgent):
    """Writer agent that composes the final .docx report via WordDocumentTool."""

    name: str = "writer"
    description: str = "Writer that compiles sections and calls word_document to save .docx"

    language: str = Field(default="zh")
    filepath: str = Field(..., description="Target .docx path")
    title: str = Field(default="自动生成报告")
    next_step_prompt: str = Field(default="")
    toc_body: Optional[str] = Field(default=None, description="Text lines for the TOC section")
    reference_text: Optional[str] = Field(default=None, description="Raw reference text from uploads")
    reference_summary: Optional[str] = Field(default=None, description="Summarized reference material")
    chapter_info: Optional[dict] = Field(default=None, description="Chapter-specific information for targeted writing")

    # Only expose the writer tool to force writing action
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(WordDocumentTool())
    )
    # Finish after first document write to avoid multiple versions
    special_tool_names: list[str] = Field(
        default_factory=lambda: [WordDocumentTool().name]
    )

    # Require a tool call; avoid free-form text that won't save the doc
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.REQUIRED  # type: ignore

    max_steps: int = 2

    @model_validator(mode="after")
    def _prepare_writer_prompt(self) -> "ReportWriterAgent":
        target_words = min(getattr(config.document_config, "min_section_words", 1200), 1200)

        # Determine writing mode based on chapter_info
        if self.chapter_info:
            if self.chapter_info.get("is_first_chapter", False):
                # First chapter: include TOC and write initial content
                append_mode = "false"
                content_instruction = (
                    f"作为报告的开篇章节，请先写入目录结构作为第一部分，"
                    f"然后详细撰写第{self.chapter_info.get('chapter_number', 1)}章'{self.chapter_info.get('chapter_title', '')}'的内容。"
                    f"目录内容：\n{self.toc_body or '无目录'}\n\n"
                    f"章节要求：\n"
                    f"- 章节标题：第{self.chapter_info.get('chapter_number', 1)}章 {self.chapter_info.get('chapter_title', '')}\n"
                    f"- 内容长度：不少于{target_words}字，至少3个自然段\n"
                    f"- 逻辑清晰，层次分明\n"
                    f"- 涵盖以下小节：{', '.join(self.chapter_info.get('sections', []))}\n"
                )
            elif self.chapter_info.get("is_overview", False):
                # Overview section: summarize uploaded content
                append_mode = "true"
                content_instruction = (
                    f"撰写参考内容概述部分。请基于以下参考材料摘要：\n{self.reference_summary or '无参考材料'}\n\n"
                    f"要求：\n"
                    f"- 章节标题：参考内容概述\n"
                    f"- 内容长度：不少于{target_words//2}字\n"
                    f"- 重点提炼上传文件的关键信息\n"
                    f"- 突出与报告主题的相关性\n"
                    f"- 使用append=true追加到文档末尾"
                )
            elif self.chapter_info.get("is_references", False):
                # References section: compile all references
                append_mode = "true"
                content_instruction = (
                    f"撰写参考资料附录。要求：\n"
                    f"- 章节标题：参考文献\n"
                    f"- 收集所有研究过程中提到的引用来源\n"
                    f"- 包含上传文件名（如果有）\n"
                    f"- 使用标准学术引用格式\n"
                    f"- 使用append=true追加到文档末尾"
                )
            else:
                # Regular chapter: write chapter content and append
                append_mode = "true"
                content_instruction = (
                    f"撰写第{self.chapter_info.get('chapter_number', 1)}章'{self.chapter_info.get('chapter_title', '')}'的内容。要求：\n"
                    f"- 章节标题：第{self.chapter_info.get('chapter_number', 1)}章 {self.chapter_info.get('chapter_title', '')}\n"
                    f"- 内容长度：不少于{target_words}字，至少3个自然段\n"
                    f"- 逻辑清晰，层次分明\n"
                    f"- 涵盖以下小节：{', '.join(self.chapter_info.get('sections', []))}\n"
                    f"- 与前面章节保持连贯性\n"
                    f"- 使用append=true追加到文档末尾"
                )
        else:
            # Default behavior for backward compatibility
            append_mode = "false"
            content_instruction = (
                f"撰写完整报告。使用 `word_document` 工具一次性写入完整文档（append={append_mode}）："
                f"参数包含 `filepath`: '{self.filepath}', `document_title`: '{self.title}', "
                f"`sections`: [{{heading, level(1-3), content}}...]。"
                f"严格要求：每个章节的 content 不少于 {target_words} 字，至少 3 个自然段。"
                "此外，请将下面提供的目录文本作为第一节：heading='内容目录'，content 为原样多行文本：\n" +
                (self.toc_body or "(无目录文本)" ) + "\n"
                + ("可参考以下'参考材料摘要'，优先吸收关键信息用于写作：\n" + self.reference_summary + "\n" if self.reference_summary else "")
            )

        self.next_step_prompt = (
            f"你是专业的报告撰稿人。{content_instruction}\n\n"
            f"写作指令：\n"
            f"- 输出语言：{self.language}\n"
            f"- 文件路径：{self.filepath}\n"
            f"- 使用append={append_mode}模式\n"
            f"- 确保内容专业、准确、逻辑清晰\n"
            f"- 完成后只进行一次工具调用，不要多次写入\n\n"
            f"现在开始写作并调用word_document工具。"
        )
        return self


class ChapterContentAgent(BaseAgent):
    """章节内容生成Agent，专门用于生成单个章节的详细内容"""

    name: str = "chapter_writer"
    description: str = "Chapter content generator that creates detailed content for a specific chapter"

    language: str = Field(default="zh")
    topic: str = Field(..., description="报告主题")
    chapter_number: int = Field(..., description="章节编号")
    chapter_title: str = Field(..., description="章节标题")
    sections: list[str] = Field(default_factory=list, description="章节下的小节列表")
    reference_summary: Optional[str] = Field(default=None, description="参考资料摘要")
    previous_chapters: Optional[str] = Field(default=None, description="前面章节的内容摘要")

    # Internal state for chapter generation
    _search_results: Optional[str] = None
    _content_generated: bool = False

    # Set max_steps to allow both search and content generation
    max_steps: int = 3

    async def step(self) -> str:
        """Execute single step: search first, then generate content"""
        try:
            # Step 1: Search for information
            if self._search_results is None:
                search_prompt = (
                    f"请为报告'{self.topic}'的第{self.chapter_number}章'{self.chapter_title}'搜索相关信息。"
                    f"章节包含的小节：{', '.join(self.sections) if self.sections else '无特定小节'}。"
                    f"请搜索最新的数据、案例、统计信息等专业资料。"
                )

                web_search_tool = WebSearch()
                try:
                    search_results = await web_search_tool.execute(query=search_prompt)
                    self._search_results = search_results
                    return f"已搜索{self.chapter_title}相关信息"
                except Exception:
                    # Fail open: continue to content generation without search results
                    self._search_results = ""
                    return f"搜索{self.chapter_title}相关信息失败，继续撰写内容"

            # Step 2: Generate content
            elif not self._content_generated:
                target_words = min(getattr(config.document_config, "min_section_words", 1200), 1200)
                sections_text = "\n".join([f"- {section}" for section in self.sections]) if self.sections else "无特定小节"

                content_prompt = (
                    f"你是专业的内容撰稿人，负责撰写报告的第{self.chapter_number}章。\n\n"
                    f"报告主题：{self.topic}\n"
                    f"当前章节：第{self.chapter_number}章 {self.chapter_title}\n"
                    f"小节内容：{sections_text}\n"
                    f"参考资料摘要：{self.reference_summary or '无'}\n"
                    f"前面章节内容：{self.previous_chapters or '无（这是第一章）'}\n"
                    f"搜索结果：{self._search_results if self._search_results else '无搜索结果'}\n\n"
                    f"写作要求：\n"
                    f"1. 内容长度：不少于{target_words}字，至少3个自然段\n"
                    f"2. 专业准确：内容要专业、准确、有深度，基于真实数据\n"
                    f"3. 逻辑清晰：结构清晰，层次分明，论证有力\n"
                    f"4. 连贯性：与前面章节保持逻辑连贯\n"
                    f"5. 覆盖完整：涵盖列出的所有小节内容\n"
                    f"6. 输出语言：{self.language}\n\n"
                    f"重要：只输出第{self.chapter_number}章的正文内容，不要包含章节标题、步骤说明或任何系统信息。"
                    f"内容应该直接从正文开始，格式为纯文本段落，不要任何前缀或标记。\n\n"
                    f"现在请撰写第{self.chapter_number}章'{self.chapter_title}'的完整内容："
                )

                # Generate chapter content via LLM directly
                # Note: CreateChatCompletion is a tool intended to be called by a ToolCallAgent;
                # using it directly here with `messages` returns an empty string.
                # To actually generate content we ask the LLM.
                content_result = await self.llm.ask(
                    messages=[{"role": "user", "content": content_prompt}],
                    stream=False,
                    temperature=0.3,
                )

                # Clean and store the generated content
                if isinstance(content_result, str):
                    content = self._clean_content(content_result.strip())
                    self._final_content = content
                    self._content_generated = True
                    self.state = AgentState.FINISHED
                    return f"已生成第{self.chapter_number}章内容"

                return "内容生成失败，请手动补充。"

            # Step 3: Return final content
            else:
                if hasattr(self, '_final_content'):
                    return self._final_content
                return "内容生成未完成"

        except Exception as e:
            return f"第{self.chapter_number}章内容生成出错：{str(e)}，请手动补充。"

    def _clean_content(self, content: str) -> str:
        """Clean generated content to remove system information"""
        # Clean possible system output prefixes
        prefixes_to_remove = [
            "Step 1:", "Step 2:", "Step 3:",
            "Observed output of cmd",
            "Terminated:",
            "ChapterContentAgent:",
            "Assistant:"
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()

        # Clean multi-line system output
        lines = content.split('\n')
        clean_lines = []
        for line in lines:
            line = line.strip()
            # Skip system information lines
            if not any(marker in line for marker in [
                "Observed output", "executed:", "Search results for",
                "URL:", "Description:", "听", "问题分析中"
            ]):
                clean_lines.append(line)

        return '\n'.join(clean_lines).strip()

    async def run(self, input_text: str = "") -> str:
        """Override run method to return clean content only"""
        # Call parent run to get execution log
        execution_log = await super().run(input_text)

        # Return only the final clean content
        if hasattr(self, '_final_content'):
            return self._final_content
        return execution_log


class TocGeneratorAgent(ToolCallAgent):
    """目录生成Agent，专门用于根据报告主题生成专业的目录结构"""

    name: str = "toc_generator"
    description: str = "TOC generator that creates professional table of contents based on report topic"

    language: str = Field(default="zh")
    topic: str = Field(..., description="报告主题")
    reference_summary: Optional[str] = Field(default=None, description="参考资料摘要")

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(CreateChatCompletion())
    )

    max_steps: int = 1
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.NONE  # 不强制使用工具，主要生成文本

    @model_validator(mode="after")
    def _prepare_toc_prompt(self) -> "TocGeneratorAgent":
        language_text = "中文" if self.language.startswith("zh") else "English"

        self.next_step_prompt = (
            f"你是一个专业的报告目录设计师。请根据以下信息生成一份专业的报告目录结构：\n\n"
            f"报告主题：{self.topic}\n"
            f"输出语言：{language_text}\n"
            f"参考资料摘要：{self.reference_summary or '无'}\n\n"
            "请生成一份结构清晰、逻辑合理的报告目录。\n\n"
            "严格要求：\n"
            "1. 必须包含5个主要章节（章）\n"
            "2. 每个章节最多包含3个小节\n"
            "3. 只输出目录内容，不要其他解释文字\n"
            "4. 使用纯文本格式，每行一个目录项\n"
            "5. 使用缩进表示层级（章节用数字+点，小节用空格+数字+点+数字）\n"
            "6. 章节标题要简洁明确，与主题相关\n\n"
            "输出格式示例：\n"
            "1. 章节标题\n"
            "  1.1 小节标题\n"
            "  1.2 小节标题\n"
            "  1.3 小节标题\n"
            "2. 章节标题\n"
            "  2.1 小节标题\n"
            "  2.2 小节标题\n"
            "...\n\n"
            "重要：只输出目录内容，不要任何解释或标题！\n\n"
            f"现在请为'{self.topic}'主题生成5章x3节的专业目录："
        )
        return self


class SubsectionContentAgent(BaseAgent):
    """小节内容生成Agent，只生成某一章的某个小节正文。

    - 先可选进行 Web 搜索获取素材
    - 再调用底层 LLM 直接生成纯正文（不含任何系统前缀或小节标题）
    """

    name: str = "subsection_writer"
    description: str = "Subsection content generator for a specific chapter subsection"

    language: str = Field(default="zh")
    topic: str = Field(..., description="报告主题")
    chapter_number: int = Field(..., description="章节编号")
    chapter_title: str = Field(..., description="章节标题")
    subsection_code: str = Field(..., description="小节编号，如 1.1")
    subsection_title: str = Field(..., description="小节标题")
    reference_summary: Optional[str] = Field(default=None, description="参考资料摘要")
    previous_chapters: Optional[str] = Field(default=None, description="前序章节摘要")

    _search_results: Optional[str] = None
    viewed_urls: List[str] = Field(default_factory=list, description="本小节搜索阶段查看的URL列表")
    _content_generated: bool = False
    max_steps: int = 3

    async def step(self) -> str:
        try:
            # Step 1: Web search (optional)
            if self._search_results is None:
                search_prompt = (
                    f"为报告'{self.topic}'第{self.chapter_number}章'{self.chapter_title}'的{self.subsection_code} '{self.subsection_title}'搜索相关信息。"
                    f"请检索最新数据、案例和统计信息，简要输出关键要点。"
                )
                web_search_tool = WebSearch()
                try:
                    self._search_results = await web_search_tool.execute(query=search_prompt)
                    # Try to collect URLs from structured response or rendered text
                    urls: List[str] = []
                    try:
                        if hasattr(self._search_results, "results") and self._search_results.results:
                            urls = [getattr(r, "url", "") for r in self._search_results.results if getattr(r, "url", "")]
                        else:
                            import re as _re
                            urls = _re.findall(r"https?://[^\s)]+", str(self._search_results))
                    except Exception:
                        pass
                    if urls:
                        # de-duplicate while preserving order
                        seen = set()
                        self.viewed_urls.extend([u for u in urls if not (u in seen or seen.add(u))])
                    return f"已搜索{self.subsection_code}相关信息"
                except Exception:
                    self._search_results = ""
                    return f"搜索{self.subsection_code}相关信息失败，继续撰写内容"

            # Step 2: Generate subsection content
            elif not self._content_generated:
                target_words = min(getattr(config.document_config, "min_section_words", 1200), 1200) // 2
                content_prompt = (
                    f"你是专业的报告撰稿人，现仅撰写报告的一个小节正文。\n\n"
                    f"报告主题：{self.topic}\n"
                    f"所属章节：第{self.chapter_number}章 {self.chapter_title}\n"
                    f"当前小节：{self.subsection_code} {self.subsection_title}\n"
                    f"前序章节摘要：{self.previous_chapters or '无'}\n"
                    f"参考资料摘要：{self.reference_summary or '无'}\n"
                    f"搜索结果：{self._search_results or '无'}\n\n"
                    f"写作要求：\n"
                    f"1. 长度：不少于{target_words}字，分2-3个自然段\n"
                    f"2. 专业准确：给出关键事实/数据/案例（如有）\n"
                    f"3. 逻辑清晰：围绕该小节标题展开\n"
                    f"4. 输出语言：{self.language}\n\n"
                    f"重要：只输出该小节的正文内容，不要包含任何标题、编号、提示或系统信息。"
                )

                content_result = await self.llm.ask(
                    messages=[{"role": "user", "content": content_prompt}],
                    stream=False,
                    temperature=0.3,
                )

                if isinstance(content_result, str):
                    content = self._clean_content(content_result.strip())
                    self._final_content = content
                    self._content_generated = True
                    self.state = AgentState.FINISHED
                    return f"已生成{self.subsection_code}内容"
                return "小节内容生成失败，请手动补充。"

            # Step 3: Return final
            else:
                if hasattr(self, "_final_content"):
                    return self._final_content
                return "小节内容生成未完成"

        except Exception as e:
            return f"{self.subsection_code}内容生成出错：{str(e)}，请手动补充。"

    def _clean_content(self, content: str) -> str:
        prefixes_to_remove = [
            "Step 1:", "Step 2:", "Step 3:",
            "Observed output of cmd",
            "Terminated:",
            "ChapterContentAgent:",
            "Assistant:"
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()

        lines = content.split('\n')
        clean_lines = []
        for line in lines:
            line = line.strip()
            if not any(marker in line for marker in [
                "Observed output", "executed:", "Search results for",
                "URL:", "Description:", "听", "问题分析中"
            ]):
                clean_lines.append(line)
        return '\n'.join(clean_lines).strip()

    async def run(self, input_text: str = "") -> str:
        execution_log = await super().run(input_text)
        if hasattr(self, "_final_content"):
            return self._final_content
        return execution_log
