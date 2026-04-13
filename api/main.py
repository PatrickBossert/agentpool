# api/main.py
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.config import get_settings
from api.routers import projects, run, outputs, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan, favicon_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
