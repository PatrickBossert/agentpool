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


def _python_images() -> set[str]:
    return {
        identity.image.rsplit("/", 1)[-1]
        for identity in AGENT_IDENTITY.values()
        if identity.image
    }


def test_the_parser_reads_both_maps():
    """Guard the guard. Two empty sets are equal, and a regex that stopped matching would
    make every assertion below pass while the files diverged freely."""
    assert len(_frontend_names()) == 17, sorted(_frontend_names())
    assert len(_frontend_images()) == 17, sorted(_frontend_images())


def test_the_two_files_name_the_same_seventeen_people():
    python_names = {identity.display_name for identity in AGENT_IDENTITY.values()}
    assert python_names == _frontend_names(), (
        "agents/identity.py and ui/src/components/agentStatus.ts disagree about who the "
        "agents are. The Python map is a transcription of the TypeScript one; whichever was "
        "edited, the other has to follow."
    )


def test_the_two_files_show_the_same_seventeen_faces():
    assert _python_images() == _frontend_images(), (
        "agents/identity.py and ui/src/components/agentStatus.ts disagree about which "
        "headshot belongs to the roll."
    )


def test_the_guard_does_not_cross_the_two_by_formatting_the_id():
    """The rule this file must not encode, asserted directly so that a later rewrite into the
    'obvious' joined form fails here rather than passing quietly.

    A display name derivable from its id has not been decoupled from the id; it has been
    spelled differently. Not one of the seventeen is.
    """
    for agent_id, identity in AGENT_IDENTITY.items():
        assert identity.display_name != agent_id.replace("_", " ").title()
