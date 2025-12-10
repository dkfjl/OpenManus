from __future__ import annotations

from datetime import datetime
from typing import Optional
import enum

import sqlalchemy as sa
from sqlalchemy import Index, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for report file storage tables."""


class FileStatus(enum.Enum):
    active = "active"
    expired = "expired"
    deleted = "deleted"


class AccessType(enum.Enum):
    preview = "preview"
    download = "download"


class ReportFile(Base):
    """报告文件元数据表"""
    __tablename__ = "report_files"

    # SQLite兼容：使用Integer而不是BigInteger作为主键
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(sa.String(36), unique=True, nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    storage_type: Mapped[str] = mapped_column(sa.String(50), default="oss", nullable=False)
    content_type: Mapped[str] = mapped_column(
        sa.String(100),
        default="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    # SQLite兼容：使用DateTime而不是TIMESTAMP
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime, nullable=True)
    download_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    # SQLite兼容：对于Enum，使用String存储值
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default="active",
        nullable=False
    )
    # SQLite支持JSON（SQLite 3.9+）
    # 注意：metadata是SQLAlchemy保留字段，改用extra_metadata
    extra_metadata: Mapped[Optional[dict]] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        Index("idx_created_by", "created_by"),
        Index("idx_created_at", "created_at"),
        Index("idx_status", "status"),
    )


class FileAccessLog(Base):
    """文件访问日志表"""
    __tablename__ = "file_access_logs"

    # SQLite兼容：使用Integer而不是BigInteger作为主键
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    file_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(sa.String(100), nullable=True)
    # SQLite兼容：对于Enum，使用String存储值
    access_type: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False
    )
    access_ip: Mapped[Optional[str]] = mapped_column(sa.String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    presign_url: Mapped[Optional[str]] = mapped_column(sa.String(1000), nullable=True)
    # SQLite兼容：使用DateTime而不是TIMESTAMP
    expire_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime, nullable=True)
    access_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False
    )

    __table_args__ = (
        Index("idx_user_id", "user_id"),
        Index("idx_access_at", "access_at"),
    )
