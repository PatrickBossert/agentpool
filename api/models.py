# api/models.py
from api.services.interview_script_model import DEFAULT_DISCIPLINES
from pydantic import BaseModel, Field
from typing import Literal


class ProjectCreate(BaseModel):
    client_slug: str
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    sector: str
    stakeholder_groups: list[str] = []
    value_stream_labels: list[str] = []
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    review_gates: bool = True
    slack_channel: str = ""


class ProjectSettings(BaseModel):
    llm_mode: Literal["standard", "sensitive", "fallback"] = "standard"
    # Removes HOSTED_INFERENCE from whatever this project's mode grants, so a `standard`
    # engagement can be measured against local models while its documents stay in Chroma
    # Cloud. It only ever narrows - see api/services/deployment_modes.py::project_grants.
    # Platform-tier (`_PLATFORM_TIER_SETTINGS` in api/routers/projects.py) because clearing
    # it *widens*: it moves an engagement's prompts back onto hosted inference.
    # `projects.force_local_inference` is the authority; the copy here is what the Settings
    # tab round-trips, and `get_project_settings` overwrites it from the column on the way
    # out so the copy can never be the thing a save sends back.
    force_local_inference: bool = False
    sector: str
    stakeholder_groups: list[str] = []
    value_stream_labels: list[str] = []
    roadmap_time_axis: Literal["quarters", "years", "horizons"] = "quarters"
    review_gates: bool = True
    slack_channel: str = ""
    # When true, all outbound project email goes to a single dev address instead
    # of real stakeholders. Defaults to true: emailing real people the first time
    # the scheduler runs correctly is a worse failure than emailing nobody.
    dev_mode: bool = True
    discovery_brief: str = ""
    discovery_links: list[dict] = []
    discovery_document_ids: list[int] = []
    interview_method: Literal["agent", "none"] = "none"
    # Wall-clock budget for one elaboration press (api/services/interview_service.py).
    # Declared here or it does not exist: pydantic v2 defaults to extra='ignore', so an
    # undeclared key is dropped inbound on PATCH, stripped outbound on GET, and erased from
    # config_json by update_project_settings, which writes model_dump() as the whole config.
    # Bounded rather than free because the UI's min/max are advisory only - a cleared number
    # input sends Number('') === 0, which reaches asyncio.wait_for(timeout=0) and silently
    # skips every press.
    elaboration_press_timeout_seconds: int = Field(default=8, ge=1, le=60)
    # Model selection. Defaults here rather than in the registry so a project created before
    # this feature resolves exactly as it did before, and so the UI has something to show.
    anthropic_fast_model: str = "anthropic/claude-haiku-4-5-20251001"
    anthropic_deep_model: str = "anthropic/claude-opus-4-6"
    local_fast_model: str = "gemma4:fast"
    local_fast_url: str = "http://localhost:11434/v1"
    local_deep_model: str = "qwen27b:reasoning"
    local_deep_url: str = "http://localhost:11434/v1"
    brand_header_image_url: str = ""
    brand_primary_color: str = Field(default="#0d9488", pattern=r"^#[0-9a-fA-F]{3,8}$")
    brand_text_color: str = Field(default="#1f2937", pattern=r"^#[0-9a-fA-F]{3,8}$")
    # Retained so a stored config keeps round-tripping, and **no longer read by the interview
    # portal**: the interviewer's name and face come from the session's stamp through
    # `resolve_agent_config`, which is keyed on the permanent `agent_id` and overridable per
    # project in `project_agent_config`. The default here was the literal "Avery Singh", which
    # meant every project that had ever saved settings held it and the server could not tell a
    # brand decision from an inheritance - so with two interviewers on the roster, half of
    # every project's participants would have heard Laura and read Avery. No UI has ever
    # offered either field. Task 5 decides whether they are retired outright.
    brand_interviewer_image_url: str = ""
    brand_interviewer_name: str = ""
    brand_interviewer_tagline: str = "I'll be guiding our conversation today"
    # Which interviewer a participant meets. Resolved once per session, at creation, and
    # stamped on the row - never re-read at interview time, so a project that changes this
    # setting does not change who conducted an interview that has already been issued.
    #
    # Deliberately **not** platform-tier (`_PLATFORM_TIER_SETTINGS` in api/routers/projects.py).
    # It decides the tone of a conversation, not where a project's material is sent, and the
    # eight fields on that list are there because they move data across a boundary. A
    # project_admin configuring their own engagement's interview programme is exactly the
    # authority sp44 widened those fifteen doors for.
    #
    # `always_male` and `always_female` are answered from the *voices'* own ElevenLabs
    # metadata rather than from any list in this codebase - see
    # api/services/interviewer_selection.py. `random` is the default and needs no metadata at
    # all, so the shipped path makes no call to ask.
    interviewer_selection: Literal["always_male", "always_female", "random"] = "random"
    # Which regional accent this project's interviewer voices are picked from. Held in
    # **ElevenLabs' own vocabulary** - british, scottish, irish, australian, new zealand -
    # and forwarded to `GET /v1/shared-voices?accent=` unmodified, so nothing here translates
    # it and no list of accents is maintained against theirs. A plain `str` rather than a
    # `Literal` for that reason: closing the set would restate a vocabulary that is not ours,
    # and an unrecognised value comes back as an empty listing with the accent named rather
    # than as an outage. `""` means every accent.
    #
    # **Not derived from `locale` below**, which is the country and is `GB` for a Scottish
    # engagement exactly as it is for a British one - the first of the four planned
    # engagements is the case that breaks the derivation. See api/services/voice_settings.py.
    interview_accent: str = "british"
    # Project context - set on Alex's setup tab to ground Maya's interview instruments, and
    # since sp56 also the participant-facing name of the engagement: `outbound_mail` heads
    # stakeholder mail with it, so a participant reads "GS Asset Management - Your interview
    # transcript" rather than the slug `sp-gs-am`. Empty is the shipped default and means
    # "no prefix" - never a fallback to the slug, and never to the registry display_name,
    # which is initialised *to* the slug at project creation.
    client_name: str = ""
    # The vertical axis Casey groups maturity themes by. Closed so that grouping is an
    # exact-value query rather than prose clustering, and per project because a discipline
    # that matters in one engagement does not in another.
    disciplines: list[str] = list(DEFAULT_DISCIPLINES)
    service_categories: str = ""
    key_vendors: str = ""
    applicable_regulations: str = ""
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
    # Both absent is refused with 400 by the handler - there is no default crew and no PAM
    # path here. Optional rather than required because either one alone is a valid request.
    crew: str | None = None   # crew name — runs that crew
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
    # When the milestone was actually reached. Null while outstanding - slippage is the
    # difference between this and due_date.
    completed_at: str | None = None
    # What it was promised, set once at activation. due_date is what is currently expected.
    baseline_date: str | None = None
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
    completed_at: str | None = None


class MilestoneRebaseline(BaseModel):
    baseline_date: str
    # Required and non-blank: a re-baseline nobody explained is indistinguishable from a
    # mistake six months later, when the only remaining evidence is that the date moved.
    reason: str
