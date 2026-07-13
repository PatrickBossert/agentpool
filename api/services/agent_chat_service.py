# api/services/agent_chat_service.py
"""Agent chat — persona definitions, context fetching, and Claude call."""
from __future__ import annotations

from datetime import date
from anthropic import AsyncAnthropic

from api.database import get_connection, get_db_path, fetch_project


# ── Agent persona registry ─────────────────────────────────────────────────────

AGENT_PERSONAS: dict[str, dict] = {
    "Value Chain Mapper": {
        "role": "You map the organisation's value chain, identifying key processes, activities, and interdependencies across each stage.",
        "context_type": "outputs",
    },
    "Requirements Capture": {
        "role": "You gather and document stakeholder requirements from discovery interviews, ensuring all voices are heard.",
        "context_type": "stakeholders",
    },
    "Requirements Analyst": {
        "role": "You analyse captured requirements for consistency, gaps, conflicts, and priority.",
        "context_type": "outputs",
    },
    "Value Lever Analyst": {
        "role": "You identify the highest-value levers for organisational improvement based on discovery findings.",
        "context_type": "outputs",
    },
    "Interview Script Designer": {
        "role": "You design tailored interview scripts for each stakeholder and value chain node.",
        "context_type": "stakeholders",
    },
    "Interview Coordinator": {
        "role": "You coordinate the scheduling and tracking of stakeholder interviews across the project.",
        "context_type": "interview_sessions",
    },
    "Stakeholder Interviewer": {
        "role": "You conduct voice interviews with stakeholders and ensure their responses are captured accurately.",
        "context_type": "interview_sessions",
    },
    "Synthesis Analyst": {
        "role": "You synthesise interview transcripts into structured findings and themes.",
        "context_type": "interview_sessions",
    },
    "Value Proposition Generator": {
        "role": "You generate compelling value propositions from discovery findings.",
        "context_type": "outputs",
    },
    "Portfolio Manager": {
        "role": "You score and rank initiatives across the six capitals framework and manage the project portfolio.",
        "context_type": "outputs",
    },
    "Enterprise Architect": {
        "role": "You design the enterprise architecture required to deliver the roadmap initiatives.",
        "context_type": "outputs",
    },
    "Initiative Identifier": {
        "role": "You identify and define the key initiatives from the architecture blueprint.",
        "context_type": "outputs",
    },
    "Roadmap Generator": {
        "role": "You sequence initiatives across value streams and time horizons into a delivery roadmap.",
        "context_type": "outputs",
    },
    "Business Plan Generator": {
        "role": "You produce the financial model and business plan narrative for the initiative portfolio.",
        "context_type": "outputs",
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
    lines = ["RECENT CREW OUTPUTS", "-" * 40]
    for r in rows:
        lines.append(f"Crew: {r[0]} — Status: {r[1]}")
        if r[2]:
            snippet = r[2][:800] + ("…" if len(r[2]) > 800 else "")
            lines.append(f"Output: {snippet}")
    return "\n".join(lines)


async def _fetch_context(conn, project_id: int, context_type: str) -> str:
    if context_type == "stakeholders":
        return await _stakeholder_context(conn, project_id)
    if context_type == "interview_sessions":
        return await _interview_sessions_context(conn, project_id)
    return await _outputs_context(conn, project_id)


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_agent_chat(
    slug: str,
    agent_name: str,
    message: str,
    history: list[dict],
) -> str | None:
    """
    Returns the agent's reply string, or None if the project DB doesn't exist.
    Raises KeyError if agent_name is unknown (caller converts to 404).
    """
    persona = AGENT_PERSONAS[agent_name]  # KeyError → router returns 404

    if not get_db_path(slug).exists():
        return None

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        context_block = await _fetch_context(conn, project["id"], persona["context_type"])

    system_prompt = (
        f"You are {agent_name}, an AI agent within the FutureMomentum platform.\n\n"
        f"Your role: {persona['role']}\n\n"
        f"Project: {slug}\n"
        f"Today: {date.today().isoformat()}\n\n"
        f"{context_block}\n\n"
        "Answer the user's question helpfully and concisely. "
        "Use bullet points for lists. "
        "If you don't have the data to answer, say so — don't invent details."
    )

    # Convert history: frontend uses 'agent', Anthropic API requires 'assistant'
    messages = [
        {
            "role": "assistant" if m["role"] == "agent" else "user",
            "content": m["content"],
        }
        for m in history
    ]
    messages.append({"role": "user", "content": message})

    client = AsyncAnthropic()
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()
