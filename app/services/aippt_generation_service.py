from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.config import config
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
    return str(Path("reports") / _sanitize_filename(topic))


async def generate_pptx_from_aippt(
    *,
    topic: str,
    outline: List[dict],
    language: Optional[str] = None,
    style: Optional[str] = None,
    model: Optional[str] = None,
    filepath: Optional[str] = None,
    direct_convert: bool = False,
) -> dict:
    """
    Generate a PPTX file locally using LLM from an AIPPT-style outline.

    Args:
        topic: The main topic for the PPT
        outline: PPT outline in AIPPT JSON format
        language: Output language (zh, en, etc.)
        style: PPT style (通用, 学术风, 职场风, 教育风, 营销风)
        model: Kept for API-compatibility; ignored in local generation
        filepath: Optional custom filepath for saving the PPTX

    Returns:
        Dict containing generation result and file path
    """
    language = language or "zh"
    style = style or "通用"
    model = model or "gemini-3-pro-preview"

    # Setup file path
    target_path = filepath or str(_default_reports_path(topic))
    from app.config import config

    base = config.workspace_root
    candidate = Path(target_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.suffix.lower() != ".pptx":
        candidate = candidate.with_suffix(".pptx")
    abs_path = str(candidate)

    log_execution_event(
        "aippt_generation",
        "Starting AIPPT PPTX generation",
        {
            "topic": topic[:100],
            "language": language,
            "style": style,
            "model": model,
            "filepath": abs_path,
        },
    )

    try:
        # Local LLM generation (no third-party API)
        result = await _generate_pptx_locally(
            topic=topic,
            outline=outline,
            language=language,
            style=style,
            model=model,
            output_path=abs_path,
            direct_convert=direct_convert,
        )

        log_execution_event(
            "aippt_generation",
            "AIPPT PPTX generation completed",
            {
                "filepath": abs_path,
                "slides_generated": result.get("slides_count", 0),
                "generation_time": result.get("generation_time", 0),
            },
        )

        return {
            "status": "completed",
            "filepath": abs_path,
            "title": topic,
            "slides_count": result.get("slides_count", 0),
            "generation_time": result.get("generation_time", 0),
        }

    except Exception as e:
        log_execution_event(
            "aippt_generation",
            "AIPPT PPTX generation failed",
            {"error": str(e)},
        )
        logger.error(f"Failed to generate PPTX (local): {e}")

        return {
            "status": "failed",
            "filepath": abs_path,
            "title": topic,
            "error": str(e),
        }


# ------------------ Local generation path (no third-party API) ------------------


def _language_instruction(lang: Optional[str]) -> str:
    if not lang:
        return "请用中文"
    v = (lang or "").lower()
    if v in ("zh", "zh-cn", "cn", "中文"):
        return "请用中文"
    if v in ("en", "en-us", "english"):
        return "Please respond in English"
    if v in ("ja", "jp", "日本語"):
        return "日本語で答えてください"
    return "请用中文"


def _style_label(style: Optional[str]) -> str:
    if not style:
        return "通用风格"
    m = {
        "通用": "通用风格",
        "学术风": "学术风格",
        "职场风": "职场商务风格",
        "教育风": "教育培训风格",
        "营销风": "营销推广风格",
    }
    return m.get(style, "通用风格")


def _build_local_prompt(
    topic: str, outline: List[dict], language: Optional[str], style: Optional[str]
) -> str:
    outline_json = json.dumps(outline, ensure_ascii=False, indent=2)
    instr = _language_instruction(language)
    style_text = _style_label(style)
    prompt = (
        f"{instr}根据以下大纲生成完整的PPT数据：\n\n"
        f"主题：{topic}\n\n"
        f"大纲内容：\n{outline_json}\n\n"
        "要求：\n"
        f"1. 风格：{style_text}\n"
        "2. 返回流式JSON数据，每行一个完整的JSON对象\n"
        "3. 严格按照PPTist的AIPPT类型定义格式\n"
        "4. 每个内容项控制在合理字数内\n"
        "5. 保持内容的连贯性和专业性\n\n"
        "请逐个返回PPT页面数据，每个JSON对象一行。"
    )
    return prompt


def _normalize_slide(slide: dict) -> dict:
    try:
        stype = slide.get("type")
        data = (
            slide.setdefault("data", {})
            if isinstance(slide.get("data"), dict)
            else slide.setdefault("data", {})
        )
        if stype == "cover":
            if "text" not in data and "subTitle" in data:
                data["text"] = data.get("subTitle")
        elif stype == "contents":
            items = data.get("items", [])
            if isinstance(items, list):
                norm = []
                for it in items:
                    if isinstance(it, dict) and "title" in it:
                        norm.append(str(it.get("title")))
                    else:
                        norm.append(it if isinstance(it, str) else str(it))
                data["items"] = norm
    except Exception:
        pass
    return slide


def _parse_ndjson_or_objects(raw_text: str) -> List[dict]:
    """Parse NDJSON-like output where each line is a JSON object.

    - Skips code fences like ``` or ```json
    - Tries line-by-line JSON first; if none parsed, falls back to regex-style brace scanning for multiple objects.
    """
    slides: List[dict] = []
    if not raw_text:
        return slides

    # First pass: per-line JSON
    for line in raw_text.splitlines():
        ln = line.strip()
        if not ln or ln.startswith("```"):
            continue
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                slides.append(_normalize_slide(obj))
        except json.JSONDecodeError:
            continue

    if slides:
        return slides

    # Fallback: extract multiple JSON objects from a big blob
    # Simple brace matching to slice objects; robust enough for typical outputs
    buf = []
    depth = 0
    in_str = False
    esc = False
    for ch in raw_text:
        buf.append(ch)
        if ch == "\\" and not esc:
            esc = True
            continue
        if ch == '"' and not esc:
            in_str = not in_str
        if not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = "".join(buf).strip()
                    buf = []
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            slides.append(_normalize_slide(obj))
                    except Exception:
                        pass
        if esc:
            esc = False

    return slides


def _titles_from_items(items) -> List[str]:
    titles: List[str] = []
    try:
        for it in items or []:
            if isinstance(it, dict):
                t = (it.get("title") or "").strip()
                if t:
                    titles.append(t)
            elif isinstance(it, str):
                if it.strip():
                    titles.append(it.strip())
    except Exception:
        pass
    return titles


def _postprocess_aippt_slides(slides: List[dict]) -> List[dict]:
    """Normalize and align AIPPT slides after LLM generation (new spec).

    - contents.items: clamp to <=5
    - each content.items: clamp to exactly 1 (keep first)
    - each transition.items: set to titles of next up to 3 content slides; truncate or pad to length 3 if feasible.
    """
    if not slides:
        return slides

    # Work on a shallow copy
    out = list(slides)
    n = len(out)
    for i in range(n):
        s = out[i]
        if not isinstance(s, dict):
            continue
        st = s.get("type")
        data = s.setdefault("data", {}) if isinstance(s.get("data"), dict) else s.setdefault("data", {})

        if st == "contents":
            try:
                items = data.get("items") or []
                if isinstance(items, list) and len(items) > 5:
                    data["items"] = items[:5]
            except Exception:
                pass
        elif st == "content":
            try:
                items = data.get("items") or []
                if isinstance(items, list):
                    if len(items) >= 1:
                        data["items"] = items[:1]
                    else:
                        data["items"] = []
            except Exception:
                pass
        elif st == "transition":
            # Look ahead up to 3 content slides (until next transition/contents/end)
            titles: list[str] = []
            j = i + 1
            while j < n and len(titles) < 3:
                sj = out[j]
                if not isinstance(sj, dict):
                    j += 1
                    continue
                t = sj.get("type")
                if t == "content":
                    cj = sj.setdefault("data", {}) if isinstance(sj.get("data"), dict) else sj.setdefault("data", {})
                    itemsj = cj.get("items") or []
                    if isinstance(itemsj, list):
                        if len(itemsj) >= 1:
                            cj["items"] = itemsj[:1]
                        else:
                            cj["items"] = []
                    titles += _titles_from_items(cj.get("items") or [])[:1]
                    j += 1
                    continue
                if t in ("transition", "contents", "end", "cover"):
                    break
                j += 1
            if titles:
                # pad/truncate to 3
                if len(titles) < 3:
                    titles = titles + [titles[-1]] * (3 - len(titles))
                else:
                    titles = titles[:3]
                data["items"] = titles

    return out


async def _generate_pptx_locally(
    *,
    topic: str,
    outline: List[dict],
    language: Optional[str],
    style: Optional[str],
    model: Optional[str],
    output_path: str,
    direct_convert: bool = False,
) -> dict:
    start_time = asyncio.get_event_loop().time()

    from app.services.aippt_to_pptx_service import convert_aippt_slides_to_pptx
    if direct_convert:
        # Preserve enriched outline as-is
        conversion = convert_aippt_slides_to_pptx(outline, output_path, style=style)
    else:
        # Build prompt per the third-party server logic
        prompt = _build_local_prompt(topic, outline, language, style)
        # Use the same LLM configuration and call pattern as Step 1 (outline)
        llm = LLM()
        # Non-stream call to get complete content then slice into NDJSON lines
        response_text = await llm.ask(
            [Message.user_message(prompt)], stream=False, temperature=0.2
        )
        slides_data = _parse_ndjson_or_objects(response_text)
        if not slides_data:
            raise Exception("Local LLM did not return any slide data")
        # Enforce structural and count alignment
        slides_data = _postprocess_aippt_slides(slides_data)
        conversion = convert_aippt_slides_to_pptx(slides_data, output_path, style=style)
    generation_time = asyncio.get_event_loop().time() - start_time

    if conversion.get("status") == "success":
        return {
            "slides_count": conversion["slides_processed"],
            "generation_time": generation_time,
            "file_size": conversion["file_size"],
        }
    raise Exception(
        f"PPTX conversion failed: {conversion.get('error', 'Unknown error')}"
    )
