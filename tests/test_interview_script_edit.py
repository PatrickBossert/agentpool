# tests/test_interview_script_edit.py
"""The human edit path: PATCH /projects/{slug}/interview-scripts/{script_id}.

The old PATCH wrote outputs/interview_scripts.json - a bare, unversioned file that
insert_agent_output_sync renames away on every real write, so it never existed on any
project Maya had run. It was also keyed by node_label while the artefact SQLiteStateTool
produces is keyed by script_id. The edit went nowhere, produced no agent_outputs row and no
ledger entry, and nothing said so.

`client` is the async httpx client from tests/conftest.py running against the real app
under a sysadmin token - every call here is awaited, per CLAUDE.md's rerun trap, and every
assertion is scoped to this test's own project (SLUG), never to a global count.

seeded_scripts writes its one script through SQLiteStateTool - the same door Maya writes
by - so the artefact this test edits is versioned, validated, and already has a real ledger
row exactly as a live run would leave it, rather than a hand-built table row.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import fetch_project, get_connection

SLUG = "interview-script-edit-test"


@pytest_asyncio.fixture(autouse=True)
async def _granted_approver():
    """Every test in this file is about the edit path's own behaviour - versioning,
    staleness, ledger bookkeeping - not about authority, so caller_roles is granted
    approver on both doors throughout. The client fixture's sysadmin token names no real
    user, and caller_roles now correctly answers empty for one, per the walk every gate
    reads onto as of this task. The two tests further down that are actually about
    authority override this locally with a nested patch.
    """
    with patch("api.routers.projects.caller_roles",
               new=AsyncMock(return_value={"approver"})), \
         patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value={"approver"})):
        yield


def _valid_scripts() -> dict:
    """Mirrors tests/test_sqlite_state_validation.py's _valid_scripts - the minimal script
    body that clears validate_scripts, validate_scripts_against_registry (empty registry
    accepts anything), and validate_elicitation_order."""
    return {"SC-001": {
        "script_id": "SC-001", "node_id": "1.2", "level": "L2",
        "relationship": "internal", "node_label": "Planned Maintenance L2 Interview",
        "welcome_message": "Welcome", "closing_message": "Thanks for your time.",
        "sections": [{"section_id": "S1", "title": "Opening", "discipline": "governance",
                      "question_intent": "evidence", "elicitation": "unprompted",
                      "questions": [{"id": "Q1", "text": "..."}]}],
    }}


@pytest_asyncio.fixture
async def seeded_scripts():
    """One project, one script (SC-001) at version 1, registered in
    interview_script_ledger by interaction_designer - the state a real Maya run leaves.

    Plain sqlite3 for the write itself: SQLiteStateTool._run is synchronous. The project row
    is inserted first, through get_connection, both because that is what runs the schema
    migrations (interview_script_ledger among them) and because insert_agent_output_sync
    looks the project up by slug before it will version anything.
    """
    from agents.tools.sqlite_state import SQLiteStateTool

    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    outputs_dir = Path(settings.projects_dir) / SLUG

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()

    tool = SQLiteStateTool(slug=SLUG, agent_name="interaction_designer")
    result = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps(_valid_scripts()),
    )
    assert result.startswith("Written to"), result

    yield SLUG

    db_path.unlink(missing_ok=True)
    shutil.rmtree(outputs_dir, ignore_errors=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_human_edit_produces_a_new_version_and_a_ledger_row_naming_the_person(
        client, seeded_scripts):
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert "SC-001" in before

    r = await client.patch(
        f"/projects/{slug}/interview-scripts/SC-001",
        json={"script": {**before["SC-001"], "node_label": "Edited Label"}},
    )
    assert r.status_code == 200, r.text

    after = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert after["SC-001"]["node_label"] == "Edited Label"

    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    # Not merely "!= interaction_designer" - that also passes on the router's own
    # "human" fallback. "admin" is the sub claim tests/conftest.py's client fixture
    # signs into its sysadmin token, so this is the actual person the edit must name.
    assert row["last_author"] == "admin", "a human edit must name the person"
    assert row["last_version"] > 1, "the edit must have produced a new version"


@pytest.mark.asyncio
async def test_editing_a_reviewed_script_resets_its_review_status(client, seeded_scripts):
    """The tick described content that no longer exists."""
    slug = seeded_scripts
    review = await client.post(f"/projects/{slug}/script-ledger/SC-001/review",
                                json={"decision": "reviewed"})
    assert review.status_code == 200, review.text

    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                            json={"script": {**before["SC-001"], "node_label": "Changed"}})
    assert r.status_code == 200, r.text

    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    assert row["review_status"] == "pending"


@pytest.mark.asyncio
async def test_a_node_id_in_the_body_does_not_move_the_anchor_with_no_ledger_row(
        client, seeded_scripts):
    """node_id comes from the stored script, never the request body - and the router guard
    is the *only* thing that enforces that when there is no ledger row to check it against.

    seeded_scripts registers SC-001 through SQLiteStateTool, same as a real Maya run. This
    test deletes that ledger row before editing, reproducing the state
    _record_registration_failure exists to describe and the state every script written
    before script_ledger_backfill.py ran was in: the artefact holds the script, but
    interview_script_ledger holds nothing for it.

    That distinction is load-bearing, not incidental: validate_scripts_against_script_registry
    only refuses a move for an id it already holds a node_id for - an id with no row is, to
    that validator, indistinguishable from a fresh one, so it does not refuse this write at
    all. Without the router's own guard, the request here would return 200, the artefact
    would carry node_id 9.9, and register_scripts_sync would then INSERT a fresh ledger row
    anchored at 9.9 - permanently, because registration is append-only and a later correct
    write is refused forever once an id is held. A test that keeps the ledger row (as the
    first draft of this test did) never exercises this: the downstream validator alone
    would have caught the move and the router guard's absence would have gone unnoticed.
    """
    slug = seeded_scripts
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        await conn.execute(
            "DELETE FROM interview_script_ledger WHERE script_id=? AND project_id=?",
            ("SC-001", project["id"]),
        )
        await conn.commit()

    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert before["SC-001"]["node_id"] == "1.2"

    r = await client.patch(
        f"/projects/{slug}/interview-scripts/SC-001",
        json={"script": {**before["SC-001"], "node_id": "9.9"}},
    )
    assert r.status_code == 200, r.text

    after = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert after["SC-001"]["node_id"] == "1.2"

    # Registration is a side effect of the write (agents/tools/sqlite_state.py), so the
    # missing row gets re-created here - at the anchor the guard preserved, not the one the
    # body tried to move it to.
    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    assert row["node_id"] == "1.2"


@pytest.mark.asyncio
async def test_editing_an_unknown_script_id_is_404(client, seeded_scripts):
    slug = seeded_scripts
    r = await client.patch(f"/projects/{slug}/interview-scripts/SC-999",
                            json={"script": {"welcome_message": "hi", "closing_message": "bye",
                                              "sections": []}})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_single_script_by_id(client, seeded_scripts):
    slug = seeded_scripts
    r = await client.get(f"/projects/{slug}/interview-scripts/SC-001")
    assert r.status_code == 200, r.text
    assert r.json()["script_id"] == "SC-001"


@pytest.mark.asyncio
async def test_a_retitle_updates_the_ledgers_own_label(client, seeded_scripts):
    """script_review_service._fetch_change_requests names a sent-back script to Maya by
    l.node_label straight off the ledger row - not by re-reading the artefact. Leaving that
    column holding the pre-edit text would keep naming the edit's own retitle by the words
    it just replaced."""
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    r = await client.patch(
        f"/projects/{slug}/interview-scripts/SC-001",
        json={"script": {**before["SC-001"], "node_label": "Retitled by a human"}},
    )
    assert r.status_code == 200, r.text

    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    assert row["node_label"] == "Retitled by a human"


@pytest.mark.asyncio
async def test_editing_a_sent_back_script_clears_the_outstanding_return_to(
        client, seeded_scripts):
    """review_return_to='agent' marks a script sent back to Maya for revision. A human edit
    is not that revision - it must not leave a stale return_to still pointing an
    already-superseded send-back at whichever agent run next touches this script."""
    slug = seeded_scripts
    sent_back = await client.post(
        f"/projects/{slug}/script-ledger/SC-001/review",
        json={"decision": "changes_requested", "notes": "needs work", "return_to": "agent"},
    )
    assert sent_back.status_code == 200, sent_back.text
    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    assert next(x for x in ledger if x["script_id"] == "SC-001")["review_return_to"] == "agent"

    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                            json={"script": {**before["SC-001"], "node_label": "Fixed"}})
    assert r.status_code == 200, r.text

    ledger = (await client.get(f"/projects/{slug}/script-ledger")).json()
    row = next(x for x in ledger if x["script_id"] == "SC-001")
    assert row["review_return_to"] is None


@pytest.mark.asyncio
async def test_an_edit_from_a_superseded_version_is_refused(client, seeded_scripts):
    """Several reviewers can edit, so last-write-wins silently discards somebody's work and
    they have no way to learn it happened. This codebase has already lost a human edit to a
    silent write once."""
    slug = seeded_scripts
    ledger = {r["script_id"]: r for r in (await client.get(f"/projects/{slug}/script-ledger")).json()}
    opened_at = ledger["SC-001"]["last_version"]
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()

    first = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                                json={"script": {**before["SC-001"], "node_label": "Ana's edit"},
                                      "base_version": opened_at})
    assert first.status_code == 200, first.text

    # Bo opened the same version Ana did, and saves after her.
    second = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                                 json={"script": {**before["SC-001"], "node_label": "Bo's edit"},
                                       "base_version": opened_at})
    assert second.status_code == 409, second.text

    after = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert after["SC-001"]["node_label"] == "Ana's edit", "the first edit must survive"


@pytest.mark.asyncio
async def test_an_edit_with_no_base_version_still_works(client, seeded_scripts):
    """base_version is optional so an older client, or a caller with nothing to be stale
    against, is not broken by the check."""
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                            json={"script": {**before["SC-001"], "node_label": "No base"}})
    assert r.status_code == 200, r.text


# ── The edit and the review answer to one authority ────────────────────────────
#
# ScriptReviewPanel's "Save changes" calls this PATCH and then POSTs a review, and checks
# neither. While the PATCH used require_org_admin_or_above (a login role) and the review used
# the stakeholder flag, the two could disagree in either direction and both disagreements
# were silent damage:
#
#   is_reviewer, not org_admin -> /my-permissions says can_review, the panel offers Save
#                                 changes, the PATCH 403s.
#   org_admin, not a flagged stakeholder -> the PATCH succeeds, the review 403s, the artefact
#                                 is versioned with no review recorded, onClose never fires,
#                                 and the panel's row is stale - so retrying 409s, naming
#                                 someone else as the editor. It was them.
#
# Both endpoints now read caller_roles(slug, payload) - one function - so they cannot
# disagree. These patch it where each router *looks it up*, per CLAUDE.md's patch-target
# rule, overriding this module's autouse grant to prove the refusal path still holds.

@pytest.mark.asyncio
async def test_a_caller_the_shared_authority_refuses_cannot_edit(client, seeded_scripts):
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    with patch("api.routers.projects.caller_roles",
               new=AsyncMock(return_value=set())):
        r = await client.patch(
            f"/projects/{slug}/interview-scripts/SC-001",
            json={"script": {**before["SC-001"], "node_label": "Not mine to change"}})
    assert r.status_code == 403, r.text

    # And the refusal actually held - a 403 that still wrote would be worse than none.
    after = (await client.get(f"/projects/{slug}/interview-scripts")).json()
    assert after["SC-001"]["node_label"] != "Not mine to change"


@pytest.mark.asyncio
async def test_the_edit_asks_the_same_question_as_the_review_it_is_paired_with(
        client, seeded_scripts):
    """Same function, same roles - so the panel's two calls cannot disagree.

    Asserted on the roles demanded rather than on two 200s: both endpoints returning 200
    for a sysadmin is true whatever authority either consults, which is precisely how the
    mismatch survived the branch. A caller holding only "reviewer" - not "approver" -
    is used because that is exactly the case the two doors could previously disagree on.
    """
    slug = seeded_scripts
    before = (await client.get(f"/projects/{slug}/interview-scripts")).json()

    with patch("api.routers.projects.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.patch(f"/projects/{slug}/interview-scripts/SC-001",
                                json={"script": {**before["SC-001"], "node_label": "Edited"}})
    assert r.status_code == 200, r.text

    # 'edited' - not 'reviewed' - matches the sequence ScriptReviewPanel.tsx's "Save
    # changes" actually sends: the PATCH above, then recordReview('edited'). Both take
    # the same {"reviewer", "approver"} branch, so this changes no authority coverage,
    # but it is the real pairing the docstring above is about.
    with patch("api.routers.script_reviews.caller_roles",
               new=AsyncMock(return_value={"reviewer"})):
        r = await client.post(f"/projects/{slug}/script-ledger/SC-001/review",
                               json={"decision": "edited"})
    assert r.status_code == 200, r.text
