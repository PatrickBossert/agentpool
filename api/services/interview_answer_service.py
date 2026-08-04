# api/services/interview_answer_service.py
"""A completed session becomes tagged, addressable answers.

Written by the interview service rather than by an agent: what a person said in a session is
a fact of the session, not an opinion, and an agent that could rewrite it could rewrite the
evidence its own themes cite.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from api.config import get_settings
from agents.tools._db import latest_output_path
from api.database import fetch_interview_session_by_id, insert_interview_answer
from api.services.interview_script_model import resolve_tags

_log = logging.getLogger(__name__)


def _parent_question_id(question_id: str) -> str:
    """A probe's parent. `SC-014.S3.Q2.F1` is more evidence about `SC-014.S3.Q2`."""
    parts = question_id.split(".")
    tail = parts[-1]
    if len(parts) > 1 and tail[:1] in ("F", "B") and tail[1:].isdigit():
        return ".".join(parts[:-1])
    return question_id


def _locate(script: dict, question_id: str) -> tuple[dict, dict]:
    """The section and question a captured pair belongs to.

    Returns empty dicts rather than raising when neither resolves: the synthesis block sits
    after every section and belongs to none of them, and dropping those answers would lose
    the wrap-up, which is where an interviewee names the single most important thing.
    """
    target = _parent_question_id(question_id)
    script_id = script.get("script_id", "")

    for section in script.get("sections", []):
        section_id = section.get("section_id")
        if not section_id or not target.startswith(f"{script_id}.{section_id}"):
            continue
        for question_no, question in enumerate(section.get("questions", []), 1):
            if target.endswith(f".Q{question_no}"):
                return section, question
        return section, {}
    return {}, {}


async def record_answers(
    conn, slug: str, session_id: int, qa_pairs: list[dict], script: dict
) -> int:
    """Write one row per captured pair. Returns the number written."""
    session = await fetch_interview_session_by_id(conn, session_id)
    if session is None:
        _log.warning("record_answers[%s]: session %s not found", slug, session_id)
        return 0

    node_id = script.get("node_id", "")
    # The chain is the root of the node id, and there is none for the entity: an interview
    # about the organisation is not about one chain, and a query for everything about Fleet
    # that swept these in would attribute a board member's remark to a chain they never
    # mentioned.
    chain = node_id.split(".")[0] if node_id and node_id != "0" else None

    written_ids: list[int] = []
    for pair in qa_pairs:
        section, question = _locate(script, pair["question_id"])
        tags = resolve_tags(section, question)
        answer_text = pair.get("answer", "") or ""
        written_ids.append(await insert_interview_answer(
            conn,
            session_id=session_id,
            stakeholder_id=session["stakeholder_id"],
            script_id=script.get("script_id", ""),
            section_id=section.get("section_id", ""),
            question_id=pair["question_id"],
            question_text=pair.get("question", ""),
            answer_text=answer_text,
            # A blank answer records that the question was asked. An absent row would mean
            # "not asked", and coverage cannot tell an instrument that missed a topic from a
            # stakeholder who declined it unless both are recorded.
            answered=1 if answer_text.strip() else 0,
            follow_up=int(pair.get("follow_up", 0)),
            node_id=node_id,
            node_label=script.get("node_label", ""),
            chain=chain,
            level=script.get("level", ""),
            relationship=script.get("relationship", ""),
            party_id=session.get("party_id"),
            discipline=tags.get("discipline") or "",
            question_intent=tags.get("question_intent") or "",
            elicitation=tags.get("elicitation") or "",
            rating=None,
        ))

    return len(written_ids)


async def script_for_session(conn, slug: str, session: dict) -> dict | None:
    """The script this session was conducted from.

    By script_id through the node assignment, because that is the anchor auto_assign makes
    authoritative. Sessions created before script ids existed fall back to node_label, which
    is what they were keyed on. A session whose script cannot be resolved returns None rather
    than guessing - tagging answers from the wrong script is worse than leaving them untagged.
    """
    path = latest_output_path(
        Path(get_settings().projects_dir) / slug / "outputs" / "interview_scripts.json"
    )
    if path is None:
        return None
    try:
        scripts = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(scripts, dict):
        return None

    async with conn.execute(
        "SELECT script_id FROM node_template_assignments "
        "WHERE project_id = ? AND node_label = ?",
        (session["project_id"], session["node_label"]),
    ) as cur:
        row = await cur.fetchone()

    script_id = row["script_id"] if row else None
    if script_id and script_id in scripts:
        return scripts[script_id]
    for script in scripts.values():
        if isinstance(script, dict) and script.get("node_label") == session["node_label"]:
            return script
    return None
