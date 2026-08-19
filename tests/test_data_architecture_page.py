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

`project_llm_mode` caches per slug for the life of the process, and this file used to clear it
three times by hand - twice in the fixture below and once in `_payload` - because without that
the second read returns the first's answer and the mode assertions pass for the wrong reason.
All three are gone, and **all three were already covered by `create_project` invalidating the
mode cache on the way out**, which is worth knowing before adding a fourth. Every test here
that reads a mode reaches it through `_payload` (a POST) or through `PATCH /{slug}/settings`,
and both doors invalidate - so no clear of any kind is load-bearing in this file. Verified by
neutering `conftest.reset_process_caches` and running the whole suite: this file passes.

That fixture is named here only so the next reader knows suite-wide isolation exists and need
not re-add a local one. It is not what covers this file, and an earlier version of this
docstring said it was - a mechanism that happens to be true of the suite is not the mechanism
that makes a particular test pass, and only the second is worth writing down.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agents.charter import CREW_CHARTER, DISPATCH_PATHS
from agents.egress import TOOL_EGRESS, Egress, Reach, is_gated_by_mode
from agents.graph import build_graph
from agents.reads import AGENT_READS, CREW_DISPATCH_READS, Medium
from api.config import get_settings
from api.services.data_architecture_service import (
    data_architecture,
    dispatch_wrapper_reaches_build_and_run_crew,
    system_database_tables,
)
from api.services.knowledge_tiers import SHARED_TIERS, TIER_SCOPE

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
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)


async def _payload(client, mode: str = "standard") -> dict:
    await client.post("/projects", json={**PROJECT, "llm_mode": mode})
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

    # The uncomfortable half, and the reason the page names it: a sensitive project still
    # reaches out through the search and fetch tools, neither of which consults `llm_mode`.
    # `SlackNotifyTool` and `HumanInputTool` were named here too, both reaching the n8n webhook
    # in either mode. Retiring n8n removed the first tool and left the second reaching nothing,
    # so this set shrank by two - which is a narrowing of the exposure, not of the assertion.
    still_out = {
        row["tool"] for row in sensitive["tools"] if row["leaves_deployment"]
    }
    assert {"TavilySearchTool", "WebFetchTool"} <= still_out
    assert "HumanInputTool" not in still_out, (
        "the review gate reaches out again on a sensitive project - it posted to n8n before "
        "that integration was retired, and nothing has replaced the notification"
    )

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
async def test_no_declared_tool_is_held_by_nobody(client):
    """The caveat the page carried, asserted gone rather than observed gone.

    `ChainlitHumanInputTool` was its one member: declared, reachable only through a Chainlit
    handler whose every branch failed, and rendered under "Declared, and held by no agent on
    this deployment". Retiring Chainlit makes every declared tool a tool some agent holds, so
    the list is empty and the caveat does not render at all.

    Both assertions, because they fail differently. The first says the declaration and the
    holders now agree exactly; the second says the join that computes the difference still
    works, so an emptiness produced by a broken derivation cannot pass for this one.
    """
    payload = await _payload(client)
    unheld = {row["tool"] for row in payload["declared_not_held"]}
    held = {row["tool"] for row in payload["tools"]}

    assert unheld == set(TOOL_EGRESS) - held
    assert held == set(TOOL_EGRESS), (
        f"declared and held by nobody: {sorted(set(TOOL_EGRESS) - held)}; held and undeclared: "
        f"{sorted(held - set(TOOL_EGRESS))}"
    )
    assert not unheld


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
    assert {source for _, source in expected} <= top_level


@pytest.mark.asyncio
async def test_a_shared_table_earns_the_badge_as_readily_as_a_shared_collection(client):
    """The predicate is asked of every medium, not only of collections.

    `agent_skill_notes` and `skills` are in the system database - global across engagements -
    and both are folded into every agent's instructions on every crew run. While the flag was
    `medium is VECTOR_COLLECTION and ...` they could never earn it whatever they were called,
    so the panel a reader consults with exactly this question said nothing about the two stores
    that most needed saying. Both halves are asserted: every system table declared as a read is
    flagged, and no project table is.
    """
    payload = await _payload(client)
    system_tables = system_database_tables()
    assert {"agent_skill_notes", "skills"} <= system_tables

    flagged = {row["source"] for row in payload["shared_sources"]}
    assert {"agent_skill_notes", "skills"} <= flagged

    declared_tables = {
        read.source
        for reads in list(AGENT_READS.values()) + [CREW_DISPATCH_READS]
        for read in reads
        if read.medium is Medium.DATABASE_TABLE
    }
    assert flagged & declared_tables == declared_tables & system_tables
    # A project table must not be swept in: these are in the project's own database.
    assert not flagged & {"stakeholders", "interview_sessions", "validation_warnings"}


@pytest.mark.asyncio
async def test_the_panel_names_who_can_reach_a_collection_not_only_who_is_told_to(client):
    """The declared readers are half the truth, and a generated table inherits authority.

    `AGENT_READS` declares three agents on `sector_{sector}`. `ChromaQueryTool` takes the
    collection as an argument, so every one of its holders can query it by naming it. Six can.
    The panel must carry the wider set beside the declared one, and it is derived from the route
    rather than counted by hand.

    The gap used to be wider than that: the sector store was the tool's *fallback* for any
    unrecognised value, so an agent reached it without naming it. `collection_for` refuses
    anything outside the four tiers now, so reaching a tier takes naming it - the gap is real
    and no longer something an agent can fall into.
    """
    payload = await _payload(client)
    sector = next(r for r in payload["shared_sources"] if r["source"] == "sector_{sector}")

    holders = sorted(
        node.display_name
        for node in build_graph().agents.values()
        if sector["via"] in node.tools
    )
    assert sector["reachable_by"] == holders
    assert len(sector["reachable_by"]) > len(sector["read_by"])
    assert set(sector["read_by"]) < set(sector["reachable_by"])


@pytest.mark.asyncio
async def test_the_name_and_the_tier_agree_about_which_stores_are_shared(client):
    """Two derivations of one fact, held equal rather than one trusted.

    `shared_beyond_this_project` is read off the collection **name** - a template with no
    `{slug}` in it. `SHARED_TIERS` is read off the declared **tier**. They must agree for every
    collection on the page, and a disagreement is the interesting case either way round: a
    collection renamed into a slug-less template without its tier changing, or a tier moved onto
    a collection that is this project's alone.
    """
    payload = await _payload(client)
    reads = [
        source
        for agent in payload["agents"]
        for source in agent["sources"]
    ] + payload["dispatch_reads"]

    checked = 0
    for source in reads:
        if source["tier"] is None:
            continue
        assert source["shared_beyond_this_project"] == (source["tier"] in SHARED_TIERS), (
            f"{source['source']} is declared at the {source['tier']!r} tier and flagged "
            f"shared={source['shared_beyond_this_project']} - the name and the tier disagree"
        )
        checked += 1
    assert checked, "no tiered read reached the payload"


@pytest.mark.asyncio
async def test_every_shared_store_says_with_whom_and_not_only_that_it_is_shared(client):
    """The reason, which "not scoped to this project" could never carry.

    `sector_{sector}` and `org_{org_slug}` are both outside this engagement and are shared with
    entirely different people - the first with other clients on this deployment, the second with
    this organisation's own sibling projects. A reader told only that neither is theirs cannot
    tell those apart, and the difference is the one that matters to them.
    """
    payload = await _payload(client)
    tiered = {row["source"]: row for row in payload["shared_sources"] if row["tier"]}
    assert set(tiered) == {"sector_{sector}", "org_{org_slug}"}

    for source, row in tiered.items():
        assert row["tier_scope"] == TIER_SCOPE[row["tier"]]
        assert row["tier_scope"], f"{source} carries a tier with no reason beside it"
    assert tiered["sector_{sector}"]["tier_scope"] != tiered["org_{org_slug}"]["tier_scope"], (
        "the two shared tiers are given the same reason, so the panel still cannot tell a "
        "store shared with other clients from one shared inside this organisation"
    )

    # The system database's tables are shared for a different reason and must not be dressed as
    # a tier: they are the deployment's own, not a width of the knowledge store.
    for source in ("agent_skill_notes", "skills"):
        row = next(r for r in payload["shared_sources"] if r["source"] == source)
        assert row["tier"] is None and row["tier_scope"] is None


@pytest.mark.asyncio
async def test_the_organisation_store_appears_with_nobody_instructed_to_read_it(client):
    """The empty `read_by` this change makes live rather than hypothetical.

    The organisation tier became writable on this branch, so an org_admin can put an
    organisation's strategy into `org_{org_slug}` today. No agent's task description names it,
    so nothing draws on it - but every holder of `ChromaQueryTool` could, and until this change
    the store appeared nowhere on the page at all. Absent is the one answer that is worse than
    either of those.
    """
    payload = await _payload(client)
    row = next(r for r in payload["shared_sources"] if r["source"] == "org_{org_slug}")

    assert row["read_by"] == [], "an agent is instructed to read the organisation store"
    assert row["handed_to_every_agent"] is False, (
        "the organisation store is not handed to anybody - it is offered and unasked for, and "
        "the two must not render the same way"
    )
    holders = sorted(
        node.display_name
        for node in build_graph().agents.values()
        if row["via"] in node.tools
    )
    assert row["reachable_by"] == holders
    assert row["reachable_by"], "nobody can reach it either, so the row says nothing"


@pytest.mark.asyncio
async def test_a_store_handed_to_every_agent_says_so_rather_than_naming_nobody(client):
    """`CREW_DISPATCH_READS` reaches an agent without any agent asking, so `read_by` is empty.

    An empty reader list rendered as "read by " would read as "nobody reads it", which of the
    skills library is the opposite of the truth.
    """
    payload = await _payload(client)
    for source in ("agent_skill_notes", "skills"):
        row = next(r for r in payload["shared_sources"] if r["source"] == source)
        assert row["handed_to_every_agent"] is True
        assert row["read_by"] == []


@pytest.mark.asyncio
async def test_what_the_dispatch_path_hands_every_agent_is_rendered(client):
    payload = await _payload(client)
    served = [(r["source"], r["note"]) for r in payload["dispatch_reads"]]
    assert served == [(r.source, r.note) for r in CREW_DISPATCH_READS]


@pytest.mark.asyncio
async def test_only_the_paths_that_reach_build_and_run_crew_carry_that_material(client):
    """Derived from the dispatchers, not from a count typed into the caption.

    Every path that remains funnels through `build_and_run_crew`, so all three carry the
    material - but the derivation is what says so, not this sentence. The discriminating case
    was the Chainlit console: it called `kickoff_async` itself and injected none of the skill
    notes, change requests or validation warnings, so "every crew run carries these" was wrong
    for it. With it gone this reads as a flat "all of them", and the flag it is derived from is
    still per path, which is the point - `build_and_run_agent` is reachable from the API and
    injects none of this, so a fourth path with the same shape would land here as False.
    """
    payload = await _payload(client)
    carrying = {p["trigger"] for p in payload["dispatch_paths"] if p["injects_dispatch_reads"]}
    assert carrying == {t.value for t in DISPATCH_PATHS}


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


# ── The clusters and the edges the view is drawn from ─────────────────────────
#
# The view renders these and nothing else, so this is the layer at which "would the picture be
# wrong?" can be asked of the back end. Every expectation is rebuilt from `build_graph()` rather
# than typed out, for the reason the rest of this file gives.


@pytest.mark.asyncio
async def test_the_payload_carries_every_cluster_with_its_crews_in_pipeline_order(client):
    payload = await _payload(client)
    graph = build_graph()

    assert [c["cluster_id"] for c in payload["clusters"]] == list(graph.clusters)
    for row in payload["clusters"]:
        node = graph.clusters[row["cluster_id"]]
        assert row["crew_ids"] == list(node.crew_ids)
        assert row["orchestrator_id"] == node.orchestrator_id
        assert row["orchestrator"] == graph.agents[node.orchestrator_id].display_name
        assert row["dispatches"] == list(node.dispatches)


@pytest.mark.asyncio
async def test_the_payload_carries_the_bands_the_view_is_laid_out_from(client):
    """The view draws parallel crews side by side, and only the bands say which those are.

    A payload with the flat order alone would leave the frontend to work out the depths for
    itself - a second computation of the pipeline, in the one place that cannot be held against
    `CREW_DEPENDENCIES`. So the grouping travels, and it must agree with the flat order it is
    printed beside.
    """
    payload = await _payload(client)
    graph = build_graph()

    for row in payload["clusters"]:
        node = graph.clusters[row["cluster_id"]]
        assert row["crew_bands"] == [list(band) for band in node.crew_bands]
        assert [c for band in row["crew_bands"] for c in band] == row["crew_ids"]

    banded = {
        crew_id: index
        for cluster in payload["clusters"]
        for index, band in enumerate(cluster["crew_bands"])
        for crew_id in band
    }
    for crew in payload["crews"]:
        for upstream in crew["depends_on_ids"]:
            assert banded[upstream] < banded[crew["crew_id"]], (
                f"{crew['crew_id']} is banded no lower than {upstream}, which it waits on"
            )


@pytest.mark.asyncio
async def test_two_crews_waiting_on_the_same_crew_are_banded_together(client):
    """The parallel pair, at the endpoint the picture is drawn from."""
    payload = await _payload(client)
    band = next(
        band
        for cluster in payload["clusters"]
        for band in cluster["crew_bands"]
        if "assessment_design" in band
    )
    assert set(band) == {"assessment_design", "stakeholder_management"}


@pytest.mark.asyncio
async def test_the_stakeholder_crews_flow_is_the_value_chain_at_the_endpoint(client):
    """The corrected dependency, as the page receives it."""
    payload = await _payload(client)
    into_jordan = {
        e["source"]: e for e in payload["crew_edges"] if e["target"] == "stakeholder_management"
    }
    assert "assessment_design" not in into_jordan
    assert into_jordan["discovery_mapping"]["kind"] == "information"
    assert "value_chain_registry" in into_jordan["discovery_mapping"]["artefacts"]


@pytest.mark.asyncio
async def test_every_crew_in_the_payload_names_the_cluster_that_owns_it(client):
    """No crew may fall outside the clusters, or the view is shorter than the table beside it."""
    payload = await _payload(client)
    owner = {
        crew_id: cluster["cluster_id"]
        for cluster in payload["clusters"]
        for crew_id in cluster["crew_ids"]
    }
    assert {crew["crew_id"] for crew in payload["crews"]} == set(owner)
    for crew in payload["crews"]:
        assert crew["cluster"] == owner[crew["crew_id"]]


@pytest.mark.asyncio
async def test_a_crew_row_carries_the_ids_its_names_stand_for(client):
    """The page shows the label and links on the id, so both must travel and must agree."""
    payload = await _payload(client)
    graph = build_graph()
    for crew in payload["crews"]:
        node = graph.crews[crew["crew_id"]]
        assert crew["agent_ids"] == list(node.agent_ids)
        assert crew["agents"] == [graph.agents[a].display_name for a in node.agent_ids]
        assert crew["depends_on_ids"] == list(node.depends_on)
        assert crew["trigger_ids"] == [t.value for t in node.triggers]


@pytest.mark.asyncio
async def test_the_payloads_edges_are_the_graphs_edges(client):
    payload = await _payload(client)
    graph = build_graph()
    assert [
        (e["source"], e["target"], e["kind"], tuple(e["artefacts"]), e["declared"])
        for e in payload["crew_edges"]
    ] == [
        (e.source, e.target, e.kind.value, e.artefacts, e.declared) for e in graph.edges
    ]


@pytest.mark.asyncio
async def test_an_edge_that_carries_nothing_is_reported_as_sequencing(client):
    """The auditor's distinction, at the endpoint.

    Two declared edges hand over no artefact. Reporting them the same way as the seven that do
    would tell a reader material passes between two crews when none does.
    """
    payload = await _payload(client)
    declared = [e for e in payload["crew_edges"] if e["declared"]]
    assert {e["kind"] for e in declared} == {"information", "sequencing"}
    for edge in declared:
        assert bool(edge["artefacts"]) == (edge["kind"] == "information")


@pytest.mark.asyncio
async def test_no_edge_names_a_crew_the_payload_does_not_carry(client):
    payload = await _payload(client)
    known = {crew["crew_id"] for crew in payload["crews"]}
    for edge in payload["crew_edges"]:
        assert edge["source"] in known and edge["target"] in known


@pytest.mark.asyncio
async def test_the_edges_move_when_a_read_is_declared(client, monkeypatch):
    """Driven, not observed: change one declaration and the endpoint's edge changes with it.

    `requirements -> delivery` carries nothing today. Declaring one of the requirements crew's
    outputs as a read of the roadmap generator must turn that edge into an information flow in
    the payload the page renders.
    """
    from agents.reads import AGENT_READS, Medium, Read

    def edge(payload):
        return next(
            e for e in payload["crew_edges"]
            if e["source"] == "requirements" and e["target"] == "delivery"
        )

    assert edge(await _payload(client))["kind"] == "sequencing"

    artefact = sorted(build_graph().crew_writes("requirements"))[0]
    reads = dict(AGENT_READS)
    reads["roadmap_generator"] = reads["roadmap_generator"] + (
        Read(artefact, Medium.ARTEFACT_JSON, "SQLiteStateTool", "invented for this test"),
    )
    monkeypatch.setattr("agents.graph._AGENT_READS", reads)

    after = edge(data_architecture(SLUG))
    assert after["kind"] == "information"
    assert artefact in after["artefacts"]


@pytest.mark.asyncio
async def test_every_name_the_payload_shows_travels_with_the_id_it_stands_for(client):
    """A link is made on the id and rendered on the name, so the two must stay in step.

    Parallel arrays are the risk this closes: `held_by` and `held_by_ids` are sorted separately
    in the sense that either could be, and a page that showed one agent's name over another's
    anchor would be quietly wrong in the direction hardest to notice. Two display names could
    also become identical - nothing refuses that - which is why the join is on the id.
    """
    payload = await _payload(client)
    graph = build_graph()
    name = {agent_id: node.display_name for agent_id, node in graph.agents.items()}

    def agree(names, ids, where):
        assert [name[i] for i in ids] == list(names), where

    for row in payload["tools"]:
        agree(row["held_by"], row["held_by_ids"], row["tool"])
    for row in payload["shared_sources"]:
        agree(row["read_by"], row["read_by_ids"], f"{row['source']} read_by")
        agree(row["reachable_by"], row["reachable_by_ids"], f"{row['source']} reachable_by")
    for row in payload["agents"]:
        assert row["crews"] == [graph.crews[c].display_name for c in row["crew_ids"]]


@pytest.mark.asyncio
async def test_the_agents_a_crew_names_and_the_crews_an_agent_names_are_one_relation(client):
    """Read from the crew and read from the agent, the membership must be the same set."""
    payload = await _payload(client)
    from_crews = {
        (crew["crew_id"], agent_id)
        for crew in payload["crews"]
        for agent_id in crew["agent_ids"]
    }
    from_agents = {
        (crew_id, agent["agent_id"])
        for agent in payload["agents"]
        for crew_id in agent["crew_ids"]
    }
    assert from_crews == from_agents
