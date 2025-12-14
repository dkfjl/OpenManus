from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ThinkchainAnalysisRequest(BaseModel):
    chain_id: str = Field(..., description="链ID")
    session_id: Optional[str] = Field(None, description="会话ID（可选，默认最新）")
    language: Optional[str] = Field(None, description="分析语言（默认跟随链语言）")


class ThinkchainAnalysisResponse(BaseModel):
    status: str = Field(..., description="success/error")
    chain_id: str
    session_id: str
    analysis: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = Field(False, description="是否来自缓存")
