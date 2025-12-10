from __future__ import annotations

from typing import Optional, Dict, List

from pydantic import BaseModel, Field


class ChatData(BaseModel):
    """聊天数据模型（入参）

    保持与说明书一致的字段命名。
    """

    app_id: str = Field(..., description="应用ID，必需")
    user_id: str = Field(..., description="用户ID，必需")
    query: str = Field(..., description="用户查询，必需")
    answer: str = Field(..., description="AI回答，必需")

    # 模型信息（可选）
    model_provider: str = Field(default="custom", description="模型提供商")
    model_id: str = Field(default="custom-model", description="模型ID")

    # 幂等/锚点
    conversation_id: Optional[str] = Field(
        default=None, description="会话ID，可选。提供则复用/幂等创建"
    )
    mode: str = Field(default="chat", description="会话模式，默认 chat")

    # 附件与上下文
    files: List[Dict] = Field(default_factory=list, description="文件列表")
    inputs: Dict = Field(default_factory=dict, description="输入参数（JSON）")
    metadata: Dict = Field(default_factory=dict, description="元数据（JSON）")


class InsertResult(BaseModel):
    """插入结果（出参）"""

    success: bool
    conversation_id: str
    message_id: str
    error: Optional[str] = None


class FileData(BaseModel):
    """文件数据模型（入参files元素）"""

    type: str = Field(
        default="document",
        description="文件类型：document/image/audio/video/other",
    )
    transfer_method: str = Field(
        default="local_file", description="传输方式：local_file/remote_url"
    )
    url: str = Field(..., description="文件URL或本地绝对路径；不做签名/托管")
    belongs_to: str = Field(
        default="user", description="归属：user/assistant/system"
    )
    upload_file_id: Optional[str] = Field(
        default=None, description="外部上传ID，可选"
    )


class ChatRequest(BaseModel):
    """聊天请求模型（HTTP层）

    按说明书保持字段命名；包含常用可选项。
    """

    app_id: str
    user_id: str
    query: str
    answer: str
    model_provider: str = "custom"
    model_id: str = "custom-model"
    conversation_id: Optional[str] = None
    mode: str = "chat"
    files: List[Dict] = Field(default_factory=list)
    inputs: Dict = Field(default_factory=dict)
    metadata: Dict = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """聊天响应模型（HTTP层）"""

    success: bool
    conversation_id: str
    message_id: str
    error: Optional[str] = None
