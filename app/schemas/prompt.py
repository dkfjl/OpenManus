"""
提示词库 API 数据模型定义
"""

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# ============ 请求模型 ============

class PromptCreate(BaseModel):
    """创建个人提示词请求"""
    name: str = Field(..., max_length=20, description="提示词名称，最长20字符")
    description: Optional[str] = Field(None, max_length=50, description="描述，最长50字符")
    prompt: str = Field(..., min_length=1, description="提示词内容")
    ownerId: str = Field(..., description="所有者ID")


class PromptUpdate(BaseModel):
    """更新个人提示词请求"""
    name: Optional[str] = Field(None, max_length=20, description="提示词名称")
    description: Optional[str] = Field(None, max_length=50, description="描述")
    prompt: Optional[str] = Field(None, min_length=1, description="提示词内容")
    version: Optional[int] = Field(None, description="版本号，用于并发控制")


# ============ 响应模型 ============

class PromptMetadata(BaseModel):
    """提示词元数据（用于列表展示）"""
    id: str = Field(..., description="提示词ID")
    name: str = Field(..., description="提示词名称")
    description: Optional[str] = Field(None, description="描述")


class PersonalPromptMetadata(PromptMetadata):
    """个人提示词元数据（扩展字段）"""
    ownerId: str = Field(..., description="所有者ID")
    version: int = Field(..., description="版本号")
    createdAt: str = Field(..., description="创建时间（ISO格式）")
    updatedAt: str = Field(..., description="更新时间（ISO格式）")


class RecommendedPrompt(PromptMetadata):
    """推荐模板（完整信息）"""
    prompt: str = Field(..., description="提示词内容")


class PersonalPrompt(PersonalPromptMetadata):
    """个人提示词（完整信息）"""
    prompt: str = Field(..., description="提示词内容")


class PromptOverviewResponse(BaseModel):
    """提示词列表响应"""
    items: List[Any] = Field(..., description="提示词列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")


class PromptDetailResponse(BaseModel):
    """提示词详情响应"""
    data: Any = Field(..., description="提示词详细信息")


class PromptCreateResponse(BaseModel):
    """创建提示词响应"""
    data: Dict[str, str] = Field(..., description="包含创建的提示词ID")
    message: str = Field(default="创建成功", description="响应消息")


class PromptUpdateResponse(BaseModel):
    """更新提示词响应"""
    data: Dict[str, str] = Field(..., description="包含更新的提示词ID")
    message: str = Field(default="更新成功", description="响应消息")


class PromptDeleteResponse(BaseModel):
    """删除提示词响应"""
    data: Dict[str, str] = Field(..., description="包含删除的提示词ID")
    message: str = Field(default="删除成功", description="响应消息")


# ============ 错误响应模型 ============

class ErrorDetail(BaseModel):
    """错误详情"""
    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    details: Optional[Any] = Field(None, description="详细错误信息")


class ErrorResponse(BaseModel):
    """错误响应"""
    error: ErrorDetail = Field(..., description="错误信息")


# ============ /run 接口扩展 ============

class RunRequestWithPrompt(BaseModel):
    """扩展的 /run 请求（支持 promptId 注入）"""
    prompt: Optional[str] = Field(None, description="任务提示内容")
    promptId: Optional[str] = Field(None, description="提示词模板ID")
    promptType: Optional[Literal["recommended", "personal"]] = Field(
        "recommended", description="提示词类型"
    )
    mergeVars: Optional[Dict[str, str]] = Field(None, description="变量替换字典")
    allow_interactive_fallback: bool = Field(
        default=False,
        description="是否在缺少 prompt 时回退到交互输入（HTTP 接口默认关闭）",
    )


# ============ 查询参数模型 ============

class PromptOverviewQuery(BaseModel):
    """提示词列表查询参数"""
    type: Literal["recommended", "personal"] = Field(..., description="提示词类型")
    name: Optional[str] = Field(None, description="名称模糊搜索")
    page: int = Field(1, ge=1, description="页码，从1开始")
    pageSize: int = Field(20, ge=1, le=100, description="每页数量，最大100")


class PromptDetailQuery(BaseModel):
    """提示词详情查询参数"""
    type: Literal["recommended", "personal"] = Field(..., description="提示词类型")
    id: str = Field(..., description="提示词ID")

