from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PPTOutlineResponse(BaseModel):
    status: str = Field(..., description="处理状态：success/error")
    outline: List[Dict[str, Any]] = Field(
        default_factory=list, description="PPT大纲项目列表"
    )
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

