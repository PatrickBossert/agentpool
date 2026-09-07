"""Unit tests for the three discovery interview agent modules."""
from unittest.mock import MagicMock, patch
import pytest


def _mock_agent():
    return MagicMock()


# ── Interview Coordinator ─────────────────────────────────────────────────────

def test_interview_coordinator_task_includes_assignments():
    """Task description includes the stakeholder assignments block when provided."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(
            agent=agent,
            stakeholder_assignments="- Alice Chen (Head of Ops) → L2: Order Fulfilment",
        )
    _, kwargs = MockTask.call_args
    assert "Alice Chen" in kwargs["description"]
    assert "interview_plan" in kwargs["description"]


def test_coordinator_task_reads_interview_scripts():
    """Task description instructs agent to read interview_scripts (not value_chain_tree)."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "interview_scripts" in kwargs["description"]
    assert "value_chain_tree" not in kwargs["description"]


def test_coordinator_task_writes_interview_plan():
    """Task description instructs agent to write interview_plan."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]


def test_coordinator_task_asks_for_the_script_id_in_every_plan_entry():
    """The plan is where script_id enters the system, so the prompt is where it is asked for.

    Deliberately a weak assertion about a prompt rather than a strong one about behaviour -
    what actually guarantees a stored script_id is InterviewSessionTool._create, which
    resolves an omitted id from the label itself (tests/test_session_script_citation.py).
    This only holds the near end of the plumbing: the coordinator's example session entry
    used to show stakeholder_id, name, node_label, and voice_config, and an entry the
    example does not contain is one the model has no reason to emit.
    """
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert '"script_id"' in kwargs["description"], (
        "the session entry example must carry script_id, not just prose about it"
    )


def test_coordinator_task_injects_assignments():
    """Task description includes injected stakeholder assignment data."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(
            agent=agent,
            stakeholder_assignments="- Bob Smith → L3: Packing",
        )
    _, kwargs = MockTask.call_args
    assert "Bob Smith" in kwargs["description"]


def _everything_taylor_is_given() -> dict[str, str]:
    """Every string the Coordinator's agent and task carry, keyed by field.

    **Five fields, not one.** The first version of the guard below read
    `kwargs["description"]` alone, and a reviewer reinstated the locale table by putting the
    four correct ids in the **backstory** - green against the whole suite. An agent's `role`,
    `goal` and `backstory` reach the model exactly as its task does, so a guard about what the
    model is told has to read all of them or it guards one field and implies five.
    """
    from agents.discovery.interview_coordinator import (
        create_interview_coordinator,
        create_interview_coordinator_task,
    )

    with patch("agents.discovery.interview_coordinator.Agent") as MockAgent:
        MockAgent.return_value = MagicMock()
        create_interview_coordinator("some-slug", MagicMock(), [])
    _, agent_kwargs = MockAgent.call_args

    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=_mock_agent(), stakeholder_assignments="")
    _, task_kwargs = MockTask.call_args

    fields = {
        "role": agent_kwargs["role"],
        "goal": agent_kwargs["goal"],
        "backstory": agent_kwargs["backstory"],
        "description": task_kwargs["description"],
        "expected_output": task_kwargs["expected_output"],
    }
    assert all(isinstance(v, str) and v for v in fields.values()), fields
    return fields


# The stock voices the two retired tables named between them, plus the four verified defaults
# a "corrected" table would name. Held here rather than derived, because `agents/identity.py`
# stores ids and not ElevenLabs' names for them - and a list inside a guard is not a
# declaration the product reads, which is the distinction that makes it acceptable here and
# unacceptable in a prompt.
STOCK_VOICE_NAMES = (
    "Rachel", "Bella", "Domi", "Elli", "Josh", "Adam", "Sam", "Antoni", "Arnold",
    "Daniel", "Alice", "Mark", "Belinda",
)


def test_nothing_taylor_is_given_chooses_a_voice_in_any_vocabulary():
    """The inversion of `test_coordinator_task_includes_voice_locale_table`, widened twice.

    That test asserted Taylor's prompt *carried* a locale-to-voice-id table. It held eight
    rows in prose naming ElevenLabs' stock Rachel - a female voice - for `en/GB` and `en/US`,
    and a dead TypeScript twin at `ui/src/utils/voiceLocale.ts` disagreed with it on four of
    the eight. Both are deleted, and the ids were **not corrected**: a corrected table is a
    fifth declaration of voice facts that happens to be right today, which is the state that
    produced four disagreeing copies.

    **The first replacement guard caught only the shape it had found.** It read the task
    description and matched a 20-character id, and a reviewer reinstated the table three ways
    against a green suite: under voice **names** (`en/GB -> Rachel`), as **prose with no ids at
    all**, and with the four **correct ids in the backstory**. Enumerating the forms a table
    can take is a race nobody wins, so this does the inverse: it permits exactly two sentences
    - `SANCTIONED_VOICE_MENTIONS`, both of which say a voice is *not Taylor's to choose* - and
    then forbids the entire subject everywhere else in everything he is given.

    Four vocabularies, because a mapping can be written in any of them:

    | Signal | Catches |
    |---|---|
    | `voice`, `elevenlabs` | prose with no ids and no names - "for British interviews use Rachel" still has to say what Rachel is |
    | a 20-character base62 token | ids, correct or retired |
    | `xx/YY`, `xx_YY`, `xx-YY` | a locale table's left-hand column, whatever its right-hand column holds |
    | the stock voice names | a table keyed on names instead of ids |

    Stripping the sanctioned sentences by importing them, rather than by matching a substring,
    is what keeps this honest: editing either sentence cannot silently widen the hole, because
    the constant the prompt uses is the constant the test removes.

    **This is one file wide, and the other two files' worth is next door.** The two axes that
    are about a voice *fact* rather than about wording - an id, and a locale pairing - are
    applied to every discovery agent module and the crew factory by
    `tests/test_voice_catalogue.py::test_no_discovery_module_declares_a_voice_fact_in_a_
    string_it_can_send`. The vocabulary axis stays here deliberately: Avery legitimately says
    "voice interview" and carries `voice_config`, and Maya says "customer voice" throughout,
    so a copied vocabulary rule would fire on both. Nothing in *Taylor's* remit needs the
    word, which is what makes it sustainable for him alone.
    """
    import re

    from agents.discovery.interview_coordinator import SANCTIONED_VOICE_MENTIONS

    fields = _everything_taylor_is_given()
    for name, text in fields.items():
        for sanctioned in SANCTIONED_VOICE_MENTIONS:
            text = text.replace(sanctioned, " ")

        assert "voice" not in text.lower(), (
            f"{name} mentions a voice outside the two sanctioned sentences; a voice is "
            "resolved from project_agent_config when the session is created"
        )
        assert "elevenlabs" not in text.lower(), name
        assert not re.search(r"\b[A-Za-z0-9]{20}\b", text), (
            f"{name} carries something shaped like an ElevenLabs voice id"
        )
        assert not re.search(r"\b[a-z]{2}[/_-][A-Z]{2}\b", text), (
            f"{name} carries a locale pair - the left-hand column of the table that was "
            "removed, whatever its right-hand column now holds"
        )
        for stock in STOCK_VOICE_NAMES:
            assert not re.search(rf"\b{stock}\b", text), (
                f"{name} names the stock voice {stock!r}: a table keyed on names is the same "
                "declaration as one keyed on ids"
            )


def test_the_sanctioned_sentences_are_the_ones_actually_used():
    """`SANCTIONED_VOICE_MENTIONS` is the hole the guard above punches, so it must be real.

    If either constant drifted out of the prompt - reworded inline, or left declared and
    unused - the guard would still strip it, still pass, and be permitting a sentence nobody
    sends while the real wording went unchecked. That is the "test one layer away from where
    the property holds" shape, arriving inside the fix for it.
    """
    from agents.discovery.interview_coordinator import (
        VOICE_IS_NOT_IN_THE_OUTPUT,
        VOICE_IS_NOT_YOURS,
    )

    fields = _everything_taylor_is_given()
    assert VOICE_IS_NOT_YOURS in fields["description"]
    assert VOICE_IS_NOT_IN_THE_OUTPUT in fields["expected_output"]


def test_the_session_entry_example_carries_no_voice_config_key():
    """An entry the example contains is one the model has a reason to emit.

    Kept separate from the vocabulary guard because it is about the *example* specifically:
    the JSON spelling is what a model copies, and it would survive any rewording of the prose
    around it.
    """
    assert '"voice_config"' not in _everything_taylor_is_given()["description"]


def test_coordinator_task_tells_taylor_the_voice_is_not_his():
    """Deleting the table is half of it; the other half is saying so.

    Silence would leave a model that has planned interviews before free to invent a
    `voice_config` from its own training - which `InterviewSessionTool._create` would discard,
    but only after the tokens were spent and a reviewer had read a plan implying the model
    chose the voice.
    """
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "Do not include a voice_config" in kwargs["description"]


# ── Stakeholder Interviewer ───────────────────────────────────────────────────

def test_stakeholder_interviewer_task_reads_interview_plan():
    """Task description instructs agent to read interview_plan."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]
    assert "interview_transcripts" in kwargs["description"]


def test_interviewer_task_creates_sessions():
    """Task description instructs agent to use InterviewSessionTool with operation='create'."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "InterviewSessionTool" in kwargs["description"]
    assert "create" in kwargs["description"]


def test_interviewer_task_reads_interview_plan():
    """Task description reads interview_plan from SQLiteStateTool."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]


def test_interviewer_task_writes_interview_transcripts():
    """Task description writes interview_transcripts via SQLiteStateTool."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_transcripts" in kwargs["description"]


# ── Synthesis Analyst ─────────────────────────────────────────────────────────

def test_synthesis_analyst_task_writes_all_three_keys():
    """Task description instructs agent to write activity_insights, requirements, themes.

    `value_levers` was the third until the crews were re-sequenced. Morgan writes those and
    now runs first, so a write here would land on top of the levers Maya designed the
    instruments against and a reviewer approved.
    """
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    for key in ("activity_insights", "requirements", "themes"):
        assert key in kwargs["description"], f"Key '{key}' missing from task description"
    assert "value_levers" not in kwargs["description"]


def test_synthesis_analyst_task_reads_the_answer_store():
    """He reads answers, not the transcript blob.

    This asserted on `interview_transcripts` until answers became addressable. A blob cannot
    be filtered by discipline or by who the speaker is to this organisation, and the corpus
    is too large to read whole - both of which are the point of the tagged store.
    """
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "collection='interviews'" in kwargs["description"]
    assert "interview_transcripts" not in kwargs["description"]
