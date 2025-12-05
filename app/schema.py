from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Message role options"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


ROLE_VALUES = tuple(role.value for role in Role)
ROLE_TYPE = Literal[ROLE_VALUES]  # type: ignore


class ToolChoice(str, Enum):
    """Tool choice options"""

    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


TOOL_CHOICE_VALUES = tuple(choice.value for choice in ToolChoice)
TOOL_CHOICE_TYPE = Literal[TOOL_CHOICE_VALUES]  # type: ignore


class AgentState(str, Enum):
    """Agent execution states"""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class Function(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    """Represents a tool/function call in a message"""

    id: str
    type: str = "function"
    function: Function


class Message(BaseModel):
    """Represents a chat message in conversation"""

    role: ROLE_TYPE = Field(...)  # type: ignore
    content: Optional[str] = Field(default=None)
    tool_calls: Optional[List[ToolCall]] = Field(default=None)
    name: Optional[str] = Field(default=None)
    tool_call_id: Optional[str] = Field(default=None)
    base64_image: Optional[str] = Field(default=None)

    def __add__(self, other) -> List["Message"]:
        """支持 Message + list 或 Message + Message 的操作"""
        if isinstance(other, list):
            return [self] + other
        elif isinstance(other, Message):
            return [self, other]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(self).__name__}' and '{type(other).__name__}'"
            )

    def __radd__(self, other) -> List["Message"]:
        """支持 list + Message 的操作"""
        if isinstance(other, list):
            return other + [self]
        else:
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(other).__name__}' and '{type(self).__name__}'"
            )

    def to_dict(self) -> dict:
        """Convert message to dictionary format"""
        message = {"role": self.role}
        if self.content is not None:
            message["content"] = self.content
        if self.tool_calls is not None:
            message["tool_calls"] = [tool_call.dict() for tool_call in self.tool_calls]
        if self.name is not None:
            message["name"] = self.name
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.base64_image is not None:
            message["base64_image"] = self.base64_image
        return message

    @classmethod
    def user_message(
        cls, content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create a user message"""
        return cls(role=Role.USER, content=content, base64_image=base64_image)

    @classmethod
    def system_message(cls, content: str) -> "Message":
        """Create a system message"""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def assistant_message(
        cls, content: Optional[str] = None, base64_image: Optional[str] = None
    ) -> "Message":
        """Create an assistant message"""
        return cls(role=Role.ASSISTANT, content=content, base64_image=base64_image)

    @classmethod
    def tool_message(
        cls, content: str, name, tool_call_id: str, base64_image: Optional[str] = None
    ) -> "Message":
        """Create a tool message"""
        return cls(
            role=Role.TOOL,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            base64_image=base64_image,
        )

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs,
    ):
        """Create ToolCallsMessage from raw tool calls.

        Args:
            tool_calls: Raw tool calls from LLM
            content: Optional message content
            base64_image: Optional base64 encoded image
        """
        formatted_calls = [
            {"id": call.id, "function": call.function.model_dump(), "type": "function"}
            for call in tool_calls
        ]
        return cls(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=formatted_calls,
            base64_image=base64_image,
            **kwargs,
        )


class Memory(BaseModel):
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = Field(default=200)

    def add_message(self, message: Message) -> None:
        """Add a message to memory"""
        self.messages.append(message)
        self._trim_messages()

    def add_messages(self, messages: List[Message]) -> None:
        """Add multiple messages to memory"""
        self.messages.extend(messages)
        self._trim_messages()

    def clear(self) -> None:
        """Clear all messages"""
        self.messages.clear()

    def get_recent_messages(self, n: int) -> List[Message]:
        """Get n most recent messages"""
        return self.messages[-n:]

    def to_dict_list(self) -> List[dict]:
        """Convert messages to list of dicts"""
        return [msg.to_dict() for msg in self.messages]

    def _trim_messages(self) -> None:
        """Ensure message buffer stays within limit and tool replies stay valid."""
        if len(self.messages) <= self.max_messages:
            return

        buffer = self.messages[-self.max_messages :]

        cleaned: List[Message] = []
        for msg in buffer:
            if msg.role == Role.TOOL:
                if not cleaned:
                    continue
                prev = cleaned[-1]
                if prev.role != Role.ASSISTANT or not prev.tool_calls:
                    continue
                if not msg.tool_call_id:
                    continue
                if not any(call.id == msg.tool_call_id for call in prev.tool_calls):
                    continue
            cleaned.append(msg)

        self.messages = cleaned


class Substep(BaseModel):
    """PPT大纲子步骤"""

    key: str = Field(..., description="步骤唯一标识")
    text: str = Field(..., description="步骤描述文本")
    showDetail: bool = Field(default=False, description="是否显示详细信息")
    detailType: Optional[str] = Field(
        default=None, description="详情类型：markdown/ppt"
    )
    detailPayload: Optional[Dict[str, Any]] = Field(
        default=None, description="详情负载数据"
    )


class MetaData(BaseModel):
    """PPT大纲元数据"""

    summary: str = Field(..., description="该步骤的摘要说明")
    substeps: List[Substep] = Field(default_factory=list, description="子步骤列表")


class PPTOutlineItem(BaseModel):
    """PPT大纲项目"""

    key: str = Field(..., description="项目唯一标识")
    title: str = Field(..., description="标题")
    description: str = Field(..., description="描述")
    detailType: str = Field(default="markdown", description="详情类型")
    meta: MetaData = Field(..., description="元数据信息")


class PPTOutlineRequest(BaseModel):
    """PPT大纲生成请求"""

    topic: str = Field(..., description="PPT主题")
    language: str = Field(default="zh", description="输出语言，默认为中文")
    file_uuids: Optional[List[str]] = Field(
        default=None, description="已上传文件的UUID列表，用于引用之前上传的文件"
    )


class PPTOutlineResponse(BaseModel):
    """PPT大纲生成响应"""

    status: str = Field(..., description="处理状态：success/error")
    outline: List[PPTOutlineItem] = Field(
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


class FileInfo(BaseModel):
    """文件信息"""

    uuid: str = Field(..., description="文件UUID")
    original_name: str = Field(..., description="原始文件名")
    saved_name: str = Field(..., description="保存的文件名")
    size: int = Field(..., description="文件大小（字节）")
    type: str = Field(..., description="文件MIME类型")


class FileUploadResponse(BaseModel):
    """文件上传响应"""

    status: str = Field(..., description="上传状态：success/error")
    uuids: List[str] = Field(default_factory=list, description="上传文件的UUID列表")
    files: List[FileInfo] = Field(
        default_factory=list, description="上传文件的信息列表"
    )
    message: str = Field(..., description="响应消息")


class FileUploadRequest(BaseModel):
    """文件上传请求（用于文档说明）"""

    max_files: int = Field(default=5, description="最大文件数量")
    supported_types: List[str] = Field(
        default=["pdf", "docx", "txt", "jpg", "jpeg", "png", "html", "htm"],
        description="支持的文件类型",
    )
    max_file_size: int = Field(
        default=10 * 1024 * 1024, description="最大文件大小（字节）"
    )
