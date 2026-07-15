# api/models.py
from pydantic import BaseModel, Field
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


class ProjectSettings(BaseModel):
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
    discovery_brief: str = ""
    discovery_links: list[dict] = []
    discovery_document_ids: list[int] = []
    interview_method: Literal["agent", "none"] = "none"
    brand_header_image_url: str = ""
    brand_primary_color: str = Field(default="#0d9488", pattern=r"^#[0-9a-fA-F]{3,8}$")
    brand_text_color: str = Field(default="#1f2937", pattern=r"^#[0-9a-fA-F]{3,8}$")
    brand_interviewer_image_url: str = ""
    brand_interviewer_name: str = "Avery Singh"
    brand_interviewer_tagline: str = "I'll be guiding our conversation today"
    # Questionnaire configuration
    standards_references: str = ""
    preferred_questionnaire_sections: int = 4
    preferred_questions_per_section: int = 3
    # Locale (ISO 3166-1 alpha-2 country code)
    locale: str = "GB"
    # Schedule window — stored so PAM reports and other views read the same window
    sched_start: str | None = None
    sched_duration_weeks: int | None = None


class OutputContent(BaseModel):
    content: str
    output_type: str


class ProjectResponse(BaseModel):
    id: int
    slug: str
    llm_mode: str
    sector: str
    status: str


class RunRequest(BaseModel):
    crew: str | None = None   # None = trigger PAM (full run)
    agent: str | None = None  # internal agent key — runs that single agent standalone


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
    is_current: bool = True
    reviewer_notes: str | None = None
    revision_notes: str | None = None
    created_at: str = ''


class OrchestrationRunStatus(BaseModel):
    id: int
    status: str
    started_at: str | None
    completed_at: str | None
    error_detail: str | None = None


class StatusResponse(BaseModel):
    project_slug: str
    project_status: str
    crew_runs: list[dict]
    latest_orchestration_run: OrchestrationRunStatus | None = None


class Milestone(BaseModel):
    id: int
    slug: str
    milestone_key: str
    title: str
    description: str
    due_date: str | None
    status: str
    notes: str
    sort_order: int
    created_at: str


class MilestoneCreate(BaseModel):
    milestone_key: str = ""
    title: str
    description: str = ""
    due_date: str | None = None
    notes: str = ""
    sort_order: int = 999


class MilestoneUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_date: str | None = None
    status: str | None = None
    notes: str | None = None
    sort_order: int | None = None
