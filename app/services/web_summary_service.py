from __future__ import annotations

from typing import List, Tuple, Optional

from app.logger import logger
from app.services.execution_log_service import log_execution_event
from app.tool.web_search import WebSearch


async def collect_search_summaries(
    *, query: str, top_k: int = 8, include_urls: bool = True
) -> Tuple[str, List[str]]:
    """Run WebSearch (Bocha→Google fallback) and aggregate result summaries.

    Returns a tuple of (summary_text, source_urls).
    The text is trimmed to a safe size for prompts (about 1500 chars).
    """
    ws = WebSearch()
    res = await ws.execute(query=query, num_results=max(1, min(50, top_k)), fetch_content=False)

    pieces: List[str] = []
    sources: List[str] = []
    for r in res.results or []:
        title = (r.title or "").strip()
        desc = (r.description or "").strip()
        url = (r.url or "").strip()
        if include_urls:
            if title and desc:
                pieces.append(f"- {title}：{desc}")
            elif title:
                pieces.append(f"- {title}")
            elif desc:
                pieces.append(f"- {desc}")
            if url:
                sources.append(url)
        else:
            if title and desc:
                pieces.append(f"{title}：{desc}")
            elif title:
                pieces.append(title)
            elif desc:
                pieces.append(desc)

    text = "\n".join(pieces)
    # Trim to ~1500 chars to fit prompt budget
    if len(text) > 1500:
        text = text[:1500]

    log_execution_event(
        "web_summary",
        "Collected search summaries",
        {"items": len(pieces), "sources": len(sources)},
    )
    return text, sources

