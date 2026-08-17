# tests/test_pam_report_service.py
"""The report derivation must be callable outside a request.

It lived inside the route handler, so the scheduled job could not reach it.
This asserts the service exists and returns the same shape the endpoint returns.
"""
import pytest


@pytest.mark.asyncio
async def test_build_pam_report_returns_the_report_shape(client):
    await client.post("/projects", json={
        "client_slug": "pam-svc-test", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    report = await build_pam_report("pam-svc-test")

    for key in ["generated_at", "project_slug", "overall_health", "health_summary",
                "milestones", "crews", "risks", "issues", "interview_tracker"]:
        assert key in report, f"missing {key}"
    assert report["project_slug"] == "pam-svc-test"


@pytest.mark.asyncio
async def test_endpoint_and_service_agree(client):
    """The endpoint must delegate, not duplicate - otherwise they can drift."""
    await client.post("/projects", json={
        "client_slug": "pam-svc-agree", "llm_mode": "standard", "sector": "rail",
    })
    from api.services.pam_report_service import build_pam_report

    via_service = await build_pam_report("pam-svc-agree")
    resp = await client.get("/projects/pam-svc-agree/pam-report")
    via_endpoint = resp.json()

    assert resp.status_code == 200
    # generated_at is a timestamp and will differ between the two calls
    via_service.pop("generated_at", None)
    via_endpoint.pop("generated_at", None)
    assert via_service == via_endpoint


# ── Which crews the report covers ─────────────────────────────────────────────
#
# The report used to declare the crew list, the order, the labels and each crew's agents in
# four literals at the top of the service. All four had gone stale: `discovery` and
# `architecture` were listed and no longer exist, `requirements` and `capabilities` exist and
# were listed nowhere, and the Illustrator was filed under `delivery`. A reader of Pamela's
# report saw two crews that cannot run and did not see two that can.


@pytest.mark.asyncio
async def test_the_report_covers_exactly_the_crews_that_exist(client):
    from agents.graph import build_graph
    from api.services.pam_report_service import build_pam_report

    await client.post("/projects", json={
        "client_slug": "pam-crew-set", "llm_mode": "standard", "sector": "rail",
    })
    report = await build_pam_report("pam-crew-set")

    assert [c["crew_key"] for c in report["crews"]] == list(build_graph().crews)


@pytest.mark.asyncio
async def test_no_crew_is_reported_before_one_it_waits_on(client):
    """The order was hand-typed and contradicted the dependency map - it put
    stakeholder_management before assessment_design, which the graph requires first."""
    from agents.graph import build_graph
    from api.services.pam_report_service import build_pam_report

    await client.post("/projects", json={
        "client_slug": "pam-crew-order", "llm_mode": "standard", "sector": "rail",
    })
    report = await build_pam_report("pam-crew-order")

    order = [c["crew_key"] for c in report["crews"]]
    graph = build_graph()
    for position, crew_key in enumerate(order):
        for upstream in graph.crews[crew_key].depends_on:
            assert order.index(upstream) < position, f"{crew_key} listed before {upstream}"


@pytest.mark.asyncio
async def test_each_crew_carries_the_label_the_graph_gives_it(client):
    from agents.graph import build_graph
    from api.services.pam_report_service import build_pam_report

    await client.post("/projects", json={
        "client_slug": "pam-crew-labels", "llm_mode": "standard", "sector": "rail",
    })
    report = await build_pam_report("pam-crew-labels")

    labels = {c["crew_key"]: c["crew_label"] for c in report["crews"]}
    assert labels == {c.crew_id: c.display_name for c in build_graph().crews.values()}


@pytest.mark.asyncio
async def test_an_output_is_counted_against_the_crew_its_author_runs_in(client):
    """One output per agent, then every crew's count must equal its own membership. The
    deleted map filed `visual_illustrator` under `delivery`, so the Illustrator's brief was
    counted against a crew he is not in and missing from the one he is."""
    from agents.graph import build_graph
    from api.database import get_connection, fetch_project
    from api.services.pam_report_service import build_pam_report

    slug = "pam-crew-outputs"
    await client.post("/projects", json={
        "client_slug": slug, "llm_mode": "standard", "sector": "rail",
    })
    graph = build_graph()
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        for agent_id in graph.agents:
            await conn.execute(
                "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
                " version, is_current) VALUES (?,?,?,?,1,1)",
                (project["id"], agent_id, f"{agent_id}_output", f"/tmp/{agent_id}.json"),
            )
        await conn.commit()

    report = await build_pam_report(slug)
    by_crew = {c["crew_key"]: set(c["output_types"]) for c in report["crews"]}
    for crew in graph.crews.values():
        assert by_crew[crew.crew_id] == {f"{a}_output" for a in crew.agent_ids}
