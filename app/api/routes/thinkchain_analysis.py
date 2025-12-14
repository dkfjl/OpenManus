from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query

from app.logger import logger
from app.schemas.thinkchain_analysis import (
    ThinkchainAnalysisRequest,
    ThinkchainAnalysisResponse,
)
from app.services.thinkchain_analysis_service import thinkchain_analysis_service


router = APIRouter()


@router.get("/api/thinkchain/analysis", response_model=ThinkchainAnalysisResponse)
async def thinkchain_analysis_endpoint(
    chain_id: str = Query(..., description="链ID"),
    session_id: Optional[str] = Query(None, description="会话ID（可选）"),
    language: Optional[str] = Query(None, description="输出语言，默认跟随链语言"),
):
    try:
        # Try cache first
        cached = thinkchain_analysis_service.load_cached_analysis(chain_id, session_id)
        if cached:
            return ThinkchainAnalysisResponse(
                status="success",
                chain_id=cached.get("chain_id"),
                session_id=cached.get("session_id"),
                analysis=cached.get("analysis") or {},
                cached=True,
            )

        payload = await thinkchain_analysis_service.generate_analysis(
            chain_id=chain_id, session_id=session_id, language=language
        )
        return ThinkchainAnalysisResponse(
            status="success",
            chain_id=payload.get("chain_id"),
            session_id=payload.get("session_id"),
            analysis=payload.get("analysis") or {},
            cached=False,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未找到对应的链日志文件")
    except Exception as e:
        logger.error(f"Thinkchain analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"综合分析生成失败: {str(e)}")

