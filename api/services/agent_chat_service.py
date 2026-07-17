# api/services/agent_chat_service.py
"""Agent chat — persona definitions, context fetching, and Claude call."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from anthropic import AsyncAnthropic

from api.database import get_connection, get_db_path, fetch_project
from api.config import get_settings

# Max characters to include per output file in chat context.
_OUTPUT_CONTENT_LIMIT = 6_000


# ── Agent persona registry ─────────────────────────────────────────────────────
# output_types: list of agent_outputs.output_type values to load as file context.
# The most recent version of each type is fetched and included in the system prompt.

AGENT_PERSONAS: dict[str, dict] = {
    "PAM": {
        "first_name": "Pamela",
        "role": (
            "You are Pamela Reid, the Pipeline Automation Manager for this project. "
            "You coordinate all AI crews, track progress, and have full visibility of "
            "the project settings, milestones, schedule, and crew run history."
        ),
        "context_type": "pam",
        "output_types": [],
    },
    "Value Chain Mapper": {
        "first_name": "Alex",
        "role": "You decompose the organisation into a structured three-level value chain, assign stable numeric IDs to every node, and maintain the permanent registry that all downstream crews consume.",
        "context_type": "outputs",
        "output_types": ["value_chain", "state"],
    },
    "Interaction Designer": {
        "first_name": "Maya",
        "role": "You design the complete set of assessment instruments — interview scripts and maturity questionnaires — for every active value chain node, ensuring instruments are grounded in organisational structure and industry standards.",
        "context_type": "outputs",
        "output_types": ["value_chain", "state"],
    },
    "Stakeholder Manager": {
        "first_name": "Jordan",
        "role": "You actively manage stakeholder engagement across the interview programme: analysing coverage gaps, drafting invitation and reminder communications calibrated to seniority, and tracking session completion status.",
        "context_type": "stakeholders",
        "output_types": [],
    },
    "Requirements Capture": {
        "first_name": "Sam",
        "role": "You gather and document stakeholder requirements from discovery interviews, recording only what the team explicitly states using their exact wording.",
        "context_type": "stakeholders",
        "output_types": [],
    },
    "Requirements Analyst": {
        "first_name": "Riley",
        "role": "You analyse captured requirements for consistency, gaps, conflicts, and priority.",
        "context_type": "outputs",
        "output_types": ["discovery", "value_chain"],
    },
    "Value Lever Analyst": {
        "first_name": "Morgan",
        "role": "You identify the highest-value levers for organisational improvement based on discovery findings.",
        "context_type": "outputs",
        "output_types": ["discovery", "value_chain"],
    },
    "Interview Coordinator": {
        "first_name": "Taylor",
        "role": "You coordinate the scheduling and tracking of stakeholder interviews across the project.",
        "context_type": "interview_sessions",
        "output_types": [],
    },
    "Stakeholder Interviewer": {
        "first_name": "Avery",
        "role": "You conduct voice interviews with stakeholders and ensure their responses are captured accurately.",
        "context_type": "interview_sessions",
        "output_types": [],
    },
    "Synthesis Analyst": {
        "first_name": "Casey",
        "role": "You synthesise interview transcripts into structured findings and themes, identifying patterns that cross individual responses.",
        "context_type": "interview_sessions",
        "output_types": ["discovery"],
    },
    "Value Proposition Generator": {
        "first_name": "Quinn",
        "role": "You generate compelling value propositions from discovery findings.",
        "context_type": "outputs",
        "output_types": ["discovery", "value_chain"],
    },
    "Portfolio Manager": {
        "first_name": "Blake",
        "role": "You score and rank initiatives across the six capitals framework and manage the project portfolio.",
        "context_type": "outputs",
        "output_types": ["value_propositions", "discovery"],
    },
    "Enterprise Architect": {
        "first_name": "Drew",
        "role": "You design the enterprise architecture required to deliver the roadmap initiatives.",
        "context_type": "outputs",
        "output_types": ["architecture", "value_propositions", "value_chain"],
    },
    "Initiative Identifier": {
        "first_name": "Sage",
        "role": "You identify and define the key initiatives from the architecture blueprint.",
        "context_type": "outputs",
        "output_types": ["architecture", "value_chain"],
    },
    "Roadmap Generator": {
        "first_name": "River",
        "role": "You sequence initiatives across value streams and time horizons into a delivery roadmap.",
        "context_type": "outputs",
        "output_types": ["roadmap", "architecture"],
    },
    "Visual Illustrator": {
        "first_name": "Luca",
        "role": "You translate structured engagement outputs into richly contextualised illustration briefs ready for image generation, specifying visual style, composition, labelling, and flow elements.",
        "context_type": "outputs",
        "output_types": ["roadmap", "value_propositions", "architecture", "value_chain"],
    },
    "Business Plan Generator": {
        "first_name": "Finley",
        "role": "You produce the financial model and business plan narrative for the initiative portfolio.",
        "context_type": "outputs",
        "output_types": ["business_plan", "value_propositions", "roadmap"],
    },
}


# ── Context fetchers ───────────────────────────────────────────────────────────

async def _stakeholder_context(conn, project_id: int) -> str:
    async with conn.execute(
        "SELECT name, job_title, organisation, interview_status, "
        "interview_invited_at, interview_completed_at "
        "FROM stakeholders WHERE project_id=? ORDER BY name ASC",
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No stakeholders registered for this project yet."
    lines = ["STAKEHOLDERS", "-" * 40]
    for r in rows:
        status = r[3] or "not started"
        role_part = f", {r[1]}" if r[1] else ""
        org_part = f" ({r[2]})" if r[2] else ""
        lines.append(f"• {r[0]}{role_part}{org_part} — interview: {status}")
    return "\n".join(lines)


async def _interview_sessions_context(conn, project_id: int) -> str:
    async with conn.execute(
        """
        SELECT s.name, s.job_title, s.organisation,
               is_.node_label, is_.status, is_.started_at, is_.completed_at
        FROM interview_sessions is_
        LEFT JOIN stakeholders s ON s.id = is_.stakeholder_id
        WHERE is_.project_id = ?
        ORDER BY s.name ASC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No interview sessions have been created for this project yet."
    lines = ["INTERVIEW SESSIONS", "-" * 40]
    for r in rows:
        name = r[0] or "Unknown"
        role_part = f", {r[1]}" if r[1] else ""
        org_part = f" ({r[2]})" if r[2] else ""
        node = r[3]
        status = r[4]
        started = f", started {r[5]}" if r[5] else ""
        completed = f", completed {r[6]}" if r[6] else ""
        lines.append(f"• {name}{role_part}{org_part} — {node} — {status}{started}{completed}")
    return "\n".join(lines)


async def _outputs_context(conn, project_id: int) -> str:
    async with conn.execute(
        "SELECT crew_name, status, result_json FROM crew_runs "
        "WHERE project_id=? ORDER BY created_at DESC LIMIT 6",
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return "No crew runs have completed for this project yet."
    lines = ["RECENT CREW RUNS", "-" * 40]
    for r in rows:
        lines.append(f"Crew: {r[0]} — Status: {r[1]}")
    return "\n".join(lines)


async def _output_files_context(conn, project_id: int, output_types: list[str]) -> str:
    """Load the most recent file content for each requested output_type."""
    if not output_types:
        return ""
    blocks: list[str] = []
    for otype in output_types:
        async with conn.execute(
            "SELECT file_path, version FROM agent_outputs "
            "WHERE project_id=? AND output_type=? ORDER BY version DESC LIMIT 1",
            (project_id, otype),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            continue
        file_path = Path(row["file_path"])  # relative to repo root (server CWD)
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        if len(content) > _OUTPUT_CONTENT_LIMIT:
            content = content[:_OUTPUT_CONTENT_LIMIT] + "\n… [truncated]"
        blocks.append(
            f"OUTPUT: {otype} (v{row['version']})\n" + "-" * 40 + "\n" + content
        )
    if not blocks:
        return ""
    return "AGENT OUTPUT FILES\n" + "=" * 40 + "\n" + "\n\n".join(blocks)


async def _pam_context(conn, project_id: int) -> str:
    """Full project overview for PAM: settings, schedule, milestones, and crew run history."""
    import json as _json

    # Project settings (config_json)
    async with conn.execute(
        "SELECT slug, sector, config_json FROM projects WHERE id=?", (project_id,)
    ) as cur:
        project_row = await cur.fetchone()

    settings_lines = ["PROJECT SETTINGS", "-" * 40]
    if project_row:
        settings_lines.append(f"Slug: {project_row[0]}")
        if project_row[1]:
            settings_lines.append(f"Sector: {project_row[1]}")
        if project_row[2]:
            try:
                cfg = _json.loads(project_row[2])
                for key in ("locale", "sched_start", "sched_duration_weeks",
                            "n8n_webhook_url", "public_url"):
                    val = cfg.get(key)
                    if val is not None:
                        label = key.replace("_", " ").title()
                        settings_lines.append(f"{label}: {val}")
            except Exception:
                pass

    # Milestones
    async with conn.execute(
        "SELECT title, due_date, status, notes FROM project_milestones "
        "WHERE slug=? ORDER BY sort_order ASC",
        (project_row[0] if project_row else "",),
    ) as cur:
        milestone_rows = await cur.fetchall()

    milestone_lines = ["MILESTONES", "-" * 40]
    if milestone_rows:
        for r in milestone_rows:
            due = f", due {r[1]}" if r[1] else " (no date set)"
            note = f" — {r[3]}" if r[3] else ""
            milestone_lines.append(f"• {r[0]}{due} [{r[2]}]{note}")
    else:
        milestone_lines.append("No milestones found.")

    # Crew run history
    async with conn.execute(
        "SELECT crew_name, status, created_at FROM crew_runs "
        "WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
        (project_id,),
    ) as cur:
        run_rows = await cur.fetchall()

    run_lines = ["CREW RUN HISTORY", "-" * 40]
    if run_rows:
        for r in run_rows:
            run_lines.append(f"• {r[0]} — {r[1]} (started {r[2]})")
    else:
        run_lines.append("No crew runs yet.")

    return "\n".join(settings_lines) + "\n\n" + "\n".join(milestone_lines) + "\n\n" + "\n".join(run_lines)


async def _fetch_context(conn, project_id: int, context_type: str, output_types: list[str]) -> str:
    parts: list[str] = []
    if context_type == "pam":
        parts.append(await _pam_context(conn, project_id))
    elif context_type == "stakeholders":
        parts.append(await _stakeholder_context(conn, project_id))
    elif context_type == "interview_sessions":
        parts.append(await _interview_sessions_context(conn, project_id))
    else:
        parts.append(await _outputs_context(conn, project_id))

    file_ctx = await _output_files_context(conn, project_id, output_types)
    if file_ctx:
        parts.append(file_ctx)

    return "\n\n".join(parts)


# ── Multi-agent crew prompt ────────────────────────────────────────────────────

def _first_name(agent_name: str) -> str:
    return AGENT_PERSONAS.get(agent_name, {}).get("first_name", agent_name.split()[0])


def _parse_resolved_agent(response: str, crew_agents: list[str]) -> str:
    """Return the agent whose first name prefixes the response (e.g. 'Taylor: …')."""
    for agent in crew_agents:
        fn = _first_name(agent)
        if response.startswith(f"{fn}:") or response.startswith(f"{fn} :"):
            return agent
    return crew_agents[0]


async def _build_crew_system_prompt(
    conn, project_id: int, crew_agents: list[str], slug: str
) -> str:
    """Build a combined system prompt for a multi-agent crew.

    The model is instructed to self-select the right voice and prefix its reply
    with the agent's first name — no separate routing call needed.
    """
    # Roster with first names
    roster_lines = []
    for name in crew_agents:
        if name not in AGENT_PERSONAS:
            continue
        p = AGENT_PERSONAS[name]
        roster_lines.append(f"- {p['first_name']} ({name}): {p['role']}")
    roster = "\n".join(roster_lines)

    # Load context for each unique context_type, merge output_types
    seen_context_types: set[str] = set()
    all_output_types: list[str] = []
    context_parts: list[str] = []
    for name in crew_agents:
        if name not in AGENT_PERSONAS:
            continue
        p = AGENT_PERSONAS[name]
        ct = p["context_type"]
        if ct not in seen_context_types:
            seen_context_types.add(ct)
            ctx = await _fetch_context(conn, project_id, ct, [])
            context_parts.append(ctx)
        for ot in p.get("output_types", []):
            if ot not in all_output_types:
                all_output_types.append(ot)

    file_ctx = await _output_files_context(conn, project_id, all_output_types)
    if file_ctx:
        context_parts.append(file_ctx)

    context_block = "\n\n".join(context_parts)
    example_name = _first_name(crew_agents[0])

    return (
        f"You are part of an AI crew within the TaskReimagination.ai platform.\n\n"
        f"Your crew:\n{roster}\n\n"
        f"Project: {slug}\n"
        f"Today: {date.today().isoformat()}\n\n"
        f"{context_block}\n\n"
        f"Based on the user's question, respond as the single most appropriate crew member. "
        f"Begin your reply with your first name followed by a colon — for example: '{example_name}: …' "
        f"Use bullet points for lists. "
        f"If you don't have the data to answer, say so — don't invent details."
    )


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_agent_chat(
    slug: str,
    agent_name: str,
    message: str,
    history: list[dict],
    injected_docs: list[dict] | None = None,
    injected_links: list[dict] | None = None,
    crew_agents: list[str] | None = None,
) -> tuple[str, str] | None:
    """
    Returns (resolved_agent_name, reply) or None if the project DB doesn't exist.
    Multi-agent crews use a single combined prompt; the model self-selects a voice
    and prefixes its reply with the agent's first name (e.g. 'Taylor: …').
    Raises KeyError if agent_name is unknown (caller converts to 404).
    """
    is_multi = bool(crew_agents and len(crew_agents) > 1)

    # Validate the primary agent name exists (raises KeyError → 404 in router)
    if agent_name not in AGENT_PERSONAS:
        raise KeyError(agent_name)

    if not get_db_path(slug).exists():
        return None

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None

        if is_multi:
            system_prompt = await _build_crew_system_prompt(
                conn, project["id"], crew_agents, slug
            )
        else:
            persona = AGENT_PERSONAS[agent_name]
            context_block = await _fetch_context(
                conn, project["id"], persona["context_type"], persona.get("output_types", [])
            )
            system_prompt = (
                f"You are {agent_name}, an AI agent within the TaskReimagination.ai platform.\n\n"
                f"Your role: {persona['role']}\n\n"
                f"Project: {slug}\n"
                f"Today: {date.today().isoformat()}\n\n"
                f"{context_block}\n\n"
                "Answer the user's question helpfully and concisely. "
                "Use bullet points for lists. "
                "If you don't have the data to answer, say so — don't invent details."
            )

    if injected_docs:
        for doc in injected_docs:
            system_prompt += f"\n\n--- Shared file: {doc['original_name']} ---\n"
            if doc.get("is_image"):
                system_prompt += "[Image file — the user has shared this for context.]\n"
            else:
                system_prompt += doc.get("preview_text", "") or "[No text extracted]"

    if injected_links:
        for lnk in injected_links:
            system_prompt += f"\n\n--- Web page: {lnk['label']} ({lnk['url']}) ---\n"
            system_prompt += lnk.get("content_preview", "") or "[No content retrieved]"

    api_messages = [
        {
            "role": "assistant" if m["role"] == "agent" else "user",
            "content": m["content"],
        }
        for m in history
    ]
    api_messages.append({"role": "user", "content": message})

    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=system_prompt,
        messages=api_messages,
    )
    reply = response.content[0].text.strip()

    # Resolve which agent answered from the name prefix in the reply
    resolved = _parse_resolved_agent(reply, crew_agents) if is_multi else agent_name
    return resolved, reply
