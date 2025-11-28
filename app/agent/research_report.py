from typing import List, Optional

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.schema import ToolChoice
from app.tool import CreateChatCompletion, WebSearch, WordDocumentTool, Terminate, ToolCollection


class ResearchReportAgent(ToolCallAgent):
    """Research agent that orchestrates report generation using tool calls.

    - Consumes a thinking template (steps) and topic/language.
    - Produces a .docx by calling the `word_document` tool with structured sections.
    - Optionally may use `web_search` or `create_chat_completion` to enrich content.
    """

    name: str = "research_report"
    description: str = "Lead agent that turns a thinking template into a polished report (.docx)."

    topic: str
    language: str = Field(default="zh", description="Output language")
    steps: List[dict] = Field(default_factory=list, description="Thinking template steps array")
    filepath: str = Field(..., description="Target .docx path within workspace")

    # Tools: include document writer and optional helpers
    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), WebSearch(), WordDocumentTool(), Terminate()
    )
    tool_choices = ToolChoice.AUTO  # type: ignore
    max_steps: int = 12

    @model_validator(mode="after")
    def _setup_prompts(self) -> "ResearchReportAgent":
        # Normalize language hint
        lang = (self.language or "zh").strip()

        # Keep only necessary fields from steps and bound to <= 20
        simplified_steps: List[dict] = []
        for s in (self.steps or [])[:20]:
            simplified_steps.append(
                {
                    "key": s.get("key"),
                    "title": s.get("title"),
                    "descirption": s.get("descirption") or s.get("description"),
                    "showDetail": bool(s.get("showDetail", False)),
                    **({"detailType": s.get("detailType")} if s.get("showDetail") else {}),
                }
            )

        system = (
            "You are the lead research/report agent. You coordinate sub-tasks, "
            "synthesize findings, and produce a well-structured report. "
            "Use tool calls. When writing the final document, call the `word_document` tool. "
            "After the document is saved, call the `terminate` tool to finish."
        )

        # Strong, explicit next-step instruction for tool usage
        user = (
            f"目标/Topic: {self.topic}\n"
            f"语言/Language: {lang}\n"
            f"输出格式/Format: .docx\n"
            f"输出路径/Filepath: {self.filepath}\n"
            "思考模版/Thinking Template (JSON Array):\n"
            f"{simplified_steps}\n\n"
            "你的任务：\n"
            "1) 依据思考模版梳理章节结构（不要机械照搬，可合并/重命名为更自然的章节）。\n"
            "2) 生成每章的精炼标题与成体系内容（包含背景、要点、小结；如有数据/发现可用列表形式）。\n"
            "3) 调用 `word_document` 工具一次性写入：参数包含 `filepath`, `document_title`, `sections`。\n"
            "   - sections: 每个对象包含 `heading`、可选 `level`（1-3）、`content` 文本。\n"
            "   - 内容必须使用指定语言撰写，与主题强相关，不要占位符。\n"
            "4) 文档保存完成后，调用 `terminate` 工具结束。\n"
            "只通过工具完成任务，不要输出解释性文字。"
        )

        self.system_prompt = system
        self.next_step_prompt = user
        return self

