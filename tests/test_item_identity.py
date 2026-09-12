"""Item identity is declared beside ownership, not hoped for.

`OUTPUT_OWNERS` says who may write an output type. `ITEM_IDENTITY` says whether that output
type is a collection and which field identifies an item inside it, which is the question
per-item review turns on: a reviewer sends back SC-014, node 3.3.3, lever LV-003, or section
6.1.1 of a business case, and every one of those is an id an artefact had to carry first.

Fourteen of the twenty declared output types have never been written on any project, so this
is mostly a constraint on artefacts that do not exist yet - which is the point. `value_levers`
is what happens when the question is asked afterwards: ten levers whose only identifying field
was a sentence their own author reworded on every run.
"""
import pathlib
import re

import pytest

from agents.tools.ownership import (
    ITEM_IDENTITY,
    OUTPUT_OWNERS,
    collections_with_no_item_id,
)

AGENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "agents"


def test_every_declared_output_type_declares_its_item_identity():
    """Set equality, so a new output type fails here rather than defaulting to "not a
    collection" - which is the answer that asks nothing and is therefore the one a silent
    default would hand every new artefact."""
    assert set(ITEM_IDENTITY) == set(OUTPUT_OWNERS), (
        f"declared for output types that do not exist: {set(ITEM_IDENTITY) - set(OUTPUT_OWNERS)}; "
        f"output types with no identity declared: {set(OUTPUT_OWNERS) - set(ITEM_IDENTITY)}"
    )


def test_no_collection_output_type_is_left_without_a_field_identifying_an_item():
    """The guard. A collection whose items cannot be named cannot be reviewed per item, and
    an artefact that reaches a reviewer before anybody asks this question is one where the
    answer costs a migration and a regeneration rather than a line of prompt.

    **What this cannot see**, stated plainly because a guard's account of its own reach has
    been wrong three times on this codebase: it reads a declaration. An output type whose
    items carry the declared field *empty*, or *duplicated*, or *renumbered on every run* -
    which is precisely the failure `value_levers` was in - passes this without complaint.
    It checks that the question was asked, not that it was answered well. The property that
    an id survives regeneration is asserted per artefact, against the real write path, in
    `tests/test_value_lever_ledger.py` and `tests/test_value_chain_ledger.py`; this is the
    thing that stops the NEXT artefact being built without anybody noticing there is nothing
    to assert.
    """
    assert collections_with_no_item_id(ITEM_IDENTITY) == []


def test_the_guard_reports_a_collection_with_no_id_field_and_passes_everything_else():
    """Driven both ways over a given mapping, which is what makes the guard above a
    mechanism rather than an assertion about one table.

    A checker that returned everything and a checker that returned nothing would each pass a
    one-sided test - the first against the failing case, the second against the real
    declaration. Both cases here, plus the case that is deliberately not a defect: an output
    type that is not a collection owes no id field at all.
    """
    assert collections_with_no_item_id({
        "fine": (True, "id", "has one"),
        "broken": (True, None, "does not"),
        "also_broken": (True, "", "empty is not a field name"),
        "not_a_collection": (False, None, "owes nothing"),
    }) == ["also_broken", "broken"]
    assert collections_with_no_item_id({}) == []


def _joined(text: str) -> str:
    """Source with Python's adjacent-string-literal breaks closed up.

    A prompt is written as a column of literals, so `operation='write', key='x'` is routinely
    split across two of them and a search of the raw source finds neither half beside the
    other. Closing the seams is what makes a window search mean what it looks like it means.
    """
    return re.sub(r"['\"]\s*\n\s*['\"]", "", text)


def _module_that_writes(output_type: str) -> pathlib.Path | None:
    """The module that writes this output type, found by behaviour rather than by name.

    `OUTPUT_OWNERS` gives the owning agent and the agent's module is only *usually* named
    after it - `stakeholder_manager` lives in `stakeholder_manager_agent.py` - and three
    name-keyed sweeps have already missed a file on this codebase.

    A window rather than a file-wide conjunction, which was the first version and was wrong:
    `roadmap_generator.py` READS `key='value_levers'` and writes `roadmap_data`, so "names
    the key somewhere and says write somewhere" made it the writer of Morgan's levers.

    The fallback to `agents/tools/` is `value_chain_registry`, which no prompt instructs a
    write of at all: `DeriveRegistryTool` derives it from the tree, and that tool is where
    its ids are actually assigned.
    """
    needle = f"key='{output_type}'"
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        if "tools" in path.parts or path.name == "__init__.py":
            continue
        joined = _joined(path.read_text())
        for match in re.finditer(re.escape(needle), joined):
            if "operation='write'" in joined[max(0, match.start() - 160):match.start()]:
                return path
    for path in sorted((AGENTS_DIR / "tools").rglob("*.py")):
        if f'output_type="{output_type}"' in path.read_text():
            return path
    return None


@pytest.mark.parametrize(
    "output_type",
    sorted(k for k, (collection, _, _) in ITEM_IDENTITY.items() if collection),
)
def test_a_declared_id_field_appears_in_the_prompt_that_writes_it(output_type):
    """The declaration held against the prompts, so it is a fact about the product rather
    than a note about intentions. A field declared here and absent from the schema the agent
    is given is a field no artefact will ever carry.

    Two honest limits, the first of them demonstrated rather than supposed. **A file-level
    search cannot tell which of several item schemas in one prompt carries the field.**
    Deleting `"id": "DATA-001"` from the enterprise architect's data-layer schema left this
    test green, because the technology and organisation layers still name `id` in the same
    file - a mutation that really does ship an unidentifiable entity, and this cannot see it.
    `test_each_architecture_layer_carries_its_own_id_series` below is what catches that one,
    and it is a claim about that artefact rather than a rule this guard could express.
    Second: a prompt can name a field while the agent omits it. Only an artefact settles
    that, and fourteen of these artefacts do not exist.
    """
    _, id_field, _ = ITEM_IDENTITY[output_type]
    module = _module_that_writes(output_type)
    assert module is not None, (
        f"no agent module instructs a write of {output_type!r} - either the key is dead or "
        "this search has stopped finding the file that writes it"
    )
    text = module.read_text()
    quoted = [f'\\"{id_field}\\"', f'"{id_field}"', f"'{id_field}'"]
    assert any(form in text for form in quoted), (
        f"{module.name} writes {output_type!r} and never names {id_field!r}, which "
        f"ITEM_IDENTITY says identifies an item in it"
    )


def test_the_module_search_finds_a_writer_for_every_collection_and_not_by_accident():
    """The negative control for the search above. A regex that matched nothing would make
    every parametrised case fail loudly; a regex that matched everything would make them all
    pass vacuously, and that is the direction worth checking.
    """
    assert _module_that_writes("value_levers").name == "value_lever_analyst.py", \
        "roadmap_generator.py reads value_levers and writes roadmap_data - a search that " \
        "does not look at the window around the key calls it the writer of both"
    assert _module_that_writes("interview_scripts").name == "interaction_designer.py"
    assert _module_that_writes("stakeholder_engagement_plan").name == \
        "stakeholder_manager_agent.py", \
        "the owner is `stakeholder_manager` and the module is not named after it - which is " \
        "exactly why this search reads the prompts rather than the filenames"
    assert _module_that_writes("value_chain_registry").name == "derive_registry.py", \
        "no prompt instructs a registry write; the derive tool is the door"
    assert _module_that_writes("no_such_output_type_at_all") is None


def test_each_architecture_layer_carries_its_own_id_series():
    """`architecture_register` holds three lists of entities in one artefact, and each needs
    an id of its own.

    Here rather than in the guard above because the guard reads a declaration, and a
    declaration of one field name cannot say "three times, once per layer". This exists
    because the mutation it catches survived everything else: deleting the data layer's
    `"id": "DATA-001"` left the whole file green, since the other two layers still name `id`
    a few lines down. An entity with no id is one a reviewer cannot send back and a later run
    cannot match to what it replaced - the same failure `value_levers` was in.
    """
    text = _joined((AGENTS_DIR / "architecture" / "enterprise_architect.py").read_text())
    for layer, prefix in (("Data", "DATA-001"), ("Technology", "TECH-001"),
                          ("Organisation", "ORG-001")):
        marker = f"{layer} layer"
        at = text.find(marker + " — each entity:")
        assert at != -1, f"the {layer} layer's entity schema is not where this expects it"
        # The schema itself, not merely the same file. Asserting the id appears anywhere in
        # the module passed while the data layer had none, because the placeholder object
        # further up still carried one - proximity to the layer's own heading is what makes
        # this an assertion about that layer's entity rather than about the prompt at large.
        assert f'\\"id\\": \\"{prefix}\\"' in text[at:at + 200], (
            f"the {layer} layer's entity schema does not carry an id"
        )


def test_an_id_is_never_the_item_position():
    """`rank`, `position` and `order` are what a regeneration moves, and they are the fields
    most likely to be reached for when an artefact needs "something to key on".

    Written as a rule rather than left to review: `portfolio_register` genuinely carries a
    `rank`, beside the `id` its items keep - and the ranking is the thing the scoring
    changes, so a review state hung on it would move every time the portfolio was rescored.
    """
    forbidden = {"rank", "position", "order", "index", "number", "label", "title", "name"}
    for output_type, (collection, id_field, _) in ITEM_IDENTITY.items():
        if not collection:
            continue
        assert id_field not in forbidden, (
            f"{output_type} is identified by {id_field!r}, which is a position or a label - "
            "regeneration is free to move it, so review state hung on it does not survive"
        )
