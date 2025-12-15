"""
Service to generate flexible planning steps for ThinkChain overview using LLM.
No fixed THEMES; the LLM designs step titles and descriptions given the topic.
Falls back to a deterministic minimal plan when LLM fails.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.llm import LLM
from app.logger import logger
from app.schema import Message


class ThinkchainOverviewService:
    def __init__(self) -> None:
        self.llm = LLM()

    async def generate_steps(
        self,
        *,
        topic: str,
        language: str = "zh",
        count: int = 10,
        reserved_titles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        # Respect caller's count; route ensures overall 8–12 with pre-steps
        count = max(0, int(count or 0))
        if count == 0:
            return []
        user_prompt = (
            f"请基于主题：{topic}，生成一个任务拆解的步骤列表。\n"
            f"要求：\n"
            f"1) 仅返回 JSON 数组；每个元素是一个对象，字段：key(1开始递增)、title、description。\n"
            f"2) 步骤数量约为 {count}（允许±1），每个 description 要具体、可执行，避免空泛。\n"
            f"3) 允许自拟合适的阶段名称，不要局限于固定模板。\n"
            f"4) 输出语言：{'中文' if language=='zh' else 'English'}。\n"
            f"不要添加 Markdown 代码块标记或多余解释。"
        )
        if reserved_titles:
            banned = "，".join(reserved_titles[:8])
            user_prompt += f"\n请不要包含以下主题或与之重复的步骤：{banned}。"
        try:
            resp = await self.llm.ask(
                [Message.user_message(user_prompt)], stream=False, temperature=0.4
            )
            data = self._extract_json_array(resp)
            if not isinstance(data, list) or not data:
                raise ValueError("empty or invalid array")
            steps: List[Dict[str, Any]] = []
            for i, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or f"步骤{i}")
                desc = str(item.get("description") or "")
                steps.append(
                    {
                        "key": int(item.get("key", i)),
                        "title": title,
                        "description": desc,
                    }
                )
            if not steps:
                raise ValueError("no valid steps")
            return steps[: count + 2]
        except Exception as e:
            logger.warning(f"Overview LLM failed, using fallback: {e}")
            return [
                {
                    "key": i + 1,
                    "title": f"步骤{i+1}",
                    "description": (
                        f"围绕主题‘{topic}’推进本阶段工作，明确产出与验收标准，形成可执行要点。"
                    ),
                }
                for i in range(count)
            ]

    def _extract_json_array(self, text: str) -> Any:
        text = (text or "").strip()
        if not text:
            return []
        try:
            if text.startswith("[") and text.endswith("]"):
                return json.loads(text)
            if text.startswith("{") and text.endswith("}"):
                obj = json.loads(text)
                return obj.get("steps", []) if isinstance(obj, dict) else []
            import re

            m = re.search(r"\[(?:.|\n|\r)*\]", text)
            if m:
                return json.loads(m.group(0))
        except Exception:
            return []

    async def detect_intents(
        self,
        *,
        topic: str,
        language: str = "zh",
        has_files: bool = False,
        query_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Use LLM to extract intents for pre-steps. Fallback to heuristics.

        Strict rule (product requirement):
        - Both kb_specific and kb_generic MUST only trigger when the user intent
          clearly leans to INTERNAL materials (internal knowledge/docs/intranet/private/confidential).
        - We enforce this even if the LLM suggests kb_* = true by post-filtering
          with an `internal_leaning` detection based on strong keywords.
        """
        text = (query_text or topic or "").strip()
        if not text:
            return {
                "use_files": bool(has_files),
                "want_prompt_opt": False,
                "want_kb_specific": False,
                "kb_name": None,
                "want_kb_generic": False,
            }

        def _has_internal_leaning(s: str) -> bool:
            s = (s or "").lower()
            # Strong signals for INTERNAL intent (Chinese + English)
            strong_terms = [
                # zh
                "内部", "内部文档", "内部资料", "内部知识", "公司内部", "集团内", "企业内", "内网",
                "私有", "保密", "机密", "非公开", "私域", "本地知识库", "私有知识库", "内部wiki",
                "企业wiki", "内控手册", "内部手册", "sop(内部)", "sop（内部）", "内部sop",
                # en
                "internal", "intranet", "private", "confidential", "proprietary",
                "company-internal", "internal docs", "internal documents", "internal knowledge",
                "internal kb", "private kb", "internal wiki",
            ]
            return any(term in s for term in strong_terms)

        internal_leaning = _has_internal_leaning(text)

        sys = (
            "You are an intent classifier. Only output a compact JSON object with the requested fields."
        )
        user = (
            f"Text: {text}\n"
            "Classify and return JSON with exact keys: {\n"
            "  \"use_files\": boolean,\n"
            "  \"want_prompt_opt\": boolean,\n"
            "  \"want_kb_specific\": boolean,\n"
            "  \"kb_name\": string|null,\n"
            "  \"want_kb_generic\": boolean\n"
            "}.\n"
            f"Language hint: {'Chinese' if (language or 'zh')=='zh' else 'English'}.\n"
            "Do not add any extra text or code fences."
        )
        try:
            resp = await self.llm.ask(
                [Message.system_message(sys), Message.user_message(user)],
                stream=False,
                temperature=0.0,
            )
            obj = self._extract_json_obj(resp)
            if not isinstance(obj, dict):
                raise ValueError("invalid json")
            # Merge has_files as an upper bound
            obj["use_files"] = bool(obj.get("use_files", False) or has_files)
            # Post-filter with internal leaning: both kb flags only allowed if internal intent is clear
            want_kb_specific = bool(obj.get("want_kb_specific", False)) and internal_leaning
            want_kb_generic = bool(obj.get("want_kb_generic", False)) and internal_leaning
            kb_name = obj.get("kb_name") if want_kb_specific and obj.get("kb_name") else None
            return {
                "use_files": bool(obj.get("use_files", False)),
                "want_prompt_opt": bool(obj.get("want_prompt_opt", False)),
                "want_kb_specific": want_kb_specific,
                "kb_name": kb_name,
                "want_kb_generic": want_kb_generic,
            }
        except Exception:
            # Heuristic fallback
            s = text
            s_low = s.lower()
            want_prompt_opt = any(
                k in s or k in s_low
                for k in ["提示词优化", "优化提示", "优化提示词", "prompt 优化", "prompt improve", "prompt refine"]
            )
            import re

            m = re.search(r"(?:知识库|kb)[:：\s]*([\w\-\u4e00-\u9fa5]{2,32})", s, re.IGNORECASE)
            kb_name = m.group(1) if m else None
            # Enforce internal leaning for kb triggers
            want_kb_specific = (kb_name is not None) and internal_leaning
            want_kb_generic = (
                any(
                    term in s or term in s_low
                    for term in ["知识库", "kb", "wiki", "资料库", "文档库", "语料库"]
                )
                and internal_leaning
            )
            if not want_kb_specific:
                kb_name = None
            return {
                "use_files": bool(has_files),
                "want_prompt_opt": want_prompt_opt,
                "want_kb_specific": want_kb_specific,
                "kb_name": kb_name,
                "want_kb_generic": want_kb_generic,
            }

    async def generate_pre_steps(
        self,
        *,
        topic: str,
        language: str = "zh",
        has_files: bool = False,
        query_text: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Generate pre-steps with fixed titles but LLM-crafted descriptions.

        Returns (steps, fixed_titles)
        """
        intents = await self.detect_intents(
            topic=topic, language=language, has_files=has_files, query_text=query_text
        )
        # Fixed titles for deterministic downstream logic
        PRE_TITLES = {
            "files": "[PRE] 文件审阅与要点整合",
            "prompt": "[PRE] 提示词优化与验收标准",
            "kb_specific": "[PRE] 检索特定知识库并汇总证据",
            "kb_generic": "[PRE] 检索相关知识库并构建材料池",
        }

        required_keys: List[str] = []
        if intents.get("use_files"):
            required_keys.append("files")
        if intents.get("want_prompt_opt"):
            required_keys.append("prompt")
        if intents.get("want_kb_specific"):
            required_keys.append("kb_specific")
        if intents.get("want_kb_generic"):
            required_keys.append("kb_generic")

        # Prepare optimized topic regardless of required pre-steps
        optimized_topic = topic

        # Ask LLM to optimize topic and craft contents for needed keys
        kb_name = intents.get("kb_name")
        lang_hint = "中文" if (language or "zh") == "zh" else "English"
        system = (
            "You refine a task request and prepare planning pre-steps. Only return JSON without extra text."
        )
        prompt_lines = [
            f"主题：{topic}",
            f"语言：{lang_hint}",
            "请返回一个JSON对象，键包括：",
            "- optimized_topic: 提炼后的任务目的/核心主题（不含行为动词，简洁）。",
        ]
        if required_keys:
            prompt_lines.append("- 以下键的内容：")
            if "files" in required_keys:
                prompt_lines.append("  - files: 1-2句说明如何审阅与整合已提供文件。")
            if "prompt" in required_keys:
                prompt_lines.append("  - prompt: 已优化的完整 Prompt 文本（可直接使用）。")
            if "kb_specific" in required_keys:
                prompt_lines.append(
                    f"  - kb_specific: 5-8个检索关键词（逗号分隔），用于特定知识库 {kb_name or ''}。"
                )
            if "kb_generic" in required_keys:
                prompt_lines.append("  - kb_generic: 5-8个通用检索关键词（逗号分隔）。")
        prompt_lines.append("仅返回JSON，不要代码块或解释。")
        user = "\n".join(prompt_lines)
        descs: Dict[str, str] = {}
        try:
            resp = await self.llm.ask(
                [Message.system_message(system), Message.user_message(user)],
                stream=False,
                temperature=0.2,
            )
            obj = self._extract_json_obj(resp)
            if isinstance(obj, dict):
                ot = obj.get("optimized_topic")
                if isinstance(ot, str) and ot.strip():
                    optimized_topic = ot.strip()
                for k in ("files", "prompt", "kb_specific", "kb_generic"):
                    v = obj.get(k)
                    if isinstance(v, str) and v.strip():
                        descs[k] = v.strip()
        except Exception:
            descs = {}

        # Fallback default descriptions
        defaults = {
            "files": "列出并审阅已提供的参考文件，抽取关键信息并标注引用，形成可复用要点。",
            "prompt": "优化提示词与约束：明确目标、输入边界、输出格式、验收指标与反例。",
            "kb_specific": f"检索指定知识库 {kb_name or ''}，设定范围/关键词/排除项，整理支撑性证据并记录引用。",
            "kb_generic": "检索主题相关知识库，设定来源优先级与筛选标准，构建材料池并记录引用。",
        }

        steps: List[Dict[str, Any]] = []
        fixed_titles: List[str] = []
        order = ["files", "prompt", "kb_specific", "kb_generic"]
        for k in order:
            if k not in required_keys:
                continue
            title = PRE_TITLES[k]
            fixed_titles.append(title)
            desc = descs.get(k) or defaults[k]
            steps.append({"key": 0, "title": title, "description": desc})

        return steps, fixed_titles, optimized_topic

    def _extract_json_obj(self, text: str) -> Any:
        text = (text or "").strip()
        if not text:
            return {}
        try:
            if text.startswith("{") and text.endswith("}"):
                return json.loads(text)
            import re
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                return json.loads(m.group(0))
        except Exception:
            return {}


thinkchain_overview_service = ThinkchainOverviewService()
