# api/services/project_service.py
import json
import logging
import os
import tempfile
import yaml
from pathlib import Path
from api.config import get_settings
from api.database import (
    get_connection,
    get_db_path,
    is_contained_slug,
    insert_project,
    insert_stakeholder,
    fetch_stakeholders,
    seed_default_milestones,
    fetch_project,
    fetch_crew_runs,
    fetch_latest_orchestration_run,
    fetch_agent_outputs,
    list_projects,
    update_project_config,
    fetch_pending_reviews,
    fetch_all_orchestration_runs,
    get_system_connection,
    fetch_user,
    fetch_org_projects,
    fetch_user_project_memberships,
)
from api.services.invite_service import issue_invite
from api.models import ProjectCreate, ProjectSettings, OutputContent  # noqa: F401

logger = logging.getLogger(__name__)

# What the consultant is told about the invite that has just been minted, and it is worded
# this way because the truth is narrower than "an email is on its way".
#
# **Nothing in this product delivers an invite.** `issue_invite` writes a row to
# `auth_tokens` and returns the raw token; no caller anywhere passes it to
# `send_project_mail` or `send_platform_mail`, in any deployment mode. The scope for this
# work expected `dev_mode` to be the thing worth warning about - project mail is held and
# redirected to the operator - and `dev_mode` does not reach this path at all, because there
# is no send for it to hold. Saying "held and redirected" here would have been the exact
# defect CLAUDE.md's mail section records and calls the shape to watch for: a door answering
# `{"sent": true}` over a message nobody sent.
#
# So the response says what actually happened and what the consultant must now do. The route
# is `POST /projects/{slug}/stakeholders/{id}/resend-invite`, which returns the raw token for
# hand delivery, and its own docstring carries the second half of the bad news: there is no
# page in `ui/src` that redeems a token, so the link currently has nowhere to send somebody.
_INVITE_ISSUED = (
    "An invite has been issued for the approver. Nothing delivers it automatically - use "
    "Resend invite on the Stakeholders tab to retrieve the link and pass it to them."
)
_INVITE_NOT_ISSUED = (
    "The approver was recorded, but their invite could not be issued. They cannot reach the "
    "engagement until it is - use Resend invite on the Stakeholders tab."
)
_INVITE_ALREADY_ISSUED = (
    "This engagement already exists and already has this approver, so no second invite was "
    "issued. Use Resend invite on the Stakeholders tab if the original link was lost."
)


async def _ensure_approver(slug: str, name: str, email: str) -> dict:
    """Record the engagement's first approver, and invite them. Returns the approver state.

    **The two halves fail differently, on purpose, and this inverts one of CLAUDE.md's
    standing rules.** That rule - *a side effect must not veto the thing it is a side effect
    of* - is why `PATCH /reviews/{id}` files a skill proposal without letting a failed
    proposal hold a paused crew. The approver is not a side effect of creating a project; it
    is the reason this write exists. A creation that succeeded without the stakeholder row
    would answer 201 over precisely the dead end the field was added to close.

    So:

    - **the stakeholder write is unguarded and propagates.** If it raises, the creation
      fails.
    - **the invite mint is guarded and does not.** Losing it costs a recoverable token, not
      an engagement: `resend-invite` mints a fresh one, which is how the owner was unblocked
      by hand on `helia-digital-tau`. Failing the creation for a transient `system.db` lock,
      after the project directory, the database, the project row and the milestone schedule
      are all written, would be the worse trade in both directions.

    **Idempotent on the address, which is what makes the re-POST safe.**
    `create_project_endpoint` answers 200 to a re-POST of an existing slug, and that path
    must not mint a second stakeholder or a second token. Keying on the email rather than on
    a count of approvers is deliberate: a consultant who has since added a second approver
    through the Stakeholders tab, or removed this one and named somebody else, must not have
    their roster rewritten by a re-POST. The comparison is `.strip().lower()`, matching
    `_stakeholder_matches_invite` rather than inventing a third convention.

    That same condition is the repair path for the guarded half above: a creation whose
    invite mint failed is re-POSTed, finds the stakeholder already there, and - because a row
    that already exists is not re-invited - is told so rather than being handed a token
    silently. The operator's route back is `resend-invite` either way, which is the one door
    built for it.

    **No `has_linked_login` conjunct**, unlike `_issue_invite_if_newly_privileged` in
    `api/routers/stakeholders.py`, which needs it to stop a re-granted role minting an
    unsolicited password-reset credential onto a login that can already authenticate. That
    question cannot have a true answer here: it asks whether a login already reaches *this*
    project through `project_memberships`, and this project was created seconds ago with no
    memberships and no stakeholders for one to point at. A guard that can never fire is
    worse than no guard - it reads to the next reader as a case that has been considered and
    handled. The re-POST path does not reach the mint at all.
    """
    normalised = email.strip().lower()
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            # Unreachable from create_project, which has just inserted the row. Explicit
            # rather than an IndexError three frames down if it ever becomes reachable.
            raise RuntimeError(f"project {slug} vanished between creation and approver write")
        existing = [
            s
            for s in await fetch_stakeholders(conn, project_id=project["id"])
            if (s.get("email") or "").strip().lower() == normalised
        ]
        if existing:
            return {
                "stakeholder_id": existing[0]["id"],
                "name": existing[0]["name"],
                "email": existing[0]["email"],
                "created": False,
                "invited": False,
                "delivery": _INVITE_ALREADY_ISSUED,
            }
        stakeholder_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name=name,
            email=email,
            # is_approver alone. Not is_reviewer as well, and not is_project_admin: the hole
            # being closed is content approval, and the two axes are deliberately separate
            # (see CLAUDE.md). An approver can already contribute - `caller_may_contribute`
            # tests {reviewer, approver} - so adding is_reviewer would grant nothing and
            # would overstate what the consultant asked for. is_participant stays false: an
            # approver is not an interviewee by virtue of approving.
            is_approver=True,
            project_role="approver",
        )

    invited = False
    try:
        await issue_invite(email=email, project_slug=slug, stakeholder_id=stakeholder_id)
        invited = True
    except Exception:
        # Loudly, and then carry on. The stakeholder row is the thing that could not be lost
        # and it is already written; the token is the recoverable half. `exception` rather
        # than `warning` so the traceback reaches the log - an operator reading
        # `_INVITE_NOT_ISSUED` in the response needs somewhere to find out why.
        logger.exception(
            "approver stakeholder %s recorded on %s but the invite could not be issued",
            stakeholder_id,
            slug,
        )

    return {
        "stakeholder_id": stakeholder_id,
        "name": name,
        "email": email,
        "created": True,
        "invited": invited,
        "delivery": _INVITE_ISSUED if invited else _INVITE_NOT_ISSUED,
    }


async def create_project(req: ProjectCreate) -> dict:
    slug = req.client_slug
    settings = get_settings()

    # Create project directory structure
    project_dir = Path(settings.projects_dir) / slug
    (project_dir / "docs").mkdir(parents=True, exist_ok=True)
    (project_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Write config.yaml atomically (tempfile + os.replace prevents partial writes).
    # llm_mode is excluded: the database column (written below via insert_project) is
    # the sole authority for it, and config.yaml is read with a fail-open default, so a
    # copy here would let a drifted file route a sensitive project's work to a hosted
    # provider. config_json below keeps it - that copy is what the Settings tab round-trips.
    # The approver is excluded from both copies of the config, not merely from the YAML the
    # way llm_mode is. The stakeholder row is the authority on who approves: it is what
    # `caller_roles` walks, what the roster renders, and what the Stakeholders tab edits. A
    # copy in config_json would be a second answer to "who is the approver?" that no door
    # reads and nothing updates - stale the first time somebody changes the roster - and it
    # would put an address into the blob `ProjectSettings` round-trips, which CLAUDE.md
    # records as its own hazard.
    config = req.model_dump(exclude={"approver_name", "approver_email"})
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        yaml_config = {k: v for k, v in config.items() if k != "llm_mode"}
        fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.dump(yaml_config, f, default_flow_style=False)
            os.replace(tmp_path, config_path)
        except Exception:
            os.unlink(tmp_path)
            raise

    # Initialise SQLite DB and insert project
    async with get_connection(slug) as conn:
        await insert_project(
            conn,
            slug=slug,
            llm_mode=req.llm_mode,
            sector=req.sector,
            config_json=json.dumps(config),
        )
        # The default milestone set, written once here rather than lazily by the first
        # GET /projects/{slug}/milestones. That read did the seeding until sp38, which made
        # it a write behind a read gate: the operation POST /milestones/seed is
        # administration-gated for was reachable by any member simply by opening a fresh
        # project's dashboard. Creation is where an administrator is present by definition.
        #
        # Idempotent - it skips milestone_key values that already exist - so the
        # re-POST that create_project_endpoint answers 200 to on an existing slug is also
        # the repair path for a project predating this change whose table is still empty.
        await seed_default_milestones(conn, slug)
        result = await fetch_project(conn, slug=slug)

    # After the project row, because the stakeholder is a child of it - and unguarded,
    # because a project with no approver is the state this field exists to make
    # unreachable. See `_ensure_approver` for which half of it may fail and which may not.
    result["approver"] = await _ensure_approver(
        slug, req.approver_name, req.approver_email
    )

    await _register_daily_report_job(slug)
    return result


async def _register_daily_report_job(slug: str) -> None:
    """Register Pamela's daily report job for a newly created project.

    Boot-time registration (`api.main._register_scheduled_jobs`) only covers
    projects that already exist when the process starts, so a project created
    while the server is running would otherwise have no scheduled_jobs row
    until someone restarts it - silently producing no daily report, possibly
    for weeks. Uses the same upsert (ON CONFLICT DO NOTHING) and next_due_at
    computation as the boot path. Must never fail project creation - a
    scheduling problem is logged, not raised.
    """
    import logging
    from datetime import datetime

    from api.database import upsert_scheduled_job
    from api.services.pam_report_job import JOB_NAME
    from api.services.scheduler_service import next_due_at

    log = logging.getLogger(__name__)
    try:
        async with get_system_connection() as sys_conn:
            await upsert_scheduled_job(
                sys_conn, job_name=JOB_NAME, slug=slug,
                next_due_at=next_due_at(datetime.now()),
            )
    except Exception:
        log.exception("scheduler: could not register daily report job for %s", slug)


async def get_project_status(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        runs = await fetch_crew_runs(conn, project_id=project["id"])
        latest_orch = await fetch_latest_orchestration_run(conn, project_id=project["id"])
        return {
            "project_slug": slug,
            "project_status": project["status"],
            "crew_runs": runs,
            "latest_orchestration_run": latest_orch,
        }


async def get_project_outputs(slug: str) -> list[dict]:
    if not get_db_path(slug).exists():
        return []
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return []
        return await fetch_agent_outputs(conn, project_id=project["id"])


async def list_all_projects(payload: dict | None = None) -> list[dict]:
    """Return projects visible to the calling user. Pass None to skip filtering (internal use)."""
    settings = get_settings()
    data_dir = Path(settings.database_dir)
    if not data_dir.exists():
        return []
    all_slugs = [p.stem for p in data_dir.glob("*.db") if p.stem != "system"]

    if payload is None or payload.get("role") == "sysadmin":
        slugs_to_show = all_slugs
    else:
        async with get_system_connection() as sys_conn:
            if payload.get("role") == "org_admin":
                org_id = payload.get("org_id")
                rows = await fetch_org_projects(sys_conn, org_id=org_id) if org_id else []
                visible = {r["slug"] for r in rows}
            else:  # reviewer
                user = await fetch_user(sys_conn, username=payload["sub"])
                if not user:
                    return []
                rows = await fetch_user_project_memberships(sys_conn, user_id=user["id"])
                visible = {r["project_slug"] for r in rows}
        slugs_to_show = [s for s in all_slugs if s in visible]

    results = []
    for slug in slugs_to_show:
        if get_db_path(slug).exists():
            async with get_connection(slug) as conn:
                project = await fetch_project(conn, slug=slug)
                if project:
                    results.append(dict(project))
    return sorted(results, key=lambda p: p.get("created_at", ""), reverse=True)


async def read_project_config(slug: str) -> dict:
    """One project's stored `config_json`, or `{}` when there is nothing to read.

    The defensive read behind every "what has this project chosen for X?" accessor, extracted
    when the second one appeared rather than after the fourth. It differs from
    `get_project_settings` in what it is *for*: that answers the Settings tab, resolves
    `force_local_inference` from its authoritative column, and returns `None` so a missing
    project becomes a 404. This answers a single setting for a caller that has a default and
    no way to report a 404 - `InterviewSessionTool` runs inside a crew - so every "no answer
    here" state collapses to the same empty mapping and the caller applies its own default.

    **A blank slug raises**, the rule `project_llm_mode` was corrected to and
    `resolve_agent_config` follows: a caller that lost its slug must not be answered the
    defaults, because the same mistake in the LLM seam sent a sensitive engagement's
    interview answers to a hosted model. **A slug with no database answers `{}`**, which is
    the opposite case and deliberately not the same one - and `is_contained_slug` is asked
    before the path is touched so that probing slugs cannot materialise a database file per
    guess, the guard `caller_roles` already carries.
    """
    if not slug or not slug.strip():
        raise ValueError(
            "read_project_config requires a slug; a blank one is a caller that lost it, "
            "not a project that does not exist"
        )
    if not is_contained_slug(slug) or not get_db_path(slug).exists():
        return {}
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
    if not project:
        return {}
    try:
        config = json.loads(project.get("config_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return config if isinstance(config, dict) else {}


async def get_project_settings(slug: str) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        raw = project.get("config_json") or "{}"
        config = json.loads(raw)
        config.pop("client_slug", None)
        # `projects.force_local_inference` is the authority; config_json holds a copy so the
        # Settings tab can round-trip it. Answer from the column, because what this returns
        # is what the tab sends back: a project whose column was set before config_json ever
        # carried the key would otherwise be handed `false`, and the next save of an
        # unrelated field would clear the override without anybody asking. The same "read the
        # authority, never the copy" rule `_refuse_platform_tier_setting_changes` follows one
        # router over, applied to the read half - and that guard *depends* on this line
        # rather than carrying a copy of it, because two overrides would mean one of them
        # could be deleted with nothing failing. Removing this widens the door.
        config["force_local_inference"] = bool(project.get("force_local_inference") or 0)
        return config


async def update_project_settings(slug: str, settings: ProjectSettings) -> dict | None:
    if not get_db_path(slug).exists():
        return None
    settings_dict = settings.model_dump()
    full_config = {"client_slug": slug, **settings_dict}
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        await update_project_config(
            conn,
            slug=slug,
            project_id=project["id"],
            llm_mode=settings.llm_mode,
            force_local_inference=settings.force_local_inference,
            sector=settings.sector,
            config_json=json.dumps(full_config),
        )
    # llm_mode and force_local_inference are excluded from config.yaml for the same reason
    # as project creation: the database columns (written above via update_project_config)
    # are the sole authority for them, and config.yaml is read with a fail-open default.
    # full_config keeps both for config_json, which is what the Settings tab round-trips.
    project_dir = Path(get_settings().projects_dir) / slug
    config_path = project_dir / "config.yaml"
    project_dir.mkdir(parents=True, exist_ok=True)
    yaml_config = {
        k: v for k, v in full_config.items()
        if k not in ("llm_mode", "force_local_inference")
    }
    fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(yaml_config, f, default_flow_style=False)
        os.replace(tmp_path, config_path)
    except Exception:
        os.unlink(tmp_path)
        raise
    return settings_dict


async def get_output_content(slug: str, output_id: int) -> dict | None:
    """Return file content for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"content": str, "output_type": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path, output_type FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    content = file_path.read_text(encoding="utf-8")
    return {"content": content, "output_type": row["output_type"]}


async def get_output_file(slug: str, output_id: int) -> dict | None:
    """Locate the file for a given output record.

    Returns:
        None — project not found or output not found in this project's DB
        {"not_found_on_disk": True} — row exists but file deleted from disk
        {"file_path": Path, "filename": str} — success
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs WHERE id=? AND project_id=?",
            (output_id, project["id"]),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return {"file_path": file_path, "filename": file_path.name}


async def get_roadmap_data(slug: str) -> dict | None:
    """Return parsed roadmap JSON for the Gantt tab.

    Returns:
        None — project not found or no roadmap_data output exists
        {"not_found_on_disk": True} — row exists but file deleted from disk
        dict — parsed roadmap_data JSON (periods, initiatives, etc.)
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY created_at DESC LIMIT 1",
            (project["id"], "roadmap_data"),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    return json.loads(file_path.read_text(encoding="utf-8"))


async def get_financial_summary(slug: str) -> dict | None:
    """Return parsed financial summary metrics from the latest excel output.

    Returns:
        None — project not found or no excel output exists
        {"not_found_on_disk": True} — row exists but file deleted
        dict — six metric keys extracted from Sheet 2
    """
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        async with conn.execute(
            "SELECT file_path FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY created_at DESC LIMIT 1",
            (project["id"], "excel"),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
    file_path = Path(row["file_path"])
    if not file_path.exists():
        return {"not_found_on_disk": True}
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    if "Financial Summary" not in wb.sheetnames:
        return {"not_found_on_disk": True}
    ws = wb["Financial Summary"]
    keys = ["npv", "irr", "payback_period", "max_borrowing", "total_investment", "total_benefits"]
    return {key: ws.cell(row=i + 2, column=2).value for i, key in enumerate(keys)}


async def get_portfolio_register(slug: str) -> list | None:
    """Return the portfolio register JSON array for a project.

    Returns:
        None  — project DB does not exist (unknown project)
        []    — project exists but portfolio_register.json not on disk yet
        list  — parsed JSON array from outputs/portfolio_register.json
    """
    if not get_db_path(slug).exists():
        return None
    from agents.tools._db import current_output_path

    file_path = current_output_path(slug, "portfolio_register")
    if file_path is None:
        return []
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


async def get_pending_reviews(slug: str) -> list[dict] | None:
    """Return pending HITL reviews for a project. Returns None if project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_pending_reviews(conn, project_id=project["id"])


async def get_run_history(slug: str) -> list[dict] | None:
    """Return all orchestration runs with crew summaries. None = project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_all_orchestration_runs(conn, project_id=project["id"])


def get_value_chain_node_index(slug: str) -> dict[str, dict]:
    """Map every registered activity id to its label, level, and active flag.

    The registry is the canonical spine: an assignment stores only the node id, and the
    label it should be shown under is read back from here rather than copied onto the
    assignment row. Ask the ledger, never the copy.

    Returns {} when no registry has been written yet, which is the ordinary state of a
    project before the value chain mapper has run - a caller shows the raw id then.
    """
    from agents.tools._db import current_output_path

    path = current_output_path(slug, "value_chain_registry")
    if path is None or not path.exists():
        return {}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    index: dict[str, dict] = {}
    for activity in registry.get("activities", []):
        node_id = activity.get("id")
        if not node_id:
            continue
        index[str(node_id)] = {
            "label": activity.get("label", ""),
            "level": activity.get("level", ""),
            "active": bool(activity.get("active", True)),
        }
    return index


# get_value_chain_tree retired with the field it served. It read value_chain_tree.json,
# whose nodes carry a label, a level and their children and no id at all, for the assignment
# endpoint - which assigns by node id. `get_value_chain_node_index` above is the id-carrying
# read, and the registry endpoint serves the browser directly.
