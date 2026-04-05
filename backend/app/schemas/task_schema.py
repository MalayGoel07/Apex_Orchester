from pydantic import BaseModel, Field
from typing import List, Optional

class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=500)
    enable_quality_check: bool=False

class TaskResponse(BaseModel):
    status: str
    output: str
    selected_agent: str
    fallback_used: bool
    agents_used: List[str] = []
    gemini_quota_remaining: Optional[int] = None
    warning: Optional[str] = None
    error: Optional[str] = None
