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
