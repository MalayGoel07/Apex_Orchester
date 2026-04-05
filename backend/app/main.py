from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers.auth import router as auth_router
from backend.app.routers.health import router as health_router
from backend.app.routers.task import router as orchestration_router
from backend.app.routers.tasks_demo import router as tasks_router

app = FastAPI()
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"],)
app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(orchestration_router)
app.include_router(auth_router)
