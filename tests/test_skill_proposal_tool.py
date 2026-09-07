# tests/test_skill_proposal_tool.py
"""The agent proposes, and cannot damage the revision by doing so.

Three properties, and only the first is about the tool in isolation:

- `SkillProposalTool._run` never raises, whatever `propose_skill` does. The reviewer asked for
  a revision, not a skill.
- A run that reaches the tool still completes, still closes the change request it was answering,
  and leaves the artefact the agent revised exactly as the agent wrote it. Asserted through
  `build_and_run_crew` against a stub crew, because the property is about the run and a test at
  the tool boundary alone would be one layer away from it - the shape CLAUDE.md's *recurring
  failure mode* section is a list of.
- The instruction to propose reaches the task only when something was actually sent back, and
  reaches it once however many blocks fired.

Nothing here calls Anthropic: `propose_skill` is patched at
`api.services.skills_service.propose_skill`, which is also the assertion that the tool resolves
it through the module at call time. Binding the function itself at import - `from ... import
propose_skill` - makes these tests run the real service and two of them fail, which is the
mutation that establishes the claim. Importing the *module* at module level changes nothing
here; that is a cycle question rather than a patchability one, and the two were conflated until
a power-check separated them.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml

from agents.tools.skill_proposal import SkillProposalTool
from api.database import get_connection, insert_output_change, insert_project

SLUG = "skill-proposal-tool-test"


def _tool(agent_name: str = "interaction_designer") -> SkillProposalTool:
    return SkillProposalTool(slug=SLUG, agent_name=agent_name)


# ── The tool cannot fail the run ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def crew_project(tmp_path, monkeypatch):
    """A project on disk and in SQLite, with an outputs directory to hold an artefact."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    project_dir = projects_dir / SLUG
    (project_dir / "outputs").mkdir(parents=True)
    (project_dir / "config.yaml").write_text(
        yaml.dump({"llm_mode": "standard", "sector": "utilities"})
    )
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield project_dir
    get_settings.cache_clear()


async def _sent_back(conn, request: str) -> int:
    """An open change request against a current output of the requirements crew's own agent.

    This is what makes the run a revision rather than an ordinary run, and therefore what
    injects the proposal instruction.
    """
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,'requirements_analyst','requirements_doc','r_v1.json',1,1,'pending')"
    )
    await conn.commit()
    output_id = cur.lastrowid
    await insert_output_change(
        conn, output_id=output_id, requested_by="alice", source="review",
        request=request, summary="", kind="change_request",
    )
    return output_id


async def _change_status(output_id: int):
    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT status, applied_run_id FROM output_changes WHERE output_id=?",
            (output_id,),
        ) as cur:
            return await cur.fetchone()


def _crew_that_revises_then_proposes(artefact, revised: str, replies: list[str]):
    """A stub crew whose one task writes the revision and then calls the real tool.

    The order is the order the instruction asks for, and it is the order that makes the
    artefact assertion meaningful: the file is on disk, holding the revision, before anything
    about a skill happens. A tool that raised would abandon the run between the two.
    """
    task = MagicMock()
    task.description = "original task body"
    crew = MagicMock()
    crew.tasks = [task]

    async def _kickoff():
        artefact.write_text(revised, encoding="utf-8")
        replies.append(
            _tool("requirements_analyst")._run(
                rule="State units on every figure you carry forward.",
                source_ref="requirements_doc",
            )
        )
        return "done"

    crew.kickoff_async = AsyncMock(side_effect=_kickoff)
    return crew, task


@pytest.mark.asyncio
async def test_a_failing_proposal_does_not_fail_the_run(crew_project):
    """The property the design states as absolute, driven through the run.

    `propose_skill` raises. The assertion is on the artefact and on the bookkeeping, not only
    on a status: a run that dies here would leave the revision written but the change request
    still open, so the reviewer's note would be re-injected on the next run and the agent would
    be asked to make a correction it had already made.
    """
    artefact = crew_project / "outputs" / "requirements_doc_v2.json"
    revised = '{"revision": "units stated on every figure"}'
    replies: list[str] = []

    async with get_connection(SLUG) as conn:
        output_id = await _sent_back(conn, "state the units on every figure")

    crew, _task = _crew_that_revises_then_proposes(artefact, revised, replies)

    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    from api.services import skills_service

    with patch.object(
        skills_service, "propose_skill",
        AsyncMock(side_effect=RuntimeError("the comparison model is unreachable")),
    ), patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(SLUG, "requirements", run_id=11)

    assert result == "done"
    assert artefact.read_text(encoding="utf-8") == revised
    row = await _change_status(output_id)
    assert row["status"] == "applied"
    assert row["applied_run_id"] == 11
    assert len(replies) == 1
    assert "no effect on the revision" in replies[0]


@pytest.mark.asyncio
async def test_a_successful_proposal_leaves_the_same_run_intact(crew_project):
    """The control for the test above.

    Without it, a tool that answered the failure sentence unconditionally - or one that never
    reached `propose_skill` at all - would satisfy every assertion there. This also pins what
    the tool passes: the agent id it was built with, the project slug as the provenance, and the
    reference the agent named.
    """
    artefact = crew_project / "outputs" / "requirements_doc_v2.json"
    revised = '{"revision": "units stated on every figure"}'
    replies: list[str] = []

    async with get_connection(SLUG) as conn:
        output_id = await _sent_back(conn, "state the units on every figure")

    crew, _task = _crew_that_revises_then_proposes(artefact, revised, replies)
    proposed = AsyncMock(return_value={
        "action": "created", "skill_id": 7, "status": "pending",
        "occurrences": 1, "name": "State units", "agent": "Requirements Analyst",
    })

    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    from api.services import skills_service

    with patch.object(skills_service, "propose_skill", proposed), patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(SLUG, "requirements", run_id=12)

    assert result == "done"
    assert artefact.read_text(encoding="utf-8") == revised
    assert (await _change_status(output_id))["status"] == "applied"

    args, kwargs = proposed.call_args
    assert args[0] == "requirements_analyst"
    assert args[1] == "State units on every figure you carry forward."
    assert args[2] == SLUG
    assert args[3] == "requirements_doc"
    assert kwargs == {"name": None}
    assert "until somebody approves it" in replies[0]


@pytest.mark.asyncio
async def test_an_agent_no_approval_could_reach_is_refused_without_raising():
    """`_role_name_for` raises `UnknownProposingAgent` rather than guessing a name, because a
    proposal filed under an unresolvable one is approvable and reaches no prompt for ever.

    That refusal is correct and it is a `ValueError` arriving after the revision is already
    made, so this is where it is swallowed. Driven through the **real** `propose_skill`, not a
    stub of it - the refusal is raised before any database or model work, so the call is offline,
    and stubbing it would assert only that this test can raise an exception.
    """
    reply = _tool("no_such_agent")._run(rule="Some general rule about something.")

    assert "could not be recorded" in reply
    assert "carry on with your task" in reply


class _AbruptStop(BaseException):
    """Stands in for `KeyboardInterrupt` and `SystemExit` in the test below.

    Those are the real cases - `await_sync` runs the coroutine under `asyncio.run`, on a
    worker thread whenever a loop is already live, and `concurrent.futures` re-raises whatever
    the work item set, `BaseException` included. Neither is usable here: pytest treats both as
    "stop the session", so the `except Exception` mutation would abort the run rather than
    fail a test, and an aborted run is a much weaker signal than a named failure. A plain
    `BaseException` subclass exercises the same branch and is caught by the same `except`.
    """


def test_a_base_exception_from_the_proposal_is_still_swallowed():
    """`_run` catches `BaseException`, and this is what distinguishes that from `Exception`.

    Nothing did before: mutating the `except` to `Exception` left the whole backend suite
    green, so the wider catch was an assertion made only in a comment.

    It is also *not* the case the comment used to claim. A `CancelledError` from the
    comparison's own timeout never reaches this frame: `asyncio.wait_for` converts it to
    `TimeoutError` inside `find_duplicate_skill`, which catches it there. The catch is
    belt-and-braces, and that is now what the comment says.
    """
    with patch("api.services.skills_service.propose_skill", side_effect=_AbruptStop):
        reply = _tool()._run(rule="A general rule worth remembering.")

    assert "could not be recorded" in reply
    assert "carry on with your task" in reply


def test_an_empty_rule_is_refused_rather_than_recorded():
    """A blank proposal must not reach the queue, and must not look like a failure either -
    the agent is told to say nothing rather than to try again."""
    with patch("api.services.skills_service.propose_skill") as never:
        reply = _tool()._run(rule="   ")
    never.assert_not_called()
    assert "a rule was not supplied" in reply


@pytest.mark.parametrize(
    "outcome",
    [None, "created", {"action": "who knows"}, {}],
    ids=["not-a-dict", "a-string", "unknown-action", "empty"],
)
def test_a_reply_the_tool_cannot_read_is_reported_as_a_failure(outcome):
    """`propose_skill`'s contract could change under this tool, and this runs after the
    revision: a `KeyError` on a renamed key would be a proposal failing a finished run."""
    from agents.tools.skill_proposal import _describe

    assert "could not be recorded" in _describe(outcome)


def test_the_two_outcomes_are_told_apart():
    """Guard the guard above: if every outcome resolved to the failure sentence, the
    parametrised test would pass against a function that reports nothing."""
    from agents.tools.skill_proposal import _describe

    created = _describe({"action": "created", "occurrences": 1})
    incremented = _describe({"action": "incremented", "occurrences": 3})

    assert "could not be recorded" not in created
    assert "could not be recorded" not in incremented
    assert created != incremented
    assert "3 occurrences" in incremented


# ── Who holds it ──────────────────────────────────────────────────────────────────────────


def test_every_agent_that_can_be_sent_work_back_holds_the_tool():
    """The registration rule, held against `_CREW_AGENT_NAMES` rather than a list typed twice.

    Every agent a crew dispatches writes `agent_outputs` rows a reviewer's note reaches through
    `_fetch_change_requests`, so every one of them can be sent work back and every one must be
    able to propose. Asserted against what `get_tools_for_agent` actually returns, not against
    the graph's reading of the literal, because a run-time substitution is the one thing the
    reading could not see.
    """
    from agents.tools.registry import get_tools_for_agent
    from api.services.run_service import _CREW_AGENT_NAMES

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}
    assert dispatched, "no agent is dispatched by any crew - this guard proves nothing"
    without = sorted(
        name for name in dispatched
        if not any(
            type(tool).__name__ == "SkillProposalTool"
            for tool in get_tools_for_agent(name, slug=SLUG, run_id=1, sector="test")
        )
    )
    assert not without, (
        f"{without} produce an output a reviewer can send back and cannot propose the rule "
        f"behind a correction - the lesson evaporates for them."
    )


def test_pam_does_not_hold_it():
    """Excluded on both halves of the rule, and asserted so the exclusion is a decision rather
    than an oversight of the same shape as the two registries the Illustrator was missing from.

    PAM orchestrates rather than producing an artefact, so nothing of hers is sent back; and she
    is in no `_CREW_AGENT_NAMES` entry, so `_fetch_skill_notes` injects nothing for her - a
    proposal of hers would be queued, approvable, and would still reach no prompt.
    """
    from agents.tools.registry import get_tools_for_agent
    from api.services.run_service import _CREW_AGENT_NAMES, _SNAKE_TO_DISPLAY

    held = {
        type(tool).__name__
        for tool in get_tools_for_agent("pam", slug=SLUG, run_id=1, sector="test")
    }
    assert "SkillProposalTool" not in held
    assert "pam" in _SNAKE_TO_DISPLAY
    assert not any("pam" in agents for agents in _CREW_AGENT_NAMES.values())


def test_the_tool_declares_the_model_call_it_makes_and_declares_it_as_gated():
    """`propose_skill` asks a model whether the rule restates one already held, and that call
    goes through `project_completion`, so it moves with the project like every other prompt.

    Both halves matter and they fail differently. A tool that made a model call and declared
    `Reach.NOTHING` would under-report on the page whose job is being right about where a
    client's material goes; a tool that declared an *ungated* reach - which this one did for
    one commit, honestly, while `skills_service` built `AsyncAnthropic` directly - would tell
    an auditor that a sensitive engagement reaches Anthropic when it no longer does.

    Asserted through the resolver rather than against the table, and in both directions:
    contained on a project without the grant, hosted on one with it.
    """
    from agents.egress import is_gated_by_grant, resolve_egress
    from api.services.deployment_modes import granted_to

    standard = resolve_egress("SkillProposalTool", granted_to("standard"))
    sensitive = resolve_egress("SkillProposalTool", granted_to("sensitive"))

    assert standard != sensitive
    assert standard.leaves_deployment
    assert not sensitive.leaves_deployment
    assert is_gated_by_grant("SkillProposalTool")


# ── The instruction ───────────────────────────────────────────────────────────────────────


def _stub_crew():
    task = MagicMock()
    task.description = "original task body"
    crew = MagicMock()
    crew.tasks = [task]
    seen: list[str] = []

    async def _kickoff():
        seen.append(task.description)
        return "done"

    crew.kickoff_async = AsyncMock(side_effect=_kickoff)
    return crew, seen


@pytest.mark.asyncio
async def test_the_instruction_reaches_the_task_when_work_was_sent_back(crew_project):
    async with get_connection(SLUG) as conn:
        await _sent_back(conn, "state the units on every figure")

    crew, seen = _stub_crew()
    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "requirements", run_id=13)

    text = seen[0]
    assert "SkillProposalTool" in text
    assert "Propose the rule, not the note" in text
    # The worked pair, both halves. One without the other is the distinction the instruction
    # exists to draw, drawn on one side only.
    assert "the framing repeats the welcome" in text
    assert "the framing carries the interview's purpose" in text
    # After the block it refers to, and before the task it is attached to.
    assert text.index("state the units on every figure") < text.index("SkillProposalTool")
    assert text.index("SkillProposalTool") < text.index("original task body")


@pytest.mark.asyncio
async def test_an_ordinary_run_is_not_asked_to_propose(crew_project):
    """Nothing was sent back, so there is no correction to draw a rule from - and asking anyway
    would put the deduplication's hosted model call on every run of every crew."""
    crew, seen = _stub_crew()
    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "requirements", run_id=14)

    assert "SkillProposalTool" not in seen[0]
    assert seen[0] == "original task body"


@pytest.mark.asyncio
async def test_two_send_backs_ask_for_one_proposal_not_two(crew_project, monkeypatch):
    """A change request and a script sent back are one send-back to the agent, not two.

    `RerunDialog` already fans one note out into several `output_changes` rows, which is why
    `_fetch_change_requests` deduplicates; a second copy of "propose at most one rule" arriving
    because two *blocks* fired would be the same defect from a second source.
    """
    async with get_connection(SLUG) as conn:
        await _sent_back(conn, "state the units on every figure")

    from api.services import run_service

    async def _regeneration(slug, crew_name):
        return "SCRIPTS SENT BACK FOR REVISION:\n- SC-014 (3.2 Intake): the framing repeats it"

    monkeypatch.setattr(run_service, "_fetch_regeneration_requests", _regeneration)

    crew, seen = _stub_crew()
    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        await run_service.build_and_run_crew(SLUG, "requirements", run_id=15)

    assert seen[0].count("SkillProposalTool") == 1
    assert seen[0].count("Propose the rule, not the note") == 1


@pytest.mark.asyncio
async def test_every_task_in_a_multi_task_crew_gets_the_instruction_once(crew_project):
    """The injection is per task, and a crew has several. A loop that mutated only the first
    would leave the second agent unable to see the tool it holds."""
    async with get_connection(SLUG) as conn:
        await _sent_back(conn, "state the units on every figure")

    tasks = []
    for body in ("first task body", "second task body"):
        task = MagicMock()
        task.description = body
        tasks.append(task)
    crew = MagicMock()
    crew.tasks = tasks
    crew.kickoff_async = AsyncMock(return_value="done")

    import agents.crews.requirements_crew  # noqa: F401  importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "requirements", run_id=16)

    for task, body in zip(tasks, ("first task body", "second task body")):
        assert task.description.count("SkillProposalTool") == 1
        assert task.description.endswith(f"\n\n{body}")


@pytest.mark.asyncio
async def test_the_revision_blocks_survive_the_reordering(crew_project):
    """The injection loop was restructured to place the new block; the four that were already
    there must still arrive, in the same reading order, with the task last.

    Asserted as an ordering over all six markers rather than as six separate `in` checks, so a
    later tidy-up that keeps every block but reorders them fails here too.
    """
    async with get_connection(SLUG) as conn:
        await _sent_back(conn, "state the units on every figure")

    from api.services import run_service

    async def _warnings(slug, crew_name):
        return "STRUCTURAL WARNINGS:\n- the tree has two roots"

    async def _regeneration(slug, crew_name):
        return "SCRIPTS SENT BACK FOR REVISION:\n- SC-014"

    async def _skills(crew_name):
        return "AGENT SKILLS:\n- Units: state them"

    with patch.object(run_service, "_fetch_validation_warnings", _warnings), \
         patch.object(run_service, "_fetch_regeneration_requests", _regeneration), \
         patch.object(run_service, "_fetch_skill_notes", _skills):
        crew, seen = _stub_crew()
        import agents.crews.requirements_crew  # noqa: F401  importable before patching
        with patch(
            "agents.crews.requirements_crew.create_requirements_crew", return_value=crew
        ):
            await run_service.build_and_run_crew(SLUG, "requirements", run_id=17)

    text = seen[0]
    order = [
        "SCRIPTS SENT BACK FOR REVISION",
        "STRUCTURAL WARNINGS",
        "REQUESTED CHANGES",
        "Propose the rule, not the note",
        "AGENT SKILLS",
        "original task body",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions), text
