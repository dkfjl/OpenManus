from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.llm import LLM
from app.logger import logger
from app.schema import Message
from app.services.execution_log_service import log_execution_event


def _safe_first_item_title(content_slide: dict) -> str:
    try:
        data = content_slide.get("data") or {}
        items = data.get("items") or []
        if items:
            it0 = items[0]
            if isinstance(it0, dict):
                t = (it0.get("title") or "").strip()
                if t:
                    return t
            elif isinstance(it0, str) and it0.strip():
                return it0.strip()
    except Exception:
        pass
    return (content_slide.get("data") or {}).get("title") or "要点"


def _content_text_case(content_slide: dict) -> tuple[str, str]:
    try:
        data = content_slide.get("data") or {}
        items = data.get("items") or []
        if items:
            it0 = items[0] if isinstance(items[0], dict) else {"text": str(items[0])}
            return (it0.get("text") or "", it0.get("case") or "")
    except Exception:
        pass
    return "", ""


async def _gen_table_via_llm(
    *, topic: str, section: str, point: str, text: str, case: str, language: str
) -> dict:
    """Ask LLM to produce a compact table JSON: {"headers": [...], "rows": [[...]]}."""
    is_zh = (language or "zh").lower().startswith("zh")
    lang_note = "请用中文" if is_zh else "Please answer in English"
    prompt = (
        f"{lang_note}。基于主题/章节/要点与提供的文字内容，生成一个适合幻灯片展示的精简表格。\n"
        f"主题: {topic}\n章节: {section}\n要点: {point}\n"
        f"text: {text[:600]}\ncase: {case[:600]}\n\n"
        "要求：\n"
        "- 严格输出 JSON 对象：{\"headers\":[..3~4..], \"rows\":[[...],[...]]}，不要输出任何多余字符。\n"
        "- 列数 3~4，行数 3~5；单元格用简短短语，少于30字/20 words；不要换行、不要 Markdown。\n"
        "- 表头清晰有区分度，如 维度/指标/示例/结论。\n"
    )
    llm = LLM()
    resp = await llm.ask([Message.user_message(prompt)], stream=False, temperature=0.3)
    obj = None
    try:
        obj = json.loads(resp)
    except Exception:
        import re as _re

        m = _re.search(r"\{.*\}", resp, _re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        # fallback skeleton
        headers = ["维度", "要点", "示例"] if is_zh else ["Dimension", "Point", "Example"]
        rows = [
            [section, point, "-"],
            [section, "关键指标", "-"],
            [section, "案例要点", "-"],
        ]
        return {"headers": headers, "rows": rows}

    headers = obj.get("headers") or []
    rows = obj.get("rows") or []
    # Clamp sizes
    try:
        headers = [str(h)[:50] for h in headers][:4]
        rows = [[str(c)[:80] for c in r][: len(headers)] for r in rows][:5]
    except Exception:
        pass
    if not headers or not rows:
        return await _gen_table_via_llm(
            topic=topic, section=section, point=point, text=text, case=case, language=language
        )
    return {"headers": headers, "rows": rows}


async def enrich_tables_for_outline(
    *, outline: List[dict], topic: str, language: Optional[str] = None
) -> Dict[str, Any]:
    """Append one table item to the second content under each transition."""
    slides = list(outline or [])
    language = language or "zh"
    count_added = 0

    log_execution_event(
        "aippt_media_table", "Start table enrichment", {"slides": len(slides)}
    )

    i = 0
    n = len(slides)
    while i < n:
        s = slides[i]
        if not isinstance(s, dict):
            i += 1
            continue
        if s.get("type") != "transition":
            i += 1
            continue
        # locate next 3 content slides
        group_contents: List[dict] = []
        j = i + 1
        while j < n and len(group_contents) < 3:
            sj = slides[j]
            if isinstance(sj, dict) and sj.get("type") == "content":
                group_contents.append(sj)
            elif isinstance(sj, dict) and sj.get("type") in ("transition", "end"):
                break
            j += 1

        if len(group_contents) >= 2:
            c1 = group_contents[1]
            cdata = c1.setdefault("data", {})
            items = cdata.setdefault("items", [])
            sec_title = (s.get("data") or {}).get("title") or ""
            point_title = _safe_first_item_title(c1)
            text, case = _content_text_case(c1)
            try:
                tbl = await _gen_table_via_llm(
                    topic=topic,
                    section=sec_title,
                    point=point_title,
                    text=text,
                    case=case,
                    language=language,
                )
                items.append({"type": "table", "headers": tbl["headers"], "rows": tbl["rows"]})
                count_added += 1
            except Exception as e:
                logger.warning(f"Table enrichment failed for section {sec_title}: {e}")
        i = max(i + 1, j if 'j' in locals() else i + 1)

    log_execution_event(
        "aippt_media_table",
        "Table enrichment finished",
        {"tables_added": count_added},
    )
    return {"status": "success", "outline": slides, "tables_added": count_added}

