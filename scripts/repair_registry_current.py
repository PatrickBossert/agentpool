# scripts/repair_registry_current.py
"""Leave exactly one current row per output type.

Version numbering and is_current were scoped per agent while filenames were not, so a second
agent writing the same output type produced a second row also claiming to be current.

The original rationale is now inverted, and the script is kept rather than retired because
of it. It used to reconcile the database *to the disk*: "the highest version wins, because
that is what latest_output_path already resolves to". Readers no longer look at the disk -
current_output_path asks this table - so the database is not being brought into line with
anything. It is the authority, and two rows claiming to be current make it ambiguous.

The repair itself is unchanged and still needed: sp-gs-am carried two current 'state' rows
for months, and current_output_path breaks the tie with ORDER BY version DESC, which is
picking rather than resolving. tests/test_output_type_families.py asserts the invariant this
restores.
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
