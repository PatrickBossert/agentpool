# api/services/interview_script_model.py
"""Interview script structure, anchoring, and identity - pure, no I/O.

Mirrors api/services/value_chain_model.py: the caller loads the registry, this module only
compares. Every function returns all problems as readable sentences rather than raising on
the first, so a writer sees everything wrong in one pass.
"""
from __future__ import annotations

from api.services.value_chain_model import ENTITY_ID

# Who the interviewee is to this organisation. Without it, an auditor's script and a board
# member's script both anchor to the entity and become indistinguishable - and Casey needs to
# know that six answers about governance came from one regulator and five internal managers,
# not from eleven internal managers.
RELATIONSHIPS = frozenset({"internal", "customer", "regulator", "supplier", "partner"})

LEVELS = frozenset({"L0", "L1", "L2", "L3", "C", "A", "F", "S"})

QUESTION_INTENTS = frozenset({"context", "evidence", "maturity", "challenge", "opportunity"})

# Whether the question named the thing it asked about. A separate axis from intent, and what
# makes a count readable: "six stakeholders raised data quality" means something entirely
# different if five of them were handed the phrase.
ELICITATIONS = frozenset({"unprompted", "prompted"})

# The starting vertical axis. Per project, because a discipline that matters in one engagement
# does not in another - hard-coding one list would make the tag wrong rather than closed.
DEFAULT_DISCIPLINES = (
    "governance", "data", "technology", "process", "people",
    "commercial", "assurance", "finance", "sustainability",
)

_TAG_FIELDS = ("discipline", "question_intent", "elicitation")


def resolve_tags(section: dict, question: dict) -> dict:
    """A question's three tags, inherited from its section unless it overrides one.

    Each field falls back independently. Inheriting all three only when the question restates
    none of them would let a single override silently blank the other two.
    """
    return {field: question.get(field, section.get(field)) for field in _TAG_FIELDS}


def question_id(script_id: str, section_id: str, question_no: int) -> str:
    """A question's global address.

    Unique by construction rather than by luck of the sample: the old `Q1.1` was
    section-relative, so every one of the 17 L2 scripts emitted the same ids.
    """
    return f"{script_id}.{section_id}.Q{question_no}"


def validate_scripts(
    scripts: dict, disciplines: tuple[str, ...] = DEFAULT_DISCIPLINES
) -> list[str]:
    """Every way this script set is unciteable, unanchored, or untagged."""
    problems: list[str] = []
    seen_script_ids: set[str] = set()

    for key, script in scripts.items():
        script_id = script.get("script_id")
        label = script_id or key

        if not script_id:
            problems.append(f"script {key!r} has no script_id")
        elif script_id in seen_script_ids:
            problems.append(
                f"script_id {script_id} is used twice - ids are assigned in order and never "
                "reused, because stored citations resolve through them"
            )
        else:
            seen_script_ids.add(script_id)

        if not script.get("node_id"):
            problems.append(
                f"script {label} has no node_id - anchor it to a value chain node, or to "
                f"{ENTITY_ID!r} when it concerns the organisation as a whole"
            )
        if script.get("level") not in LEVELS:
            problems.append(
                f"script {label} has level {script.get('level')!r}, which is not one of "
                f"{sorted(LEVELS)}"
            )
        if script.get("relationship") not in RELATIONSHIPS:
            problems.append(
                f"script {label} has relationship {script.get('relationship')!r}, which is "
                f"not one of {sorted(RELATIONSHIPS)}"
            )

        seen_section_ids: set[str] = set()
        for section in script.get("sections", []):
            section_id = section.get("section_id")
            if not section_id:
                problems.append(
                    f"script {label} has a section with no section_id "
                    f"({section.get('title')!r}) - a citation to a title cites a string that "
                    "may be rewritten"
                )
                continue
            if section_id in seen_section_ids:
                problems.append(f"script {label} uses section_id {section_id} twice")
            seen_section_ids.add(section_id)

            allowed = {
                "discipline": set(disciplines),
                "question_intent": QUESTION_INTENTS,
                "elicitation": ELICITATIONS,
            }
            # The section itself is checked, then each question that overrides. Checking only
            # questions would let an empty section carry any nonsense until the moment someone
            # adds a question to it, which then silently inherits the nonsense.
            taggables = [({}, section)] + [(q, section) for q in section.get("questions", [])]
            for question, owner in taggables:
                tags = resolve_tags(owner, question)
                for field, values in allowed.items():
                    if tags[field] not in values:
                        problems.append(
                            f"script {label} section {section_id} has {field} "
                            f"{tags[field]!r}, which is not one of {sorted(values)}"
                        )

    return problems


def validate_scripts_against_registry(scripts: dict, registry: dict) -> list[str]:
    """Every script anchored to a node the registry does not hold.

    An empty registry accepts anything, which is what a first run needs and what a project
    with no registry yet must not be blocked by.
    """
    known = {entry.get("id") for entry in registry.get("activities", [])}
    if not known:
        return []
    return [
        f"script {script.get('script_id') or key} is anchored to node "
        f"{script.get('node_id')!r}, which is not in the value chain registry"
        for key, script in scripts.items()
        if script.get("node_id") not in known
    ]


def validate_script_registry_succession(current: dict, proposed: dict) -> list[str]:
    """Every way a proposed script ledger would break what the current one records.

    Same rules as the value chain registry. Growth is free and retirement is free with the
    meaning kept (`active: false`); redefining or dropping an id is refused. Dropping is the
    worst: the ledger forgets, so nothing stops the id being handed to something else later,
    and every stored citation through it silently resolves to the wrong script.
    """
    problems: list[str] = []
    proposed_entries = {e.get("id"): e for e in proposed.get("scripts", [])}

    for entry in current.get("scripts", []):
        entry_id = entry.get("id")
        successor = proposed_entries.get(entry_id)
        if successor is None:
            problems.append(
                f"script_id {entry_id} is in the registry and missing from this one - retire "
                "it with active: false rather than dropping it, so the id is never handed to "
                "another script"
            )
        elif successor.get("node_id") != entry.get("node_id"):
            problems.append(
                f"script_id {entry_id} is registered against node {entry.get('node_id')} and "
                f"this moves it to {successor.get('node_id')} - take an unused id for the new "
                "script, because stored answers cite this one"
            )
    return problems


def validate_elicitation_order(scripts: dict) -> list[str]:
    """Unaided sections precede prompted ones, in every script.

    A script may be entirely unaided - a frontline instrument legitimately never prompts -
    but once it has prompted, an unaided section afterwards is unaided in name only: the
    interviewee has already been given the framing and cannot un-hear it.
    """
    problems: list[str] = []
    for key, script in scripts.items():
        label = script.get("script_id") or key
        prompted_at: str | None = None
        for section in script.get("sections", []):
            elicitation = section.get("elicitation")
            if elicitation == "prompted":
                prompted_at = prompted_at or section.get("section_id")
            elif elicitation == "unprompted" and prompted_at is not None:
                problems.append(
                    f"script {label} asks unaided section {section.get('section_id')} after "
                    f"prompted section {prompted_at} - once a lever has been named the "
                    "interviewee cannot un-hear it, so unaided sections come first"
                )
                break
    return problems


def validate_levers_unnamed_in_unaided_sections(scripts: dict, levers: list[dict]) -> list[str]:
    """No unaided question contains a lever's own words.

    The ordering rule alone is not enough: a section tagged unprompted that quotes the annual
    report's phrasing is prompted in everything but the tag.
    """
    names = [str(lever.get("lever", "")).strip() for lever in levers]
    names = [n for n in names if n]
    if not names:
        return []

    problems: list[str] = []
    for key, script in scripts.items():
        label = script.get("script_id") or key
        for section in script.get("sections", []):
            if section.get("elicitation") != "unprompted":
                continue
            for question in section.get("questions", []):
                text = str(question.get("text", "")).lower()
                for name in names:
                    if name.lower() in text:
                        problems.append(
                            f"script {label} names the value lever {name!r} in unaided "
                            f"question {question.get('id')} of section "
                            f"{section.get('section_id')} - move it to a prompted section, or "
                            "the answer confirms the lever rather than testing it"
                        )
    return problems


def lever_status(lever: dict, answers: list[dict]) -> str:
    """What the interviews did to this hypothesis.

    Order-independent by construction: a status derived from whichever answer came last would
    make the strength of the evidence an accident of interview scheduling. Contradiction
    outranks every confirmation, because reporting "confirmed" for a lever an interviewee
    disputed is the failure this exists to prevent.

    `untested` is the one that matters most - a lever that reached value design without a
    single interview touching it, looking exactly like an established finding.
    """
    name = str(lever.get("lever", "")).strip().lower()
    if not name:
        return "untested"

    touching = [
        a for a in answers
        if name in f"{a.get('question_text', '')} {a.get('answer_text', '')}".lower()
    ]
    if not touching:
        return "untested"
    if any(not a.get("supports") for a in touching):
        return "contradicted"
    if any(a.get("elicitation") == "unprompted" for a in touching):
        return "confirmed_unprompted"
    return "confirmed_prompted"
