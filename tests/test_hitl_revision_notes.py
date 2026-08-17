# tests/test_hitl_revision_notes.py
"""A revision note posted with a review must reach the outputs of the crew being reviewed.

`insert_hitl_review` fans a reviewer's note out to every current output belonging to the
crew's own agents. Which agents those are came from a map typed inside `agents/tools/_db.py`,
and that map had gone stale in the way this whole slice exists to end: it named `discovery`
and `architecture`, crews no dispatch map has known for two sprints, and therefore knew no
agent at all for `requirements` or `capabilities`. An unrecognised crew took the empty branch
silently - the review row was written, the note was displayed in the UI, and no output ever
carried it.

Asserted on `insert_hitl_review` rather than on the graph. The graph being right is already
tested next door; what was never tested is whether the function reading it writes anything.
"""
from __future__ import annotations

import sqlite3

import pytest

from api.config import get_settings

SLUG = "hitl-notes-project"

# A crew whose membership the deleted map got wrong, and one it got right. The first is what
# regressed; the second is what a fix could plausibly have broken on the way past.
BROKEN_BEFORE = "capabilities"
WORKED_BEFORE = "value_design"


def _connect(tmp_path):
    return sqlite3.connect(str(tmp_path / "data" / f"{SLUG}.db"))


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project with one crew run per crew, and one current output per agent that runs."""
    from agents.graph import build_graph

    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    get_settings.cache_clear()

    conn = _connect(tmp_path)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
    conn.execute(
        "CREATE TABLE crew_runs (id INTEGER PRIMARY KEY, project_id INTEGER, crew_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE human_reviews (id INTEGER PRIMARY KEY, crew_run_id INTEGER,"
        " decision TEXT, prompt TEXT)"
    )
    conn.execute(
        "CREATE TABLE agent_outputs ("
        " id INTEGER PRIMARY KEY, project_id INTEGER, agent_name TEXT,"
        " output_type TEXT, file_path TEXT, version INTEGER,"
        " review_status TEXT DEFAULT 'pending', revision_notes TEXT,"
        " is_current INTEGER NOT NULL DEFAULT 1,"
        " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO projects (id, slug) VALUES (1, ?)", (SLUG,))

    graph = build_graph()
    for run_id, crew_id in enumerate(graph.crews, start=1):
        conn.execute(
            "INSERT INTO crew_runs (id, project_id, crew_name) VALUES (?,1,?)",
            (run_id, crew_id),
        )
    for agent_id in graph.agents:
        conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current) VALUES (1,?,?,?,1,1)",
            (agent_id, f"{agent_id}_output", f"/tmp/{agent_id}.json"),
        )
    conn.commit()
    conn.close()

    yield {crew_id: run_id for run_id, crew_id in enumerate(graph.crews, start=1)}
    get_settings.cache_clear()


def _notes(tmp_path) -> dict[str, str | None]:
    conn = _connect(tmp_path)
    rows = conn.execute(
        "SELECT agent_name, revision_notes FROM agent_outputs WHERE is_current=1"
    ).fetchall()
    conn.close()
    return dict(rows)


def _agents_of(crew_id: str) -> set[str]:
    from agents.graph import build_graph
    return set(build_graph().crews[crew_id].agent_ids)


@pytest.mark.parametrize("crew_id", [BROKEN_BEFORE, WORKED_BEFORE])
def test_the_note_reaches_every_agent_of_the_crew_being_reviewed(crew_id, project, tmp_path):
    from agents.tools._db import insert_hitl_review

    insert_hitl_review(
        SLUG,
        project[crew_id],
        "Please review the output.\n\nTighten the cost bands.\n\nReply approved to continue.",
    )

    carrying = {a for a, note in _notes(tmp_path).items() if note == "Tighten the cost bands."}
    assert carrying == _agents_of(crew_id)


def test_every_crew_the_graph_holds_can_carry_a_note(project, tmp_path):
    """The general form. A stale map is not wrong about every crew at once - it was right
    about six of nine, which is exactly why nobody noticed the other three."""
    from agents.tools._db import insert_hitl_review
    from agents.graph import build_graph

    for crew_id, run_id in project.items():
        insert_hitl_review(
            SLUG, run_id, f"Please review.\n\nnote-for-{crew_id}\n\nReply approved to continue."
        )

    notes = _notes(tmp_path)
    for crew in build_graph().crews.values():
        for agent_id in crew.agent_ids:
            assert notes[agent_id] == f"note-for-{crew.crew_id}", (
                f"{agent_id} runs in {crew.crew_id} and carries {notes[agent_id]!r}"
            )


def test_an_agent_in_no_crew_is_left_alone(project, tmp_path):
    """PAM is in no crew, so no crew's review is hers. A fan-out that reached every agent
    would pass every assertion above and still be wrong."""
    from agents.tools._db import insert_hitl_review

    insert_hitl_review(
        SLUG, project[WORKED_BEFORE], "Please review.\n\nsomething\n\nReply approved to continue."
    )
    assert _notes(tmp_path)["pam"] is None
