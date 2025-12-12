import json
import re
from typing import ClassVar, List, Optional, Union

from pydantic import Field, model_validator

from app.agent.base import BaseAgent
from app.logger import logger
from app.schema import AgentState


class ThinkingStepsAgent(BaseAgent):
    """Agent that generates a structured thinking steps array.

    Produces step objects with fields: key, title, description, showDetail,
    and conditional detailType when showDetail is True.
    """

    name: str = "thinking_steps_agent"
    description: str = "Generates a 15-20 step structured thinking plan"

    goal: Optional[str] = Field(default=None, description="Target goal/context")
    count: int = Field(default=17, description="Desired number of steps (15-20)")
    format: str = Field(default="json", description="Output format: json/md")
    steps: List[dict] = Field(default_factory=list, description="Generated steps")

    max_steps: int = Field(default=25, description="Upper bound for step loop")

    @model_validator(mode="after")
    def _clamp_and_prepare(self) -> "ThinkingStepsAgent":
        self.count = max(15, min(20, int(self.count)))
        if self.max_steps < self.count:
            self.max_steps = self.count
        self.format = self.format.lower()
        if self.format not in ["json", "md"]:
            self.format = "json"
        return self

    THEMES: ClassVar[List[str]] = [
        "理解与界定",
        "规划与拆解",
        "信息收集",
        "方案设计",
        "实现与验证",
        "风险与合规",
        "总结与交付",
    ]

    DETAIL_CYCLE: ClassVar[List[str]] = ["text", "image", "list", "table"]

    THEME_DESCRIPTIONS: ClassVar[dict] = {
        "理解与界定": "深入分析项目需求，明确目标边界、用户群体和核心业务目标，为后续工作提供清晰的方向指引",
        "规划与拆解": "制定详细的项目时间线和任务分解方案，将复杂目标拆解为可管理和可执行的具体模块",
        "信息收集": "系统性地收集和分析相关数据、资料和最佳实践，为决策提供充分的信息支撑",
        "方案设计": "基于分析结果设计具体的技术方案和实施路径，确保方案的可行性和创新性",
        "实现与验证": "按照设计方案执行具体任务，建立有效的测试和验证机制确保质量达标",
        "风险与合规": "识别潜在风险并制定应对策略，确保项目符合相关法规和标准要求",
        "总结与交付": "整理项目成果，总结经验教训，完成最终交付并进行效果评估",
    }

    def _generate_detailed_description(self, theme: str, goal_text: str, step_index: int) -> str:
        """Generate detailed description based on theme and goal."""
        base_desc = self.THEME_DESCRIPTIONS.get(theme, f"完成{theme}相关工作")

        # Add goal-specific context
        if goal_text and goal_text != "通用任务":
            return f"针对'{goal_text}'目标，{base_desc}，确保每个环节都能有效支撑最终目标的实现。"
        else:
            return f"{base_desc}，为项目的成功推进奠定坚实基础。"

    def _fallback_generate_steps(self) -> List[dict]:
        """Local deterministic fallback when LLM fails."""
        goal_text = self.goal or "通用任务"
        steps: List[dict] = []

        for i in range(self.count):
            theme = self.THEMES[i % len(self.THEMES)]
            show = (i + 1) % 2 == 0

            step = {
                "key": i + 1,
                "title": theme,
                "description": self._generate_detailed_description(theme, goal_text, i),
                "showDetail": show,
            }

            if show:
                step["detailType"] = self.DETAIL_CYCLE[i % len(self.DETAIL_CYCLE)]

            steps.append(step)

        return steps

    def _extract_json_from_response(self, text: str) -> Optional[List[dict]]:
        """Extract JSON array from LLM response."""
        text = text.strip()

        # Remove code fences
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text, flags=re.DOTALL)

        # Try direct JSON parsing
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in text
        match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", text)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def _validate_and_normalize_step(self, item: dict, index: int, goal_text: str) -> Optional[dict]:
        """Validate and normalize a single step."""
        if not isinstance(item, dict):
            return None

        key = int(item.get("key", index + 1))
        title = str(item.get("title", self.THEMES[index % len(self.THEMES)]))

        # Force title to be one of THEMES
        if title not in self.THEMES:
            title = self.THEMES[index % len(self.THEMES)]

        # Get description, fallback to detailed description
        desc = str(item.get("description") or item.get("descirption") or "")
        if not desc:
            desc = self._generate_detailed_description(title, goal_text, index)

        show = bool(item.get("showDetail", False))

        step = {
            "key": key,
            "title": title,
            "description": desc,
            "showDetail": show,
        }

        if show:
            dt = item.get("detailType")
            if dt not in self.DETAIL_CYCLE:
                dt = self.DETAIL_CYCLE[index % len(self.DETAIL_CYCLE)]
            step["detailType"] = dt

        return step

    def _format_as_markdown(self, steps: List[dict]) -> str:
        """Format steps as Markdown."""
        if not steps:
            return "# 思考步骤\n\n暂无步骤数据。"

        goal_text = self.goal or "通用任务"
        lines = [f"# 思考步骤：{goal_text}", ""]

        for step in steps:
            title = step.get("title", "")
            description = step.get("description", "")
            show_detail = step.get("showDetail", False)
            detail_type = step.get("detailType", "")

            lines.append(f"## {step['key']}. {title}")
            lines.append("")
            lines.append(description)
            lines.append("")

            if show_detail and detail_type:
                lines.append(f"**细节类型**: `{detail_type}`")
                lines.append("")

        return "\n".join(lines)

    async def _generate_all_steps_with_llm(self) -> List[dict]:
        """Generate all steps using LLM with enhanced prompts."""
        themes_text = ", ".join(self.THEMES)
        detail_types = ", ".join(self.DETAIL_CYCLE)
        goal_text = self.goal or "一个通用任务"

        system_prompt = (
            "你是一个专业的规划助理，负责将复杂目标拆解为清晰可执行的步骤。"
            "你需要生成结构化、详细且实用的思考步骤。"
            "严格遵守输出格式要求，仅返回 JSON 数组，不要包含任何多余文字或代码块标记。"
        )

        user_prompt = (
            f"请基于目标：{goal_text}，生成恰好 {self.count} 个详细的执行步骤。\n\n"
            f"约束条件：\n"
            f"1) 每个步骤的 title 必须且只能从以下主题中选择：[{themes_text}]\n"
            f"2) 字段必须包含：key(1开始递增)、title、description、showDetail\n"
            f"3) 当 showDetail=true 时，额外包含 detailType，取值必须是 [{detail_types}] 中之一\n"
            f"4) description 字段必须详细具体，说明该步骤的具体动作、目的和预期产出\n"
            f"5) 只返回 JSON 数组，不要解释或添加 Markdown 标记\n\n"
            f"请确保每个步骤的描述都充分详细，能够指导实际执行。"
        )

        messages = [{"role": "user", "content": user_prompt}]
        system_msgs = [{"role": "system", "content": system_prompt}]

        # Configure LLM for robust output
        prev_max = getattr(self.llm, "max_tokens", 1024)
        try:
            self.llm.max_tokens = min(int(prev_max or 1024), 2048)
            resp = await self.llm.ask(
                messages,
                system_msgs=system_msgs,
                stream=False,
                temperature=0.3
            )
        except Exception as e:
            logger.warning(f"LLM generation failed, using fallback: {e}")
            return self._fallback_generate_steps()
        finally:
            self.llm.max_tokens = prev_max

        # Extract and validate JSON
        data = self._extract_json_from_response(resp)
        if not data:
            logger.warning("Invalid JSON response, using fallback")
            return self._fallback_generate_steps()

        # Normalize and validate steps
        steps: List[dict] = []
        for i, item in enumerate(data[:self.count]):
            step = self._validate_and_normalize_step(item, i, goal_text)
            if step:
                steps.append(step)

        # Pad if needed
        while len(steps) < self.count:
            i = len(steps)
            theme = self.THEMES[i % len(self.THEMES)]
            steps.append({
                "key": i + 1,
                "title": theme,
                "description": self._generate_detailed_description(theme, goal_text, i),
                "showDetail": False,
            })

        return steps

    async def step(self) -> str:
        """Execute single step in the agent workflow."""
        if not self.steps:
            generated = await self._generate_all_steps_with_llm()
            self.steps = generated

        if len(self.steps) >= self.count:
            self.state = AgentState.FINISHED
            return "completed"

        idx = len(self.steps)
        return f"ready step {idx}"

    def get_formatted_output(self) -> Union[List[dict], str]:
        """Get steps in the requested format."""
        if self.format == "md":
            return self._format_as_markdown(self.steps)
        return self.steps
