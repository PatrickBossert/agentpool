"""Re-type Maya's pre-ec92bc1 outputs and recompute is_current.

Before ec92bc1 (25 Jul) SQLiteStateTool wrote every output as output_type='state'.
insert_agent_output_sync supersedes by (project, agent, output_type), so each write
marked all her earlier outputs is_current=0 - and 'state' is in the UI's
INTERNAL_TYPES, so none of them displayed at all. This derives the real type from
the filename, exactly as the fixed tool would now write it.
"""
import os, re, sqlite3, sys

db = sys.argv[1]
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row

rows = c.execute(
    "SELECT id, file_path, version, agent_name, project_id FROM agent_outputs "
    "WHERE agent_name='interaction_designer' AND output_type='state'"
).fetchall()

for r in rows:
    stem = re.sub(r'_v\d+\.json$', '', os.path.basename(r['file_path']))
    c.execute("UPDATE agent_outputs SET output_type=? WHERE id=?", (stem, r['id']))

# Recompute is_current: highest version per (project, agent, output_type) wins.
c.execute("UPDATE agent_outputs SET is_current=0 WHERE agent_name='interaction_designer'")
c.execute("""
    UPDATE agent_outputs SET is_current=1 WHERE id IN (
        SELECT id FROM agent_outputs a
        WHERE a.agent_name='interaction_designer'
          AND a.version = (SELECT MAX(b.version) FROM agent_outputs b
                           WHERE b.project_id=a.project_id AND b.agent_name=a.agent_name
                             AND b.output_type=a.output_type)
    )
""")
c.commit()

n_cur = c.execute("SELECT COUNT(*) FROM agent_outputs WHERE agent_name='interaction_designer' AND is_current=1").fetchone()[0]
n_scripts = c.execute("SELECT COUNT(*) FROM agent_outputs WHERE agent_name='interaction_designer' AND is_current=1 AND output_type LIKE 'interview_scripts%'").fetchone()[0]
print(f"  re-typed {len(rows)} rows")
print(f"  is_current=1 now: {n_cur} (was 1)")
print(f"  of which interview_scripts*: {n_scripts}")
