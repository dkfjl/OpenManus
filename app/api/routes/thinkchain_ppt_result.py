from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.logger import logger
from app.services.thinkchain_log_service import thinkchain_log_service
from app.utils.async_tasks import get_enhanced_outline_status
from app.services.enhanced_outline_storage import enhanced_outline_storage


router = APIRouter()


@router.get("/api/thinkchain/ppt-result")
async def get_ppt_result(
    chain_id: str = Query(..., description="链ID"),
    session_id: str = Query(..., description="会话ID"),
):
    try:
        # Find last PPT post-action events
        last_ok = thinkchain_log_service.find_last_event(
            chain_id, session_id, ["post_action_ppt"]
        )
        last_fail = thinkchain_log_service.find_last_event(
            chain_id, session_id, ["post_action_ppt_failed"]
        )

        if last_fail:
            return {
                "status": "success",
                "chain_id": chain_id,
                "session_id": session_id,
                "ppt_status": "failed",
                "error": (last_fail.get("data") or {}).get("error"),
            }

        if not last_ok:
            return {
                "status": "success",
                "chain_id": chain_id,
                "session_id": session_id,
                "ppt_status": "pending",
                "message": "未发现PPT生成触发事件，可能仍在队列中或未开启自动触发。",
            }

        res = (last_ok.get("data") or {}).get("result") or {}
        enhanced_uuid = res.get("enhanced_outline_uuid")
        if not enhanced_uuid:
            return {
                "status": "success",
                "chain_id": chain_id,
                "session_id": session_id,
                "ppt_status": "pending",
                "message": "尚未获取到增强版大纲UUID。",
            }

        # Query status from storage/task manager
        status_info = await get_enhanced_outline_status(enhanced_uuid)
        outline = None
        if status_info.get("status") == "completed":
            outline = await enhanced_outline_storage.get_outline(enhanced_uuid)

        return {
            "status": "success",
            "chain_id": chain_id,
            "session_id": session_id,
            "ppt_status": status_info.get("status"),
            "enhanced_outline_uuid": enhanced_uuid,
            "outline": outline,
            "topic": status_info.get("topic"),
            "language": status_info.get("language"),
            "created_at": status_info.get("created_at"),
            "updated_at": status_info.get("updated_at"),
            "reference_sources": status_info.get("reference_sources"),
            "message": status_info.get("error_message"),
        }
    except Exception as e:
        logger.error(f"ppt-result endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")

