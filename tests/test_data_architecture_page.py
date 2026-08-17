# tests/test_data_architecture_page.py
"""The privacy page's answer is generated, and its door is closed.

Two properties, and the reason they are asserted here rather than beside the declarations:

- **Generated.** `ui/src/pages/DataArchitecture.tsx` used to hold every fact it displayed. The
  page now renders whatever `GET /projects/{slug}/data-architecture` returns, so the question
  "would this test fail if the code were wrong?" is answered at the endpoint - the layer where
  a declaration becomes a claim on a page. A test that asserted `TOOL_EGRESS` has an entry for
  `WebFetchTool` would pass on the old page too, which named that tool and gave it no
  destination anywhere. Every assertion below therefore reads the HTTP response, and every
  expectation is derived from the declaration rather than typed out beside it.
- **Closed.** The route sat outside every guard. Guarding the page alone would move the
  omission rather than end it, so the endpoint refuses the same callers, and both halves are
  asserted - the front end's half in `ui/src/__tests__/DataArchitectureRoute.test.tsx`.

`project_llm_mode` caches per slug for the life of the process, so every test that changes a
project's mode calls `forget_project_mode` - without it the second read in a test returns the
first's answer and the mode assertions pass for the wrong reason.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agents.charter import CREW_CHARTER, DISPATCH_PATHS, Trigger
from agents.egress import TOOL_EGRESS, Egress, Reach, is_gated_by_mode
from agents.graph import build_graph
from agents.reads import AGENT_READS, CREW_DISPATCH_READS, Medium
from api.config import get_settings
from api.services.chroma_client import forget_project_mode
from api.services.data_architecture_service import (
    data_architecture,
    dispatch_wrapper_reaches_build_and_run_crew,
)

SLUG = "data-arch-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}
URL = f"/projects/{SLUG}/data-architecture"


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    proj_dir = Path(settings.projects_dir) / SLUG
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    forget_project_mode(SLUG)
    yield
    forget_project_mode(SLUG)
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


async def _payload(client, mode: str = "standard") -> dict:
    await client.post("/projects", json={**PROJECT, "llm_mode": mode})
    forget_project_mode(SLUG)
    resp = await client.get(URL)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── The door ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_is_refused(client):
    """The condition that was true of the page for its whole life, asserted of the endpoint."""
    from api.main import app

    await client.post("/projects", json=PROJECT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        resp = await anon.get(URL)
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_a_reviewer_on_this_very_project_is_refused(client):
    """Administrator-only, not merely signed-in - and the reviewer is a member of the project.

    The membership is the whole point. A reviewer with no membership is refused by
    `check_project_access` whatever the dependency says, so a test using one passes
    identically with `require_any_auth` in place of `require_org_admin_or_above` - which is
    exactly what the first draft of this test did, and the power-check caught it. Granting the
    membership removes the other reason to refuse, so the 403 can only come from the role.
    """
    from api.auth import create_access_token, hash_password
    from api.database import get_system_connection, insert_project_membership, insert_user
    from api.main import app

    await client.post("/projects", json=PROJECT)
    async with get_system_connection() as conn:
        await insert_user(
            conn,
            username="member-reviewer",
            role="reviewer",
            hashed_pw=hash_password("irrelevant"),
        )
        user = await conn.execute_fetchall(
            "SELECT id FROM users WHERE username='member-reviewer'"
        )
        await insert_project_membership(conn, user_id=user[0][0], project_slug=SLUG)
        await conn.commit()

    token = create_access_token("member-reviewer", "reviewer", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as reviewer:
        # The control: this membership genuinely opens the neighbouring door, so the refusal
        # below is the role gate and not a missing grant.
        assert (await reviewer.get(f"/projects/{SLUG}/settings")).status_code == 200
        resp = await reviewer.get(URL)

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_an_administrator_is_served(client):
    """The other half: a guard that refused everyone would pass the two tests above."""
    payload = await _payload(client)
    assert payload["slug"] == SLUG


@pytest.mark.asyncio
async def test_an_unknown_project_is_a_404_rather_than_a_standard_mode_answer(client):
    """`project_llm_mode` answers "standard" for a database it cannot find.

    Serving that would describe a hosted engagement to somebody asking about a project nobody
    has created - the same class of mistake as `project_llm_mode("")`, which CLAUDE.md records
    as how a sensitive project's answers reached Anthropic.
    """
    resp = await client.get("/projects/no-such-engagement/data-architecture")
    assert resp.status_code == 404


# ── The table is generated, and complete ──────────────────────────────────────


@pytest.mark.asyncio
async def test_every_tool_an_agent_holds_is_in_the_table_and_nothing_else_is(client):
    payload = await _payload(client)
    expected = {tool for node in build_graph().agents.values() for tool in node.tools}
    assert {row["tool"] for row in payload["tools"]} == expected


@pytest.mark.asyncio
async def test_every_row_carries_the_declared_reach_sentence_and_resolved_destination(client):
    """The declaration, end to end, rather than the fact that a declaration exists.

    Each of the three fields is compared with the declaration it comes from, so an endpoint
    that dropped `sends` - the sentence saying what of the client's material travels - fails
    here rather than producing a table that merely looks complete.
    """
    from agents.egress import resolve_egress

    payload = await _payload(client)
    for row in payload["tools"]:
        declared = TOOL_EGRESS[row["tool"]]
        destination = resolve_egress(row["tool"], "standard")
        assert row["reaches"] == declared.reaches.value
        assert row["sends"] == declared.sends
        assert row["destination"] == destination.label
        assert row["leaves_deployment"] is destination.leaves_deployment
        assert row["gated_by_mode"] is is_gated_by_mode(row["tool"])


@pytest.mark.asyncio
async def test_web_fetch_is_named_with_a_destination(client):
    """The specific hole the hand-typed page had, closed at the level it was open.

    The old page listed "Web fetch" among two agents' tools and gave it no destination in any
    row or table. Asserting that `TOOL_EGRESS` has an entry for it would have passed then too.
    """
    payload = await _payload(client)
    row = next(r for r in payload["tools"] if r["tool"] == "WebFetchTool")
    assert row["destination"] == "any address the agent names"
    assert row["leaves_deployment"] is True
    assert row["held_by"], "a destination nobody reaches is not the finding"


@pytest.mark.asyncio
async def test_inference_is_in_the_table_although_no_tool_carries_it(client):
    """The largest thing that leaves the building, and the one a tools-only table omits."""
    payload = await _payload(client)
    assert payload["inference"]["destination"] == "Anthropic's API"
    assert payload["inference"]["leaves_deployment"] is True
    assert payload["inference"]["gated_by_mode"] is True


@pytest.mark.asyncio
async def test_a_sensitive_project_moves_the_vector_store_and_inference_and_nothing_else(client):
    """The uncomfortable half of the egress finding, asserted as a difference.

    Comparing the two payloads rather than asserting sensitive's labels one by one: the claim
    worth holding is that exactly two things move, and a per-label assertion would still pass
    if a third quietly started moving as well.
    """
    standard = await _payload(client, "standard")

    # Through the real door, which is also what invalidates the mode cache. Writing the row
    # directly would leave `project_llm_mode` answering "standard" from its per-slug cache and
    # the comparison below would find nothing moved - passing, for the wrong reason.
    patched = await client.patch(
        f"/projects/{SLUG}/settings",
        json={"llm_mode": "sensitive", "sector": "rail", "review_gates": True},
    )
    assert patched.status_code == 200, patched.text
    resp = await client.get(URL)
    sensitive = resp.json()

    assert sensitive["llm_mode"] == "sensitive"
    assert sensitive["inference"]["destination"] == "the local model on this host"
    assert sensitive["inference"]["leaves_deployment"] is False

    by_tool = {row["tool"]: row for row in standard["tools"]}
    moved = {
        row["tool"]
        for row in sensitive["tools"]
        if row["destination"] != by_tool[row["tool"]]["destination"]
    }
    assert moved == {"ChromaQueryTool", "DocumentIngestionTool"}

    still_out = {
        row["tool"] for row in sensitive["tools"] if row["leaves_deployment"]
    }
    assert {"TavilySearchTool", "WebFetchTool", "SlackNotifyTool", "HumanInputTool"} <= still_out

    # The per-agent summary is resolved separately from the table - it comes off the graph,
    # which is built for a mode of its own - so it needs its own assertion. Without this, the
    # graph could be assembled in the wrong mode and every row above would still be right,
    # while each agent's own list of where it reaches described a hosted engagement. The
    # power-check found exactly that.
    labels = {
        d["label"] for agent in sensitive["agents"] for d in agent["destinations"]
    }
    assert "the local model on this host" in labels
    assert "Anthropic's API" not in labels
    assert "Chroma Cloud" not in " | ".join(labels)


@pytest.mark.asyncio
async def test_a_declared_tool_no_agent_holds_is_reported_as_held_by_nobody(client):
    """`ChainlitHumanInputTool` must not read as a live review channel.

    Its only production caller sits in a Chainlit handler whose every branch fails, so no crew
    can reach it. It is still declared, and dropping it silently would be the under-reporting
    this page exists to end - so it appears, and it appears as unheld.
    """
    payload = await _payload(client)
    unheld = {row["tool"] for row in payload["declared_not_held"]}
    held = {row["tool"] for row in payload["tools"]}
    assert unheld == set(TOOL_EGRESS) - held
    assert "ChainlitHumanInputTool" in unheld


# ── Reads ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_declared_read_reaches_the_payload(client):
    payload = await _payload(client)
    served = {
        agent["agent_id"]: [(s["source"], s["via"]) for s in agent["sources"]]
        for agent in payload["agents"]
    }
    declared = {
        agent_id: [(read.source, read.via) for read in reads]
        for agent_id, reads in AGENT_READS.items()
    }
    assert served == declared


@pytest.mark.asyncio
async def test_the_shared_sector_store_is_never_reported_as_this_project_alone(client):
    """The single most misleading thing a per-project page could say.

    `sector_{sector}` carries no slug, so it is one collection shared by every engagement in
    the sector. A reader on a page headed with their own engagement would take an unmarked row
    as theirs alone. Both sides are asserted: the flag is set on exactly the collections whose
    template has no slug in it, and the shared store is lifted to a section of its own.
    """
    payload = await _payload(client)

    flagged = {
        (agent["agent_id"], s["source"])
        for agent in payload["agents"]
        for s in agent["sources"]
        if s["shared_beyond_this_project"]
    }
    expected = {
        (agent_id, read.source)
        for agent_id, reads in AGENT_READS.items()
        for read in reads
        if read.medium is Medium.VECTOR_COLLECTION and "{slug}" not in read.source
    }
    assert flagged == expected
    assert expected, "no shared collection found - this test would assert nothing"

    top_level = {row["source"] for row in payload["shared_sources"]}
    assert top_level == {source for _, source in expected}
    assert all(row["read_by"] for row in payload["shared_sources"])


@pytest.mark.asyncio
async def test_what_the_dispatch_path_hands_every_agent_is_rendered(client):
    payload = await _payload(client)
    served = [(r["source"], r["note"]) for r in payload["dispatch_reads"]]
    assert served == [(r.source, r.note) for r in CREW_DISPATCH_READS]


@pytest.mark.asyncio
async def test_only_the_paths_that_reach_build_and_run_crew_carry_that_material(client):
    """Derived from the dispatchers, not from a count typed into the caption.

    Three of the four paths funnel through `build_and_run_crew`; the Chainlit console calls
    `kickoff_async` itself and injects none of the skill notes, change requests or validation
    warnings. Saying "every crew run carries these" would be wrong for that path, and it is
    the path that carries none of them that a reader most needs told.
    """
    payload = await _payload(client)
    carrying = {p["trigger"] for p in payload["dispatch_paths"] if p["injects_dispatch_reads"]}
    assert carrying == {t.value for t in DISPATCH_PATHS} - {Trigger.CHAINLIT_CONSOLE.value}


def test_dispatch_crew_still_reaches_build_and_run_crew():
    """The one link in that derivation that is not a declaration.

    `dispatch_crew` is a wrapper around `build_and_run_crew`, and the service reads the pair
    as one. If the wrapper ever stops calling it, two of the four paths would still be shown
    as carrying material they no longer carry.
    """
    assert dispatch_wrapper_reaches_build_and_run_crew()


# ── Crews, and the scope of the account ───────────────────────────────────────


@pytest.mark.asyncio
async def test_every_crew_purpose_and_trigger_reaches_the_payload(client):
    payload = await _payload(client)
    served = {c["crew_id"]: (c["purpose"], tuple(c["triggers"])) for c in payload["crews"]}
    expected = {
        crew_id: (
            charter.purpose,
            tuple(DISPATCH_PATHS[t].label for t in charter.triggers),
        )
        for crew_id, charter in CREW_CHARTER.items()
    }
    assert served == expected


@pytest.mark.asyncio
async def test_the_account_names_every_agent_the_graph_puts_in_no_crew(client):
    """Nine crews are declared and eleven run, so the page must state its own scope.

    PAM's own two crews are built by `orchestration_service` and are in no registry the graph
    reads, which is why `pam` is in none of the nine. The page cannot simply present nine as
    everything that executes on an engagement, and the fact it states is derived here rather
    than written into the copy - an agent that falls out of every crew tomorrow is named
    without anybody remembering to edit a sentence.
    """
    payload = await _payload(client)
    graph = build_graph()
    in_a_crew = {a for crew in graph.crews.values() for a in crew.agent_ids}
    expected = set(graph.agents) - in_a_crew

    assert {a["agent_id"] for a in payload["scope"]["agents_in_no_crew"]} == expected
    assert expected, "if every agent is in a crew this assertion means nothing"
    assert payload["scope"]["crew_count"] == len(graph.crews)


# ── The declaration is what is rendered ───────────────────────────────────────


def test_a_changed_declaration_changes_the_answer(monkeypatch):
    """The property the whole task rests on, driven rather than assumed.

    Every test above compares the payload with the declaration as it stands, and all of them
    would still pass if the service had transcribed the declaration into a second copy. This
    one changes the declaration and reads the answer again.
    """
    before = data_architecture(SLUG)
    monkeypatch.setitem(
        TOOL_EGRESS,
        "WebFetchTool",
        Egress(reaches=Reach.NOTHING, sends="nothing at all, in this test"),
    )
    after = data_architecture(SLUG)

    was = next(r for r in before["tools"] if r["tool"] == "WebFetchTool")
    now = next(r for r in after["tools"] if r["tool"] == "WebFetchTool")
    assert was["leaves_deployment"] is True and now["leaves_deployment"] is False
    assert now["sends"] == "nothing at all, in this test"
