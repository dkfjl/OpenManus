from typing import Optional

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.schema import ToolChoice, TOOL_CHOICE_TYPE
from app.tool import ToolCollection
from app.tool.markdown_document import MarkdownDocumentTool
from app.tool.chart_visualization import DataVisualization, NormalPythonExecute


class MdSlideWriterAgent(ToolCallAgent):
    """Writer agent that composes Marp Markdown slides and writes via MarkdownDocumentTool."""

    name: str = "md_writer"
    description: str = "Writer that outputs Marp Markdown and saves it through markdown_document tool"

    language: str = Field(default="zh")
    filepath: str = Field(..., description="Target .md path")
    title: str = Field(default="自动生成演示文稿")
    next_step_prompt: str = Field(default="")
    toc_body: Optional[str] = Field(default=None, description="Agenda lines for TOC slide")
    reference_summary: Optional[str] = Field(default=None, description="Summarized reference material")
    background_image: Optional[str] = Field(default=None, description="Default background image path for Marp front-matter")
    style_front_matter: Optional[str] = Field(default=None, description="Full YAML front-matter text to start the document (Marp)")

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            MarkdownDocumentTool(),
            DataVisualization(),
            NormalPythonExecute(),
        )
    )
    special_tool_names: list[str] = Field(
        default_factory=lambda: [MarkdownDocumentTool().name]
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.REQUIRED  # type: ignore
    max_steps: int = 2

    @model_validator(mode="after")
    def _prepare_prompt(self) -> "MdSlideWriterAgent":
        # Build front-matter: prefer provided style_front_matter; otherwise use a rich default with layout helpers
        default_fm = (
            "---\n"
            "marp: true\n"
            "theme: gaia\n"
            "paginate: true\n"
            "backgroundColor: #fff\n"
            "style: |\n"
            "  /* 全局样式 */\n"
            "  section { font-family: 'Helvetica Neue', 'Microsoft YaHei', sans-serif; font-size: 26px; padding: 50px; color: #333; }\n"
            "  p, li { line-height: 1.4; }\n"
            "  table { font-size: 24px; }\n"
            "  /* 分栏 */\n"
            "  div.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: center; }\n"
            "  div.columns-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }\n"
            "  div.left-narrow { display: grid; grid-template-columns: 30% 65%; gap: 5%; }\n"
            "  /* 卡片 */\n"
            "  div.card { background: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); text-align: center; border-top: 5px solid #0066cc; }\n"
            "  /* 图片 */\n"
            "  img { border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); width: 100%; }\n"
            "  h1 { color: #004488; }\n"
            "  h2 { color: #0066cc; }\n"
            "---\n\n"
        )
        fm = (self.style_front_matter or default_fm)
        # Inject backgroundImage if provided and not present
        if self.background_image and "backgroundImage:" not in fm:
            if "style:" in fm:
                fm = fm.replace("style:", f"backgroundImage: url('{self.background_image}')\nstyle:")
            else:
                fm = fm.replace("\n---\n", f"\nbackgroundImage: url('{self.background_image}')\n---\n")

        # A practical Marp starter; the model must fill content and call markdown_document once.
        self.next_step_prompt = (
            "你是一名演示文稿撰写者。根据计划状态中的 Notes 综合所有上游结果，"
            f"以{self.language}生成基于 Marp 的 Markdown 幻灯片（--- 分隔）。\n"
            "使用 `markdown_document` 工具一次写入完整内容（append=false），参数包含：\n"
            f"`filepath`: '{self.filepath}', `content`: '<完整markdown文本>'。\n"
            "Markdown 必须以以下 YAML front-matter 开头（原样粘贴）：\n" + fm +
            f"封面页标题使用: {self.title}。\n"
            + ("请添加一页‘目录’(Agenda) 幻灯片，目录内容如下逐行列出：\n" + self.toc_body + "\n" if self.toc_body else "")
            + "为保证排版美观，必须在适合的页面使用这些布局类：\n  - `div.columns`（左右两栏，左文右图 / 左文右表）；\n  - `div.columns-3`（三栏卡片）；\n  - `div.left-narrow`（左窄右宽，时间轴 / Roadmap）；\n  关键结论使用 `div.card` 包裹。\n"
            + ("以下是上传资料的摘要，可择要融入相关页：\n" + self.reference_summary + "\n" if self.reference_summary else "")
            + "如计划步骤包含表格/图片/图表，请：\n"
            "- 表格：使用 Markdown 表格语法；图片/图表：先用 data_visualization 或 python_execute 生成 png 到 workspace，再以 `![w:700](相对路径)` 引用；必要时可临时使用网络图片；\n"
            "- 分页：使用 `---` 清晰分隔每一页。\n"
            "长度与结构要求：\n- 至少 12 页；\n- 每个内容页≥5条要点或≥120字正文；\n- 必含：KPIs、重点项目A/B、问题与改进、2026 Roadmap、所需支持、参考资料。\n"
            "输出规范：尽量短句要点式，强调数字和结论；目录与章节标题编号一致；最后添加‘参考资料’页面（若没有，我会在后处理阶段追加）。\n"
            "生成完成后，仅调用一次 `markdown_document`。"
        )
        return self
