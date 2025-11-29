from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.llm import LLM
from app.logger import logger
from app.schema import Message
from app.services.execution_log_service import log_execution_event


def _collect_content_indices(
    slides: List[dict],
) -> List[Tuple[int, dict, Optional[dict]]]:
    """Return list of (index, content_slide, prev_transition_slide|None)."""
    out: List[Tuple[int, dict, Optional[dict]]] = []
    prev = None
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            prev = s
            continue
        t = s.get("type")
        if t == "content":
            out.append(
                (
                    i,
                    s,
                    (
                        prev
                        if isinstance(prev, dict) and prev.get("type") == "transition"
                        else None
                    ),
                )
            )
        prev = s
    return out


def _build_enrich_prompt(
    *,
    topic: str,
    language: str,
    items: List[Dict[str, Any]],
    reference_snippet: Optional[str] = None,
) -> str:
    """Build prompt asking the LLM to enrich each content slide.

    items element schema:
      {"key": str, "section": str, "content_title": str, "point_title": str, "transition_points": [str]}
    """
    lang_note = (
        "请用中文作答"
        if (language or "zh").lower().startswith("zh")
        else "Please answer in the specified language"
    )
    head = (
        f"{lang_note}。根据主题与上下文，为下列 content 幻灯片补充更充实的内容。\n"
        f"主题: {topic}\n"
        "每个条目的输出只返回 JSON 对象数组（不包含多余文字）。格式：\n"
        '[{"key": "...", "item": {"title": "...", "text": "...", "case": "..."}}]。\n'
        "严格要求：\n"
        "- 保持 title 不变（可微调措辞但不改变含义）。\n"
        "- text：信息密度高、语句简洁，优先包含可验证的数据/指标，中文建议 80~120 字（英文 40~80 words）。\n"
        "- case：给出一个具体案例（企业/项目/事件/政策落地），中文建议 140~200 字（英文 80~120 words），避免空话套话。\n"
        "- 不要使用 Markdown，不要段落标题，不要列表符号。\n"
        "- 严格返回 JSON 数组，数组元素顺序与输入一致，仅包含上述字段。\n"
    )

    src = ""
    if reference_snippet:
        src = f"\n参考材料节选：\n{reference_snippet[:1200]}\n"

    lst = []
    for it in items:
        key = it.get("key")
        sec = it.get("section") or ""
        ctitle = it.get("content_title") or ""
        ptitle = it.get("point_title") or ""
        tpoints = it.get("transition_points") or []
        lst.append(
            {
                "key": key,
                "section": sec,
                "content_title": ctitle,
                "point_title": ptitle,
                "transition_points": tpoints,
            }
        )

    body = json.dumps(lst, ensure_ascii=False, indent=2)
    return head + src + "\n需要补充的 content 列表：\n" + body


def _safe_first_item_title(content_slide: dict) -> str:
    try:
        data = content_slide.get("data") or {}
        items = data.get("items") or []
        if items:
            it = items[0]
            if isinstance(it, dict):
                t = (it.get("title") or "").strip()
                if t:
                    return t
            elif isinstance(it, str) and it.strip():
                return it.strip()
    except Exception:
        pass
    return (content_slide.get("data") or {}).get("title") or "要点"


async def enrich_aippt_content(
    *,
    outline: List[dict],
    topic: str,
    language: Optional[str] = None,
    reference_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Enrich content slides' text and case via a dedicated LLM call.

    Returns: {"status": "success", "outline": List[dict]} or {"status":"failed","error": str}
    """
    language = language or "zh"
    slides = list(outline or [])
    pairs = _collect_content_indices(slides)
    if not pairs:
        return {"status": "success", "outline": slides}

    # Prepare batch (to control tokens); simple strategy: process all in one shot
    batch: List[Dict[str, Any]] = []
    for idx, content, maybe_tr in pairs:
        key = f"S{idx:03d}"
        cdata = content.get("data") or {}
        batch.append(
            {
                "key": key,
                "section": (
                    maybe_tr.get("data", {}).get("title")
                    if maybe_tr
                    else cdata.get("title") or ""
                ),
                "content_title": cdata.get("title") or "",
                "point_title": _safe_first_item_title(content),
                "transition_points": (
                    maybe_tr.get("data", {}).get("items") if maybe_tr else []
                )
                or [],
            }
        )

    prompt = _build_enrich_prompt(
        topic=topic,
        language=language,
        items=batch,
        reference_snippet=(reference_content or "").strip() or None,
    )

    log_execution_event(
        "aippt_enrich",
        "Enrich content prompt prepared",
        {"count": len(batch), "language": language},
    )

    try:
        llm = LLM()
        resp = await llm.ask(
            [Message.user_message(prompt)], stream=False, temperature=0.5
        )
        data = None
        try:
            data = json.loads(resp)
        except Exception:
            # try to find an array
            import re as _re

            m = _re.search(r"\[.*\]", resp, _re.DOTALL)
            if m:
                data = json.loads(m.group(0))
        if not isinstance(data, list):
            raise ValueError("LLM did not return a JSON array")

        # Map by key
        by_key = {str(d.get("key")): d for d in data if isinstance(d, dict)}
        updated = 0
        for idx, content, _ in pairs:
            key = f"S{idx:03d}"
            rec = by_key.get(key)
            if not rec or not isinstance(rec.get("item"), dict):
                continue
            item = rec["item"]
            # Normalize text/case
            title = (
                item.get("title") or (content.get("data") or {}).get("title") or ""
            ).strip()
            text = (item.get("text") or "").strip()
            case = (item.get("case") or "").strip()
            cdata = content.setdefault("data", {})
            cdata["title"] = title or cdata.get("title") or ""
            # Ensure items exactly 1
            cdata["items"] = [
                {"title": _safe_first_item_title(content), "text": text, "case": case}
            ]
            updated += 1

        # Enforce length requirements with targeted refinement
        # - text >= 40 chars (zh) (~ or >= 32 words for non-zh)
        # - total(text+case) >= 160 chars (zh) (~ or >= 96 words for non-zh)
        need_refine: List[Tuple[int, dict]] = []
        is_zh = (language or "zh").lower().startswith("zh")
        min_text = 40 if is_zh else 32
        min_total = 160 if is_zh else 96
        for idx, content, _ in pairs:
            cdata = content.get("data") or {}
            items = cdata.get("items") or []
            if not items:
                continue
            it0 = items[0] if isinstance(items[0], dict) else {"title": str(items[0])}
            tx = (it0.get("text") or "").strip()
            cs = (it0.get("case") or "").strip()
            if len(tx) < min_text or (len(tx) + len(cs)) < min_total:
                need_refine.append((idx, content))

        async def _refine_one(idx: int, content_slide: dict):
            cdata = content_slide.get("data") or {}
            items = cdata.get("items") or []
            it0 = (
                items[0] if items else {"title": _safe_first_item_title(content_slide)}
            )
            pt = (it0.get("title") or "").strip() or _safe_first_item_title(
                content_slide
            )
            tx0 = (it0.get("text") or "").strip()
            cs0 = (it0.get("case") or "").strip()
            section = cdata.get("title") or ""
            lang_note = (
                "请用中文作答" if is_zh else "Please answer in the specified language"
            )
            req_text = (
                f"中文不少于{min_text}字" if is_zh else f"at least {min_text} words"
            )
            req_total = (
                f"中文总字数不少于{min_total}字"
                if is_zh
                else f"total at least {min_total} words"
            )
            refine_prompt = (
                f"{lang_note}。针对下述 content 要点，补全/扩写 text 与 case。\n"
                f"主题: {topic}\n章节: {section}\n要点标题: {pt}\n"
                f"当前 text: {tx0 or '(空)'}\n当前 case: {cs0 or '(空)'}\n"
                f'要求：text {req_text}，且 text+case {req_total}；给出可核查的数据或细节；返回 JSON 对象 {{"text":"...", "case":"..."}}，不要多余内容。'
            )
            rs = await llm.ask(
                [Message.user_message(refine_prompt)], stream=False, temperature=0.5
            )
            try:
                obj = json.loads(rs)
            except Exception:
                import re as _re

                m = _re.search(r"\{.*\}", rs, _re.DOTALL)
                obj = json.loads(m.group(0)) if m else {}
            new_text = (obj.get("text") or tx0).strip()
            new_case = (obj.get("case") or cs0).strip()
            # Apply back
            items[0] = {"title": pt, "text": new_text, "case": new_case}
            cdata["items"] = items[:1]

        if need_refine:
            for idx, content in need_refine:
                try:
                    await _refine_one(idx, content)
                except Exception as _e:
                    logger.warning(f"Refine content S{idx:03d} failed: {_e}")

        log_execution_event(
            "aippt_enrich",
            "Content enrichment applied",
            {"updated": updated, "total": len(pairs)},
        )
        return {"status": "success", "outline": slides, "updated": updated}
    except Exception as e:
        logger.warning(f"Content enrichment failed: {e}")
        return {"status": "failed", "error": str(e), "outline": slides}
