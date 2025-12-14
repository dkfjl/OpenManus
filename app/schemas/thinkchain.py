from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Allowed detail types for substep details
DetailType = Literal["text", "image", "list", "table"]


class OverviewStep(BaseModel):
    """A single planning step produced by /overview."""

    key: int = Field(..., description="1-based step index")
    title: str = Field(..., description="Step title")
    description: str = Field(..., description="Detailed description of the step")


class ChainOverview(BaseModel):
    steps: List[OverviewStep] = Field(default_factory=list)


class ThinkchainOverviewResponse(BaseModel):
    status: str = Field(..., description="success/error")
    chain_id: str = Field(..., description="Server-side identifier for the chain")
    task_type: str = Field(..., description="normal/report/ppt")
    topic: str = Field(..., description="Task topic")
    language: str = Field(..., description="Output language")
    reference_sources: List[str] = Field(default_factory=list)
    uuid_files: List[str] = Field(default_factory=list, description="Validated existing file UUIDs")
    chain: ChainOverview = Field(...)


class DetailPayload(BaseModel):
    """Detail payload for substeps. Markdown-first per spec."""

    format: str = Field(default="markdown")
    content: str = Field(..., description="Markdown content")
    imageUrl: Optional[str] = Field(default=None)
    assetId: Optional[str] = Field(default=None)
    alt: Optional[str] = Field(default=None)
    caption: Optional[str] = Field(default=None)

    class Config:
        extra = "allow"


class Substep(BaseModel):
    key: str
    text: str
    showDetail: bool
    detailType: Optional[DetailType] = None
    detailPayload: Optional[Dict[str, Any]] = None


class OutlineItemMeta(BaseModel):
    summary: str
    substeps: List[Substep] = Field(default_factory=list)


class OutlineItem(BaseModel):
    key: str
    title: str
    description: str
    detailType: Optional[DetailType] = Field(default="text")
    meta: OutlineItemMeta


class ThinkchainGenerateResponse(BaseModel):
    status: str
    outline: List[Dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    is_completed: Optional[bool] = None
    topic: str
    language: str
    execution_time: float
    reference_sources: List[str] = Field(default_factory=list)
