# api/models.py
from pydantic import BaseModel
from typing import Literal


class ProjectCreate(BaseModel):
    client_slug: str
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    sector: str
    stakeholder_groups: list[str] = []
    value_stream_labels: list[str] = []
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    crews_enabled: list[str] = [
        "discovery", "value_design", "architecture", "delivery", "business_plan"
    ]
    review_gates: bool = True
    slack_channel: str = ""


class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str


class RunRequest(BaseModel):
    crew: str | None = None  # None = trigger PAM (full run)


class RunResponse(BaseModel):
    run_id: int
    project_slug: str
    crew: str
    status: str


class OutputResponse(BaseModel):
    id: int
    agent_name: str
    output_type: str
    file_path: str
    version: int
    review_status: str


class OrchestrationRunStatus(BaseModel):
    id: int
    status: str
    started_at: str | None
    completed_at: str | None


class StatusResponse(BaseModel):
    project_slug: str
    project_status: str
    crew_runs: list[dict]
    latest_orchestration_run: OrchestrationRunStatus | None = None
