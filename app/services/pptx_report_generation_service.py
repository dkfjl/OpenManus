from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from app.agent.pptx_report_agents import (
    PptxResearchAgent,
    PptxSearchAgent,
    PptxWriterAgent,
)
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.services.execution_log_service import log_execution_event
from app.tool.pptx_presentation import PptxPresentationTool


def _sanitize_filename(topic: str) -> str:
    sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "presentation"
    return f"{sanitized}.pptx"


def _default_reports_path(topic: str) -> Path:
    return Path("reports") / _sanitize_filename(topic)


async def generate_pptx_report_from_steps(
    *,
    topic: str,
    steps: List[dict],
    language: Optional[str] = None,
    filepath: Optional[str] = None,
    reference_content: Optional[str] = None,
    reference_sources: Optional[List[str]] = None,
) -> dict:
    target_path = filepath or str(_default_reports_path(topic))

    # Normalize to absolute path (do not reuse docx-only helpers)
    from app.config import config

    base = config.workspace_root
    candidate = Path(target_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.suffix.lower() != ".pptx":
        candidate = candidate.with_suffix(".pptx")
    abs_path = str(candidate)

    log_execution_event(
        "report_gen",
        "Initializing PPTX Report Agents",
        {"topic": topic, "language": language, "filepath": abs_path},
    )

    # Build a plain-text TOC for a dedicated TOC slide
    def _build_toc_body(steps: List[dict]) -> str:
        lines = ["目录", ""]
        for idx, s in enumerate(steps[:20], start=1):
            title = s.get("title") or "章节"
            desc = (s.get("descirption") or s.get("description") or "").strip()
            line = f"{idx}. {title}"
            if desc:
                line += f" —— {desc[:60]}"
            lines.append(line)
        return "\n".join(lines)

    toc_body = _build_toc_body(steps)

    # Convert thinking steps into plan lines
    def classify(title: str) -> str:
        t = (title or "").lower()
        if any(k in t for k in ["信息收集", "检索", "搜索", "调研", "search"]):
            return "search"
        if any(k in t for k in ["实现", "验证", "实验", "分析", "evaluate", "validate", "analysis"]):
            return "research"
        if any(k in t for k in ["总结", "交付", "写作", "撰写", "报告", "幻灯片"]):
            return "writer"
        return "research"

    plan_steps: list[str] = []
    for s in steps[:20]:
        title = s.get("title") or "任务"
        desc = s.get("descirption") or s.get("description") or ""
        agent_key = classify(title)
        flags = []
        detail_type = (s.get("detailType") or s.get("detail_type") or "").lower()
        if detail_type in {"image", "images", "chart", "diagram"}:
            flags.append("IMAGE")
        if detail_type in {"table", "tables"}:
            flags.append("TABLE")
        flag_str = (" " + " ".join(f"[{f}]" for f in flags)) if flags else ""
        plan_steps.append(f"[{agent_key.upper()}]{flag_str} {title} — {desc[:160]}")

    if not any("[WRITER]" in step for step in plan_steps):
        plan_steps.append(
            f"[WRITER] 整合与成文 — 将 Notes 汇编为幻灯片并写入 {abs_path}"
        )

    agents: Dict[str, object] = {
        "research": PptxResearchAgent(),
        "search": PptxSearchAgent(),
        "writer": PptxWriterAgent(
            language=language or "zh",
            filepath=abs_path,
            title=topic,
            toc_body=toc_body,
            reference_summary=(reference_content[:2000] if reference_content else None),
        ),
    }

    # Clamp token budget where applicable
    for _k, _agent in agents.items():
        try:
            if hasattr(_agent, "llm") and hasattr(_agent.llm, "max_tokens"):
                _agent.llm.max_tokens = min(int(_agent.llm.max_tokens or 1024), 4096)
        except Exception:
            pass

    flow = PlanningFlow(agents, primary_agent_key="research")

    await flow.planning_tool.execute(
        command="create",
        plan_id=flow.active_plan_id,
        title=f"PPTX Report Plan: {topic[:60]}",
        steps=plan_steps,
    )

    log_execution_event(
        "report_gen",
        "PPTX plan created",
        {"plan_id": flow.active_plan_id, "steps": len(plan_steps)},
    )

    summary = await flow.execute("")

    # Extract references from notes and append dedicated slides
    try:
        plan = flow.planning_tool.plans.get(flow.active_plan_id, {})
        notes = plan.get("step_notes", []) or []
        import re as _re

        urls: list[str] = []
        seen = set()
        for text in notes:
            if not isinstance(text, str):
                continue
            for m in _re.findall(r"https?://[^\s)]+", text):
                u = m.rstrip('.,;')
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
        all_sources = list(dict.fromkeys(urls + (reference_sources or [])))
        if all_sources:
            # Chunk sources across multiple slides for readability (<=12 bullets/slide)
            target = Path(abs_path)
            tool = PptxPresentationTool()
            chunk = 12
            slides = []
            for i in range(0, len(all_sources), chunk):
                part = all_sources[i : i + chunk]
                slides.append({
                    "title": "参考资料" if i == 0 else f"参考资料（续 {i//chunk+1}）",
                    "bullets": part,
                })
            await tool.execute(
                filepath=abs_path,
                slides=slides,
                append=True,
            )
            log_execution_event(
                "report_gen",
                "References slides appended (urls + uploads)",
                {"count": len(all_sources)},
            )
    except Exception as e:
        logger.warning(f"References extraction/append failed: {e}")

    # Fallback: ensure a PPTX is created even if writer failed
    try:
        target = Path(abs_path)
        tool = PptxPresentationTool()
        if (not target.exists()) or (target.exists() and target.stat().st_size < 3_000):
            sections: List[dict] = []
            # Directory/TOC as the first slide body
            sections.append({"heading": "目录", "content": toc_body})
            for i, s in enumerate(steps[:15]):
                heading = s.get("title") or f"第{i+1}步"
                desc = s.get("descirption") or s.get("description") or ""
                sections.append({
                    "heading": heading,
                    "content": desc,
                })
            await tool.execute(
                filepath=abs_path,
                presentation_title=topic,
                sections=sections,
                append=False,
            )
            log_execution_event(
                "report_gen",
                "Fallback PPTX created",
                {"filepath": abs_path, "sections": len(sections)},
            )
    except Exception as e:
        logger.warning(f"Fallback PPTX writer failed: {e}")

    # reference slides are handled above by combining urls + uploaded sources

    return {
        "status": "completed",
        "filepath": abs_path,
        "title": topic,
        "agent_summary": summary or "",
    }
