# tests/test_script_duration_validation.py
"""A script's welcome must agree with its own sections about how long it takes.

SC-014's welcome says "about 45 minutes". The timer the participant watches says 55, summed from
the nine sections' own `target_minutes`. Across the live artefact 83 of 84 scripts disagreed with
their own budget - two declarations of one fact, neither looking at the other.

Every rule here is a pure function over given data, driven directly and in both directions, which
is the repair this repository prescribes every time a guard's reach has turned out to be
described rather than established.
"""
import pytest

from api.services.script_duration_validation import (
    DURATION_TOLERANCE_MINUTES,
    TRANSCRIPT_REVIEW_MINUTES,
    expected_duration_minutes,
    find_duration_disagreements,
    script_timebox_minutes,
    stated_duration_minutes,
    validate_script_durations,
)

# SC-014's real section budget, which is the case that started this.
SC014_MINUTES = [7, 7, 7, 6, 7, 6, 6, 5, 4]


def _script(welcome: str, minutes=SC014_MINUTES) -> dict:
    return {
        "welcome_message": welcome,
        "sections": [{"section_id": f"S{i}", "target_minutes": m}
                     for i, m in enumerate(minutes, 1)],
    }


def test_the_budget_is_the_sum_of_the_sections():
    assert script_timebox_minutes(_script("")) == 55


@pytest.mark.parametrize("sections", [
    [{"section_id": "S1", "target_minutes": 8}, {"section_id": "S2"}],   # one undeclared
    [{"section_id": "S1", "target_minutes": 0}],                          # zero is not a budget
    [{"section_id": "S1", "target_minutes": "8"}],                        # a string is not one
    [{"section_id": "S1", "target_minutes": True}],                       # nor is a bool
    [],
])
def test_a_budget_is_nothing_rather_than_a_partial_sum(sections):
    """0, exactly as `scriptTimeboxMinutes` in `VoiceInterview.tsx` answers 0.

    A partial sum would accuse a script of understating its duration when the shortfall was the
    guard's own arithmetic - a warning that is wrong about the thing it is warning about.
    """
    assert script_timebox_minutes({"sections": sections}) == 0


def test_the_expected_duration_includes_the_review_step():
    """The half nothing had ever told a participant about.

    Named here rather than left implicit in an arithmetic assertion, so removing the allowance
    fails rather than shifting a number this test would have accepted either way.
    """
    assert expected_duration_minutes(_script("")) == 55 + TRANSCRIPT_REVIEW_MINUTES
    assert TRANSCRIPT_REVIEW_MINUTES > 0


@pytest.mark.parametrize("text, expected", [
    ("This will take about 45 minutes.", 45),
    ("about 45 mins", 45),
    ("roughly 45 min", 45),
    # A range: the upper bound is what a participant plans around.
    ("This takes 45-55 minutes.", 55),
    ("This takes 45 to 55 minutes.", 55),
    ("This takes 45–55 minutes.", 55),
    ("It will take about an hour.", 60),
    ("It will take 1.5 hours.", 90),
    # The largest claim wins: a welcome promising the whole and describing a part must not be
    # read as promising the part.
    ("I will take 5 minutes to explain, then about 45 minutes of questions.", 45),
])
def test_the_duration_a_welcome_claims_is_read_from_it(text, expected):
    assert stated_duration_minutes(text) == expected


@pytest.mark.parametrize("text", ["", "Thank you for your time.", None, "Section 3 of 9."])
def test_a_welcome_claiming_no_duration_claims_none(text):
    """Silence is not a wrong number, and must not be reported as one."""
    assert stated_duration_minutes(text) is None


def test_the_live_defect_is_found():
    """SC-014 exactly: 45 stated, 55 of sections, 65 once the review step is counted."""
    found = find_duration_disagreements({"SC-014": _script("This will take about 45 minutes.")})
    assert found == [("SC-014", 45, 65)]


def test_a_welcome_that_states_the_derived_total_is_not_a_finding():
    """The control. Without it a guard that fired on everything would pass every test above."""
    welcome = "This will take about 65 minutes, including 10 minutes to read through your answers."
    assert find_duration_disagreements({"SC-014": _script(welcome)}) == []


def test_rounding_is_not_disagreement():
    """A guard that fires on good prose gets switched off, and takes its siblings with it."""
    within = 65 - DURATION_TOLERANCE_MINUTES
    assert find_duration_disagreements({"SC": _script(f"About {within} minutes.")}) == []
    beyond = 65 - DURATION_TOLERANCE_MINUTES - 1
    assert find_duration_disagreements({"SC": _script(f"About {beyond} minutes.")}) != []


def test_a_script_with_no_section_budget_is_not_judged():
    """Nothing to compare against. Reporting it would be the partial-sum defect by another route."""
    script = {"welcome_message": "About 45 minutes.", "sections": [{"section_id": "S1"}]}
    assert find_duration_disagreements({"SC": script}) == []


def test_a_welcome_that_says_nothing_about_length_is_not_a_finding():
    assert find_duration_disagreements({"SC": _script("Thank you for making the time.")}) == []


def test_the_warning_names_the_scripts_and_the_arithmetic():
    """An agent asked to fix a number needs the number, and where the number came from."""
    warnings = validate_script_durations({"SC-014": _script("About 45 minutes.")})
    assert len(warnings) == 1
    assert warnings[0]["code"] == "stated_duration_disagrees"
    assert warnings[0]["measure"] == 1
    detail = warnings[0]["detail"]
    assert "SC-014" in detail and "45" in detail and "65" in detail
    assert str(TRANSCRIPT_REVIEW_MINUTES) in detail


def test_nothing_is_warned_about_when_every_script_agrees():
    """`complete=True` means an empty list clears the warning, so this is the clearing path."""
    welcome = "About 65 minutes, including 10 minutes to review."
    assert validate_script_durations({"A": _script(welcome), "B": _script(welcome)}) == []


@pytest.mark.parametrize("scripts", [None, [], "", {"SC": "not a script"}, {"SC": None}])
def test_a_shape_it_does_not_recognise_is_not_an_exception(scripts):
    """A warner that raises is caught and dropped by `SQLiteStateTool`, so it would go silent
    rather than loudly - which is the worst available direction for a guard."""
    assert validate_script_durations(scripts) == []


def test_the_warner_judges_the_batch_and_not_the_accumulated_artefact():
    """**The property that decides whether this guard survives contact with the deployment.**

    `SQLiteStateTool` merges before validating, so every warner on `interview_scripts` is handed
    the whole accumulated artefact. 83 of the 84 scripts already stored disagree with their own
    budget, and the owner has decided they stay as they are rather than spend credit
    regenerating them. A duration warner given the merged artefact would therefore report 83
    findings on **every write, for ever** - noise that gets the warner switched off, and its two
    siblings with it.

    So `_warn_script_durations` reads its third argument. Driven here rather than described:
    the merged artefact is full of pre-existing disagreements and the batch is clean, and the
    warner must answer nothing.
    """
    from agents.tools.sqlite_state import _warn_script_durations

    legacy = {f"SC-{n:03d}": _script("About 45 minutes.") for n in range(83)}
    clean_welcome = "About 65 minutes, including 10 minutes to read through your answers."
    batch = {"SC-999": _script(clean_welcome)}
    merged = {**legacy, **batch}

    assert _warn_script_durations(merged, "sp-gs-am", batch) == []
    # And it is not simply silent: the same batch, written wrongly, is reported.
    wrong = {"SC-999": _script("About 45 minutes.")}
    assert _warn_script_durations({**legacy, **wrong}, "sp-gs-am", wrong) != []


def test_the_duration_warner_is_registered_on_the_write_path():
    """A guard nothing calls is a guard that does not exist - this repository's own recurring
    finding, recorded against a Deepgram door that was mounted and dark for four months."""
    from agents.tools.sqlite_state import _WARNERS, _warn_script_durations

    registered = dict((warner, source) for source, warner in _WARNERS["interview_scripts"])
    assert _warn_script_durations in registered
    assert registered[_warn_script_durations] == "script_duration"


def test_maya_is_told_the_same_review_allowance_this_guard_checks():
    """One declaration, not two.

    The instruction Maya follows and the arithmetic this module checks are the same fact, and a
    prompt carrying its own hardcoded `10` is exactly the shape of defect the instruction exists
    to fix - one layer up, and invisible until somebody changes one of them.
    """
    import inspect

    import agents.discovery.interaction_designer as designer

    src = inspect.getsource(designer)
    assert "HOW LONG IT TAKES" in src, "the duration instruction is not in the prompt"
    # Interpolated rather than typed: the constant is imported and formatted in.
    assert "from api.services.script_duration_validation import TRANSCRIPT_REVIEW_MINUTES" in src
    assert "{TRANSCRIPT_REVIEW_MINUTES}" in src
    # And it tells her to derive it from the sections rather than reach for a round number.
    assert "target_minutes" in src and "DERIVED, never typed" in src
