from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.agent.md_slide_writer_agent import MdSlideWriterAgent
from app.agent.report_agents import (ReportResearchAgent, ReportSearchAgent,
                                     TocGeneratorAgent)
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.services.execution_log_service import log_execution_event
from app.tool.markdown_document import MarkdownDocumentTool


def _sanitize_filename(topic: str) -> str:
    sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "slides"
    return f"{sanitized}.md"


def _default_reports_path(topic: str) -> Path:
    return Path("reports") / _sanitize_filename(topic)


async def generate_marp_markdown_from_steps(
    *,
    topic: str,
    language: Optional[str] = None,
    filepath: Optional[str] = None,
    reference_content: Optional[str] = None,
    reference_sources: Optional[List[str]] = None,
) -> dict:
    target_path = filepath or str(_default_reports_path(topic))

    # Normalize to absolute path
    from app.config import config
    base = config.workspace_root
    candidate = Path(target_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.suffix.lower() != ".md":
        candidate = candidate.with_suffix(".md")
    abs_path = str(candidate)

    log_execution_event(
        "report_gen",
        "Initializing TocGeneratorAgent for slides",
        {"topic": topic, "language": language, "filepath": abs_path},
    )

    # Generate professional TOC using TocGeneratorAgent
    toc_generator = TocGeneratorAgent(
        language=language or "zh",
        topic=topic,
        reference_summary=(reference_content[:2000] if reference_content else None),
    )

    # Clamp token budget if present
    try:
        if hasattr(toc_generator, "llm") and hasattr(toc_generator.llm, "max_tokens"):
            toc_generator.llm.max_tokens = min(int(toc_generator.llm.max_tokens or 1024), 2048)
    except Exception:
        pass

    toc_result = await toc_generator.run("")
    toc_body = toc_result.strip() if toc_result else "1. 引言\n2. 主要内容\n3. 结论\n4. Q&A"

    log_execution_event(
        "report_gen",
        "TOC generated for slides",
        {"toc_length": len(toc_body)},
    )

    # Construct simple 2-step plan: research and write
    plan_steps: list[str] = [
        f"[RESEARCH] 收集研究资料 — 针对'{topic}'主题进行深入研究和信息收集",
        f"[MD_WRITER] 汇编成 Marp Markdown 幻灯片并写入目标文件"
    ]

    # default background image inside workspace
    try:
        from app.config import config as _cfg
        default_bg_abs = str((_cfg.workspace_root / "templates" / "template.jpg").resolve())
    except Exception:
        default_bg_abs = None

    # Try to load a style template from workspace/templates/marp_template.md
    front_matter_text: Optional[str] = None
    try:
        template_path = (_cfg.workspace_root / "templates" / "marp_template.md")
        if template_path.exists():
            front_matter_text = template_path.read_text(encoding="utf-8")
    except Exception:
        front_matter_text = None

    # Inject backgroundImage if not present
    # Use relative path from the target md directory to improve portability
    md_dir = Path(abs_path).parent
    default_bg_rel = None
    if default_bg_abs and os.path.exists(default_bg_abs):
        try:
            default_bg_rel = os.path.relpath(default_bg_abs, start=str(md_dir))
        except Exception:
            default_bg_rel = default_bg_abs
    if front_matter_text and default_bg_rel and "backgroundImage:" not in front_matter_text:
        if "style:" in front_matter_text:
            front_matter_text = front_matter_text.replace("style:", f"backgroundImage: url('{default_bg_rel}')\nstyle:")
        else:
            front_matter_text = front_matter_text.replace("\n---\n", f"\nbackgroundImage: url('{default_bg_rel}')\n---\n")

    agents: Dict[str, object] = {
        "research": ReportResearchAgent(),
        "search": ReportSearchAgent(),
        "md_writer": MdSlideWriterAgent(
            language=language or "zh",
            filepath=abs_path,
            title=topic,
            toc_body=toc_body,
            reference_summary=(reference_content[:3000] if reference_content else None),
            background_image=default_bg_rel,
            style_front_matter=front_matter_text,
        ),
    }

    # Clamp max tokens if present
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
        title=f"MD Slides Plan: {topic[:60]}",
        steps=plan_steps,
    )

    log_execution_event(
        "report_gen",
        "MD slides plan created",
        {"plan_id": flow.active_plan_id, "steps": len(plan_steps)},
    )

    summary = await flow.execute("")

    # Append combined references slide based on notes + upload filenames
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
        extra_sources = reference_sources or []
        all_sources = list(dict.fromkeys(urls + extra_sources))
        if all_sources:
            md_tool = MarkdownDocumentTool()
            bullets = "\n".join([f"- {s}" for s in all_sources])
            references_slide = f"\n---\n\n# 参考资料\n\n{bullets}\n"
            await md_tool.execute(filepath=abs_path, content=references_slide, append=True)
            log_execution_event(
                "report_gen",
                "References slide appended (md)",
                {"count": len(all_sources)},
            )
    except Exception as e:
        logger.warning(f"Append references slide failed: {e}")

    # Fallback: ensure file exists
    try:
        target = Path(abs_path)
        if (not target.exists()) or target.stat().st_size < 200:
            md_tool = MarkdownDocumentTool()
            if front_matter_text:
                fm = front_matter_text
            else:
                bg_line = f"backgroundImage: url('{default_bg_rel}')\n" if default_bg_rel else ""
                fm = (
                    "---\nmarp: true\ntheme: gaia\npaginate: true\nbackgroundColor: #fff\n" +
                    bg_line +
                    "style: |\n  section { font-family: 'Helvetica Neue', 'Microsoft YaHei', sans-serif; font-size: 26px; padding: 50px; color: #333; }\n  p, li { line-height: 1.4; }\n  table { font-size: 24px; }\n  div.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: center; }\n  div.columns-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }\n  div.left-narrow { display: grid; grid-template-columns: 30% 65%; gap: 5%; }\n  div.card { background: #f8f9fa; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); text-align: center; border-top: 5px solid #0066cc; }\n  img { border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); width: 100%; }\n  h1 { color: #004488; }\n  h2 { color: #0066cc; }\n---\n\n"
                )
            boilerplate = (
                fm + f"# {topic}\n\n---\n\n# 目录 Agenda\n\n{toc_body}\n"
            )
            await md_tool.execute(filepath=abs_path, content=boilerplate, append=False)
            log_execution_event(
                "report_gen",
                "Fallback MD created",
                {"filepath": abs_path},
            )
    except Exception:
        pass

    # Try to convert MD to PPTX with marp and delete MD afterwards
    final_path = abs_path
    try:
        md_path = Path(abs_path)
        if md_path.exists() and md_path.suffix.lower() == ".md":
            pptx_path = md_path.with_suffix(".pptx")

            async def _run(cmd: list[str], cwd: Path):
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(cwd),
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                except asyncio.TimeoutError:
                    proc.kill()
                    raise
                return proc.returncode, stdout.decode(), stderr.decode()

            code, out, err = await _run(["marp", md_path.name, "-o", pptx_path.name, "--allow-local-files"], md_path.parent)
            if code == 0 and pptx_path.exists():
                try:
                    md_path.unlink()
                except Exception:
                    pass
                final_path = str(pptx_path)
                log_execution_event("report_gen", "Marp conversion succeeded", {"pptx": final_path})
            else:
                log_execution_event("report_gen", "Marp conversion failed", {"returncode": code, "stderr": err[-400:]})
    except FileNotFoundError:
        log_execution_event("report_gen", "Marp CLI not found; kept MD", {})
    except Exception as e:
        log_execution_event("report_gen", "Marp conversion error", {"error": str(e)})

    return {
        "status": "completed",
        "filepath": final_path,
        "title": topic,
        "agent_summary": summary or "",
    }
