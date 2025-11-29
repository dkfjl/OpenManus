from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.logger import logger
from app.services.execution_log_service import log_execution_event

from .aippt_media_layout_service import enforce_three_contents_per_transition
from .aippt_image_enrichment_service import enrich_images_for_outline
from .aippt_table_enrichment_service import enrich_tables_for_outline


async def enrich_media_outline(
    *, outline: List[dict], topic: str, language: Optional[str] = None
) -> Dict[str, Any]:
    """Orchestrate media enrichment in two dedicated passes after text enrichment.

    Steps:
      1) Normalize layout so each transition has exactly 3 content slides.
      2) Append an image (via remote URL) to the first content of each transition.
      3) Append a table (via LLM) to the second content of each transition.
    """
    language = language or "zh"
    log_execution_event(
        "aippt_media_orchestrator",
        "Start media enrichment orchestrator",
        {"slides": len(outline or [])},
    )

    # Step 1: enforce 3-contents-per-transition
    aligned = enforce_three_contents_per_transition(outline or [])

    # Step 2: images (await async enrichment)
    img_res = await enrich_images_for_outline(
        outline=aligned, topic=topic, language=language
    )
    slides_after_img = img_res.get("outline", aligned)

    # Step 3: tables
    tbl_res = await enrich_tables_for_outline(
        outline=slides_after_img, topic=topic, language=language
    )
    final_outline = tbl_res.get("outline", slides_after_img)

    log_execution_event(
        "aippt_media_orchestrator",
        "Media enrichment completed",
        {
            "images_added": img_res.get("images_added", 0),
            "tables_added": tbl_res.get("tables_added", 0),
            "slides": len(final_outline),
        },
    )
    return {
        "status": "success",
        "outline": final_outline,
        "images_added": img_res.get("images_added", 0),
        "tables_added": tbl_res.get("tables_added", 0),
    }
