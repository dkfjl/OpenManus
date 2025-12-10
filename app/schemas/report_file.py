"""报告文件存储相关的Pydantic schemas"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FileMetadata(BaseModel):
    """文件元数据"""
    name: str = Field(..., description="文件名")
    size: int = Field(..., description="文件大小（字节）")
    type: str = Field(default="docx", description="文件类型")


class PreviewOptions(BaseModel):
    """预览选项"""
    max_size: int = Field(default=50 * 1024 * 1024, description="最大预览文件大小（字节）")
    supported_features: list[str] = Field(
        default_factory=lambda: ["text", "tables", "images", "lists", "basic_formatting"],
        description="支持的功能"
    )
    unsupported_features: list[str] = Field(
        default_factory=lambda: ["charts", "advanced_graphics", "macros"],
        description="不支持的功能"
    )


class FileInfoResponse(BaseModel):
    """文件信息响应"""
    file_uuid: str = Field(..., description="文件UUID")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    created_at: datetime = Field(..., description="创建时间")


class PreviewURLResponse(BaseModel):
    """预览URL响应"""
    preview_url: str = Field(..., description="预览URL")
    expire_at: datetime = Field(..., description="过期时间")
    file_info: FileInfoResponse = Field(..., description="文件信息")


class PreviewDataResponse(BaseModel):
    """预览数据响应"""
    preview_url: str = Field(..., description="预览URL")
    file_metadata: FileMetadata = Field(..., description="文件元数据")
    preview_options: PreviewOptions = Field(..., description="预览选项")
    expires_at: datetime = Field(..., description="URL过期时间")


class DownloadURLResponse(BaseModel):
    """下载URL响应"""
    download_url: str = Field(..., description="下载URL")
    expires_in: int = Field(..., description="过期时间（秒）")


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    file_uuid: str = Field(..., description="文件UUID")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    created_at: datetime = Field(..., description="创建时间")
    preview_url: str = Field(..., description="预览URL路径")


class MetadataResponse(BaseModel):
    """元数据响应"""
    file_uuid: str = Field(..., description="文件UUID")
    filename: str = Field(..., description="文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    file_size_human: str = Field(..., description="人类可读的文件大小")
    created_at: str = Field(..., description="创建时间（ISO格式）")
    content_type: str = Field(..., description="内容类型")
    supports_preview: bool = Field(default=True, description="是否支持预览")
    preview_compatible: bool = Field(default=True, description="是否与docx-preview兼容")


class DeleteFileResponse(BaseModel):
    """删除文件响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
