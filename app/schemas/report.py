from typing import Optional

from pydantic import BaseModel, Field


class ReportResult(BaseModel):
    status: str
    filepath: str
    title: str
    agent_summary: Optional[str] = None

