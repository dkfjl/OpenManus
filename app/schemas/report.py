from typing import Optional

from pydantic import BaseModel, Field


class ReportResult(BaseModel):
    status: str
    filepath: str
    title: str
    agent_summary: Optional[str] = None
    # 对象存储相关字段
    file_uuid: Optional[str] = Field(None, description="文件在对象存储中的UUID")
    preview_url: Optional[str] = Field(None, description="预览URL路径")
    download_url: Optional[str] = Field(None, description="下载URL路径")
    storage_enabled: bool = Field(False, description="是否启用了对象存储")

