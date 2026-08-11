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

    ON CONFLICT(script_id) DO NOTHING, so running it twice is harmless and a row already
    present - one the write path has since registered - is never overwritten by older JSON.
    Deliberately not INSERT OR IGNORE: that clause swallows every constraint violation on the
    row, not only the primary-key conflict it is meant for, and node_label is TEXT NOT NULL -
    an old JSON registry carrying anything but a string or null there would be silently
    dropped with no error and no row (agents/tools/_db.py's register_scripts_sync carries the
    full account of why this matters). entry.get("node_label", "") has the same failure mode
    as register_scripts_sync did before its own fix: an explicit `"node_label": null` returns
    None, not "", straight into the NOT NULL bind. Matched to or "" here for the same reason.
    """
    entries = registry.get("scripts", []) if isinstance(registry, dict) else (registry or [])
    inserted = 0
    for entry in entries:
        script_id = entry.get("id")
        node_id = entry.get("node_id")
        if not script_id or not node_id:
            continue
        cur = await conn.execute(
            "INSERT INTO interview_script_ledger"
            " (script_id, project_id, node_id, node_label, active, last_author)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(script_id) DO NOTHING",
            (script_id, project_id, node_id, entry.get("node_label") or "",
             1 if entry.get("active", True) else 0, "interaction_designer"),
        )
        inserted += cur.rowcount
    await conn.commit()
    return inserted
