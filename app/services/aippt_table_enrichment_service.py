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
    *,
    topic: str,
    section: str,
    point: str,
    text: str,
    case: str,
    external_facts: str,
    language: str,
    _attempt: int = 0,
    _max_attempts: int = 2,
) -> dict:
    """Ask LLM to produce a compact table JSON using content + external facts.

    Expected JSON: {"headers": [...], "rows": [[...]]}
    """
    is_zh = (language or "zh").lower().startswith("zh")
    lang_note = "请用中文" if is_zh else "Please answer in English"
    prompt = (
        f"{lang_note}。基于主题/章节/要点与提供的文字内容，并结合外部检索事实external_facts，生成一个适合幻灯片展示且以数字为主的精简表格。\n"
        f"主题: {topic}\n章节: {section}\n要点: {point}\n"
        f"text: {text[:600]}\ncase: {case[:600]}\n"
        f"external_facts: {external_facts[:2000]}\n\n"
        "严格要求：\n"
        "1) 只返回 JSON 对象：{\"headers\":[..3~4..], \"rows\":[[...],[...]]}，不要任何额外文字；优先使用 external_facts 中的可信数字。\n"
        "2) 列数 3~4，行数 3~5。\n"
        "3) 单元格尽量包含数字（数量/百分比/区间/年份/金额/指标值），至少一半以上单元格含有阿拉伯数字。\n"
        "4) 每个单元格极短：中文≤12字；英文≤12 chars；禁止换行/标点说明。\n"
        "5) 尽量避免 '-' 或 'N/A'；仅当 external_facts 无法提供任何有效数值时才使用。\n"
        "6) 表头清晰，如 维度/指标/值/同比 或 Dimension/Metric/Value/YoY。\n"
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
        # fallback or retry
        if _attempt >= _max_attempts:
            headers = ["维度", "指标", "值"] if is_zh else ["Dimension", "Metric", "Value"]
            rows = [[section[:12], point[:12], "-"]] * 3
            return {"headers": headers, "rows": rows}
        return await _gen_table_via_llm(
            topic=topic,
            section=section,
            point=point,
            text=text,
            case=case,
            external_facts=external_facts,
            language=language,
            _attempt=_attempt + 1,
            _max_attempts=_max_attempts,
        )

    headers = obj.get("headers") or []
    rows = obj.get("rows") or []
    # Clamp sizes
    try:
        headers = [str(h)[:20] for h in headers][:4]
        # clamp cells and coerce to very short strings
        rows = [[str(c)[:16] for c in r][: len(headers)] for r in rows][:5]
    except Exception:
        pass

    # If not enough numeric cells, ask LLM to compress to numeric view
    total = sum(len(r) for r in rows) or 1
    digit_cells = sum(1 for r in rows for c in r if any(ch.isdigit() for ch in str(c)))
    ratio = digit_cells / total
    if ratio < 0.5:
        try:
            refine_note = (
                "将该表压缩为以数字为主的版本：保持3-4列、3-5行，大多数单元格包含数字；每格≤12字；仅返回JSON。"
                if is_zh
                else "Compress this table to numeric: keep 3-4 cols, 3-5 rows, most cells contain digits; <=12 chars; JSON only."
            )
            tbl_json = json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False)
            llm2 = LLM()
            resp2 = await llm2.ask(
                [
                    Message.user_message(
                        f"{refine_note}\nCurrent table JSON:\n{tbl_json}"
                    )
                ],
                stream=False,
                temperature=0.2,
            )
            obj2 = None
            try:
                obj2 = json.loads(resp2)
            except Exception:
                import re as _re

                m2 = _re.search(r"\{.*\}", resp2, _re.DOTALL)
                obj2 = json.loads(m2.group(0)) if m2 else None
            if isinstance(obj2, dict):
                headers = obj2.get("headers") or headers
                rows = obj2.get("rows") or rows
                # clamp again
                headers = [str(h)[:20] for h in headers][:4]
                rows = [[str(c)[:16] for c in r][: len(headers)] for r in rows][:5]
        except Exception:
            pass
    if not headers or not rows:
        if _attempt >= _max_attempts:
            headers = ["维度", "指标", "值"] if is_zh else ["Dimension", "Metric", "Value"]
            rows = [[section[:12], point[:12], "-"]] * 3
            return {"headers": headers, "rows": rows}
        return await _gen_table_via_llm(
            topic=topic,
            section=section,
            point=point,
            text=text,
            case=case,
            external_facts=external_facts,
            language=language,
            _attempt=_attempt + 1,
            _max_attempts=_max_attempts,
        )
    return {"headers": headers, "rows": rows}

async def _gather_external_facts(
    *, topic: str, section: str, point: str, language: str, num_results: int = 6
) -> tuple[str, List[str]]:
    """Gather short factual snippets via WebSearch. Returns facts text and source URLs."""
    try:
        from app.tool.web_search import WebSearch
        ws = WebSearch()
        q = " ".join(x for x in [topic, section, point] if x)
        res = await ws.execute(query=q, num_results=min(8, max(3, num_results)), fetch_content=True)
        facts: List[str] = []
        urls: List[str] = []
        for r in res.results[: num_results]:
            snippet = (r.raw_content or r.description or "")[:600].replace("\n", " ")
            title = (r.title or "").strip()[:80]
            facts.append(f"- {title}: {snippet}")
            if r.url:
                urls.append(r.url)
        return "\n".join(facts), urls
    except Exception as e:
        logger.warning(f"external facts gather failed: {e}")
        return "", []

def _placeholder_ratio(headers: List[str], rows: List[List[str]]) -> float:
    total = max(1, sum(len(r) for r in rows))
    bad = 0
    for r in rows:
        for c in r[: len(headers)]:
            s = str(c).strip().lower()
            if s in ("-", "n/a", "na", "unknown", "?") or s == "":
                bad += 1
    return bad / total

async def _revise_content_to_match_table(
    *, topic: str, section: str, point: str, language: str, old_text: str, headers: List[str], rows: List[List[str]]
) -> str:
    is_zh = (language or "zh").lower().startswith("zh")
    lang_note = "请用中文" if is_zh else "Please use English"
    table_preview = json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False)
    base = (
        f"{lang_note}。根据下表总结2-4条与本页内容一致的要点，不改变主题/章节/要点。只返回合并后的文本，逐行列出要点。"
        if is_zh
        else "Summarize 2-4 concise bullets consistent with this table without changing the topic/section/point. Return the merged text only, one bullet per line."
    )
    prompt = (
        f"{base}\nTopic: {topic}\nSection: {section}\nPoint: {point}\nCurrent text: {old_text[:400]}\nTable JSON: {table_preview}"
    )
    llm = LLM()
    try:
        resp = await llm.ask([Message.user_message(prompt)], stream=False, temperature=0.2)
        return resp.strip()
    except Exception:
        return old_text


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
                # Step A: gather external facts
                facts, sources = await _gather_external_facts(
                    topic=topic, section=sec_title, point=point_title, language=language, num_results=6
                )

                # Step B: generate table using content + external facts
                tbl = await _gen_table_via_llm(
                    topic=topic,
                    section=sec_title,
                    point=point_title,
                    text=text,
                    case=case,
                    external_facts=facts,
                    language=language,
                )

                headers, rows = tbl.get("headers") or [], tbl.get("rows") or []

                # Step B2: If too many placeholders, broaden search and retry once
                if _placeholder_ratio(headers, rows) > 0.25:
                    facts2, _ = await _gather_external_facts(
                        topic=topic, section=sec_title, point=point_title, language=language, num_results=8
                    )
                    tbl = await _gen_table_via_llm(
                        topic=topic,
                        section=sec_title,
                        point=point_title,
                        text=text,
                        case=case,
                        external_facts=f"{facts}\n{facts2}",
                        language=language,
                        _attempt=1,
                        _max_attempts=2,
                    )
                    headers, rows = tbl.get("headers") or [], tbl.get("rows") or []

                # Step C: append table
                items.append({"type": "table", "headers": headers, "rows": rows})

                # Step D: revise text bullets to match table (do not change topic)
                new_text = await _revise_content_to_match_table(
                    topic=topic,
                    section=sec_title,
                    point=point_title,
                    language=language,
                    old_text=text,
                    headers=headers,
                    rows=rows,
                )
                # Merge to first text item
                if items:
                    if isinstance(items[0], str):
                        items[0] = {"text": items[0]}
                    if isinstance(items[0], dict):
                        items[0]["text"] = new_text
                    else:
                        items.insert(0, {"text": new_text})
                else:
                    items.append({"text": new_text})
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
