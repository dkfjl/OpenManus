from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.llm import LLM, MULTIMODAL_MODELS
from app.logger import logger
from app.schema import Message
from app.services.execution_log_service import log_execution_event
from app.services.image_retrieval_service import (
    discover_image_assets_with_refine,
)


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


async def _pick_image_urls_for_query(query: str, max_images: int = 3) -> List[str]:
    """Search the web and extract a few plausible image URLs for the query.

    Strategy: use WebSearch to get result URLs, fetch pages, prefer og:image and <img src>.
    """
    from app.tool.web_search import WebSearch

    ws = WebSearch()
    # fully async: await the web search
    search = await ws.execute(query=query, num_results=4, fetch_content=False)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    out: List[str] = []
    seen = set()
    for res in search.results[:4]:
        try:
            resp = requests.get(res.url, headers=headers, timeout=8)
            if resp.status_code != 200 or not resp.text:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                u = urljoin(res.url, og.get("content"))
                if u not in seen:
                    out.append(u)
                    seen.add(u)
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if not src:
                    continue
                u = urljoin(res.url, src)
                # basic URL heuristics to skip likely-bad resources
                low = u.lower()
                bad_hint = any(
                    h in low
                    for h in [
                        "qr",
                        "qrcode",
                        "logo",
                        "icon",
                        "sprite",
                        ".svg",
                        "placeholder",
                    ]
                )
                if (
                    any(low.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"])
                    and not bad_hint
                    and u not in seen
                ):
                    out.append(u)
                    seen.add(u)
                if len(out) >= max_images:
                    break
        except Exception:
            continue
        if len(out) >= max_images:
            break
    return out[:max_images]


def _extract_json_array(text: str) -> Optional[list]:
    try:
        import json, re
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\[[\s\S]*?\]", text)
            if m:
                return json.loads(m.group(0))
    except Exception:
        return None


async def _filter_relevant_images(
    *,
    topic: str,
    section: str,
    point: str,
    candidates: List[str],
    language: Optional[str] = None,
) -> Optional[str]:
    """Use text LLM to judge relevance from URL semantics; avoid logos/QR/irrelevant.

    Returns a single best URL or None. Falls back to heuristics.
    """
    language = (language or "zh").lower()
    if not candidates:
        return None

    # Text-only relevance classification over URL strings
    try:
        llm = LLM()  # use general text model per config
        ask = (
            "根据下列图片URL线索（文件名/路径/域名等）判断其与内容是否相关；避开二维码/Logo/占位图/无关领域。如果没有合适的，返回空数组[]。只返回索引数组，如 [0] 或 [0,2]。"
            if language.startswith("zh")
            else "Given the image URLs (filenames/paths/domains), pick URLs relevant to the content; avoid QR/logos/placeholders/off-topic. If none qualify, return []. Respond with an index array only, e.g., [0] or [0,2]."
        )
        desc = f"topic: {topic}\nsection: {section}\npoint: {point}\nurls:\n" + "\n".join(f"[{i}] {u}" for i, u in enumerate(candidates))
        resp = await llm.ask([Message.user_message(f"{ask}\n{desc}")], stream=False, temperature=0.1)
        arr = _extract_json_array(resp)
        if isinstance(arr, list) and arr:
            try:
                idx = int(arr[0])
                if 0 <= idx < len(candidates):
                    return candidates[idx]
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Text relevance check failed: {e}")

    # Heuristic fallback: prefer URLs containing topic/section/point keywords, avoid qr/logo
    key_parts = [topic or "", section or "", point or ""]
    key_parts = [k.lower() for k in key_parts if k]

    def score(u: str) -> int:
        s = 0
        low = u.lower()
        for k in key_parts:
            if k and k in low:
                s += 2
        if any(
            h in low
            for h in ["qr", "qrcode", "logo", "icon", "sprite", "placeholder", ".svg"]
        ):
            s -= 3
        return s

    ranked = sorted(((score(u), u) for u in candidates), reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    return None


async def _filter_relevant_images_multi(
    *,
    topic: str,
    section: str,
    point: str,
    candidates: List[str],
    language: Optional[str] = None,
    max_select: int = 2,
) -> List[str]:
    language = (language or "zh").lower()
    if not candidates:
        return []

    # Text-only classifier over URL list
    try:
        llm = LLM()
        ask = (
            f"从这些图片URL中选出至多{max_select}个与给定内容高度相关的；若无合适，返回[]。避免二维码/Logo/占位图/无关领域。只返回索引数组（如 [0,2]）。"
            if language.startswith("zh")
            else f"Pick up to {max_select} image URLs relevant to the content; if none, return []. Avoid QR/logos/placeholders/off-topic. Return an index array only, e.g., [0,2]."
        )
        desc = f"topic: {topic}\nsection: {section}\npoint: {point}\nurls:\n" + "\n".join(f"[{i}] {u}" for i, u in enumerate(candidates))
        resp = await llm.ask([Message.user_message(f"{ask}\n{desc}")], stream=False, temperature=0.1)
        arr = _extract_json_array(resp)
        if isinstance(arr, list):
            picks: List[str] = []
            for idx in arr:
                try:
                    i = int(idx)
                    if 0 <= i < len(candidates):
                        picks.append(candidates[i])
                except Exception:
                    continue
                if len(picks) >= max_select:
                    break
            if picks:
                return picks
    except Exception as e:
        logger.warning(f"Text multi-select failed: {e}")

    key_parts = [k.lower() for k in [topic, section, point] if k]
    def score(u: str) -> int:
        s = 0
        low = u.lower()
        for k in key_parts:
            if k and k in low:
                s += 2
        if any(h in low for h in ["qr", "qrcode", "logo", "icon", "sprite", "placeholder", ".svg"]):
            s -= 3
        return s
    ranked = sorted(((score(u), u) for u in candidates), reverse=True)
    out = [u for sc, u in ranked if sc > 0][:max_select]
    if out:
        return out
    # 没有正分候选，判定为不相关，交由上层触发重检索
    return []


# Note: previous logic that asked LLM to produce direct image URLs has been
# intentionally removed. Image discovery now relies on official image search
# APIs or headless browser rendering; the LLM is only used for relevance
# checking in _filter_relevant_images.


async def enrich_images_for_outline(
    *, outline: List[dict], topic: str, language: Optional[str] = None
) -> Dict[str, Any]:
    """Append up to two image items (remote URLs) to the first content under each transition.

    - Only appends; does not remove existing text. Converter will place them in the proper media area
      for the first content (variant=0). When more than two candidates are relevant, only two are kept.
    """
    slides = list(outline or [])
    count_added = 0

    log_execution_event(
        "aippt_media_image", "Start image enrichment", {"slides": len(slides)}
    )

    # Find transitions and ensure for each, get its first following content
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

        if group_contents:
            c0 = group_contents[0]
            cdata = c0.setdefault("data", {})
            items = cdata.setdefault("items", [])
            # Build query: topic + section title + first item title
            sec_title = (s.get("data") or {}).get("title") or ""
            point_title = _safe_first_item_title(c0)
            # Strategy: up to 3 attempts — refine → search → relevance multi-select
            attempts = 0
            while attempts < 3:
                assets = await discover_image_assets_with_refine(
                    topic=topic, section=sec_title, point=point_title, language=language, desired=3, max_attempts=3
                )
                urls = [a.url for a in assets]
                chosen_list = await _filter_relevant_images_multi(
                    topic=topic,
                    section=sec_title,
                    point=point_title,
                    candidates=urls,
                    language=language,
                    max_select=2,
                )
                if chosen_list:
                    keep = chosen_list[:2]
                    for idx, u in enumerate(keep, start=1):
                        title = point_title if len(keep) == 1 else f"{point_title} ({idx})"
                        # 找到对应的来源页，作为下载时的 Referer
                        ref = None
                        try:
                            for a in assets:
                                if a.url == u:
                                    ref = a.source
                                    break
                        except Exception:
                            ref = None
                        img_item = {"type": "image", "url": u, "title": title}
                        if ref:
                            img_item["referer"] = ref
                        items.append(img_item)
                    count_added += 1
                    break
                attempts += 1
        i = max(i + 1, j if "j" in locals() else i + 1)

    log_execution_event(
        "aippt_media_image",
        "Image enrichment finished",
        {"images_added": count_added},
    )
    return {"status": "success", "outline": slides, "images_added": count_added}
