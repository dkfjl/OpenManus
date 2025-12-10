from __future__ import annotations

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Index, UniqueConstraint, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    """Declarative base for chat feature tables."""


class ConversationStatus(enum.Enum):
    normal = "normal"
    archived = "archived"
    deleted = "deleted"


class MessageStatus(enum.Enum):
    normal = "normal"
    error = "error"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    status: Mapped[ConversationStatus] = mapped_column(
        sa.Enum(ConversationStatus), default=ConversationStatus.normal, nullable=False
    )
    inputs: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    from_end_user_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    from_source: Mapped[str] = mapped_column(sa.String(32), default="api", nullable=False)
    mode: Mapped[str] = mapped_column(sa.String(32), default="chat", nullable=False)
    dialogue_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_conv_app_created", "app_id", "created_at"),
        Index("idx_conv_user_created", "from_end_user_id", "created_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        sa.String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    app_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    inputs: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    query: Mapped[str] = mapped_column(sa.Text, nullable=False)
    message: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    message_tokens: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    answer: Mapped[str] = mapped_column(sa.Text, nullable=False)
    answer_tokens: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    provider_response_latency: Mapped[float] = mapped_column(
        sa.DECIMAL(10, 3), default=0, nullable=False
    )
    total_price: Mapped[float] = mapped_column(
        sa.DECIMAL(18, 6), default=0, nullable=False
    )
    message_unit_price: Mapped[float] = mapped_column(
        sa.DECIMAL(18, 6), default=0, nullable=False
    )
    answer_unit_price: Mapped[float] = mapped_column(
        sa.DECIMAL(18, 6), default=0, nullable=False
    )
    from_source: Mapped[str] = mapped_column(sa.String(32), default="api", nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(8), default="USD", nullable=False)
    status: Mapped[MessageStatus] = mapped_column(
        sa.Enum(MessageStatus), default=MessageStatus.normal, nullable=False
    )
    error: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    message_metadata: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_msg_conv_created", "conversation_id", "created_at"),
    )


class MessageFile(Base):
    __tablename__ = "message_files"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        sa.String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(sa.String(16), default="document", nullable=False)
    transfer_method: Mapped[str] = mapped_column(
        sa.String(16), default="local_file", nullable=False
    )
    url: Mapped[str] = mapped_column(sa.String(2048), nullable=False)
    belongs_to: Mapped[str] = mapped_column(sa.String(16), default="user", nullable=False)
    upload_file_id: Mapped[Optional[str]] = mapped_column(sa.String(128), nullable=True)
    created_by_role: Mapped[str] = mapped_column(
        sa.String(16), default="end_user", nullable=False
    )
    created_by: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (Index("idx_file_msg", "message_id"),)
