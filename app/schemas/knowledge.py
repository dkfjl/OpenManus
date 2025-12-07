from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class ExpansionInfo(BaseModel):
    seedQuery: str = Field(..., description="原始查询")
    paraphrases: List[str] = Field(default_factory=list, description="同义改写列表")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    perQueryHits: Dict[str, int] = Field(default_factory=dict, description="每个子查询命中数")
    failedQueries: List[str] = Field(default_factory=list, description="检索失败的子查询")
    dataset_id: Optional[str] = Field(default=None, description="使用的数据集 ID")


class ConflictVariant(BaseModel):
    statement: str = Field(..., description="版本表述")
    sources: List[str] = Field(default_factory=list, description="来源标识（如URL/文档ID）")


class ConflictItem(BaseModel):
    claim: str = Field(..., description="冲突点标准化描述")
    variants: List[ConflictVariant] = Field(default_factory=list, description="不同版本")
    resolution: Optional[str] = Field(default=None, description="本次采用的结论或未裁决说明")
    basis: Optional[str] = Field(default=None, description="取舍依据（权威/新鲜度/一致性/相关性）")


class DecisionBasis(BaseModel):
    rules: List[str] = Field(default_factory=lambda: [
        "authority>freshness>consistency>relevance"
    ])
    applied: List[str] = Field(default_factory=list, description="本次应用的取舍说明列表")


class KnowledgeSearchRequest(BaseModel):
    """Request body for /api/kb/retrieve with per-request overrides and expansion control."""

    query: str = Field(..., description="搜索问题或关键词")
    # Per-request override
    api_key: Optional[str] = Field(default=None, description="覆盖 Dify API Key（仅当次请求）")
    dataset_id: Optional[str] = Field(default=None, alias="datasetId", description="数据集ID覆盖")
    topK: Optional[int] = Field(default=None, description="返回条数（可选，不传则使用系统默认）")
    scoreThreshold: Optional[float] = Field(default=None, description="最小相关性阈值（可选）")

    # Expansion controls
    strategy: Optional[Literal["fast", "thorough"]] = Field(
        default="fast", description="查询扩展策略：快速/深入"
    )
    maxParaphrases: Optional[int] = Field(default=2, description="最大改写数")
    maxKeywords: Optional[int] = Field(default=5, description="最大关键词数")
    returnExpansion: Optional[bool] = Field(default=True, description="是否返回查询扩展信息")

    class Config:
        allow_population_by_field_name = True


class KnowledgeRecord(BaseModel):
    content: str = Field("", description="命中片段文本")
    score: Optional[float] = Field(None, description="相关性得分")
    metadata: Optional[Dict[str, Any]] = Field(None, description="命中元数据")


class KnowledgeSearchResponse(BaseModel):
    items: List[KnowledgeRecord] = Field(..., description="检索结果列表")
    total: int = Field(..., description="总命中数")
    query: str = Field(..., description="原始查询")
    expansion: Optional[ExpansionInfo] = Field(default=None, description="查询扩展信息")


class KnowledgeAnswerRequest(KnowledgeSearchRequest):
    answerStyle: Optional[Literal["concise", "detailed", "bullet"]] = Field(
        default="concise", description="回答风格"
    )
    returnCitations: Optional[bool] = Field(
        default=True, description="是否返回引用/证据"
    )
    returnConflicts: Optional[bool] = Field(
        default=True, description="是否返回冲突清单"
    )
    authorityHint: Optional[List[str]] = Field(
        default=None, description="优先来源提示（域名/标签）"
    )
    freshnessWindowDays: Optional[int] = Field(
        default=None, description="优先近 N 天证据"
    )


class KnowledgeAnswerResponse(BaseModel):
    answer: str = Field(..., description="基于知识片段生成的回答")
    citations: Optional[List[KnowledgeRecord]] = Field(
        default=None, description="引用的片段（可选）"
    )
    usedRecords: Optional[List[KnowledgeRecord]] = Field(
        default=None, description="用于生成的片段（可选，便于前端折叠展示）"
    )
    conflicts: Optional[List[ConflictItem]] = Field(
        default=None, description="冲突清单（可选）"
    )
    decisionBasis: Optional[DecisionBasis] = Field(
        default=None, description="本次取舍依据说明"
    )
    expansion: Optional[ExpansionInfo] = Field(default=None, description="查询扩展信息")
