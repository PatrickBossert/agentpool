# scripts/repair_registry_current.py
"""Leave exactly one current row per output type.

Version numbering and is_current were scoped per agent while filenames were not, so a second
agent writing the same output type produced a second row also claiming to be current. The
highest version wins, because that is what latest_output_path already resolves to on disk -
the database is being brought into line with what every reader already sees.
"""
from __future__ import annotations


async def repair_duplicate_current(conn, *, output_type: str) -> int:
    """Clear is_current from every row but the highest version. Returns rows corrected."""
    cur = await conn.execute(
        "UPDATE agent_outputs SET is_current=0"
        " WHERE output_type=? AND is_current=1 AND version < ("
        "   SELECT MAX(version) FROM agent_outputs WHERE output_type=? AND is_current=1)",
        (output_type, output_type),
    )
    await conn.commit()
    return cur.rowcount
