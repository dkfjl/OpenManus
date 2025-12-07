import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.agent.report_agents import (
    ReportResearchAgent,
    ReportSearchAgent,
    ReportWriterAgent,
    TocGeneratorAgent,
    # newly used for subsection-level content
    
)
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.services.document_service import DocumentGenerator
from app.services.execution_log_service import log_execution_event
from app.tool.word_document import WordDocumentTool


def _clean_agent_text(text: str) -> str:
    """Remove execution-log artifacts like "Step 1:", "Terminated:" etc.

    This mirrors the cleaning logic used by ChapterContentAgent so that TOC
    or any plain-text agent output won't pollute parsing.
    """
    if not text:
        return ""

    t = text.strip()
    # Drop common leading prefixes
    prefixes = [
        "Step 1:", "Step 2:", "Step 3:",
        "Observed output of cmd", "Terminated:", "Assistant:", "ChapterContentAgent:",
    ]
    for p in prefixes:
        if t.startswith(p):
            t = t[len(p):].strip()

    # Remove noisy lines
    clean_lines = []
    for line in t.split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(m in s for m in [
            "Observed output", "executed:", "Search results for", "URL:", "Description:",
            "问题分析中", "Terminated:"
        ]):
            continue
        # If a line is like "Step N: 1. XXX" keep the part after the first chapter index
        # e.g., "Step 1: 1. Title" -> "1. Title"
        s = re.sub(r"^Step\s*\d+\s*:\s*", "", s)
        clean_lines.append(s)
    return "\n".join(clean_lines).strip()


def _default_reports_path(topic: str) -> Path:
    # Reuse DocumentGenerator's sanitization, but place under reports/
    filename = DocumentGenerator._default_filename(topic)  # e.g., sanitized.docx
    return Path("reports") / filename


async def generate_report_from_steps(
    *,
    topic: str,
    language: Optional[str] = None,
    fmt: str = "docx",
    filepath: Optional[str] = None,
    reference_content: Optional[str] = None,
    reference_sources: Optional[List[str]] = None,
) -> dict:
    if fmt.lower() != "docx":
        raise ValueError("当前仅支持 docx 格式")

    target_path = filepath or str(_default_reports_path(topic))

    # Resolve to absolute path inside workspace and ensure .docx suffix
    abs_path = str(DocumentGenerator._resolve_path(target_path))

    log_execution_event(
        "report_gen",
        "Starting parallel report generation",
        {"topic": topic, "language": language, "filepath": abs_path},
    )

    # Step 1: Generate TOC
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
    toc_raw = toc_result.strip() if toc_result else "1. 引言\n2. 正文\n3. 结论\n4. 参考文献"
    toc_body = _clean_agent_text(toc_raw)

    log_execution_event(
        "report_gen",
        "TOC generated",
        {"toc_length": len(toc_body)},
    )

    # Step 2: Parse TOC to extract chapter structure
    toc_lines = [line.strip() for line in toc_body.split('\n') if line.strip()]
    chapters = []
    current_chapter = None

    for line in toc_lines:
        # Match main chapters (e.g., "1. 章节标题") allowing any leading noise already trimmed
        chapter_match = re.match(r'^(\d+)\.\s+(.+)$', line)
        if chapter_match:
            if current_chapter:
                chapters.append(current_chapter)
            current_chapter = {
                "number": int(chapter_match.group(1)),
                "title": chapter_match.group(2).strip(),
                "sections": []
            }
        # Match sections (e.g., "  1.1 小节标题" or "1.1 小节标题")
        elif current_chapter:
            section_match = re.match(r'^\s*(\d+\.\d+)\s+(.+)$', line)
            if section_match:
                section_title = section_match.group(2).strip()
                current_chapter["sections"].append(section_title)

    if current_chapter:
        chapters.append(current_chapter)

    # Fallback: if parsing failed or no chapters found, create default structure
    if not chapters:
        chapters = [
            {"number": 1, "title": "引言与背景", "sections": ["研究背景", "问题陈述", "研究目标"]},
            {"number": 2, "title": "现状分析", "sections": ["当前状况", "主要问题", "影响因素"]},
            {"number": 3, "title": "解决方案", "sections": ["总体思路", "具体措施", "实施路径"]},
            {"number": 4, "title": "实施效果", "sections": ["预期成果", "风险评估", "应对策略"]},
            {"number": 5, "title": "结论与展望", "sections": ["主要结论", "发展建议", "未来展望"]}
        ]

    # Step 3: Parallel subsection content generation
    import asyncio
    from app.agent.report_agents import SubsectionContentAgent

    subsection_tasks = []
    subsection_agents = []
    index_map = []  # (chapter_idx, subsection_idx)
    limited_chapters = chapters[:5]
    for ci, chapter in enumerate(limited_chapters):
        sections = chapter.get("sections") or []
        for si, sec_title in enumerate(sections[:3]):  # cap to 3 per design
            agent = SubsectionContentAgent(
                language=language or "zh",
                topic=topic,
                chapter_number=chapter["number"],
                chapter_title=chapter["title"],
                subsection_code=f"{chapter['number']}.{si+1}",
                subsection_title=sec_title,
                reference_summary=(reference_content[:2000] if reference_content else None),
                previous_chapters=None if ci == 0 else f"已生成第{limited_chapters[ci-1]['number']}章概述",
            )
            try:
                if hasattr(agent, "llm") and hasattr(agent.llm, "max_tokens"):
                    agent.llm.max_tokens = min(int(getattr(agent.llm, "max_tokens", 1024) or 1024), 2048)
            except Exception:
                pass
            subsection_tasks.append(agent.run(""))
            subsection_agents.append(agent)
            index_map.append((ci, si))

    log_execution_event(
        "report_gen",
        "Starting parallel subsection generation",
        {"subsections_count": len(subsection_tasks)},
    )

    subsection_results = await asyncio.gather(*subsection_tasks, return_exceptions=True)

    # Organize subsection content into chapters
    subsection_contents: List[List[str]] = [
        [""] * min(3, len(ch.get("sections") or [])) for ch in limited_chapters
    ]
    for (ci, si), result in zip(index_map, subsection_results):
        if isinstance(result, Exception):
            logger.warning(f"Subsection {ci+1}.{si+1} generation failed: {result}")
            subsection_contents[ci][si] = f"第{limited_chapters[ci]['number']}.{si+1}节内容生成失败，请手动补充。"
        else:
            subsection_contents[ci][si] = (result or "").strip() or f"第{limited_chapters[ci]['number']}.{si+1}节内容生成为空，请手动补充。"

    log_execution_event(
        "report_gen",
        "Parallel subsection generation completed",
        {"chapters": len(limited_chapters), "subsections_generated": sum(len(x) for x in subsection_contents)},
    )

    # Step 4: Document writing with chapters and subsections
    word_tool = WordDocumentTool()
    # First write: title + TOC only
    await word_tool.execute(
        filepath=abs_path,
        document_title=topic,
        sections=[{"heading": "内容目录", "level": 1, "content": toc_body}],
        append=False,
    )

    # Then write each chapter heading and its subsections
    for i, ch in enumerate(limited_chapters):
        sections_payload = []
        sections_payload.append({
            "heading": f"第{ch['number']}章 {ch['title']}",
            "level": 1,
        })
        for si, sec_title in enumerate((ch.get("sections") or [])[:3]):
            content = subsection_contents[i][si] if si < len(subsection_contents[i]) else ""
            sections_payload.append({
                "heading": f"{ch['number']}.{si+1} {sec_title}",
                "level": 2,
                "content": content,
            })
        await word_tool.execute(
            filepath=abs_path,
            sections=sections_payload,
            append=True,
        )

    # Step 5: Add overview and references if applicable
    overview_section = None
    if reference_content and reference_content.strip():
        overview_section = {
            "heading": "参考内容概述",
            "level": 1,
            "content": f"基于上传的参考资料，以下是对关键信息的概述：\n{reference_content[:2000]}"
        }
        await word_tool.execute(
            filepath=abs_path,
            sections=[overview_section],
            append=True,
        )

    # Step 6: Add references
    if reference_sources:
        sources_text = "\n".join([f"- {source}" for source in reference_sources])
        references_section = {
            "heading": "参考文献",
            "level": 1,
            "content": f"本次报告参考了以下资料来源：\n{sources_text}"
        }
        await word_tool.execute(
            filepath=abs_path,
            sections=[references_section],
            append=True,
        )

    # Step 7: Append searched URL list gathered during subsection generation
    try:
        viewed_urls: List[str] = []
        seen_urls = set()
        for ag in subsection_agents:
            for u in getattr(ag, "viewed_urls", []) or []:
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    viewed_urls.append(u)
        if viewed_urls:
            await word_tool.execute(
                filepath=abs_path,
                sections=[{
                    "heading": "搜索中查看的 URL",
                    "level": 1,
                    "bullets": viewed_urls,
                }],
                append=True,
            )
    except Exception as _e:
        logger.warning(f"Append viewed URLs failed: {_e}")

    log_execution_event(
        "report_gen",
        "Parallel report generation completed",
        {
            "filepath": abs_path,
            "chapters_generated": len(limited_chapters),
            "subsections_generated": sum(len(x) for x in subsection_contents),
            "with_overview": overview_section is not None,
            "with_references": bool(reference_sources)
        },
    )

    summary = (
        f"并行生成了{len(limited_chapters)}章的分节内容，"
        f"包含目录、各章标题、各节正文、参考概述、参考文献和搜索URL清单"
    )

    return {
        "status": "completed",
        "filepath": abs_path,
        "title": topic,
        "agent_summary": summary,
    }
