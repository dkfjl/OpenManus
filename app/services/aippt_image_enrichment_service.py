from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.logger import logger
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
                if any(
                    u.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]
                ) and u not in seen:
                    out.append(u)
                    seen.add(u)
                if len(out) >= max_images:
                    break
        except Exception:
            continue
        if len(out) >= max_images:
            break
    return out[:max_images]


async def enrich_images_for_outline(
    *, outline: List[dict], topic: str, language: Optional[str] = None
) -> Dict[str, Any]:
    """Append one image item (remote URL) to the first content under each transition.

    - Only appends; does not remove existing text. Converter will place it in the right media area
      for the first content (variant=0).
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
            query = " ".join(x for x in [topic, sec_title, point_title] if x)
            urls = await _pick_image_urls_for_query(query, max_images=2)
            if urls:
                items.append({"type": "image", "url": urls[0], "title": point_title})
                count_added += 1
        i = max(i + 1, j if 'j' in locals() else i + 1)

    log_execution_event(
        "aippt_media_image",
        "Image enrichment finished",
        {"images_added": count_added},
    )
    return {"status": "success", "outline": slides, "images_added": count_added}
