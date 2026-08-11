"""One-time load of the JSON script ledger into interview_script_ledger.

The artefact is retiring, but every id it holds has already been issued and may already
be cited by a stakeholder assignment or a stored answer. Starting the table empty would
put all of them outside the succession guarantee at once.
"""
import aiosqlite


async def backfill_script_ledger(
    conn: aiosqlite.Connection, *, project_id: int, registry: dict
) -> int:
    """Insert a ledger row per registry entry. Returns the number inserted.

    INSERT OR IGNORE, so running it twice is harmless and a row already present - one
    the write path has since registered - is never overwritten by older JSON.
    """
    entries = registry.get("scripts", []) if isinstance(registry, dict) else (registry or [])
    inserted = 0
    for entry in entries:
        script_id = entry.get("id")
        node_id = entry.get("node_id")
        if not script_id or not node_id:
            continue
        cur = await conn.execute(
            "INSERT OR IGNORE INTO interview_script_ledger"
            " (script_id, project_id, node_id, node_label, active, last_author)"
            " VALUES (?,?,?,?,?,?)",
            (script_id, project_id, node_id, entry.get("node_label", ""),
             1 if entry.get("active", True) else 0, "interaction_designer"),
        )
        inserted += cur.rowcount
    await conn.commit()
    return inserted
