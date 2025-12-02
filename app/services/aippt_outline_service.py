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

    prompt_template = f"""任务：为主题 "{topic}" 生成 PPT 大纲，输出 **唯一且完整的 JSON 对象**，严格遵守下面的结构和约束。不要输出任何多余文本、注释或代码块 —— 仅返回 JSON。

输出格式（必须）：
{{
  "status": "ok" | "error",
  "slides": [ ... ],            // 当 status=="ok" 时为页面数组
  "meta": {{ "topic": "...", "language": "zh" }}
  // 当 status=="error" 时，返回 {{ "status":"error", "reason":"解释原因", "partial": {{... 可选}} }}
}}

页面类型（slides 中元素）只允许下列 type 值并符合相应 data 结构：

1) cover:
{{
  "type": "cover",
  "data": {{
    "title": "PPT 标题",
    "text": "副标题或简短描述（<= 50 字）"
  }}
}}

2) contents:   // 目录页，items 数组长度必须为 4 或 5
{{
  "type": "contents",
  "data": {{
    "items": ["章节1 标题", "章节2 标题", "..."]
  }}
}}

3) transition:
{{
  "type": "transition",
  "data": {{
    "title": "章节标题",
    "items": ["要点1 标题", "要点2 标题", "要点3 标题"],  // 恰好 3 个
    "text": "一句 20~60 字的串联总结（不超过 80 字）"
  }}
}}

4) content:  // 每个 content 的 items 数量必须为 1
{{
  "type": "content",
  "data": {{
    "title": "页面标题",
    "items": [
      {{
        "title": "要点标题",
        "text": "要点说明（<= 100 字）",
        "case": "案例说明（建议 80~150 字；如果整套幻灯片页数 > 12，则把案例缩短到 <= 80 字）"
      }}
    ]
  }}
}}

5) end:
{{ "type": "end", "data": {{}} }}

关键约束（Machine-check，必须满足）：
- slides 数组必须按顺序： cover → contents → (transition + N * content)+ → end
  - 其中每个 contents.items 中的章节数（4或5）与后续 transition 的数量一致；
  - 对于每个 transition，其后应至少跟随 1 个 content（通常 3 个 content 对应 transition.items 的 3 要点）；但总体上，每个目录项应对应一组 transition + 至少 1 content。
- contents.items 的长度必须是 5（严格）。
- 每个 transition.items 必须有且恰好 3 个要点字符串。
- 每个 content.data.items 必须恰好包含 1 个对象，包含 title、text、case 三个字段。
- 所有 text/case 字段长度限制请遵守上面说明。
- 若任何约束无法满足，请返回 {{"status":"error","reason":"...","partial": <可选已生成内容>}} 并停止。

语言说明：
- 输出语言请使用 "{language}"（只影响页面文本），不要混用语言。

参考资料：
- 若有参考材料，请只采纳关键信息并融入章节标题或要点，切勿逐字复制。若输入参考材料无法在约束下全部使用，则优先保留与主题最相关的要点。

注意：
- 只返回 JSON；不要包含额外解释或示例。
- 尽量使每个页面简洁、适合幻灯片展示（句子短、要点清晰）。

现在请生成满足上述约束的完整 JSON 并把 topic/参考材料整合进去。
"""

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
    """Extract slides array from LLM response.

    Supports two shapes:
    - legacy: a JSON array of slide objects
    - new: {"status":"ok","slides":[...],"meta":{...}} or {"status":"error",...}
    """
    text = response.strip()
    # First try full JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            status = str(parsed.get("status", "")).lower()
            if status == "ok" and isinstance(parsed.get("slides"), list):
                return list(parsed.get("slides") or [])
            if status == "error":
                reason = parsed.get("reason") or "LLM returned error"
                raise ValueError(f"Outline generation error: {reason}")
            # Some models may wrap slides under a different root without status
            if isinstance(parsed.get("slides"), list):
                return list(parsed.get("slides") or [])
    except Exception:
        pass

    # Fallback: find a top-level array in the text
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    raise ValueError("No valid slides JSON found in LLM response")


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
            # Clamp TOC items to at most 5（严格上限，提示要求 4-5）
            try:
                items = slide["data"].get("items") or []
                if isinstance(items, list) and len(items) > 5:
                    slide["data"]["items"] = items[:5]
            except Exception:
                pass
        elif slide_type == "end":
            has_end = True
            # End slide doesn't need data
        elif slide_type in ["transition", "content"]:
            # Ensure these have basic structure
            if "data" not in slide:
                slide["data"] = {}
            if slide_type == "content" and "items" not in slide["data"]:
                slide["data"]["items"] = []
            # New spec: content.items MUST be exactly 1 (keep first if multiple)
            if slide_type == "content":
                try:
                    items = slide["data"].get("items") or []
                    if isinstance(items, list):
                        if len(items) >= 1:
                            slide["data"]["items"] = items[:1]
                        else:
                            slide["data"]["items"] = []
                except Exception:
                    pass
            # New spec: transition.items should be exactly 3 (truncate if longer)
            if slide_type == "transition":
                try:
                    titems = slide["data"].get("items") or []
                    if isinstance(titems, list) and len(titems) > 3:
                        slide["data"]["items"] = titems[:3]
                except Exception:
                    pass

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
    """Rebuild outline to follow: cover → contents → (transition + N*content)+ → end.

    - contents.items is clamped to <= 5
    - Each transition is followed by up to 3 content slides (min 1). For each content,
      ensure data.items has exactly 1 object. Transition.data.items is exactly 3
      titles (pad by repeating last if fewer).
    """
    if not outline:
        return outline
    toc_items = _extract_toc_items(outline)
    if not toc_items:
        return outline
    toc_items = toc_items[:5]

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

    new_outline: List[dict] = []
    if cover:
        new_outline.append(cover)
    if contents:
        try:
            cdata = contents.setdefault("data", {})
            cdata["items"] = toc_items
        except Exception:
            pass
        new_outline.append(contents)

    # All content slides to reuse
    remaining_contents = [
        s for s in other_slides if isinstance(s, dict) and s.get("type") == "content"
    ]

    for idx_toc, item in enumerate(toc_items, start=1):
        # Take up to 3 content slides for this toc item
        group: List[dict] = []
        for _ in range(3):
            if remaining_contents:
                group.append(remaining_contents.pop(0))
            else:
                break
        if not group:
            group = [{"type": "content", "data": {"title": item, "items": []}}]

        titles: List[str] = []
        for j, c in enumerate(group, start=1):
            try:
                cdata = c.setdefault("data", {})
                if not cdata.get("title"):
                    cdata["title"] = item
                items = cdata.get("items") or []
                if isinstance(items, list):
                    if len(items) >= 1:
                        cdata["items"] = items[:1]
                    else:
                        cdata["items"] = [
                            {"title": f"{item} - 要点{j}", "text": "", "case": ""}
                        ]
                it = cdata["items"][0]
                t = (it.get("title") or "").strip() if isinstance(it, dict) else str(it)
                titles.append(t or f"要点{j}")
            except Exception:
                titles.append(f"要点{j}")

        # Transition with exactly 3 titles
        if len(titles) < 3:
            titles = (
                titles + [titles[-1]] * (3 - len(titles))
                if titles
                else ["要点1", "要点2", "要点3"]
            )
        titles = titles[:3]
        t_text = "；".join(titles)
        new_outline.append(
            {
                "type": "transition",
                "data": {"title": item, "items": titles, "text": t_text},
            }
        )
        new_outline.extend(group)

    if end_slide is None:
        end_slide = {"type": "end"}
    new_outline.append(end_slide)

    return new_outline


def _create_fallback_outline(topic: str, language: str) -> List[dict]:
    """Create a basic fallback outline when generation fails (conforms to new spec)."""
    if language == "zh":
        toc = ["概述", "主体", "扩展", "总结"]
        slides: List[dict] = []
        slides.append(
            {"type": "cover", "data": {"title": topic, "text": "自动生成的演示文稿"}}
        )
        slides.append({"type": "contents", "data": {"items": toc[:5]}})
        for sec in toc[:5]:
            t_items = ["要点1", "要点2", "要点3"]
            slides.append(
                {
                    "type": "transition",
                    "data": {
                        "title": sec,
                        "items": t_items,
                        "text": "；".join(t_items),
                    },
                }
            )
            for k in range(3):
                slides.append(
                    {
                        "type": "content",
                        "data": {
                            "title": sec,
                            "items": [
                                {"title": t_items[k], "text": "简要说明", "case": ""}
                            ],
                        },
                    }
                )
        slides.append({"type": "end", "data": {}})
        return slides


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
