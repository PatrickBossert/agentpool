# api/services/interview_answer_service.py
"""A completed session becomes tagged, addressable answers.

Written by the interview service rather than by an agent: what a person said in a session is
a fact of the session, not an opinion, and an agent that could rewrite it could rewrite the
evidence its own themes cite.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from api.config import get_settings
from agents.tools._db import current_output_path
from api.database import (
    fetch_interview_answers,
    fetch_interview_session_by_id,
    insert_interview_answer,
)
from api.services.chroma_client import get_chroma_client
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

    # The tag this table has always carried under `level` is "what kind of interview was
    # this" - which, for a role-node script, is the role (a customer's answer reads
    # differently from a frontline technician's), not the structural tier the split now
    # keeps separately in `perspective`. Preferring `perspective` when it is set reproduces
    # that pre-split meaning for both shapes: a script written after the split names its
    # role there; a script written before it, or normalised from one, still names it in
    # `level` directly. Either way this table - and the citation frame built from it in
    # answer_document - keeps showing "F"/"A"/"C"/"S" for a role interview and the tier for
    # an ordinary one, exactly as it always did.
    evidence_level = script.get("perspective") or script.get("level") or ""

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
            level=evidence_level,
            relationship=script.get("relationship", ""),
            party_id=session.get("party_id"),
            discipline=tags.get("discipline") or "",
            question_intent=tags.get("question_intent") or "",
            elicitation=tags.get("elicitation") or "",
            rating=None,
        ))

    if written_ids:
        # Indexed after the rows are committed, and from the rows rather than the pairs, so
        # every document carries the id it will be cited by.
        written = set(written_ids)
        stored = await fetch_interview_answers(conn, session_id=session_id)
        await _index_in_background(slug, [r for r in stored if r["id"] in written])

    return len(written_ids)


async def script_for_session(conn, slug: str, session: dict) -> dict | None:
    """The script this session was conducted from.

    By the session's own script_id, because a session is for exactly one script and that
    column is the authority on which one. Sessions created before the column existed fall
    back to a node_label scan, which is what they were keyed on - label matching cannot
    distinguish two scripts that normalise to the same label, which is exactly why the
    column exists. A session whose script cannot be resolved returns None rather than
    guessing - tagging answers from the wrong script is worse than leaving them untagged.

    That last sentence used to be a claim rather than a description. The code fell through
    from a failed script_id lookup straight into the label scan, so a session naming a
    script the current artefact no longer holds was silently cited to a same-labelled
    neighbour - and the scan itself returned its first match, guessing whenever a label was
    shared. The two branches are now exclusive, and the scan refuses an ambiguous label:

      script_id set   -> that script, or None. The scan is not consulted; the session
                         already answered the question and got it wrong, or the instrument
                         is gone. Either way a neighbour is not it.
      script_id NULL  -> the label scan, and only if exactly one script carries the label.

    Normalised on the way out, same as the two GET /interview-scripts* endpoints - this reads
    the raw current artefact directly rather than through either of them, so without this a
    script written before the level/perspective split (level: 'F', no perspective) would be
    the one shape in the system still handed out as-is.
    """
    from api.services.interview_script_model import normalise_script_fields

    path = current_output_path(slug, "interview_scripts")
    if path is None:
        return None
    try:
        scripts = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(scripts, dict):
        return None

    # The session names its own script, and that is the end of the question - resolved or
    # not. Falling through to the label scan here is what turned "cannot resolve" into
    # "resolved to something else".
    script_id = session.get("script_id")
    if script_id:
        script = scripts.get(script_id)
        return normalise_script_fields(script) if isinstance(script, dict) else None

    # Only for a session created before the column existed. One match is an answer; two are
    # not, and neither is zero.
    matches = [s for s in scripts.values()
               if isinstance(s, dict) and s.get("node_label") == session["node_label"]]
    return normalise_script_fields(matches[0]) if len(matches) == 1 else None


_META_FIELDS = ("script_id", "section_id", "question_id", "node_id", "chain", "level",
                "relationship", "discipline", "question_intent", "elicitation",
                "stakeholder_id", "follow_up")


def answer_document(row: dict) -> str:
    """The text embedded for one answer, with a preamble so a hit carries its own frame.

    A semantic hit arrives as a sentence with no context otherwise, and a reader cannot tell
    whose answer it was or what it was about.
    """
    node = row.get("node_label") or row.get("node_id")
    frame = (f"[{node} ({row.get('node_id')}) | {row.get('level')} | "
             f"{row.get('relationship')} | discipline: {row.get('discipline')}]")
    return f"{frame}\nQ: {row.get('question_text', '')}\nA: {row.get('answer_text', '')}"


def answer_metadata(row: dict) -> dict:
    """Filterable tags for one answer, so retrieval filters before it ranks.

    Chroma accepts only scalars and rejects None. Every entity-anchored answer has a null
    chain, so passing it through would fail the upsert for the whole A, C, and S programme.
    """
    meta = {field: row.get(field) for field in _META_FIELDS}
    meta["answer_id"] = row.get("id")
    return {k: ("" if v is None else v) for k, v in meta.items()}


def index_answers(slug: str, rows: list[dict]) -> int:
    """Upsert one Chroma document per answer. Returns how many were indexed.

    Never raises. The SQLite rows are the system of record and can be re-indexed at any
    time, so a Chroma outage must cost the session nothing - failing here would lose an
    interview a person has already given.
    """
    if not rows:
        return 0
    try:
        collection = get_chroma_client(slug).get_or_create_collection(name=f"{slug}_interviews")
        collection.upsert(
            documents=[answer_document(r) for r in rows],
            ids=[str(r["id"]) for r in rows],
            metadatas=[answer_metadata(r) for r in rows],
        )
        return len(rows)
    except Exception:
        _log.exception("index_answers[%s]: %d answers not indexed", slug, len(rows))
        return 0


async def _index_in_background(slug: str, rows: list[dict]) -> int:
    """Index off the event loop.

    index_answers is synchronous and makes a network call. Called directly from async code
    it blocks every other request in the process, not just this session - and completions
    cluster at the end of a break, exactly when other people are mid-question. Measured at
    3.66s per completion with Chroma unreachable.
    """
    return await asyncio.to_thread(index_answers, slug, rows)
