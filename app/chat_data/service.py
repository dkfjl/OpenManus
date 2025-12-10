from __future__ import annotations

from typing import Dict

from app.logger import logger
from app.chat_data import ChatData, InsertResult
from app.chat_data.db_operations import ChatDatabaseOperations


class ChatDataService:
    """聊天数据服务层：校验与编排"""

    def __init__(self, db_operations: ChatDatabaseOperations):
        self.db_ops = db_operations

    async def process_chat_data(self, data: ChatData) -> InsertResult:
        try:
            # 1) 基本校验
            self._validate_data(data)

            # 2) 会话：按 conversation_id 幂等创建/复用
            conversation_id = await self.db_ops.insert_conversation(data)

            # 3) 消息：按 (conversation_id, client_message_id) 幂等
            message_id = await self.db_ops.insert_message(conversation_id, data)

            # 4) 文件：若提供则写入
            if data.files:
                await self.db_ops.insert_message_files(
                    message_id=message_id, files=data.files, user_id=data.user_id
                )

            logger.info(
                f"chat insert succeeded: conversation_id={conversation_id}, message_id={message_id}"
            )
            return InsertResult(
                success=True, conversation_id=conversation_id, message_id=message_id
            )
        except Exception as e:  # pragma: no cover - log and map to response
            logger.exception(f"chat insert failed: {e}")
            return InsertResult(
                success=False, conversation_id="", message_id="", error=str(e)
            )

    def _validate_data(self, data: ChatData) -> None:
        if not data.app_id:
            raise ValueError("app_id 不能为空")
        if not data.user_id:
            raise ValueError("user_id 不能为空")
        if not data.query:
            raise ValueError("query 不能为空")
        if not data.answer:
            raise ValueError("answer 不能为空")

        # 文件字段基本校验
        for f in data.files:
            if not isinstance(f, Dict):
                raise ValueError("files 内元素必须为对象")
            url = f.get("url")
            if not url:
                raise ValueError("文件URL不能为空")
            if len(url) > 2048:
                raise ValueError("文件URL长度超过限制(2048)")

