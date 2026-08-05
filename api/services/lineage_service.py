# api/services/lineage_service.py
"""What each output was built from, and whether it has been overtaken."""
from __future__ import annotations


async def fetch_lineage(conn, *, project_id: int) -> list[dict]:
    """One row per output, with its state ancestry and its cited documents."""
    # Both id and output_id carry the same value: this task's own tests index rows by
    # output_id, while the staleness rule (Task 5) and the endpoint that serves it (Task 6)
    # index by id. Carrying both is what lets each read naturally without either being
    # rewritten.
    async with conn.execute(
        "SELECT id, id AS output_id, agent_name, output_type, version, is_current,"
        " review_status, created_at FROM agent_outputs WHERE project_id=? ORDER BY id",
        (project_id,),
    ) as cur:
        outputs = [dict(row) async for row in cur]

    async with conn.execute(
        "SELECT output_id, input_output_id FROM output_lineage"
    ) as cur:
        edges = [(r[0], r[1]) async for r in cur]
    async with conn.execute("SELECT output_id, doc_id FROM output_citations") as cur:
        citations = [(r[0], r[1]) async for r in cur]

    by_output: dict[int, list[int]] = {}
    for output_id, input_id in edges:
        by_output.setdefault(output_id, []).append(input_id)
    docs: dict[int, list[int]] = {}
    for output_id, doc_id in citations:
        docs.setdefault(output_id, []).append(doc_id)

    for output in outputs:
        output["input_output_ids"] = sorted(by_output.get(output["output_id"], []))
        output["document_ids"] = sorted(docs.get(output["output_id"], []))
    return outputs


def staleness(outputs: list[dict], approvals: dict[str, int]) -> dict[int, dict]:
    """Which outputs have been overtaken by a newer approved input.

    `approvals` maps output_type to the highest approved version. Measured against approval
    rather than the newest write: agents write several versions inside one run, and those are
    working state rather than deliverables.

    An output with no recorded ancestry is `unknown`, never `fresh` - outputs written before
    lineage existed know nothing about their inputs, and claiming freshness for them would
    assert something nothing knows.
    """
    by_id = {o["id"]: o for o in outputs}
    result: dict[int, dict] = {}

    for output in outputs:
        inputs = output.get("input_output_ids") or []
        if not inputs:
            result[output["id"]] = {"state": "unknown", "behind": []}
            continue

        behind = []
        for input_id in inputs:
            source = by_id.get(input_id)
            if source is None:
                continue
            approved = approvals.get(source["output_type"])
            if approved is not None and approved > source["version"]:
                behind.append({
                    "output_type": source["output_type"],
                    "built_from": source["version"],
                    "approved": approved,
                })

        result[output["id"]] = {
            "state": "stale" if behind else "fresh",
            "behind": behind,
        }
    return result


async def approved_versions(conn, *, project_id: int) -> dict[str, int]:
    """The highest approved version per output type."""
    async with conn.execute(
        "SELECT output_type, MAX(version) FROM agent_outputs"
        " WHERE project_id=? AND review_status='approved' GROUP BY output_type",
        (project_id,),
    ) as cur:
        return {row[0]: row[1] async for row in cur}
