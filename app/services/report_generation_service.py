import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.agent.report_agents import (ReportResearchAgent, ReportSearchAgent,
                                     ReportWriterAgent, TocGeneratorAgent)
from app.flow.planning import PlanningFlow
from app.logger import logger
from app.services.document_service import DocumentGenerator
from app.services.execution_log_service import log_execution_event
from app.tool.word_document import WordDocumentTool


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
    toc_body = toc_result.strip() if toc_result else "1. 引言\n2. 正文\n3. 结论\n4. 参考文献"

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
        # Match main chapters (e.g., "1. 章节标题")
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

    # Step 3: Parallel chapter content generation
    import asyncio

    from app.agent.report_agents import ChapterContentAgent

    # Create chapter content agents for parallel execution
    chapter_tasks = []
    for i, chapter in enumerate(chapters[:5]):  # Limit to 5 chapters
        agent = ChapterContentAgent(
            language=language or "zh",
            topic=topic,
            chapter_number=chapter['number'],
            chapter_title=chapter['title'],
            sections=chapter['sections'],
            reference_summary=(reference_content[:2000] if reference_content else None),
            previous_chapters=None if i == 0 else f"已生成第{i}章内容"
        )

        # Clamp token budget
        try:
            if hasattr(agent, "llm") and hasattr(agent.llm, "max_tokens"):
                agent.llm.max_tokens = min(int(agent.llm.max_tokens or 1024), 4096)
        except Exception:
            pass

        chapter_tasks.append(agent.run(""))

    log_execution_event(
        "report_gen",
        "Starting parallel chapter generation",
        {"chapters_count": len(chapter_tasks)},
    )

    # Execute all chapter generation tasks in parallel
    chapter_results = await asyncio.gather(*chapter_tasks, return_exceptions=True)

    # Extract chapter contents from results
    chapter_contents = []
    for i, result in enumerate(chapter_results):
        if isinstance(result, Exception):
            logger.warning(f"Chapter {i+1} generation failed: {result}")
            chapter_contents.append(f"第{i+1}章内容生成失败，请手动补充。")
        else:
            chapter_contents.append(result.strip() if result else f"第{i+1}章内容生成为空，请手动补充。")

    log_execution_event(
        "report_gen",
        "Parallel chapter generation completed",
        {"successful_chapters": len([c for c in chapter_contents if not c.startswith("第") and "失败" in c])},
    )

    # Step 4: Sequential document writing
    word_tool = WordDocumentTool()

    # Write TOC and first chapter
    first_chapter_content = chapter_contents[0] if chapter_contents else ""
    await word_tool.execute(
        filepath=abs_path,
        document_title=topic,
        sections=[
            {"heading": "内容目录", "level": 1, "content": toc_body},
            {"heading": f"第{chapters[0]['number']}章 {chapters[0]['title']}", "level": 1, "content": first_chapter_content}
        ],
        append=False,
    )

    # Write remaining chapters sequentially
    for i in range(1, min(len(chapter_contents), len(chapters))):
        if i < len(chapter_contents) and i < len(chapters):
            await word_tool.execute(
                filepath=abs_path,
                sections=[{
                    "heading": f"第{chapters[i]['number']}章 {chapters[i]['title']}",
                    "level": 1,
                    "content": chapter_contents[i]
                }],
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

    log_execution_event(
        "report_gen",
        "Parallel report generation completed",
        {
            "filepath": abs_path,
            "chapters_generated": len(chapter_contents),
            "with_overview": overview_section is not None,
            "with_references": bool(reference_sources)
        },
    )

    summary = f"并行生成了{len(chapters)}个章节，包含目录、正文、参考概述和参考文献"

    return {
        "status": "completed",
        "filepath": abs_path,
        "title": topic,
        "agent_summary": summary,
    }
