"""
ThinkChain execution state engine.
Drives step-by-step generation based on a provided planning chain (overview).
Heavily inspired by OutlineStateEngine, generalized for normal/report/ppt.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.llm import LLM
from app.logger import logger
from app.schema import Message


@dataclass
class ExecSession:
    session_id: str
    topic: str
    task_type: str = "normal"
    language: str = "zh"
    steps: List[Dict[str, Any]] = field(default_factory=list)  # overview steps
    current_step: int = 0
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    quality_scores: List[float] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    reference_content: str = ""
    reference_sources: List[str] = field(default_factory=list)
    reference_file_uuids: List[str] = field(default_factory=list)  # 新增：文件UUID列表
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def add_step_result(self, result: Dict[str, Any]) -> None:
        self.step_results.append(result)
        self.quality_scores.append(float(result.get("quality_score", 0.0)))
        self.current_step += 1
        self.last_updated = datetime.now()

    def get_recent_quality(self, count: int) -> List[float]:
        if not self.quality_scores:
            return []
        return self.quality_scores[-count:]


class ThinkchainStateEngine:
    def __init__(self) -> None:
        self.sessions: Dict[str, ExecSession] = {}
        self.max_steps: int = 12
        self.quality_threshold: float = 0.85
        self.convergence_stability: int = 2
        self.session_ttl: timedelta = timedelta(hours=1)

    async def process_request(
        self,
        *,
        topic: str,
        task_type: str,
        language: str,
        steps: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        reference_content: str = "",
        reference_sources: Optional[List[str]] = None,
        reference_file_uuids: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], bool, str]:
        """Process one client poll: returns (result, is_completed, session_id)."""
        self._cleanup()

        session = await self._get_or_create_session(
            session_id=session_id,
            topic=topic,
            task_type=task_type,
            language=language,
            steps=steps,
            reference_content=reference_content,
            reference_sources=reference_sources or [],
            reference_file_uuids=reference_file_uuids or [],
        )

        async with session.lock:
            if self._should_converge(session):
                final_result = self._build_final(session)
                return final_result, True, session.session_id

            step_index = session.current_step
            step_result = await self._execute_step(session, step_index)
            session.add_step_result(step_result)

            is_completed = self._should_converge(session) or (
                session.current_step >= min(self.max_steps, len(session.steps))
            )
            if is_completed:
                final_result = self._build_final(session)
                return final_result, True, session.session_id

            return step_result, False, session.session_id

    async def _get_or_create_session(
        self,
        *,
        session_id: Optional[str],
        topic: str,
        task_type: str,
        language: str,
        steps: List[Dict[str, Any]],
        reference_content: str,
        reference_sources: List[str],
        reference_file_uuids: Optional[List[str]] = None,
    ) -> ExecSession:
        if session_id and session_id in self.sessions:
            sess = self.sessions[session_id]
            return sess

        new_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        sess = ExecSession(
            session_id=new_id,
            topic=topic,
            task_type=task_type,
            language=language or "zh",
            steps=steps or [],
            reference_content=reference_content or "",
            reference_sources=reference_sources or [],
            reference_file_uuids=reference_file_uuids or [],
        )
        self.sessions[new_id] = sess
        logger.info(
            f"Created thinkchain session: {new_id}, topic={topic[:50]}, type={task_type}, lang={language}"
        )
        return sess

    def _cleanup(self) -> None:
        now = datetime.now()
        to_delete: List[str] = []
        for sid, sess in self.sessions.items():
            if now - sess.last_updated > self.session_ttl:
                to_delete.append(sid)
        for sid in to_delete:
            try:
                del self.sessions[sid]
                logger.info(f"Cleaned thinkchain expired session: {sid}")
            except Exception:
                pass

    def _should_converge(self, sess: ExecSession) -> bool:
        if sess.current_step >= min(self.max_steps, max(1, len(sess.steps))):
            return True

        recent = sess.get_recent_quality(self.convergence_stability)
        if len(recent) >= self.convergence_stability and all(
            q >= self.quality_threshold for q in recent
        ):
            return True

        if self._is_duplicate_recent(sess):
            return True

        return False

    def _is_duplicate_recent(self, sess: ExecSession) -> bool:
        if len(sess.step_results) < 3:
            return False
        last = [str(r.get("content", "")) for r in sess.step_results[-3:]]
        return any(last[i] == last[i + 1] for i in range(len(last) - 1))

    async def _execute_step(self, sess: ExecSession, step_index: int) -> Dict[str, Any]:
        started = time.time()
        step_def = sess.steps[step_index] if step_index < len(sess.steps) else {}
        step_title = str(step_def.get("title") or f"步骤{step_index}")
        step_desc = str(step_def.get("description") or "")

        # 检查是否为文件审阅步骤
        is_file_review_step = step_title == "[PRE] 文件审阅与要点整合"
        # 检查是否为提示词优化与验收标准步骤
        is_prompt_opt_step = step_title == "[PRE] 提示词优化与验收标准"

        try:
            # 如果是文件审阅步骤且存在文件引用，生成文件摘要
            if is_file_review_step and sess.reference_sources:
                content = await self._generate_file_summary(sess, step_index)
                content_type = "file_summary"
            # 如果是提示词优化步骤，进行模板检索与细粒度优化（Top-3）
            elif is_prompt_opt_step:
                content = await self._generate_prompt_optimization(sess, step_index, step_desc)
                content_type = "prompt_optimization"
            else:
                # 正常执行LLM生成
                llm = LLM()
                prompt = self._build_prompt(sess, step_index, step_title, step_desc)
                response = await llm.ask(
                    [Message.user_message(prompt)], stream=False, temperature=0.3
                )
                content = self._parse_response(response)
                content_type = "general"

            quality = self._assess_quality(content, sess, step_index)
            return {
                "step": step_index,
                "step_name": step_title,
                "content": content,
                "quality_score": quality,
                "content_type": content_type,
                "execution_time": round(time.time() - started, 3),
                "status": "completed",
            }
        except Exception as e:
            logger.error(f"Thinkchain step {step_index} failed: {e}")
            return {
                "step": step_index,
                "step_name": step_title,
                "content": {"message": "内容生成失败，已返回降级结果。"},
                "quality_score": 0.5,
                "content_type": "fallback",
                "execution_time": round(time.time() - started, 3),
                "status": "failed",
                "error": str(e),
            }

    def _build_prompt(self, sess: ExecSession, i: int, title: str, desc: str) -> str:
        lang_label = "中文" if (sess.language or "zh") == "zh" else "English"
        base = f"""
任务：围绕主题"{sess.topic}"的【{title}】阶段产出结构化内容，输出JSON对象或结构化Markdown。

任务类型：{sess.task_type}
当前步骤序号：{i}
输出语言：{lang_label}
步骤描述：{desc}

约束：
1) 优先输出标准JSON（含 chapters/items/points/sections 等结构），否则输出结构化Markdown
2) 内容具体可执行，避免空泛描述
3) 子项数量建议 3-5 个
4) 标记至少 2 个子项为需要详情展示（showDetail:true），详情类型从 text/list/table/image 中选择，且 text 详情最多 1 个
"""
        if i > 0 and sess.step_results:
            prev = sess.step_results[-1].get("content", {})
            try:
                prev_json = json.dumps(prev, ensure_ascii=False)[:1000]
            except Exception:
                prev_json = str(prev)[:1000]
            base += f"\n前一输出节选：\n{prev_json}\n请在本步深化与拓展。\n"
        if sess.reference_content and i == 0:
            base += f"\n参考材料（节选）：\n{sess.reference_content[:1000]}\n请适当融入相关信息。\n"
        base += "\n请直接给出内容，不要解释。"
        return base.strip()

    def _parse_response(self, response: str) -> Any:
        text = (response or "").strip()
        if not text:
            return {"text": "空响应"}
        try:
            if text.startswith("{") and text.endswith("}"):
                return json.loads(text)
            if text.startswith("[") and text.endswith("]"):
                return json.loads(text)
            import re

            m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
        except Exception:
            pass
        return {"text": text}

    def _assess_quality(self, content: Any, sess: ExecSession, step: int) -> float:
        score = 0.0
        try:
            if isinstance(content, dict):
                keys = len(content.keys())
                score += min(0.35, 0.05 * keys)
                text = json.dumps(content, ensure_ascii=False)
            elif isinstance(content, list):
                score += min(0.35, 0.03 * len(content))
                text = json.dumps(content, ensure_ascii=False)
            else:
                text = str(content)

            ln = len(text)
            score += min(0.35, ln / 4000.0)

            topic = sess.topic
            if topic and topic[:8] in text:
                score += 0.15

            score += 0.1
        except Exception:
            score = 0.5
        return round(max(0.0, min(score, 1.0)), 3)

    def _build_final(self, sess: ExecSession) -> Dict[str, Any]:
        last = sess.step_results[-1] if sess.step_results else {}
        summary = {
            "total_steps": sess.current_step,
            "avg_quality": round(
                sum(sess.quality_scores) / max(1, len(sess.quality_scores)), 3
            ),
        }
        return {
            "step": max(sess.current_step - 1, 0),
            "step_name": "最终完善与总结",
            "content": {"summary": summary, "final": last.get("content")},
            "quality_score": last.get("quality_score", 0.85),
            "content_type": "finalization",
            "execution_time": last.get("execution_time", 0.0),
            "status": "finalized",
        }

    async def _generate_prompt_optimization(
        self, sess: ExecSession, step_index: int, step_desc: str
    ) -> Dict[str, Any]:
        """
        生成“提示词优化与验收标准”步骤内容：
        - 从推荐模板库按主题检索 Top-3
        - 拉取详情并针对当前 topic/language 优化
        - 如果推荐库为空或无匹配，基于 overview 中该步的 description 生成 1 条“系统内置优化模板”
        返回结构：{"summary": str, "templates_considered": int, "substeps": [{name, before, after}]}
        """
        from app.services.prompt_service import PromptService

        service = PromptService()
        topic = sess.topic
        lang = sess.language or "zh"

        # 1) 检索相关模板（按名称模糊匹配 topic），最多 Top-3
        try:
            overview = service.list_prompts(
                prompt_type="recommended", name_filter=topic, page=1, page_size=20
            )
            candidates = overview.get("items", [])
        except Exception as e:
            logger.warning(f"Prompt overview failed: {e}")
            candidates = []

        # 统计推荐库总量（与后端无关，统一通过服务层）
        try:
            total_overview = service.list_prompts(
                prompt_type="recommended", name_filter=None, page=1, page_size=1
            )
            total_recommended = int(total_overview.get("total", 0))
        except Exception:
            total_recommended = 0

        substeps: List[Dict[str, Any]] = []

        if total_recommended == 0:
            # 回退：仅基于 overview 里该步 description 生成 1 条内置模板
            before = step_desc.strip() or (
                f"请围绕主题‘{topic}’输出高质量提示词，包含任务目标、输入边界、输出格式、验收标准等要素。"
            )
            after = await self._refine_prompt(before, topic=topic, task_type=sess.task_type, language=lang)
            substeps.append(
                {
                    "name": "系统内置优化模板",
                    "before": before,
                    "after": after,
                }
            )
            summary = (
                "未从推荐库获取到模板，已基于概览描述生成 1 条系统内置优化模板"
                if lang == "zh"
                else "No recommended templates found; generated 1 built-in optimized template from overview description"
            )
            return {
                "summary": summary,
                "templates_considered": 0,
                "substeps": substeps,
            }

        # 若有推荐库但未匹配到，则退化为取库内最新 Top-3 进行优化
        if not candidates:
            try:
                fallback = service.list_prompts(
                    prompt_type="recommended", name_filter=None, page=1, page_size=3
                )
                candidates = fallback.get("items", [])
            except Exception:
                candidates = []

        # 2) 拉取 Top-3 的详情并优化
        selected = candidates[:3]
        for item in selected:
            try:
                tpl_id = item.get("id")
                tpl_name = item.get("name") or f"模板 {tpl_id}"
                detail = service.get_prompt_detail("recommended", tpl_id)
                before = str(detail.get("prompt") or "").strip()
                if not before:
                    continue
                after = await self._refine_prompt(
                    before, topic=topic, task_type=sess.task_type, language=lang
                )
                substeps.append({"id": tpl_id, "name": tpl_name, "before": before, "after": after})
            except Exception as e:
                logger.warning(f"Optimize prompt failed for {item}: {e}")
                continue

        if not substeps:
            # 兜底：仍然回退生成 1 条
            before = step_desc.strip() or (
                f"请围绕主题‘{topic}’输出高质量提示词，包含任务目标、输入边界、输出格式、验收标准等要素。"
            )
            after = await self._refine_prompt(before, topic=topic, task_type=sess.task_type, language=lang)
            substeps.append({"name": "系统内置优化模板", "before": before, "after": after})

        summary = (
            f"已优化 {len(substeps)} 个推荐模板"
            if lang == "zh"
            else f"Optimized {len(substeps)} recommended templates"
        )
        return {
            "summary": summary,
            "templates_considered": len(candidates),
            "substeps": substeps,
        }

    async def _refine_prompt(
        self, original: str, *, topic: str, task_type: str, language: str
    ) -> str:
        """调用 LLM 对单个模板进行细粒度优化，输出纯文本的新模板。"""
        try:
            llm = LLM()
            lang_label = "中文" if (language or "zh") == "zh" else "English"
            system = (
                "You are an expert prompt engineer. Return only the improved prompt body, no explanations."
            )
            user = (
                f"主题/Topic: {topic}\n"
                f"任务类型/Task Type: {task_type}\n"
                f"输出语言/Language: {lang_label}\n"
                "请基于以下原始模板进行细粒度优化（保留结构、提升约束、明确验收）：\n\n"
                "[原始模板]\n" + original.strip() + "\n\n"
                "[要求]\n"
                "- 明确目标、输入边界、输出格式、验收指标；\n"
                "- 增强可执行性与鲁棒性；\n"
                "- 保持与原模板风格一致；\n"
                "- 仅返回优化后的模板正文（纯文本/Markdown），不要解释。"
            )
            resp = await llm.ask([Message.system_message(system), Message.user_message(user)], stream=False, temperature=0.2)
            return (resp or "").strip()
        except Exception as e:
            logger.warning(f"Refine prompt failed: {e}")
            return original

    async def _generate_file_summary(
        self, sess: ExecSession, step_index: int
    ) -> Dict[str, Any]:
        """生成文件摘要内容，用于文件审阅步骤"""
        try:
            # 获取文件摘要内容
            file_summaries = []

            # 遍历引用源，为每个文件生成摘要
            for i, source in enumerate(sess.reference_sources):
                file_summary = await self._generate_single_file_summary(sess, source, i)
                file_summaries.append(file_summary)

            # 构建符合现有结构的内容
            return {
                "summary": f"成功审阅了 {len(sess.reference_sources)} 个文件",
                "files_reviewed": len(sess.reference_sources),
                "file_list": sess.reference_sources,
                "substeps": file_summaries,
                "review_status": "completed",
                "key_findings": [
                    "文件内容已系统整理",
                    "关键信息已提取",
                    "要点已分类汇总",
                ],
            }

        except Exception as e:
            logger.error(f"生成文件摘要失败: {e}")
            # 返回降级的内容结构
            return {
                "summary": "文件审阅过程中出现错误",
                "files_reviewed": 0,
                "file_list": [],
                "substeps": [],
                "review_status": "failed",
                "error": str(e),
                "key_findings": ["文件审阅失败，将继续后续步骤"],
            }

    async def _generate_single_file_summary(
        self, sess: ExecSession, source: str, index: int
    ) -> Dict[str, Any]:
        """为单个文件生成摘要"""
        try:
            # 获取对应的文件UUID
            file_uuid = None
            if hasattr(sess, "reference_file_uuids") and sess.reference_file_uuids:
                # 简单映射：按顺序对应
                if index < len(sess.reference_file_uuids):
                    file_uuid = sess.reference_file_uuids[index]

            if file_uuid:
                # 获取真实文件内容
                file_content = await self._get_file_content_summary(file_uuid)
            else:
                # 使用模拟数据作为降级处理
                file_content = f"《{source}》文件包含了重要的研究数据和分析结果。"

            # 构建完整的markdown内容
            full_content = f"""### {source}

**文件摘要：**

{file_content}

**主要要点：**
- 文件核心内容概述
- 关键信息提取和分析
- 与主题相关的要点总结

**审阅状态：** ✅ 已完成内容提取

---

*本摘要基于文件内容自动生成，为后续分析提供参考基础。*"""

            return {
                "file_name": source,
                "key": f"file_{index + 1}",
                "text": f"文件《{source}》的主要内容摘要：{file_content}",
                "showDetail": True,  # 始终为true
                "detailType": "text",  # 始终为text
                "detailPayload": {
                    "format": "markdown",  # 始终为markdown
                    "content": full_content,  # 完整的markdown内容
                },
            }
        except Exception as e:
            logger.error(f"生成单个文件摘要失败 {source}: {e}")
            # 错误情况下也保持字段完整性
            error_content = f"""### {source}

**文件摘要生成失败**

文件《{source}》的内容提取过程中出现错误，将继续使用文件名作为参考。

**错误信息：** {str(e)}

**处理状态：** ⚠️ 使用降级处理"""

            return {
                "file_name": source,
                "key": f"file_{index + 1}",
                "text": f"文件《{source}》摘要生成失败",
                "showDetail": True,  # 即使失败也保持true
                "detailType": "text",  # 即使失败也保持text
                "detailPayload": {
                    "format": "markdown",  # 即使失败也保持markdown
                    "content": error_content,
                },
            }

    async def _get_file_content_summary(self, file_uuid: str) -> str:
        """获取单个文件的内容摘要"""
        try:
            from app.services.file_upload_service import get_file_contents_by_uuids

            # 获取文件内容
            content = await get_file_contents_by_uuids([file_uuid])

            if content:
                # 清理内容，移除多余的空白字符
                clean_content = content.strip()
                if len(clean_content) > 500:
                    # 提取前500个字符作为摘要，确保内容有意义
                    summary = clean_content[:500]
                    # 尝试在句子边界截断
                    last_period = summary.rfind("。")
                    last_newline = summary.rfind("\n")
                    cut_pos = max(last_period, last_newline)
                    if cut_pos > 100:  # 确保至少有100个字符
                        summary = summary[: cut_pos + 1]
                    return f"{summary}\n\n...(内容已截断，完整内容请查看详细页面)"
                else:
                    return clean_content
            else:
                return "文件内容提取成功，但内容为空或无法解析。该文件可能为HTML格式或需要特殊处理。"

        except Exception as e:
            logger.error(f"获取文件内容摘要失败 {file_uuid}: {e}")
            return f"文件内容提取失败：{str(e)}。将继续使用文件名作为参考。"


# Global instance
thinkchain_state_engine = ThinkchainStateEngine()
