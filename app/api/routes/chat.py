from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.chat_db.session import get_db_session
from app.chat_data import ChatRequest, ChatResponse, ChatData
from app.chat_data.db_operations import ChatDatabaseOperations
from app.chat_data.service import ChatDataService


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/insert", response_model=ChatResponse, summary="插入聊天数据")
async def insert_chat_data(
    request: ChatRequest, db_session: AsyncSession = Depends(get_db_session)
):
    try:
        db_ops = ChatDatabaseOperations(db_session)
        service = ChatDataService(db_ops)
        result = await service.process_chat_data(ChatData(**request.model_dump()))
        if result.success:
            return ChatResponse(
                success=True,
                conversation_id=result.conversation_id,
                message_id=result.message_id,
            )
        raise HTTPException(status_code=400, detail=result.error or "insert failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", summary="健康检查")
async def health_check():
    return {"status": "healthy", "service": "chat-data-insertion"}

