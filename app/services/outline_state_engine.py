"""
自收敛版 PPT 大纲生成状态引擎
 - 维护会话状态与步骤推进
 - 每次请求返回当前步结果，直到判断收敛
 - 轻量内存实现，单进程可用；多实例部署建议后续切换到外部存储
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


# 步骤定义与类型
STEP_DEFINITIONS: Dict[int, str] = {
    0: "需求分析与主题理解",
    1: "内容架构设计",
    2: "章节详细规划",
    3: "视觉设计建议",
    4: "制作步骤编排",
    5: "内容细化与补充",
    6: "质量优化建议",
    7: "最终完善与总结",
}

STEP_CONTENT_TYPES: Dict[int, str] = {
    0: "analysis",
    1: "structure",
    2: "detailed_planning",
    3: "design",
    4: "workflow",
    5: "enhancement",
    6: "optimization",
    7: "finalization",
}


@dataclass
class SessionState:
    session_id: str
    topic: str
    language: str = "zh"
    current_step: int = 0
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    quality_scores: List[float] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    reference_content: str = ""
    reference_sources: List[str] = field(default_factory=list)
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


class OutlineStateEngine:
    """PPT大纲自收敛生成状态引擎（内存实现）"""

    def __init__(self) -> None:
        self.sessions: Dict[str, SessionState] = {}
        self.max_steps: int = 8
        self.quality_threshold: float = 0.85
        self.convergence_stability: int = 2  # 最近 N 步质量稳定达标
        self.session_ttl: timedelta = timedelta(hours=1)

    async def process_request(
        self,
        *,
        topic: str,
        session_id: Optional[str] = None,
        language: str = "zh",
        reference_content: str = "",
        reference_sources: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        处理一次前端轮询请求，返回：(结果数据, 是否结束, 会话ID)
        """
        self._cleanup_expired_sessions()

        session = await self._get_or_create_session(
            session_id=session_id,
            topic=topic,
            language=language,
            reference_content=reference_content,
            reference_sources=reference_sources or [],
        )

        async with session.lock:
            # 收敛判断（在执行前先看是否已有充足内容）
            if self._should_converge(session):
                final_result = self._build_final_outline(session)
                logger.info(
                    f"Session {session.session_id} converged at step {session.current_step}"
                )
                # 不在此处销毁会话，交由 TTL 清理，便于客户端拿到最后一步后再请求一次也能得到相同结论
                return final_result, True, session.session_id

            # 执行当前步骤
            step = session.current_step
            step_result = await self._execute_step(session, step)
            session.add_step_result(step_result)

            # 执行后再次判断是否可收敛
            is_completed = self._should_converge(session) or (
                session.current_step >= self.max_steps
            )
            if is_completed:
                # 用“最终完善与总结”包装一次，便于前端展示收尾语义
                final_result = self._build_final_outline(session)
                return final_result, True, session.session_id

            return step_result, False, session.session_id

    async def _get_or_create_session(
        self,
        *,
        session_id: Optional[str],
        topic: str,
        language: str,
        reference_content: str,
        reference_sources: List[str],
    ) -> SessionState:
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            # 仅在首次创建时设置参考内容；后续请求忽略传入的参考材料
            return session

        new_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        session = SessionState(
            session_id=new_id,
            topic=topic,
            language=language or "zh",
            reference_content=reference_content or "",
            reference_sources=reference_sources or [],
        )
        self.sessions[new_id] = session
        logger.info(
            f"Created new outline session: {new_id}, topic={topic[:50]}, lang={language}"
        )
        return session

    def _cleanup_expired_sessions(self) -> None:
        now = datetime.now()
        to_delete: List[str] = []
        for sid, sess in self.sessions.items():
            if now - sess.last_updated > self.session_ttl:
                to_delete.append(sid)
        for sid in to_delete:
            try:
                del self.sessions[sid]
                logger.info(f"Cleaned expired session: {sid}")
            except Exception:
                pass

    def _should_converge(self, session: SessionState) -> bool:
        # 1) 达到最大步数
        if session.current_step >= self.max_steps:
            return True

        # 2) 最近 N 步质量均达阈值
        recent = session.get_recent_quality(self.convergence_stability)
        if len(recent) >= self.convergence_stability and all(
            q >= self.quality_threshold for q in recent
        ):
            return True

        # 3) 内容覆盖（粗略）：是否出现关键元素关键词
        if self._has_comprehensive_coverage(session):
            return True

        # 4) 重复内容检测（简单判等）
        if self._is_duplicate_recent(session):
            return True

        return False

    def _has_comprehensive_coverage(self, session: SessionState) -> bool:
        text = "\n".join([str(r.get("content", "")) for r in session.step_results])
        essentials = ["标题", "目录", "内容", "总结", "封面"]
        found = sum(1 for e in essentials if e in text)
        return found >= max(1, int(len(essentials) * 0.8))

    def _is_duplicate_recent(self, session: SessionState) -> bool:
        if len(session.step_results) < 3:
            return False
        last = [str(r.get("content", "")) for r in session.step_results[-3:]]
        return any(last[i] == last[i + 1] for i in range(len(last) - 1))

    async def _execute_step(self, session: SessionState, step: int) -> Dict[str, Any]:
        prompt = self._build_step_prompt(session, step)
        started = time.time()
        try:
            llm = LLM()
            response = await llm.ask([Message.user_message(prompt)], stream=False, temperature=0.3)
            content = self._parse_response_as_json_or_text(response)
            quality = self._assess_step_quality(content, session, step)
            result: Dict[str, Any] = {
                "step": step,
                "step_name": STEP_DEFINITIONS.get(step, f"步骤{step}"),
                "content": content,
                "quality_score": quality,
                "convergence_signals": self._extract_convergence_signals(content),
                "content_type": STEP_CONTENT_TYPES.get(step, "general"),
                "execution_time": round(time.time() - started, 3),
                "status": "completed",
            }
            return result
        except Exception as e:
            logger.error(f"Step {step} failed: {e}")
            return {
                "step": step,
                "step_name": STEP_DEFINITIONS.get(step, f"步骤{step}"),
                "content": {"message": "内容生成失败，已返回降级结果。"},
                "quality_score": 0.5,
                "convergence_signals": {"error": True},
                "content_type": "fallback",
                "execution_time": round(time.time() - started, 3),
                "status": "failed",
                "error": str(e),
            }

    def _build_step_prompt(self, session: SessionState, step: int) -> str:
        step_name = STEP_DEFINITIONS.get(step, f"步骤{step}")
        content_type = STEP_CONTENT_TYPES.get(step, "general")
        lang_label = "中文" if session.language == "zh" else "English"

        base = f"""
任务：为PPT主题"{session.topic}"生成【{step_name}】的具体内容，输出JSON对象或结构化Markdown。

当前步骤：{step} - {step_name}
内容类型：{content_type}
输出语言：{lang_label}

要求：
1) 内容具体可执行，避免空泛描述；2) 与前序保持一致；3) 推荐输出标准JSON对象，字段清晰（如 chapters/items/points 等）；4) 目标质量≥{self.quality_threshold}
"""

        if step > 0 and session.step_results:
            prev = session.step_results[-1].get("content", {})
            try:
                prev_json = json.dumps(prev, ensure_ascii=False)[:1000]
            except Exception:
                prev_json = str(prev)[:1000]
            base += f"\n前一步骤输出（节选）：\n{prev_json}\n请在本步深化与扩展。\n"

        if session.reference_content and step == 0:
            base += f"\n参考材料（节选）：\n{session.reference_content[:1000]}\n请适当融入相关信息。\n"

        base += "\n请直接给出内容，不要解释。"
        return base.strip()

    def _parse_response_as_json_or_text(self, response: str) -> Any:
        text = (response or "").strip()
        if not text:
            return {"message": "空响应"}
        # 尝试解析为 JSON 对象或数组
        try:
            if text.startswith("{") and text.endswith("}"):
                return json.loads(text)
            if text.startswith("[") and text.endswith("]"):
                return json.loads(text)
            # 从文本中抽取最外层 JSON
            import re

            m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
        except Exception:
            pass
        # 退化为纯文本
        return {"text": text}

    def _assess_step_quality(self, content: Any, session: SessionState, step: int) -> float:
        # 简化质量评估：结构性 + 字数/键数 + 与主题相关性（粗略）
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

            # 长度与可读性
            ln = len(text)
            score += min(0.35, ln / 4000.0)  # 长度 0~0.35

            # 主题词匹配
            topic = session.topic
            if topic and topic[:8] in text:
                score += 0.15

            # 轻微噪声项
            score += 0.1  # 偏移，避免过低
        except Exception:
            score = 0.5

        return round(max(0.0, min(score, 1.0)), 3)

    def _extract_convergence_signals(self, content: Any) -> Dict[str, Any]:
        try:
            if isinstance(content, dict):
                has_structure = any(k in content for k in ["chapters", "items", "sections", "points"])
            elif isinstance(content, list):
                has_structure = True
            else:
                has_structure = False
            return {"has_structure": has_structure}
        except Exception:
            return {"has_structure": False}

    def _build_final_outline(self, session: SessionState) -> Dict[str, Any]:
        # 简单汇总最近一步作为“最终完成”，并带上摘要
        last = session.step_results[-1] if session.step_results else {}
        summary = {
            "total_steps": session.current_step,
            "avg_quality": round(sum(session.quality_scores) / max(1, len(session.quality_scores)), 3),
        }
        return {
            "step": max(session.current_step - 1, 0),
            "step_name": "最终完善与总结",
            "content": {"summary": summary, "final": last.get("content")},
            "quality_score": last.get("quality_score", 0.85),
            "convergence_signals": {"converged": True},
            "content_type": "finalization",
            "execution_time": last.get("execution_time", 0.0),
            "status": "finalized",
        }


# 全局实例
outline_state_engine = OutlineStateEngine()

