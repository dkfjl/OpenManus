from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.logger import logger
from app.services.execution_log_service import log_execution_event


def _first_item_title(content_slide: dict) -> str:
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


def enforce_three_contents_per_transition(slides: List[dict]) -> List[dict]:
    """Ensure each transition is followed by exactly 3 content slides.

    Strategy:
    - Rebuild the middle part as: (transition + 3*content) for every transition in order.
    - Reuse existing content slides in original order; if lacking, synthesize new content slides
      using transition's title and its 3 point titles (if any).
    - Extra content slides beyond 3 for a transition are carried over to the next transition.
    - cover/contents/end are preserved as-is (first occurrences).
    """
    if not slides:
        return slides

    log_execution_event(
        "aippt_media_layout",
        "Start enforcing 3 contents per transition",
        {"slides": len(slides)},
    )

    cover = None
    contents = None
    end_slide = None
    others: List[dict] = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        t = s.get("type")
        if t == "cover" and cover is None:
            cover = s
        elif t == "contents" and contents is None:
            contents = s
        elif t == "end":
            end_slide = s
        else:
            others.append(s)

    transitions: List[dict] = [s for s in others if s.get("type") == "transition"]
    remaining_contents: List[dict] = [s for s in others if s.get("type") == "content"]

    rebuilt: List[dict] = []
    if cover:
        rebuilt.append(cover)
    if contents:
        rebuilt.append(contents)

    def _mk_content(title: str, point_title: str) -> dict:
        return {
            "type": "content",
            "data": {
                "title": title,
                "items": [{"title": point_title, "text": "", "case": ""}],
            },
        }

    for tr in transitions:
        rebuilt.append(tr)
        t_data = tr.get("data") or {}
        sec_title = t_data.get("title") or "章节"
        pt_titles = []
        try:
            pt_titles = [
                (str(it.get("title") if isinstance(it, dict) else it) or "").strip()
                for it in (t_data.get("items") or [])
            ]
        except Exception:
            pt_titles = []
        if len(pt_titles) < 3:
            # pad for synthesis
            base = pt_titles[-1] if pt_titles else "要点"
            pt_titles = (pt_titles + [base] * (3 - len(pt_titles)))[:3]

        group: List[dict] = []
        # take up to 3 existing contents in order
        for _ in range(3):
            if remaining_contents:
                group.append(remaining_contents.pop(0))
        # synthesize if lacking
        while len(group) < 3:
            idx = len(group)
            group.append(_mk_content(sec_title, pt_titles[idx]))

        # normalize: each content must have exactly 1 item object
        norm_group: List[dict] = []
        for j, c in enumerate(group, start=1):
            try:
                cdata = c.setdefault("data", {})
                if not cdata.get("title"):
                    cdata["title"] = sec_title
                items = cdata.get("items") or []
                if isinstance(items, list):
                    if len(items) >= 1:
                        cdata["items"] = items[:1]
                    else:
                        cdata["items"] = [
                            {"title": pt_titles[j - 1], "text": "", "case": ""}
                        ]
            except Exception:
                pass
            norm_group.append(c)

        rebuilt.extend(norm_group)

    if end_slide is None:
        end_slide = {"type": "end", "data": {}}
    rebuilt.append(end_slide)

    log_execution_event(
        "aippt_media_layout",
        "Enforced 3 contents per transition",
        {"slides_before": len(slides), "slides_after": len(rebuilt)},
    )
    return rebuilt

