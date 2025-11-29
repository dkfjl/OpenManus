from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.llm import LLM
from app.logger import logger
from app.schema import Message
from app.services.execution_log_service import log_execution_event


def _sanitize_filename(topic: str) -> str:
    """Sanitize topic for filename generation"""
    sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "presentation"
    return f"{sanitized}.pptx"


def _default_reports_path(topic: str) -> str:
    """Generate default file path for PPTX"""
    from pathlib import Path

    return str(Path("reports") / _sanitize_filename(topic))


async def generate_aippt_outline(
    *,
    topic: str,
    language: Optional[str] = None,
    reference_content: Optional[str] = None,
) -> dict:
    """
    Generate PPT outline in AIPPT JSON format based on user content.

    Args:
        topic: The main topic/content for the PPT
        language: Output language (zh, en, etc.)
        reference_content: Optional reference material to incorporate

    Returns:
        Dict containing the outline JSON and metadata
    """
    language = language or "zh"

    log_execution_event(
        "aippt_outline",
        "Starting AIPPT outline generation",
        {"topic": topic[:100], "language": language},
    )
    # Also print a console log so users can see progress without reading JSONL
    logger.info(
        "[AIPPT] Start outline generation | topic='{}' | language={}",
        topic,
        language,
    )

    # Build the prompt template
    language_instruction = "请用中文" if language == "zh" else "Please use English"

    prompt_template = f"""{language_instruction}为"{topic}"生成PPT大纲。
要求：
1. 返回标准的JSON格式，符合PPTist的AIPPT类型定义
2. 包含封面页、目录页、过渡页、内容页、结束页
3. 每个内容页包含3个要点，每个要点不超过50字，并任意找一个点引用案例说明
4. 内容要有逻辑性和层次性
5. 目录中的每一条目都必须在目录页之后依次对应两张页面：先 transition(标题=该目录条目)，再 content(标题建议与目录条目一致或更具体)；保证目录条目数量与随后 (transition+content) 组数完全一致；输出顺序严格为 cover → contents → (transition+content)* → end。

PPT页面类型定义：

1. 封面页 (cover):
{{
  "type": "cover",
  "data": {{
    "title": "PPT标题",
    "text": "副标题或描述"
  }}
}}

2. 目录页 (contents):
{{
  "type": "contents",
  "data": {{
    "items": ["目录项1", "目录项2", "目录项3"]
  }}
}}

3. 过渡页 (transition):
{{
  "type": "transition",
  "data": {{
    "title": "章节标题",
    "text": "章节描述"
  }}
}}

4. 内容页 (content):
{{
  "type": "content",
  "data": {{
    "title": "页面标题",
    "items": [
      {{
        "title": "要点标题",
        "text": "要点详细说明"
      }}
    ]
  }}
}}

5. 结束页 (end):
{{
  "type": "end"
}}

请生成完整的PPT大纲JSON数组，包含所有页面类型。"""

    # Add reference content if provided
    if reference_content and reference_content.strip():
        prompt_template += f"\n\n参考材料：\n{reference_content[:2000]}"

    # Auto-gather web materials (text snippets, candidate tables and image URLs)
    try:
        web_text, web_tables, web_images = _auto_gather_web_assets(topic)
        if web_text:
            prompt_template += "\n\n参考网页摘要：\n" + web_text
        if web_tables:
            # include up to 2 small tables json in prompt
            import json as _json

            tables_json = _json.dumps(web_tables[:2], ensure_ascii=False)
            prompt_template += "\n\n参考网页表格JSON（节选）：\n" + tables_json
        if web_images:
            prompt_template += "\n\n参考图片URL（节选）：\n- " + "\n- ".join(
                web_images[:5]
            )
    except Exception:
        pass

    try:
        # Initialize LLM client
        llm = LLM()

        # Generate outline
        # NOTE: LLM.ask expects a list of messages, not a raw string.
        # Passing a string leads to iterating over characters and a TypeError
        # in LLM.format_messages. Wrap the prompt as a user message.
        response = await llm.ask(
            [Message.user_message(prompt_template)],
            # Non-streaming makes it easier to parse the full JSON afterwards
            stream=False,
            temperature=0.2,
        )

        # Extract JSON from response
        outline_json = _extract_json_from_response(response)

        # Validate the outline structure
        validated_outline = _validate_outline(outline_json, topic)
        # Enforce TOC alignment: ensure (transition+content) pairs match contents items
        validated_outline = _enforce_toc_alignment(validated_outline, topic)

        log_execution_event(
            "aippt_outline",
            "AIPPT outline generated successfully",
            {"slides_count": len(validated_outline)},
        )
        # Print the whole outline to logs for visibility
        try:
            pretty_outline = json.dumps(validated_outline, ensure_ascii=False, indent=2)
        except Exception:
            pretty_outline = str(validated_outline)
        logger.info(
            "[AIPPT] Outline generated successfully ({} slides)\n{}",
            len(validated_outline),
            pretty_outline,
        )

        return {
            "status": "success",
            "outline": validated_outline,
            "topic": topic,
            "language": language,
        }

    except Exception as e:
        log_execution_event(
            "aippt_outline",
            "AIPPT outline generation failed",
            {"error": str(e)},
        )
        logger.error("[AIPPT] Outline generation failed: {}", e)

        # Return a fallback outline
        fallback_outline = _create_fallback_outline(topic, language)
        # Print fallback outline to logs for debugging/visibility
        try:
            pretty_fallback = json.dumps(fallback_outline, ensure_ascii=False, indent=2)
        except Exception:
            pretty_fallback = str(fallback_outline)
        logger.info(
            "[AIPPT] Using fallback outline ({} slides)\n{}",
            len(fallback_outline),
            pretty_fallback,
        )

        return {
            "status": "fallback",
            "outline": fallback_outline,
            "topic": topic,
            "language": language,
            "error": str(e),
        }


def _extract_json_from_response(response: str) -> List[dict]:
    """Extract JSON array from LLM response"""
    # Try to find JSON array in the response
    json_match = re.search(r"\[.*\]", response, re.DOTALL)

    if json_match:
        json_str = json_match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from match: {e}")
            raise ValueError("Invalid JSON format in LLM response")

    # Try to parse the entire response as JSON
    try:
        parsed = json.loads(response.strip())
        if isinstance(parsed, list):
            return parsed
        else:
            raise ValueError("Response is not a JSON array")
    except json.JSONDecodeError:
        raise ValueError("No valid JSON found in LLM response")


def _validate_outline(outline: List[dict], topic: str) -> List[dict]:
    """Validate and fix the outline structure"""
    if not outline:
        raise ValueError("Empty outline")

    validated = []

    # Ensure we have required slide types
    has_cover = False
    has_contents = False
    has_end = False

    for slide in outline:
        if not isinstance(slide, dict):
            continue

        slide_type = slide.get("type")
        if slide_type == "cover":
            has_cover = True
            # Ensure cover has required fields
            if "data" not in slide:
                slide["data"] = {}
            if "title" not in slide["data"]:
                slide["data"]["title"] = topic
            if "text" not in slide["data"]:
                slide["data"]["text"] = ""
        elif slide_type == "contents":
            has_contents = True
            # Ensure contents has required fields
            if "data" not in slide:
                slide["data"] = {}
            if "items" not in slide["data"]:
                slide["data"]["items"] = ["目录"]
        elif slide_type == "end":
            has_end = True
            # End slide doesn't need data
        elif slide_type in ["transition", "content"]:
            # Ensure these have basic structure
            if "data" not in slide:
                slide["data"] = {}
            if slide_type == "content" and "items" not in slide["data"]:
                slide["data"]["items"] = []

        validated.append(slide)

    # Add missing required slides
    if not has_cover:
        validated.insert(0, {"type": "cover", "data": {"title": topic, "text": ""}})

    if not has_contents:
        validated.insert(1, {"type": "contents", "data": {"items": ["目录"]}})

    if not has_end:
        validated.append({"type": "end"})

    return validated


def _extract_toc_items(outline: List[dict]) -> List[str]:
    for slide in outline:
        if isinstance(slide, dict) and slide.get("type") == "contents":
            data = slide.get("data", {}) or {}
            items = data.get("items", []) or []
            result: List[str] = []
            for it in items:
                if isinstance(it, str):
                    result.append(it.strip())
                elif isinstance(it, dict):
                    title = it.get("title") or it.get("text") or ""
                    if isinstance(title, str) and title.strip():
                        result.append(title.strip())
            return result
    return []


def _enforce_toc_alignment(outline: List[dict], topic: str) -> List[dict]:
    if not outline:
        return outline
    toc_items = _extract_toc_items(outline)
    if not toc_items:
        return outline

    # Keep cover, contents, collect the rest to reuse content pages if any
    cover = None
    contents = None
    end_slide = None
    other_slides: List[dict] = []
    for s in outline:
        t = s.get("type") if isinstance(s, dict) else None
        if t == "cover" and cover is None:
            cover = s
        elif t == "contents" and contents is None:
            contents = s
        elif t == "end":
            end_slide = s
        else:
            other_slides.append(s)

    # Rebuild sequence: cover → contents → (transition+content)* → end
    new_outline: List[dict] = []
    if cover:
        new_outline.append(cover)
    if contents:
        new_outline.append(contents)

    # Reuse existing content slides in order where possible
    remaining_contents = [
        s for s in other_slides if isinstance(s, dict) and s.get("type") == "content"
    ]

    for item in toc_items:
        # transition
        new_outline.append({"type": "transition", "data": {"title": item, "text": ""}})
        # content
        if remaining_contents:
            c = remaining_contents.pop(0)
            # If content lacks title, set it to item
            try:
                cdata = c.setdefault("data", {})
                if not cdata.get("title"):
                    cdata["title"] = item
            except Exception:
                pass
            new_outline.append(c)
        else:
            new_outline.append(
                {"type": "content", "data": {"title": item, "items": []}}
            )

    if end_slide is None:
        end_slide = {"type": "end"}
    new_outline.append(end_slide)

    return new_outline


def _create_fallback_outline(topic: str, language: str) -> List[dict]:
    """Create a basic fallback outline when generation fails"""
    if language == "zh":
        return [
            {"type": "cover", "data": {"title": topic, "text": "自动生成的演示文稿"}},
            {"type": "contents", "data": {"items": ["概述", "主要内容", "总结"]}},
            {
                "type": "content",
                "data": {
                    "title": "概述",
                    "items": [
                        {"title": "背景介绍", "text": "相关背景信息"},
                        {"title": "目标说明", "text": "本次演示的目标"},
                    ],
                },
            },
            {
                "type": "content",
                "data": {
                    "title": "主要内容",
                    "items": [
                        {"title": "核心要点", "text": "主要内容和分析"},
                        {"title": "详细说明", "text": "进一步的解释和说明"},
                    ],
                },
            },
            {
                "type": "content",
                "data": {
                    "title": "总结",
                    "items": [
                        {"title": "要点回顾", "text": "主要内容的总结"},
                        {"title": "展望", "text": "未来的发展方向"},
                    ],
                },
            },
            {"type": "end"},
        ]


def _auto_gather_web_assets(topic: str, max_pages: int = 2):
    """Search the web for the topic and collect small text snippets, simple tables and image URLs.

    Returns: (text_snippet: str, tables: List[dict], images: List[str])
    - tables use structure: {"title": str, "headers": [..], "rows": [[..],[..]]}
    - images: absolute URLs
    """
    from app.tool.web_search import WebSearch

    images: List[str] = []
    tables: List[Dict] = []
    texts: List[str] = []

    ws = WebSearch()
    # We do not fetch content here to re-fetch raw HTML for tables/images
    loop = asyncio.get_event_loop()
    search = loop.run_until_complete(
        ws.execute(query=topic, num_results=max_pages, fetch_content=False)
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    for res in search.results[:max_pages]:
        try:
            resp = requests.get(res.url, headers=headers, timeout=8)
            if resp.status_code != 200 or not resp.text:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # text snippet
            text = " ".join(soup.get_text(separator=" ", strip=True).split())
            if text:
                texts.append(text[:600])
            # images: prefer og:image and img[src]
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(urljoin(res.url, og.get("content")))
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if not src:
                    continue
                absu = urljoin(res.url, src)
                if any(
                    absu.lower().endswith(ext)
                    for ext in [".jpg", ".jpeg", ".png", ".webp"]
                ):
                    images.append(absu)
                if len(images) >= 8:
                    break
            # tables: first table
            for tb in soup.find_all("table")[:1]:
                headers_row = []
                first_tr = tb.find("tr")
                if tb.find_all("th"):
                    headers_row = [
                        th.get_text(strip=True)[:50] for th in tb.find_all("th")
                    ]
                elif first_tr:
                    headers_row = [
                        td.get_text(strip=True)[:50] for td in first_tr.find_all("td")
                    ]
                rows = []
                trs = tb.find_all("tr")
                # skip first row if used for headers
                start_idx = 1 if headers_row and len(trs) > 1 else 0
                for tr in trs[start_idx : start_idx + 5]:
                    row = [
                        td.get_text(strip=True)[:80] for td in tr.find_all(["td", "th"])
                    ]
                    if any(cell for cell in row):
                        rows.append(row)
                if headers_row or rows:
                    title = (
                        soup.title.string[:60]
                        if soup.title and soup.title.string
                        else res.title
                    )
                    tables.append(
                        {"title": title, "headers": headers_row, "rows": rows}
                    )
        except Exception:
            continue

    # de-dup images and trim
    uniq_images = []
    seen = set()
    for u in images:
        if u and u not in seen:
            uniq_images.append(u)
            seen.add(u)
        if len(uniq_images) >= 8:
            break

    text_snippet = ("\n\n".join(texts))[:1200]
    return text_snippet, tables, uniq_images
