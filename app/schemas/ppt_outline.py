from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# DetailType 类型定义（四类标准类型）
DetailType = Literal["text", "image", "list", "table"]

# 支持的 DetailType 列表（用于验证）
ALLOWED_DETAIL_TYPES: List[str] = ["text", "image", "list", "table"]


class DetailPayload(BaseModel):
    """
    详情内容载体结构（v2 规范）

    字段说明：
    - format: 承载格式，固定为 "markdown"
    - content: 具体的 Markdown 文本内容
    - imageUrl: 图片类型专用，真实可访问的图片 URL（仅当 detailType="image" 时存在）
    - alt: 图片替代文本
    - caption: 图片说明文字
    - assetId: 资源 ID（可选，用于关联上传文件）
    """

    format: str = Field(default="markdown", description="承载格式，默认为 markdown")
    content: str = Field(..., description="Markdown 格式的详情内容")

    # 图片类型专用字段（当 detailType="image" 时）
    imageUrl: Optional[str] = Field(default=None, description="图片 URL（仅图片类型）")
    assetId: Optional[str] = Field(default=None, description="资源 ID（可选）")
    alt: Optional[str] = Field(default=None, description="图片替代文本")
    caption: Optional[str] = Field(default=None, description="图片说明")

    class Config:
        extra = "allow"  # 允许额外字段以保持灵活性


class Substep(BaseModel):
    """子步骤结构"""

    key: str = Field(..., description="子步骤唯一标识")
    text: str = Field(..., description="子步骤文本描述")
    showDetail: bool = Field(..., description="是否显示详情")
    detailType: Optional[DetailType] = Field(
        default=None, description="详情类型：text/image/list/table（仅当 showDetail=true）"
    )
    detailPayload: Optional[Dict[str, Any]] = Field(
        default=None, description="详情内容载体（仅当 showDetail=true）"
    )


class OutlineItemMeta(BaseModel):
    """大纲项目元数据"""

    summary: str = Field(..., description="摘要说明")
    substeps: List[Substep] = Field(default_factory=list, description="子步骤列表")


class OutlineItem(BaseModel):
    """大纲项目结构"""

    key: str = Field(..., description="大纲项目唯一标识")
    title: str = Field(..., description="标题")
    description: str = Field(..., description="描述")
    detailType: Optional[DetailType] = Field(
        default=None, description="顶层详情类型（可选）"
    )
    meta: OutlineItemMeta = Field(..., description="元数据")
    schemaVersion: int = Field(default=2, description="数据契约版本号")


class PPTOutlineResponse(BaseModel):
    """
    PPT 大纲响应结构

    版本说明：
    - v1: 使用 detailPayload.type 和 detailPayload.data
    - v2: 使用 detailPayload.format 和 detailPayload.content，双写 data 字段兼容
    - schemaVersion=2 标记表示新版本数据结构
    """

    status: str = Field(..., description="处理状态：success/error")
    outline: List[Dict[str, Any]] = Field(
        default_factory=list, description="PPT大纲项目列表"
    )
    session_id: Optional[str] = Field(default=None, description="会话ID，用于前端轮询")
    is_completed: Optional[bool] = Field(default=None, description="是否已收敛完成")
    enhanced_outline_status: str = Field(
        default="pending",
        description="增强版大纲状态：pending/processing/completed/failed",
    )
    enhanced_outline_uuid: Optional[str] = Field(
        default=None, description="增强版大纲UUID（状态为completed时提供）"
    )
    topic: str = Field(..., description="PPT主题")
    language: str = Field(..., description="输出语言")
    execution_time: float = Field(..., description="执行时间（秒）")
    reference_sources: List[str] = Field(
        default_factory=list, description="参考文件源列表"
    )
