# agents/tools/ownership.py
"""Which agent owns which output key.

Reads are open - the pipeline depends on every agent reading upstream. Only writes are owned,
because a write is where one agent's work can destroy another's.

`value_chain_registry` is owned by `value_chain_mapper`, the only agent holding
DeriveRegistryTool. It is writable through this tool as well, where
`_validate_value_chain_registry` holds each write to the ledger's succession rules - the ledger
may grow and may retire, but may not redefine or forget. Ownership is what stops another agent
reaching for it; succession is what stops its owner corrupting it.
"""

OUTPUT_OWNERS: dict[str, str] = {
    "value_chain_model":           "value_chain_mapper",
    "value_chain_registry":        "value_chain_mapper",
    "value_chain_summary":         "value_chain_mapper",
    "value_chain_tree":            "value_chain_mapper",
    "value_levers":                "value_lever_analyst",
    "interview_scripts":           "interaction_designer",
    "stakeholder_engagement_plan": "stakeholder_manager",
    "interview_plan":              "interview_coordinator",
    "interview_transcripts":       "stakeholder_interviewer",
    "activity_insights":           "synthesis_analyst",
    "themes":                      "synthesis_analyst",
    "strategic_requirements":      "synthesis_analyst",
    "propositions":                "value_proposition_generator",
    "portfolio_register":          "portfolio_manager",
    "architecture_register":       "enterprise_architect",
    "initiative_register":         "initiative_identifier",
    "captured_requirements":       "requirements_capture",
    "requirements_analysis":       "requirements_analyst",
    "roadmap_data":                "roadmap_generator",
    "illustration_briefs":         "visual_illustrator",
}


# Whether an output type is a COLLECTION of items, and which field identifies an item.
#
# Per-item review is impossible without per-item identity, and until this table nothing
# required an artefact to have any. It held by habit: every built collection carried an id -
# SC-001, 3.3.3, VP-001 - except `value_levers`, whose only identifying field was a full
# sentence its own author reworded on every run. Habit is not a mechanism, and fourteen of
# these twenty output types have never been written at all, so the ones this has to hold for
# mostly do not exist yet. The worked case is a business case a reviewer wants revised at
# section 6.1.1: the time to constrain that is before it is built, not after.
#
# `id_field` is a promise about the ITEM, not about the artefact. The contract it carries is
# the one CLAUDE.md already states for the value chain: the ledger may grow and may retire,
# but may never redefine or forget. An id means one item for the life of the project, so
# renumbering on regeneration is the failure to design against - 6.1.1 cited in a review must
# still be 6.1.1 in the next version, and a hierarchical id is this same rule and not a
# different one.
#
# Three of these carried no id at all when the table was written - `activity_insights`,
# `architecture_register` and `illustration_briefs` - and each gained one in the same change,
# because a declaration that recorded the gap rather than closing it would have been a list
# of exemptions rather than a rule.
ITEM_IDENTITY: dict[str, tuple[bool, str | None, str]] = {
    # (is a collection, the field identifying an item, why)
    "value_chain_model": (
        True, "id",
        "segments, parties, activities, tasks and propositions each carry `id`. "
        "contributions and links are edges, identified by the endpoints they name rather "
        "than by an id of their own - an edge has no existence apart from its ends.",
    ),
    "value_chain_registry": (
        True, "id",
        "the id ledger itself; `value_chain_ledger` is the table that now holds it.",
    ),
    "value_chain_summary": (
        False, None,
        "a summary document. Its lists hold strings, not items - a reviewer disagrees with "
        "the summary, not with entry four of it.",
    ),
    "value_chain_tree": (
        True, "id",
        "the same ids as the registry, nested. A child is an item in its own right.",
    ),
    "value_levers": (
        True, "lever_id",
        "assigned in sp60 task 2. `lever` is the title and moves freely; `lever_id` is the "
        "name the lever answers to for the life of the project.",
    ),
    "interview_scripts": (
        True, "script_id",
        "a mapping keyed by SC-nnn, with the id repeated on the body. `interview_script_"
        "ledger` holds it.",
    ),
    "stakeholder_engagement_plan": (
        False, None,
        "a coverage report about the roster, not a set of reviewable items. Its nested "
        "`assignments` name stakeholders and nodes that are identified elsewhere.",
    ),
    "interview_plan": (
        True, "stakeholder_id",
        "one session entry per assigned stakeholder, which is what identifies an entry. The "
        "session's own durable identity is `session_token`, assigned in code when the "
        "session is created - the coordinator is told explicitly not to invent one.",
    ),
    "interview_transcripts": (
        True, "stakeholder_id",
        "one element per interviewed stakeholder, carrying their qa_pairs.",
    ),
    "activity_insights": (
        True, "node_id",
        "one entry per L3 value chain node. It carried only `label` until sp60 task 2b, "
        "which is the defect this table exists to catch: a label is what the registry "
        "rewrites on every rebuild, so nothing could have been sent back.",
    ),
    "themes": (True, "id", "TH-01."),
    "strategic_requirements": (True, "id", "SR-01."),
    "propositions": (True, "id", "VP-001, stated sequential in the prompt."),
    "portfolio_register": (
        True, "id",
        "the propositions' own VP-001 ids, scored and ranked. `rank` is a position and must "
        "never be mistaken for one - it is what the scoring moves.",
    ),
    "architecture_register": (
        True, "id",
        "three layers of entities. They were identified by `name` alone until sp60 task 2b.",
    ),
    "initiative_register": (True, "id", "INIT-001."),
    "captured_requirements": (True, "id", "REQ-001, one per initiative per dimension."),
    "requirements_analysis": (True, "id", "REQ-001."),
    "roadmap_data": (
        True, "id",
        "an object holding `initiatives` and `propositions`, both of which carry the ids "
        "their own registers assigned. The roadmap restates them and must not renumber.",
    ),
    "illustration_briefs": (
        True, "id",
        "an object holding `briefs`. A brief carried `reference_id` - which names something "
        "in ANOTHER artefact - and nothing of its own until sp60 task 2b.",
    ),
}


def collections_with_no_item_id(identity: dict[str, tuple[bool, str | None, str]]) -> list[str]:
    """Every output type declared a collection that names no field identifying an item.

    A pure function over a given mapping rather than a walk over the module's own, so the
    guard can be driven with a declaration that should fail as well as with the real one. A
    checker that can only be run against the live table is one that cannot be asked what it
    would say about anything else, and a one-sided test passes against a checker that
    reports everything and against one that reports nothing alike.
    """
    return sorted(
        key for key, (collection, id_field, _) in identity.items()
        if collection and not id_field
    )


def check_write(key: str, agent_name: str) -> str | None:
    """None when the write is allowed, otherwise the refusal the agent will read.

    The message names the owner, because an agent told only "no" will try again or improvise
    something worse - which is how nine batch keys came to exist.
    """
    owner = OUTPUT_OWNERS.get(key)
    if owner is None:
        return (
            f"Refused: '{key}' is not a declared output. Write only the key your task names - "
            f"splitting one output across several keys makes it invisible to the Output tab, "
            f"to review, and to validation."
        )
    if owner != agent_name:
        return (
            f"Refused: '{key}' belongs to {owner}. You may read it, not write it. If it is "
            f"wrong or missing something, say so in your output rather than correcting it - "
            f"the run that owns it must make the change."
        )
    return None
