# api/main.py
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.config import get_settings
from api.routers import projects, run, outputs, ws
from api.routers import auth as auth_router
from api.routers import documents as documents_router
from api.routers import reviews as reviews_router
from api.routers import orchestrate as orchestrate_router
from api.routers import runs as runs_router
from api.routers import stakeholders as stakeholders_router
from api.routers import campaigns as campaigns_router
from api.routers import assignment as assignment_router
from api.routers import interviews as interviews_router
from api.routers import templates as templates_router
from api.routers import admin as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.database_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.projects_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AgentPool API", version="0.1.0", lifespan=lifespan, favicon_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(run.router)
app.include_router(outputs.router)
app.include_router(ws.router)
app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(reviews_router.router)
app.include_router(orchestrate_router.router)
app.include_router(runs_router.router)
app.include_router(stakeholders_router.router)
app.include_router(campaigns_router.router)
app.include_router(assignment_router.router)
app.include_router(interviews_router.router)
app.include_router(templates_router.router)
app.include_router(admin_router.router)
