from fastapi import APIRouter

from backend.app.services.task_service import get_random_task

router = APIRouter(prefix="/api", tags=["tasks"])

@router.get("/task")
def get_task():
    return {"task": get_random_task()}
