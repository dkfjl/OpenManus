from __future__ import annotations

import json
import os
import re
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.chat_db import Conversation, Message, MessageFile
from app.chat_data import ChatData


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


class ChatDatabaseOperations:
    """聊天数据库操作类（使用 AsyncSession，按方法粒度保证原子性）"""

    def __init__(self, session: AsyncSession):
        self.session = session

        # Pricing/estimation controls: env > config.toml > defaults
        token_env = os.getenv("TOKEN_ESTIMATION_ENABLED")
        price_env = os.getenv("PRICE_PER_1000_TOKENS")
        currency_env = os.getenv("CURRENCY")

        try:
            from app.config import config as app_config

            chat_cfg = app_config.chat
        except Exception:
            chat_cfg = None

        self.token_estimation_enabled = (
            _env_bool("TOKEN_ESTIMATION_ENABLED", False)
            if token_env is not None
            else (chat_cfg.token_estimation_enabled if chat_cfg else False)
        )

        if price_env is not None:
            try:
                self.price_per_1000 = float(price_env or 0)
            except Exception:
                self.price_per_1000 = 0.0
        else:
            self.price_per_1000 = chat_cfg.price_per_1000_tokens if chat_cfg else 0.0

        self.currency = currency_env or (chat_cfg.currency if chat_cfg else "USD")

    async def insert_conversation(self, data: ChatData) -> str:
        """插入/复用会话（以 conversation_id 为幂等锚点）"""
        conversation_id = data.conversation_id or str(uuid.uuid4())

        try:
            async with self.session.begin():
                if data.conversation_id:
                    existing = await self.session.get(Conversation, data.conversation_id)
                    if existing:
                        return existing.id

                conv = Conversation(
                    id=conversation_id,
                    app_id=data.app_id,
                    name=f"Conversation {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    status="normal",
                    inputs=data.inputs or {},
                    from_source="api",
                    from_end_user_id=data.user_id,
                    mode=data.mode or "chat",
                    dialogue_count=0,
                )
                self.session.add(conv)
                # Force flush to detect DB constraint errors early
                await self.session.flush()
        except Exception:
            raise

        logger.debug("Conversation inserted: %s", conversation_id)
        return conversation_id

    async def insert_message(self, conversation_id: str, data: ChatData) -> str:
        """插入消息；计费默认关闭。"""
        message_id = str(uuid.uuid4())

        # 计费与 token：默认关闭，置零；如开启则按配置计算
        if self.token_estimation_enabled:
            message_tokens = self._estimate_tokens(data.query)
            answer_tokens = self._estimate_tokens(data.answer)
            total_price = self._calculate_price(message_tokens, answer_tokens)
        else:
            message_tokens = 0
            answer_tokens = 0
            total_price = 0.0
        # unit prices (for compatibility with remote schema)
        message_unit_price = self.price_per_1000 if self.token_estimation_enabled else 0.0
        answer_unit_price = self.price_per_1000 if self.token_estimation_enabled else 0.0

        latency = 0.0
        try:
            if isinstance(data.metadata, dict):
                latency = float(data.metadata.get("latency", 0))
        except Exception:
            latency = 0.0

        async with self.session.begin():
            msg = Message(
                id=message_id,
                app_id=data.app_id,
                model_provider=data.model_provider,
                model_id=data.model_id,
                conversation_id=conversation_id,
                inputs=data.inputs or {},
                query=data.query,
                message={"content": data.query},
                message_tokens=message_tokens,
                answer=data.answer,
                answer_tokens=answer_tokens,
                provider_response_latency=latency,
                total_price=total_price,
                message_unit_price=message_unit_price,
                answer_unit_price=answer_unit_price,
                from_source="api",
                currency=self.currency,
                status="normal",
                error=None,
                message_metadata=data.metadata or {},
            )
            self.session.add(msg)

            # 会话统计：成功插入消息后 +1
            conv = await self.session.get(Conversation, conversation_id)
            if conv:
                conv.dialogue_count = (conv.dialogue_count or 0) + 1

        logger.debug("Message inserted: %s (conv=%s)", message_id, conversation_id)
        return message_id

    async def insert_message_files(
        self, message_id: str, files: List[Dict], user_id: str
    ) -> None:
        """插入消息文件记录（仅存储URL/路径，不做签名/托管/下载校验）"""
        if not files:
            return

        async with self.session.begin():
            for f in files:
                mf = MessageFile(
                    id=str(uuid.uuid4()),
                    message_id=message_id,
                    type=f.get("type", "document"),
                    transfer_method=f.get("transfer_method", "local_file"),
                    url=f.get("url", ""),
                    belongs_to=f.get("belongs_to", "user"),
                    upload_file_id=f.get("upload_file_id"),
                    created_by_role="end_user",
                    created_by=user_id,
                )
                self.session.add(mf)

        logger.debug("Message files inserted: %d (message_id=%s)", len(files), message_id)

    # 简单估算（可替换为项目内 TokenCounter）
    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
        english = len(re.findall(r"[a-zA-Z]+", text))
        return int(chinese * 1.5 + english * 1.3)

    def _calculate_price(self, message_tokens: int, answer_tokens: int) -> float:
        return round(((message_tokens + answer_tokens) / 1000.0) * self.price_per_1000, 6)
