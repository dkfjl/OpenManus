from typing import Optional

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.schema import ToolChoice, TOOL_CHOICE_TYPE
from app.tool import CreateChatCompletion, WebSearch, ToolCollection
from app.tool.chart_visualization import DataVisualization, NormalPythonExecute
from app.tool.pptx_presentation import PptxPresentationTool


class PptxResearchAgent(ToolCallAgent):
    """Research agent reused for PPTX flow (kept minimal)."""

    name: str = "research"
    description: str = "Research and synthesis agent for PPTX planning"

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(CreateChatCompletion(), WebSearch())
    )

    max_steps: int = 1
    next_step_prompt: str = (
        "根据当前任务，必要时调用 web_search 检索，并用要点总结发现。"
        "不要写入演示文稿，不要调用 terminate。"
    )


class PptxSearchAgent(ToolCallAgent):
    name: str = "search"
    description: str = "Focused web search for PPTX context"

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(WebSearch())
    )

    max_steps: int = 1
    next_step_prompt: str = (
        "使用 web_search 检索与任务相关的信息，输出3-5条事实及来源。"
        "不要写入演示文稿，不要调用 terminate。"
    )


class PptxWriterAgent(ToolCallAgent):
    """Writer that composes slides via `pptx_presentation` tool."""

    name: str = "writer"
    description: str = "Compose slides and save .pptx using pptx_presentation tool"

    language: str = Field(default="zh")
    filepath: str = Field(..., description="Target .pptx path")
    title: str = Field(default="自动生成演示文稿")
    next_step_prompt: str = Field(default="")
    toc_body: Optional[str] = Field(default=None, description="Text lines for TOC slide")
    reference_summary: Optional[str] = Field(default=None, description="Summarized reference material")

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PptxPresentationTool(),
            DataVisualization(),
            NormalPythonExecute(),
        )
    )
    special_tool_names: list[str] = Field(
        default_factory=lambda: [PptxPresentationTool().name]
    )

    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.REQUIRED  # type: ignore
    max_steps: int = 2

    @model_validator(mode="after")
    def _prepare_writer_prompt(self) -> "PptxWriterAgent":
        self.next_step_prompt = (
            "你是演示文稿撰稿人。根据计划状态中的 Notes 综合所有上游结果，"
            f"以{self.language}撰写简洁清晰的幻灯片内容（标题+要点）。"
            "若计划步骤文本包含 [TABLE]/[IMAGE] 标记，或文字要求‘表格’/‘图片/图表’，按以下策略：\n"
            "1) 可直接在 `pptx_presentation` 的 `slides` 中提供 `table:{headers?, rows}` 渲染表格；\n"
            "2) 需要图表时，先调用 `data_visualization` 生成 png 文件到 workspace，再在 `slides[].images` 中引用其相对路径；也可用 `python_execute` 生成简单 Matplotlib 图保存为 png；\n"
            "3) 允许在 `sections`/`slides` 中同时提供 `bullets`+`images`/`table` 组合。\n"
            "最终使用 `pptx_presentation` 工具一次性写入完整演示文稿并覆盖目标文件（append=false）："
            f"参数包含 `filepath`: '{self.filepath}', `presentation_title`: '{self.title}', "
            "`sections` 或 `slides`（推荐 `slides` 以便嵌入 `images`/`table`）。"
            "严格要求：每张幻灯片标题醒目；正文采用要点式，每点不超过两行；避免大段长文。"
            + ("添加一页‘目录’幻灯片，按以下文本逐行列出：\n" + self.toc_body + "\n" if self.toc_body else "")
            + ("可参考以下‘参考材料摘要’，吸收其中的事实与数据：\n" + self.reference_summary + "\n" if self.reference_summary else "")
            + "写作完成后只进行一次工具调用完成导出。"
        )
        return self
