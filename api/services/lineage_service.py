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
