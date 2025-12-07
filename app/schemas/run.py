from typing import Optional, Dict, Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    prompt: Optional[str] = Field(default="", description="任务提示内容（可选，如果使用 promptId 则可为空）")
    promptId: Optional[str] = Field(default=None, description="提示词模板ID（可选）")
    promptType: Optional[Literal["recommended", "personal"]] = Field(
        default="recommended",
        description="提示词类型：recommended（推荐模板）或 personal（个人提示词）",
    )
    mergeVars: Optional[Dict[str, str]] = Field(
        default=None,
        description="变量字典，用于替换提示词模板中的 {变量名} 占位符",
    )
    allow_interactive_fallback: bool = Field(
        default=False,
        description="是否在缺少 prompt 时回退到交互输入（HTTP 接口默认关闭）",
    )


class RunResponse(BaseModel):
    status: str
    result: Optional[str] = None
