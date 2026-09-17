# api/services/script_duration_validation.py
"""Does a script's welcome tell the interviewee how long it will actually take?

**Two independent declarations of one fact, which is the defect class this codebase records
more than any other.** SC-014's welcome says "about 45 minutes"; the timer the participant
watches says 55, which is `scriptTimeboxMinutes` summing the nine sections' own
`target_minutes`. Measured across the live artefact, **83 of 84 scripts disagree with their own
section budget**. Nothing reconciled them because the prose was typed and the sections were
designed, and neither ever looked at the other.

The number the welcome should carry is not the section sum either. **The review step is real
time a participant spends and nothing has ever told them about it** - they finish the last
question and are then asked to read and correct every answer they gave. So the honest statement
is the section budget *plus* an explicit review allowance, and it has to be derived or it drifts
again on the next script.

WHY IT WARNS RATHER THAN REFUSES
The same reason its sibling `script_assertion_validation` does: a refusal loses the work the run
just did, and the artefact is ~400KB written across batched writes. The warning is recorded
against the run and read back into Maya's next prompt by `_fetch_validation_warnings`.

WHY IT JUDGES THE BATCH AND NOT THE ARTEFACT - and this is the half that had to be designed
rather than copied. `SQLiteStateTool` merges before validating, so every warner on
`interview_scripts` is handed the whole accumulated artefact. A duration warner given that would
report all 83 pre-existing disagreements on **every write, for ever** - and the project owner
has decided the 84 stay as they are rather than spend credit regenerating them. A warner that
fires on work nobody intends to do is a warner that gets switched off, which would take its
siblings with it. So this one is handed the **pre-merge batch**: the scripts this write actually
produced, which are the only ones Maya can still act on.
"""
from __future__ import annotations

import re

# What the participant spends after the last question, reading and correcting their answers.
# Declared here and interpolated into Maya's prompt, so the number she is told to state and the
# number this checks against are one declaration rather than two.
TRANSCRIPT_REVIEW_MINUTES = 10

# How far a stated duration may sit from the derived one before it is worth saying anything.
# Not zero: "about 50 minutes" for a 52-minute script is a human rounding a number, not a
# disagreement, and a guard that fires on good prose gets switched off. Five minutes is inside
# the rounding people actually do and well outside the 10-minute error the live scripts carry.
DURATION_TOLERANCE_MINUTES = 5

# "45 minutes", "45 mins", "about 45 min", "45-55 minutes", "45 to 55 minutes". The second
# number of a range is taken as the claim, because that is the one a participant plans around.
_DURATION = re.compile(
    r"(\d{1,3})\s*(?:(?:-|–|—|\s+to\s+)\s*(\d{1,3}))?\s*(?:minute|min\b|mins\b)",
    re.IGNORECASE,
)

# An hour, spelled the way a welcome spells it. Kept separate because the unit is different and
# because "an hour" carries no digits for the pattern above to find.
_HOURS = re.compile(r"\b(?:(\d(?:\.\d)?)\s*hours?|an?\s+hour)\b", re.IGNORECASE)

_MAX_NAMED = 6


def script_timebox_minutes(script: object) -> int:
    """The sum of a script's section budgets, or 0 when any section fails to declare one.

    **0 rather than a partial sum**, matching `scriptTimeboxMinutes` in `VoiceInterview.tsx`
    exactly - the timer shows nothing rather than a total it knows is short, and a guard that
    used a partial sum here would accuse a script of understating a duration when the shortfall
    was its own.
    """
    if not isinstance(script, dict):
        return 0
    sections = script.get("sections")
    if not isinstance(sections, list) or not sections:
        return 0
    total = 0
    for section in sections:
        if not isinstance(section, dict):
            return 0
        minutes = section.get("target_minutes")
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
            return 0
        total += int(minutes)
    return total


def expected_duration_minutes(script: object) -> int:
    """What the welcome should say: the section budget plus the review allowance.

    0 when the sections do not declare a budget, which is this module's "nothing to say".
    """
    sections = script_timebox_minutes(script)
    return sections + TRANSCRIPT_REVIEW_MINUTES if sections else 0


def stated_duration_minutes(text: str) -> int | None:
    """The duration a welcome claims, in minutes, or `None` when it claims none.

    The **largest** claim in the text wins. A welcome that says "about 45 minutes, and I will
    take 5 minutes at the start to explain" is making one promise about the whole and one about
    a part, and the participant plans around the whole; taking the first match would read the
    part as the promise on any welcome that happens to mention a smaller number first.
    """
    if not isinstance(text, str) or not text:
        return None
    found: list[int] = []
    for match in _DURATION.finditer(text):
        upper, lower = match.group(2), match.group(1)
        found.append(int(upper or lower))
    for match in _HOURS.finditer(text):
        hours = float(match.group(1)) if match.group(1) else 1.0
        found.append(int(hours * 60))
    return max(found) if found else None


def find_duration_disagreements(scripts: dict) -> list[tuple[str, int, int]]:
    """Every script whose welcome disagrees with its own sections, as (script, stated, expected).

    Silent about a script that states no duration at all: that is a different finding - and a
    welcome saying nothing about length is not *wrong* about it, which is the distinction
    between a warning worth reading and noise.
    """
    if not isinstance(scripts, dict):
        return []
    out: list[tuple[str, int, int]] = []
    for script_id, script in scripts.items():
        if not isinstance(script, dict):
            continue
        expected = expected_duration_minutes(script)
        if not expected:
            continue
        stated = stated_duration_minutes(script.get("welcome_message", ""))
        if stated is None:
            continue
        if abs(stated - expected) > DURATION_TOLERANCE_MINUTES:
            out.append((str(script_id), stated, expected))
    return out


def validate_script_durations(scripts: dict) -> list[dict]:
    """Zero warnings when every welcome's stated duration matches its own sections.

    One warning for the set rather than one per script, matching both sibling validators: a
    prompt that states the duration wrongly states it wrongly everywhere, and the actionable
    fact is the set.
    """
    findings = find_duration_disagreements(scripts)
    if not findings:
        return []
    shown = [
        f"{s} says {stated} min, sections total {expected - TRANSCRIPT_REVIEW_MINUTES} "
        f"+ {TRANSCRIPT_REVIEW_MINUTES} review = {expected}"
        for s, stated, expected in findings[:_MAX_NAMED]
    ]
    named = "; ".join(shown)
    if len(findings) > _MAX_NAMED:
        named += f"; and {len(findings) - _MAX_NAMED} more"
    return [{
        "subject": None,
        "code": "stated_duration_disagrees",
        "measure": len(findings),
        "detail": (
            f"{len(findings)} script(s) tell the interviewee a duration that disagrees with "
            f"their own section budget. The participant watches a timer built from "
            f"target_minutes, so a welcome that understates it is contradicted on screen within "
            f"the hour - and the review step afterwards, where they read and correct every "
            f"answer, is real time nothing has ever told them about. State the sum of the "
            f"section target_minutes plus {TRANSCRIPT_REVIEW_MINUTES} minutes to review the "
            f"transcript, derived from the sections rather than typed. Found: {named}."
        ),
    }]
