# api/services/theme_evidence_validation.py
"""Whether a theme's evidence says who it came from, in the fields that mean those things.

Casey's task asks each evidence entry for `answer_id`, `stakeholder_id` and `relationship`.
The first makes a claim checkable; the second names the person; the third names the role their
voice speaks from - `1.F` for the frontline, `0.A` for internal audit.

**The third field exists because the agent was right and the schema was wrong.** The first real
themes artefact carried the relationship in `stakeholder_id` on **68 of 68** evidence rows -
`"1.F"` where the row's own stakeholder is `10`. That is not a slip: in a themes document, *the
frontline said this and audit independently agreed* is the argument, while *stakeholder 10 said
this* is not, and the relationship anonymises by default. So the field was added rather than the
agent corrected, and this validator exists because the same run is the proof that prose in a
prompt does not hold a schema on its own.

Pure over given data - the answers' own ids are passed in rather than read here - so a hostile
case can be driven directly. A validator that can only run against a live project is one that
cannot be asked what it saw.

THE SHAPE IS THE HOUSE SHAPE, AND THAT IS NOT COSMETIC
`record_validation_warnings_sync` reads `subject`, `code`, `measure` and `detail`. This module
first emitted `{code, severity, message}`, and the consequence was not a mislabelled row: the
recorder's `w["detail"]` raised `KeyError`, the per-warner `except Exception: continue` in
`agents/tools/sqlite_state.py` swallowed it, and because the raise came before `commit` the
`complete=True` clearing did not run either. **The warner worked only when it found nothing** -
a clean themes artefact recorded nothing and cleared correctly, and a defective one recorded
nothing at all. Ten tests over the pure function below were green throughout, because none of
them went near the recorder.

`severity` is gone rather than kept alongside: nothing reads it, and a key nothing reads is a
claim rather than data.

`measure` is a COUNT of defective entries, not a fraction. `SKEW_RERAISE_DELTA` is 0.10, so a
dismissal expires on any change of one - which is the right direction here, since a changed
evidence set is a different claim about different rows, unlike the skew fraction that constant
was calibrated for.
"""
from __future__ import annotations

_MAX_NAMED = 5


def find_evidence_defects(
    themes: object, stakeholder_by_answer: dict[int, int]
) -> list[tuple[str, str, str]]:
    """Every evidence entry that misstates its source, as (theme_id, code, detail)."""
    out: list[tuple[str, str, str]] = []
    items = themes if isinstance(themes, list) else None
    if items is None and isinstance(themes, dict):
        # Tolerates {"themes": [...]}, which is how an agent sometimes wraps an array.
        for value in themes.values():
            if isinstance(value, list):
                items = value
                break
    if not items:
        return out

    for theme in items:
        if not isinstance(theme, dict):
            continue
        theme_id = str(theme.get("id") or "?")
        evidence = theme.get("evidence")
        if not isinstance(evidence, list):
            continue
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            answer_id = entry.get("answer_id")
            claimed = entry.get("stakeholder_id")
            actual = stakeholder_by_answer.get(answer_id) if isinstance(answer_id, int) else None

            if not isinstance(answer_id, int) or (stakeholder_by_answer and actual is None):
                out.append((theme_id, "unknown_answer", f"answer_id {answer_id!r}"))
                continue
            # `True` is an int in Python and a stakeholder id is not a boolean.
            if isinstance(claimed, bool) or not isinstance(claimed, int):
                out.append((theme_id, "stakeholder_id_not_an_integer", repr(claimed)))
            elif actual is not None and claimed != actual:
                out.append(
                    (theme_id, "stakeholder_id_disagrees", f"{claimed} for answer {answer_id}, "
                     f"whose own stakeholder is {actual}")
                )
            if not str(entry.get("relationship") or "").strip():
                out.append((theme_id, "no_relationship", f"answer {answer_id}"))
    return out


def validate_theme_evidence(
    themes: object, stakeholder_by_answer: dict[int, int]
) -> list[dict]:
    """At most one warning per code, in the shape `record_validation_warnings_sync` stores.

    One misread instruction produces a defect in every evidence row it wrote, and the
    actionable fact is the set rather than the roll-call - 68 identical findings is a warner
    somebody turns off, taking its siblings with it. `subject` is therefore None, as it is on
    every other set-level finding in this family.
    """
    defects = find_evidence_defects(themes, stakeholder_by_answer)
    if not defects:
        return []

    _MESSAGES = {
        "unknown_answer": (
            "cites an answer_id that is not in this project's interview answers. Every quote "
            "must come from a row that exists - an invented id makes the claim uncheckable"
        ),
        "stakeholder_id_not_an_integer": (
            "gives a stakeholder_id that is not an integer. The role node a voice speaks from "
            "belongs in `relationship`; `stakeholder_id` is the integer id on the answer's own "
            "row"
        ),
        "stakeholder_id_disagrees": (
            "gives a stakeholder_id that is not the one on the answer's own row"
        ),
        "no_relationship": (
            "gives no `relationship`. A reader needs to know the frontline said it and audit "
            "agreed; the person's integer id does not tell them that"
        ),
    }

    warnings: list[dict] = []
    for code, message in _MESSAGES.items():
        hits = [d for d in defects if d[1] == code]
        if not hits:
            continue
        shown = "; ".join(f"{t} ({detail})" for t, _, detail in hits[:_MAX_NAMED])
        if len(hits) > _MAX_NAMED:
            shown += f"; and {len(hits) - _MAX_NAMED} more"
        warnings.append({
            "subject": None,
            "code": code,
            "measure": len(hits),
            "detail": (
                f"{len(hits)} evidence entr{'y' if len(hits) == 1 else 'ies'} {message}: "
                f"{shown}"
            ),
        })
    return warnings
