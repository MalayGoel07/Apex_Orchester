from fastapi import APIRouter, HTTPException
from backend.app.schemas.task_schema import (TaskRequest,TaskResponse,)
from backend.app.agents.llama3 import orchestrate
import asyncio

router = APIRouter(prefix="/api", tags=["orchestration"])

@router.post("/run-task", response_model=TaskResponse)
async def run_task_api(data: TaskRequest):
    try:
        result = await asyncio.to_thread(orchestrate, data.task,data.enable_quality_check)
        agents_used = result.get("agents_used", [])
        selected_agent=", ".join(agents_used)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TaskResponse(
        status="success",
        output=result.get("output", ""),
        selected_agent=selected_agent,
        fallback_used=bool(result.get("fallback_used", False)),
        agents_used=agents_used,
        gemini_quota_remaining=result.get("gemini_quota_remaining"),
        warning=result.get("warning"),
        error=result.get("error"),
    )
