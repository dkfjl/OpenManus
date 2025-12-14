from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.logger import logger
from app.schemas.report import ReportResult
from app.services.thinkchain_log_service import thinkchain_log_service


router = APIRouter()


@router.get("/api/thinkchain/report-result")
async def get_report_result(
    chain_id: str = Query(..., description="链ID"),
    session_id: str = Query(..., description="会话ID"),
):
    try:
        # Look for last post_action_report or failure event
        last_ok = thinkchain_log_service.find_last_event(
            chain_id, session_id, ["post_action_report"]
        )
        last_fail = thinkchain_log_service.find_last_event(
            chain_id, session_id, ["post_action_report_failed"]
        )

        if last_ok:
            result = (last_ok.get("data") or {}).get("result") or {}
            return {
                "status": "success",
                "chain_id": chain_id,
                "session_id": session_id,
                "report_status": "completed",
                "report": result,
            }

        if last_fail:
            return {
                "status": "success",
                "chain_id": chain_id,
                "session_id": session_id,
                "report_status": "failed",
                "error": (last_fail.get("data") or {}).get("error"),
            }

        # Not yet available
        return {
            "status": "success",
            "chain_id": chain_id,
            "session_id": session_id,
            "report_status": "pending",
        }
    except Exception as e:
        logger.error(f"report-result endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")

