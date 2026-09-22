# api/services/script_assertion_validation.py
"""Does any spoken line in a scripts artefact tell the interviewee what they said?

This guards the layer that broke. The 4 September 2026 withdrawal removed
`synthesis_check.synthesis_prompt` from the *runtime*, and
`ui/src/__tests__/synthesisWithdrawn.test.ts` holds it out - honestly declaring, in its own
header, that it cannot see "a re-implementation under a different name". That is exactly what
happened next. Maya wrote the synthesis a second time as an ordinary section question, in the
artefact, where nothing looked at it: on 17 September an internal auditor was read a summary of
her own testimony composed weeks earlier, and answered "I think you have characterised that
pretty well actually". The guard was one layer away from the property.

So this one is about the artefact, and it is a pure function over given data - no filesystem, no
database, no project - so every property it holds can be driven directly, in both directions.
`agents/tools/sqlite_state.py` runs it on every `interview_scripts` write.

WHY IT WARNS RATHER THAN REFUSES
A refusal loses the work the run just did, and Maya's artefact is ~400KB written across batched
writes. The warning is recorded against the run and read back into her next prompt by
`_fetch_validation_warnings`, which is the same route `incomplete_coverage` already takes.

WHAT COUNTS, AND WHY THE RULE IS WHAT IT IS
The defect is the interviewer *attributing content to the interviewee* before they have supplied
it. Two shapes carry that, and either alone is a finding:

  1. An assertion of what was understood - "here's how I see", "to recap what I heard",
     "here is my summary of your assessment".
  2. A request to confirm one - "does that match your assessment?", "did I capture that
     accurately?". These presuppose an assertion was made, so they are evidence of one even
     when the assertion itself is phrased in a way this file has not seen.

A third shape is DELIBERATELY NOT a trigger on its own: a retrospective prefix such as "based on
our conversation" or "based on what you've told me". Every real instance carries a marker from
(1) or (2) as well - all seven perspective templates and the live SC-013 text were checked - so
including it buys nothing and costs a false positive on "Based on our conversation, what would
you prioritise?", which asserts nothing and is a perfectly good closing question. A guard that
fires on good questions gets switched off.

This is a heuristic over natural language and says so. It cannot catch a summary phrased with no
marker at all. It is not the only control: the prompt no longer asks for one, which is the
repair, and this is the thing that notices if that stops being true.
"""

_MAX_NAMED = 8

# The interviewer states what they understood. Written weeks before the interview, every one of
# these is a claim about a conversation that has not happened.
_ASSERTS_A_SUMMARY = (
    "here's how i see",
    "here is how i see",
    "here's my summary",
    "here is my summary",
    "here's what i heard",
    "here is what i heard",
    "here's the strategic picture",
    "here is the strategic picture",
    "here's my read",
    "here is my read",
    "to recap what i heard",
    "to recap what you",
    "let me offer a synthesis",
    "offer you a synthesis",
    "if i understand correctly",
    "if i've understood correctly",
    "if i have understood correctly",
    "so from your perspective",
    "what i'm hearing is",
    "what i am hearing is",
    "my characterisation",
    "my picture of",
)

# The interviewer asks the interviewee to confirm a summary. These presuppose one was offered,
# so they are evidence of an assertion even where the assertion itself is phrased unusually.
_SEEKS_CONFIRMATION_OF_ONE = (
    "does that match your assessment",
    "does that capture it",
    "did i capture that",
    "do those observations align",
    "does that align with your",
    "am i mischaracterising",
    "or mischaracterising",
    "correct me where i",
    "tell me where i'm wrong",
    "tell me where i am wrong",
    "where does my picture differ",
    "where did i get the picture wrong",
    "where does my characterisation differ",
)

_MARKERS = _ASSERTS_A_SUMMARY + _SEEKS_CONFIRMATION_OF_ONE

# A false promise about where the interviewee's words go. SC-013 told an internal auditor hers
# would reach the board "unfiltered"; they are synthesised by `synthesis_analyst` before anything
# is reported, so it was untrue, and it was the opposite of the assurance somebody describing
# control weaknesses in their own organisation needs.
#
# "directly" and "unchanged" are matched only where they are bound to a destination, because both
# are ordinary words - "your feedback goes directly into the improvement plan" promises nothing
# false about attribution.
# Phrases that are a promise about handling wherever they appear. Each names the destination
# or the interviewee's own words, so none of them has an innocent reading in an instrument.
_FALSE_HANDLING_PROMISES = (
    # "into the board" reads as a claim about where the words END UP, where "to the board"
    # and "straight to the board" are also how one asks about a reporting line - so those two
    # moved to _AMBIGUOUS_HANDLING_WORDS below and are matched in the promise fields only.
    "directly into the board",
    "unchanged to the board",
    "without being edited",
    "exactly as you said",
)

# Words that mean a false promise **in the welcome or the closing** and mean something
# ordinary in a question. Found live: SC-013 v38 asks "are they getting the unfiltered
# picture or a management narrative?" - a question about what the *board* sees, which is a
# perfectly good thing to ask an auditor and nothing to do with what happens to her answers.
#
# Matching it everywhere made the warner cry wolf on every write of a correct script, and
# this one runs on the write path rather than only in tests: the noise would have reached
# Maya on every run, inviting her to "fix" a question that was right. A promise about
# handling is made where handling is described, which is why the two real instances were
# both in `closing_message`.
_AMBIGUOUS_HANDLING_WORDS = (
    "unfiltered", "verbatim", "word for word",
    # Same argument, one phrase over, and latent rather than live. "Does this go straight to
    # the board, or through management?" is the identical legitimate audit question as the
    # `unfiltered` case above - a question about what the BOARD sees, not a promise about what
    # happens to the interviewee's answers. Restricted here rather than deleted, because in a
    # welcome or a closing both really are promises about handling.
    "directly to the board", "straight to the board",
)
_PROMISE_FIELDS = ("welcome_message", "closing_message")

# Of `synthesis_check`, the runtime speaks exactly ONE field, and this is an allow-list rather
# than a list of the withdrawn ones on purpose.
#
# `_spoken_strings` collected the whole of `synthesis_check`, and the cost was measured on the
# live artefact: `interview_scripts_v38.json` yielded 67 findings across 26 of 86 scripts, all
# of them in `synthesis_check.synthesis_prompt` (44) and `synthesis_check.response_probes`
# (23). `_merge_with_current` accumulates and the owner has decided those scripts stay, so this
# warner fired on every write for ever at measure 26 - verbatim the condition
# `script_duration_validation`'s header argues is unacceptable, from a sibling on the same
# output type. A dismissal could not settle it either: `SKEW_RERAISE_DELTA` is 0.10 and the
# measure is a count, so any change of one re-raises.
#
# None of the 67 was in a field a participant hears. `VoiceInterview.tsx` speaks
# `synthesis_check.peer_referral` and nothing else: `synthesis_prompt`, `forward_roadmap`,
# `portfolio_options` and `sponsorship_check` were withdrawn on 4 September 2026 and are
# commented out there; `response_probes` and `closing_invitation` were never wired at all,
# though Maya's prompt describes them as spoken. This module's scope is the spoken ones - "a
# marker in a field nobody speaks is not this guard's finding" - so the cut follows what the
# runtime says, not what the schema offers.
#
# Excluding the four withdrawn fields alone is NOT enough, measured rather than assumed: v38
# still yields 23 findings across 23 scripts, because `response_probes.if_defensive` carries
# "Where does my picture differ from yours". With the allow-list, v38 yields zero and v37 still
# catches all three live defects - SC-013's Q10.1 "let me offer a synthesis", its welcome's
# "unfiltered", and its closing's "directly into the board".
#
# The hazard an allow-list carries is a NEW spoken field going unwatched, which is precisely
# the "re-implementation under a different name" this module's header exists for. That is why
# it is held against the runtime rather than merely commented:
# tests/test_script_assertion_validation.py::test_every_synthesis_field_the_interview_speaks_is_watched
_SPOKEN_SYNTHESIS_FIELDS = ("peer_referral",)


def _spoken_strings(script: object) -> list[tuple[str, str]]:
    """Every string in one script that is SPOKEN TO the interviewee, as (where, text).

    Spoken only, deliberately. `probing_instructions` and `evasion_signals` are notes to the
    interviewer and legitimately talk about summarising; `research_brief` and `study_objectives`
    are for the consultant. A pre-written summary is dangerous because a participant hears it,
    so a marker in a field nobody speaks is not this guard's finding.

    `maturity_rating.probe_on_mismatch` is excluded for a different reason: "you described [X]
    but rated it [N]" refers to something actually said, and it is filled at run time rather
    than composed in advance, so it is the one retrospective line in the schema that can be
    true.

    Of `synthesis_check`, only `_SPOKEN_SYNTHESIS_FIELDS` is collected - see the reasoning
    beside that constant. Collecting the whole block contradicted this docstring's own first
    sentence and cost 67 standing findings on the live artefact, in fields nobody hears.
    """
    if not isinstance(script, dict):
        return []

    found: list[tuple[str, str]] = []

    def collect(where: str, value: object) -> None:
        if isinstance(value, str):
            found.append((where, value))
        elif isinstance(value, dict):
            for k, v in value.items():
                collect(f"{where}.{k}", v)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                collect(f"{where}[{i}]", v)

    collect("welcome_message", script.get("welcome_message"))
    collect("framing_block", script.get("framing_block"))
    synthesis = script.get("synthesis_check")
    if isinstance(synthesis, dict):
        for field in _SPOKEN_SYNTHESIS_FIELDS:
            collect(f"synthesis_check.{field}", synthesis.get(field))
    collect("closing_message", script.get("closing_message"))

    sections = script.get("sections")
    if isinstance(sections, list):
        for si, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            questions = section.get("questions")
            if not isinstance(questions, list):
                continue
            for qi, question in enumerate(questions):
                if not isinstance(question, dict):
                    continue
                at = question.get("id") or f"sections[{si}].questions[{qi}]"
                collect(f"{at}.text", question.get("text"))
                collect(f"{at}.follow_up_branches", question.get("follow_up_branches"))

    return found


def _hits(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = " ".join(text.lower().split())
    return [m for m in markers if m in lowered]


def find_asserted_summaries(scripts: dict) -> list[tuple[str, str, str]]:
    """Every spoken line that tells the interviewee what they said, as (script, where, marker).

    The raw finder, separate from the warning it becomes, so it can be driven directly and so a
    caller that wants the list rather than the prose can have it.
    """
    if not isinstance(scripts, dict):
        return []
    out: list[tuple[str, str, str]] = []
    for script_id, script in scripts.items():
        for where, text in _spoken_strings(script):
            for marker in _hits(text, _MARKERS):
                out.append((str(script_id), where, marker))
    return out


def find_false_handling_promises(scripts: dict) -> list[tuple[str, str, str]]:
    """Every spoken line promising the interviewee's words travel unanalysed."""
    if not isinstance(scripts, dict):
        return []
    out: list[tuple[str, str, str]] = []
    for script_id, script in scripts.items():
        for where, text in _spoken_strings(script):
            markers = list(_hits(text, _FALSE_HANDLING_PROMISES))
            if where.split(".")[0] in _PROMISE_FIELDS:
                markers += _hits(text, _AMBIGUOUS_HANDLING_WORDS)
            for marker in markers:
                out.append((str(script_id), where, marker))
    return out


def _named(findings: list[tuple[str, str, str]]) -> str:
    shown = [f"{s} at {w} ('{m}')" for s, w, m in findings[:_MAX_NAMED]]
    named = "; ".join(shown)
    if len(findings) > _MAX_NAMED:
        named += f"; and {len(findings) - _MAX_NAMED} more"
    return named


def validate_script_assertions(scripts: dict) -> list[dict]:
    """Zero warnings when no spoken line asserts a summary or a false promise.

    At most one warning per code rather than one per line, matching `validate_node_coverage`:
    one defective template produces a finding in every script it wrote, and the actionable fact
    is the set.
    """
    warnings: list[dict] = []

    summaries = find_asserted_summaries(scripts)
    if summaries:
        affected = {s for s, _, _ in summaries}
        warnings.append({
            "subject": None,
            "code": "prewritten_synthesis",
            "measure": len(affected),
            "detail": (
                f"{len(summaries)} spoken line(s) across {len(affected)} script(s) tell the "
                f"interviewee what they said, or ask them to confirm a summary, before they "
                f"have said it. Written in advance, such a line is a guess read to a real "
                f"person as their own testimony, and their agreement with it lands in the "
                f"transcript as evidence they never gave. Ask the interviewee to summarise "
                f"instead. Found: {_named(summaries)}."
            ),
        })

    promises = find_false_handling_promises(scripts)
    if promises:
        affected = {s for s, _, _ in promises}
        warnings.append({
            "subject": None,
            "code": "false_handling_promise",
            "measure": len(affected),
            "detail": (
                f"{len(promises)} spoken line(s) across {len(affected)} script(s) promise the "
                f"interviewee's words travel unfiltered, verbatim or unchanged. They do not - "
                f"answers are analysed and synthesised before anything is reported - and the "
                f"promise is the opposite of the assurance somebody describing a weakness in "
                f"their own organisation needs. Say answers are combined with other interviews "
                f"and analysed, and that they will not be quoted by name without being asked "
                f"first. Found: {_named(promises)}."
            ),
        })

    return warnings
