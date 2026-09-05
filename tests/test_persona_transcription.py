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

    The name-to-id half was open here on purpose and is now closed **elsewhere**, by
    `test_each_role_is_bridged_to_the_agent_of_that_name` below. What made it unclosable here
    was that the only candidate join was `id.replace("_", " ").title()` - the coupling Task 2
    rejected on evidence, and writing it into a test is where the next reader takes it for the
    rule. sp62 needed the bridge for a different reason (the Setup section saves an agent's
    configuration by id) so it is **declared**, in `AGENT_IDS`, and a declared map is a fact
    rather than a derivation. This test stays as it is: it needs no join key and gains nothing
    from one.
    """
    assert _python_faces() == _frontend_faces(), (
        "an agent's name and headshot are paired differently in the two files - most likely "
        "two rows were transcribed across each other"
    )


def _frontend_ids() -> dict[str, str]:
    """`AGENT_IDS` - the role key the front end is arranged by, to the permanent agent id."""
    return dict(re.findall(r"'([^']+)':\s+'([^']+)'", _block("AGENT_IDS")))


def test_the_id_parser_reads_the_bridge_map():
    """Guard the guard, again: an unreadable map makes both assertions below vacuous."""
    assert len(_frontend_ids()) == 18, sorted(_frontend_ids())


def test_the_front_end_and_the_roll_agree_about_the_agent_ids():
    """The front end is keyed by role and the server by `agent_id`, so configuring an agent
    needs a bridge - and a bridge free to disagree with the roll would post a project's voice
    choice against an id nothing reads, answering 200 the whole way.

    Set equality over the values, so a *missing* id and an *invented* one both fail. The
    second is the dangerous direction: a typo is a 404 the operator sees, but an id that
    exists and belongs to a different agent configures the wrong one silently.
    """
    assert set(_frontend_ids().values()) == set(AGENT_IDENTITY), (
        "ui/src/components/agentStatus.ts's AGENT_IDS and agents/identity.py's AGENT_IDENTITY "
        "name different agents. The front end saves an agent's configuration by the id in "
        "that map, so an id the roll does not hold is a save against nothing."
    )


def test_each_role_is_bridged_to_the_agent_of_that_name():
    """Set equality cannot see a swap - exchange two roles' ids and both sets are unchanged,
    while Avery's Setup tab now saves Laura's voice.

    This closes the name-to-id gap the face test above leaves open, and closes it the way that
    test says it must not be closed lazily: through a **declared** map rather than through
    `id.replace('_',' ').title()`.

    Counted rather than asserted, after this docstring's first version claimed nine of the
    eighteen resist that formatting: **seventeen of the eighteen match it and only PAM does
    not.** One exception is enough, and a near-total rule is the worse kind - a derivation
    correct for seventeen entries reads as correct everywhere it is used, and the eighteenth is
    wrong with nothing to say so. `test_the_bridge_is_not_a_formatting_of_the_id` below holds
    that count so this paragraph fails rather than rots.
    """
    names = dict(re.findall(r"'([^']+)':\s+'([^']+)'", _block("AGENT_HUMAN_NAME")))
    mismatched = {
        role: (names.get(role), AGENT_IDENTITY[agent_id].display_name)
        for role, agent_id in _frontend_ids().items()
        if agent_id in AGENT_IDENTITY
        and names.get(role) != AGENT_IDENTITY[agent_id].display_name
    }
    assert not mismatched, (
        "a role is bridged to an agent of a different name - {role: (front end, roll)} "
        f"{mismatched}. Two rows have most likely been transcribed across each other, which "
        "puts one agent's configuration under another's name on the Setup tab."
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


# ── The bridge's own justification, and the two sets that must contain it ─────

def test_the_bridge_is_not_a_formatting_of_the_id():
    """`AGENT_IDS` is declared rather than derived, and this is the evidence for it.

    Held as a count because the first version of the comment defending that decision gave a
    number - "nine of the eighteen" - that was wrong by a factor of eight, and a justification
    that overstates its evidence is worse than none: the next reader who checks it distrusts the
    decision it was defending, and the decision is right.

    **Seventeen of the eighteen derive; PAM alone does not.** That is what makes the derivation
    dangerous rather than merely imperfect. A rule correct for seventeen entries reads as
    correct at every call site, and there is no id shorter than the whole map that would show a
    reader the exception. Asserted in both directions - the count *and* which agent it is - so
    that renaming PAM's role key to something derivable fails here and prompts the decision
    again, rather than silently making a `.title()` one-liner look safe.
    """
    ids = _frontend_ids()
    derivable = {role for role, agent_id in ids.items()
                 if agent_id.replace("_", " ").title() == role}
    assert len(ids) - len(derivable) == 1, (
        "the number of roles that resist id.replace('_',' ').title() has moved. Recount and "
        "correct the comment on AGENT_IDS in agentStatus.ts and the docstring above - do not "
        "adjust one number to match the other."
    )
    assert set(ids) - derivable == {"PAM"}, sorted(set(ids) - derivable)


def test_every_run_dispatchable_role_is_a_key_of_the_bridge():
    """`AGENT_RUN_KEYS` derives its twelve ids from `AGENT_IDS`, and nothing type-checks that.

    `Object.fromEntries` widens to `any`, so `Record<string, string>` says nothing about a role
    name in `RUN_DISPATCHABLE` that is not a key of `AGENT_IDS`: the entry becomes
    `undefined`, `tsc` stays clean and the whole frontend suite stays green. The visible
    consequence is `ReviewDialog`'s reverse lookup silently finding nothing, which reads as a
    missing review rather than as a typo.

    A typo in an `AGENT_IDS` *key* is already caught by the two tests above; only the derived
    subset's own list was unguarded, which is precisely the surface the derivation created.
    """
    source = AGENT_STATUS.read_text()
    block = re.search(r"const RUN_DISPATCHABLE = \[(.*?)\n\]", source, re.S)
    assert block, f"RUN_DISPATCHABLE is no longer a literal array in {AGENT_STATUS.name}"
    listed = re.findall(r"'([^']+)'", block.group(1))
    assert listed, "the walk read no roles - it would excuse every one of them"
    unknown = [role for role in listed if role not in _frontend_ids()]
    assert not unknown, (
        f"{unknown} are dispatchable and are not keys of AGENT_IDS, so AGENT_RUN_KEYS maps "
        "them to undefined with tsc clean and the suite green"
    )


def test_every_crew_member_is_a_key_of_the_bridge():
    """A crew member absent from `AGENT_IDS` renders a headed section with a blank body.

    `CrewAgentConfiguration` emits the agent's heading and then `AgentConfigSection` returns
    `null` because it has no id to configure - so the failure is an empty panel under somebody's
    name, which reads as a loading fault rather than as a missing map entry. Same family as the
    test above: both are places where a name is looked up in this map and a miss is silent.
    """
    source = AGENT_STATUS.read_text()
    block = re.search(r"export const CREW_AGENTS: Record<string, string\[\]> = \{(.*?)\n\}",
                      source, re.S)
    assert block, f"CREW_AGENTS is no longer a literal map in {AGENT_STATUS.name}"
    members = set(re.findall(r"'([^']+)'", block.group(1)))
    assert len(members) >= 17, f"the walk read only {len(members)} crew members"
    unknown = sorted(members - set(_frontend_ids()))
    assert not unknown, (
        f"{unknown} are in a crew and are not keys of AGENT_IDS, so their Setup tab shows a "
        "heading with nothing under it"
    )
