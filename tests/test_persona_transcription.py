# tests/test_persona_transcription.py
"""`agents/identity.py` is a hand transcription of TypeScript, and nothing made it stay one.

Seventeen display names and seventeen image filenames were copied by hand out of
`AGENT_HUMAN_NAME` and `AGENT_AVATAR_IMAGE` in `ui/src/components/agentStatus.ts`, because no
Python module owned them. The transcription was faithful when it was made and a reviewer
checked all thirty-four. Nothing checks it now: editing the TypeScript renames an agent
everywhere a human looks while Python goes on holding the old name, and the six-way persona
disagreement this slice exists to end is simply re-created across the language boundary.

**Set equality, and nothing else.** The obvious guard crosses the two by
`agent_id.replace("_", " ").title()` - and that is precisely the coupling Task 2 rejected, on
the evidence that all fifteen entries of `_SNAKE_TO_DISPLAY` turned out to be exactly that
formatting function. Writing it into a test would encode the rejected derivation as a rule.
The two files share no key: one is keyed by agent id, the other by role. What they must share
is the seventeen names and the seventeen faces, so that is what is asserted - no join key, no
derivation, and no way for it to teach the wrong lesson.
"""
from __future__ import annotations

import re
from pathlib import Path

from agents.identity import AGENT_IDENTITY

AGENT_STATUS = Path(__file__).resolve().parent.parent / "ui" / "src" / "components" / "agentStatus.ts"


def _block(name: str) -> str:
    source = AGENT_STATUS.read_text()
    block = re.search(rf"export const {name}: Record<string, string> = \{{(.*?)\n\}}", source, re.S)
    assert block, f"{name} not found in {AGENT_STATUS} - has it been renamed?"
    return block.group(1)


def _frontend_names() -> set[str]:
    return {name for _, name in re.findall(r"'([^']+)':\s+'([^']+)'", _block("AGENT_HUMAN_NAME"))}


def _frontend_images() -> set[str]:
    """The bare filenames. The front end wraps each in `_img(...)`, which prefixes the
    configured base at run time; identity.py stores the path under `ui/public`."""
    return set(re.findall(r"_img\('([^']+)'\)", _block("AGENT_AVATAR_IMAGE")))


def _frontend_faces() -> set[tuple[str, str]]:
    """Each person paired with their headshot, joined on the role key the two maps share.

    The role key never leaves this function - it is how the *TypeScript* relates its own two
    maps, not a bridge to the Python side, so pairing here buys the mispairing check without
    introducing any relationship between an agent id and a name.

    Every role with a headshot must be a role with a name; the converse is not required, and
    Laura Nelson is the agent that makes the difference real. `Identity.image` has always been
    nullable and always said an agent without a headshot is a legitimate state - she is the
    first one actually in it, so the assertion is the direction that has to hold rather than
    the equality that happened to hold while every agent had a portrait.
    """
    names = dict(re.findall(r"'([^']+)':\s+'([^']+)'", _block("AGENT_HUMAN_NAME")))
    images = dict(re.findall(r"'([^']+)':\s+_img\('([^']+)'\)", _block("AGENT_AVATAR_IMAGE")))
    assert set(images) <= set(names), (
        f"{sorted(set(images) - set(names))} have a headshot and no name in the front end"
    )
    return {(names[role], images[role]) for role in images}


def _python_faces() -> set[tuple[str, str]]:
    return {
        (identity.display_name, identity.image.rsplit("/", 1)[-1])
        for identity in AGENT_IDENTITY.values()
        if identity.image
    }


def _python_images() -> set[str]:
    return {
        identity.image.rsplit("/", 1)[-1]
        for identity in AGENT_IDENTITY.values()
        if identity.image
    }


def test_the_parser_reads_both_maps():
    """Guard the guard. Two empty sets are equal, and a regex that stopped matching would
    make every assertion below pass while the files diverged freely.

    Eighteen names and seventeen faces: Laura Nelson has no headshot yet. The two numbers are
    written separately rather than as one because they are now separate facts, and a single
    count would go back to hiding whichever of them moved.
    """
    assert len(_frontend_names()) == 18, sorted(_frontend_names())
    assert len(_frontend_images()) == 17, sorted(_frontend_images())


def test_the_two_files_name_the_same_people():
    python_names = {identity.display_name for identity in AGENT_IDENTITY.values()}
    assert python_names == _frontend_names(), (
        "agents/identity.py and ui/src/components/agentStatus.ts disagree about who the "
        "agents are. The Python map is a transcription of the TypeScript one; whichever was "
        "edited, the other has to follow."
    )


def test_the_two_files_show_the_same_faces():
    assert _python_images() == _frontend_images(), (
        "agents/identity.py and ui/src/components/agentStatus.ts disagree about which "
        "headshot belongs to the roll."
    )


def test_each_person_has_the_same_face_in_both_files():
    """Two separate set-equality checks cannot see a swap: exchange two agents' images and
    both sets are unchanged. Pairing name with filename catches it, and needs no derivation -
    the TypeScript already relates its own two maps through a shared role key, so the pairing
    is read rather than invented.

    The name-to-id half stays open on purpose. Pairing those would need a key the two files do
    not share, and the only candidate is `id.replace("_", " ").title()` - the coupling Task 2
    rejected on evidence. So swapping two *names* between agent ids is still invisible here.
    The cost of that gap is a mislabelled agent; the cost of closing it this way is writing the
    rejected derivation into a test, where the next reader takes it for the rule.
    """
    assert _python_faces() == _frontend_faces(), (
        "an agent's name and headshot are paired differently in the two files - most likely "
        "two rows were transcribed across each other"
    )


def test_the_guard_does_not_cross_the_two_by_formatting_the_id():
    """The rule this file must not encode, asserted directly so that a later rewrite into the
    'obvious' joined form fails here rather than passing quietly.

    A display name derivable from its id has not been decoupled from the id; it has been
    spelled differently. Not one of the seventeen is.
    """
    for agent_id, identity in AGENT_IDENTITY.items():
        assert identity.display_name != agent_id.replace("_", " ").title()


# ── Where else the seventeen names are typed out ──────────────────────────────

UI_SRC = AGENT_STATUS.parent.parent

# Files allowed to hard-code the persona names, and why. Research for this slice found six
# lists; the pitch deck now derives its slide from AGENT_HUMAN_NAME, which is how it stopped
# billing Maya as the "Assessment Designer" - a role no registry has held for two sprints.
PERMITTED = {
    # The front end's own declaration, and the source agents/identity.py transcribes.
    "components/agentStatus.ts": "the declaration",
    # pages/DataArchitecture.tsx was the second entry, excused because the graph did not model
    # egress. It does now - agents/egress.py, agents/reads.py and agents/charter.py, assembled
    # by agents/graph.py and served by GET /projects/{slug}/data-architecture - so the page
    # renders the names it is given instead of holding a list of its own, and the exemption is
    # retired rather than left standing as a reason that has stopped being true.
}


def _files_naming_personas() -> dict[str, int]:
    names = {identity.display_name for identity in AGENT_IDENTITY.values()}
    found: dict[str, int] = {}
    for path in sorted(UI_SRC.rglob("*.ts*")):
        if "__tests__" in path.parts:
            continue
        text = path.read_text()
        # Three or more, so a single name quoted in a comment or a fixture is not a list.
        hits = sum(1 for name in names if f"'{name}'" in text or f"({name})" in text)
        if hits >= 3:
            found[str(path.relative_to(UI_SRC))] = hits
    return found


def test_the_persona_scan_finds_the_declaration_itself():
    """Guard the guard: a scan matching nothing would excuse every file below."""
    assert _files_naming_personas().get("components/agentStatus.ts", 0) >= 17


def test_no_new_module_types_the_seventeen_names_out():
    unexpected = {
        path: hits for path, hits in _files_naming_personas().items() if path not in PERMITTED
    }
    assert not unexpected, (
        f"{sorted(unexpected)} hard-code the agents' names. Derive them from "
        f"AGENT_HUMAN_NAME - the copy the pitch deck used to hold had already gone stale, "
        f"and a stale persona list is read by a client rather than by a developer."
    )
