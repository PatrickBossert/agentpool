# api/routers/skill_notes.py
"""Agent skill notes - a lesson taken from a reviewer's rejection of one engagement's output.

**This file used to open by declaring itself always-hosted**, on the grounds that "these notes
are global across engagements and this endpoint carries no slug, so there is no llm_mode to
route by". Both halves were false. `raw_input` is the reviewer's verbatim sentence and is free
to name the client, its people and what went wrong - *"Maya named the Q3 outage at Iberdrola in
the welcome for SC-014"* is its real shape - and the one caller, `ReviewDialog.tsx`, held the
slug in its props and used it six lines earlier before discarding it. That is the same
exemption sp61 already retired once on `find_duplicate_skill`, and the same "held the slug and
discarded it" defect CLAUDE.md records on the test-interview press.

So the extraction goes through `llm_client.project_completion(slug, "fast", ...)` like every
other non-crew call on this codebase, and the note is stored with the engagement it came from.
Both matter and they are different halves: routing decides where the *reviewer's* sentence
goes, and the stored `source_project` is what lets `_fetch_skill_notes` decide, later and
repeatedly, where the *distilled note* may be injected.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import require_any_auth, require_sysadmin
from api.database import get_system_db, insert_skill_note, fetch_skill_notes
from api.services import llm_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-skill-notes", tags=["skill-notes"])

# The tier the distillation runs on, and the budget it runs under. `fast` for the same reason
# the duplicate comparison is: this is one short sentence turned into another, and `deep` would
# put it on the model the agent's own work runs on. The deadline exists because
# `project_completion` imposes none of its own and both clients behind it are sized for a
# caller that is waiting - and this one is a reviewer holding a dialog open.
_EXTRACT_TIER = "fast"
_EXTRACT_TIMEOUT_SECONDS = 20.0

_EXTRACT_SYSTEM = (
    "You extract concise, actionable skill improvement notes from rejection feedback. "
    "Write in second person using imperative language ('Must...', 'Should...', 'Avoid...'). "
    "Focus only on what the agent should do differently in future - not on why it was wrong. "
    # The clause `extract_skill` in skills_service.py has always had, and this one never did -
    # while being the only one of the two whose output is injected into every crew's prompts.
    # **Second line of defence, not the fix.** It asks a model to behave, and a model's output
    # is not a guarantee; what actually bounds the disclosure is `source_project` on the row
    # and `_note_may_travel` on the injection. This narrows what a correctly-behaving
    # extraction writes down in the first place.
    "The note must be generic - it is applied to this agent's work on every engagement, so "
    "state the rule and never the incident. Carry across no client, project, person, system, "
    "supplier or place names, and no figures, dates or reference numbers from the feedback. "
    "Output 1-3 sentences maximum. No preamble."
)


class SkillNoteCreate(BaseModel):
    agent_name: str    # snake_case agent key, e.g. 'value_chain_mapper'
    raw_input: str     # free-text feedback from the human reviewer
    # Required, with no default. The reviewer's sentence is about work done on one engagement,
    # so which model may read it is a property of that engagement - and an optional slug
    # falling back to hosted is exactly what CLAUDE.md's seam rule forbids. It is also the
    # attribution `_fetch_skill_notes` needs later: a note stored with no engagement can never
    # be shown to a hosted run again, so accepting one would quietly create a dead row.
    slug: str


@router.post("", status_code=201)
async def create_skill_note(
    req: SkillNoteCreate,
    payload: dict = Depends(require_any_auth),
    conn=Depends(get_system_db),
):
    """Distil a reviewer's rejection feedback into a note, on the engagement's own model.

    Refused rather than defaulted when either the feedback or the engagement is missing. A
    blank slug is a caller that lost one, not a note belonging to nobody: routing it would
    send a sensitive engagement's reviewer feedback to a hosted provider, and storing it would
    create a note no hosted run may ever be shown.

    The extraction failing is a 502 rather than a note stored raw. `raw_input` is the sentence
    that must not travel unbounded; writing it into `note` because the distillation failed
    would put the reviewer's verbatim words into every future prompt for that agent, which is
    the precise thing the extraction exists to prevent.
    """
    if not req.raw_input.strip():
        raise HTTPException(status_code=422, detail="raw_input is required")
    if not req.slug.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "slug is required: the feedback is about work done on one engagement, so "
                "which model may read it is a property of that engagement, and the note is "
                "stored with it so later runs can tell whose lesson it is."
            ),
        )

    slug = req.slug.strip()
    try:
        note = (await asyncio.wait_for(
            llm_client.project_completion(
                slug,
                _EXTRACT_TIER,
                messages=[{"role": "user", "content": req.raw_input}],
                max_tokens=256,
                system=_EXTRACT_SYSTEM,
            ),
            timeout=_EXTRACT_TIMEOUT_SECONDS,
        )).strip()
    except Exception:
        log.warning("skill notes: extraction failed for %s on %r", req.agent_name, slug,
                    exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=(
                "The feedback could not be distilled into a note, so nothing was stored. The "
                "review itself was recorded."
            ),
        )
    if not note:
        raise HTTPException(
            status_code=502,
            detail="The feedback could not be distilled into a note, so nothing was stored.",
        )

    note_id = await insert_skill_note(
        conn,
        agent_name=req.agent_name,
        note=note,
        raw_input=req.raw_input,
        source_project=slug,
    )
    return {"id": note_id, "agent_name": req.agent_name, "note": note}


@router.get("")
async def list_skill_notes(
    agent_name: str | None = None,
    _payload: dict = Depends(require_sysadmin),
    conn=Depends(get_system_db),
):
    """Every stored note, with the feedback it was distilled from (sysadmin only).

    **Two columns, and only one of them is global.** `note` is the imperative the extraction
    produced - it is injected into that agent's prompt on every engagement by
    `_fetch_skill_notes`, which is what makes it the agent's published instruction rather than
    one client's material. `raw_input` is the reviewer's verbatim sentence, written from
    `ReviewDialog`, and it is free to name the engagement, its people, and what went wrong on
    it: *"Maya named the Q3 outage at Iberdrola in the welcome for SC-014"* is the shape it
    actually takes. `fetch_skill_notes` is a `SELECT *`, so this returned both to any login.

    The same finding as `list_skills`' pending queue, one table over, and closed the same way:
    whoever may act on it may read it. Nothing consumes this endpoint - `skillNotesApi.list`
    in `ui/src/api/endpoints.ts` has no caller - so the whole door is narrowed rather than the
    response projected. **If a non-admin surface is ever wanted, the split is `note` yes,
    `raw_input` no**, and it is written down here so it does not have to be rediscovered.

    `POST` stays `require_any_auth`, deliberately: leaving feedback about an agent's output is
    a reviewer's job, and writing your own sentence is not reading somebody else's.
    """
    return await fetch_skill_notes(conn, agent_name=agent_name)
