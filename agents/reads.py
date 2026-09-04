# agents/reads.py
"""What each agent draws on, and in what form.

Slice 1's rule is that nothing is declared where a registry already holds it. `OUTPUT_OWNERS`
holds every write and `agents/graph.py` inverts it for free, so the writing half of the pipeline
costs nothing. The reading half is held nowhere: it exists only as English inside CrewAI task
descriptions, and this module is the first place it is written down as a fact rather than as an
instruction.

**Why that distinction is the point of the module.** An instruction can be wrong for years and
nothing notices, because an agent that is told to read something absent gets a string back
beginning "Error:" and carries on. Three such instructions were live when this was written, and
`test_every_artefact_read_is_written_by_someone` found all three the first time it ran. They are
in `UNRESOLVABLE_READS` below with what actually happens, not in `AGENT_READS` - a declaration
that copied them would be worse than none, because the guard would then bless them.

## What counts as a read here

Information the deployment already holds and hands to an agent: an artefact, a table in the
project's database, a Chroma collection, a document the client uploaded. **Not** what a tool
fetches from outside - Tavily's answers and whatever `WebFetchTool` retrieves are declared in
`agents/egress.py`, which owns the outward direction, and restating them here would be the
duplication the graph exists to end. The two modules meet at `DocumentIngestionTool`: what it
draws on is a read, where it sends it is egress.

`via` names the route, because the same source reaches different agents by different routes and
the route is what breaks. `stakeholders` reaches the Stakeholder Manager down the dispatch path,
which folds the roster into his task before the crew starts, and reaches the Stakeholder
Interviewer through `InterviewSessionTool`, which joins names onto transcripts as it collects
them. A declaration naming only the source would record those as the same fact.

## Media

`Medium.ARTEFACT_JSON` is JSON and nothing else, which is narrower than a first reading of this
project suggests. `SQLiteStateTool` writes `outputs/{key}.json` unconditionally, and it is the
only door onto every one of `OUTPUT_OWNERS`' twenty keys, so **no declared read is of markdown**.
Markdown exists in this project in two places, neither of them read by an agent: the files
`MermaidRenderTool` writes (under output type `value_chain`, which no `OUTPUT_OWNERS` entry
covers and no task description reads), and `.md` files a client uploads, which reach an agent as
`Medium.UPLOADED_DOCUMENT` or as chunks in a collection.

`Medium.VECTOR_COLLECTION` sources are written as the templates the code builds
(`agents/tools/chroma_query.py`), because the slug and the sector are what say whose material it
is. `sector_{sector}` carries no slug on purpose: it is one collection shared by every engagement
in that sector.

## Tiers

A `VECTOR_COLLECTION` read also names its **knowledge tier** - `sector`, `organisation`,
`project` or `interviews`, the vocabulary `api/services/knowledge_tiers.py` owns. The name alone
could already tell the privacy page that `sector_{sector}` is not this project's; it could not
tell it *why*, nor tell that store apart from `org_{org_slug}`, which is shared with a quite
different set of people. The tier is what carries the reason.

It is a declaration held equal to the code: `test_every_collection_read_names_the_tier_that_
builds_it` rebuilds each `source` by calling `collection_for` with the tier, so a template typed
here that the resolver would never produce fails rather than reassures. Nothing but a collection
carries one - an artefact and a table are not in the knowledge store, and giving them a tier
would make the word mean two things.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from api.services.knowledge_tiers import Tier


class Medium(Enum):
    """How the information is held where the agent finds it."""

    ARTEFACT_JSON = "a JSON artefact in the project's outputs directory"
    DATABASE_TABLE = "a table in a SQLite database"
    VECTOR_COLLECTION = "a Chroma collection"
    UPLOADED_DOCUMENT = "a file the client uploaded, under the project's docs directory"


@dataclass(frozen=True)
class Read:
    """One thing an agent draws on: what it is, how it is held, and how it gets there.

    `note` is prose because nothing derives it. It says what the agent is actually after, which
    is the sentence a reader of the privacy page needs - "the client's own strategy and board
    material" tells them something that `{slug}_docs` does not.

    `tier` is set on `VECTOR_COLLECTION` reads and on nothing else, and `None` is a real answer
    rather than an unfilled one: an artefact under `projects/{slug}/outputs/` and a row in a
    SQLite table are not in the knowledge store, and there is no tier that would be true of them.
    """

    source: str
    medium: Medium
    via: str
    note: str
    tier: Tier | None = None


# The route for anything the dispatch path reads on an agent's behalf and folds into its task
# description before the crew starts. Not a tool: no tool the agent holds could fetch it, and the
# agent has no say in whether it arrives.
VIA_DISPATCH = "build_and_run_crew"


def _artefact(source: str, note: str) -> Read:
    """An artefact read, which is always JSON through `SQLiteStateTool`.

    Every one of the twenty output types is written by that tool as `outputs/{key}.json` and
    resolved back through the `agent_outputs` ledger, so the medium and the route are properties
    of the door rather than of the key. Spelling them out on all forty-odd reads below would
    invite one of them to be typed differently from the rest.
    """
    return Read(source, Medium.ARTEFACT_JSON, "SQLiteStateTool", note)


def _project_docs(note: str) -> Read:
    return Read("{slug}_docs", Medium.VECTOR_COLLECTION, "ChromaQueryTool", note, tier="project")


def _sector_knowledge(note: str) -> Read:
    return Read(
        "sector_{sector}",
        Medium.VECTOR_COLLECTION,
        "ChromaQueryTool",
        f"{note}. Shared across every engagement in this sector - it carries no slug",
        tier="sector",
    )


# Keyed on agent id. Every agent has an entry and an empty tuple is a real answer: assembly in
# `agents/graph.py` refuses a missing one, because an agent nobody has read yet would otherwise
# be indistinguishable from an agent that genuinely reads nothing.
AGENT_READS: dict[str, tuple[Read, ...]] = {
    # --- discovery_mapping --------------------------------------------------------------------
    "value_chain_mapper": (
        _artefact(
            "value_chain_registry",
            "his own ledger, re-read at step 0 so a rebuilt chain keeps the ids it already "
            "issued",
        ),
        Read(
            "projects/{slug}/docs/",
            Medium.UPLOADED_DOCUMENT,
            "DocumentIngestionTool",
            "every .txt, .md and .pdf the client uploaded, read whole and chunked for embedding",
        ),
        _project_docs("the client's own account of how it operates"),
        _sector_knowledge("how this sector's value chain is usually structured"),
        Read(
            "client_documents",
            Medium.DATABASE_TABLE,
            VIA_DISPATCH,
            "the original filenames of the documents a consultant marked as priority sources, "
            "named in his task description so he can weight them",
        ),
    ),
    "value_lever_analyst": (
        _artefact(
            "value_chain_model",
            "so each lever can name the activities it bears on; she leaves the references empty "
            "rather than inventing ids if it is not written yet",
        ),
        _project_docs("the client's strategy, performance and governance material"),
        _sector_knowledge("levers and transformation patterns common in this sector"),
    ),
    # --- assessment_design --------------------------------------------------------------------
    "interaction_designer": (
        _artefact("value_levers", "the hypotheses her instruments exist to test"),
        _artefact(
            "value_chain_registry",
            "every active entry, because she owes one interview script for each of them",
        ),
        _artefact(
            "interview_scripts",
            "her own, to see which scripts exist already - an absent one is what she is there "
            "to write, and an existing one may have been edited by a consultant",
        ),
        _artefact("value_chain_summary", "the client's operations, for framing"),
        _project_docs(
            "corporate context - governance posture, capability gaps, the language the "
            "organisation uses about itself"
        ),
    ),
    # --- stakeholder_management ---------------------------------------------------------------
    "stakeholder_manager": (
        _artefact(
            "value_chain_registry",
            "every active node at every level, which is the full coverage target",
        ),
        Read(
            "stakeholder_assignments",
            Medium.DATABASE_TABLE,
            VIA_DISPATCH,
            "who is assigned to which node id, with the two coverage proportions derived from "
            "it - the share of active activities nobody speaks for, and the share of the roster "
            "assigned to nothing. Computed by the dispatch path, not by him, so the figure he "
            "reports is the figure Pamela raises",
        ),
        Read(
            "stakeholders",
            Medium.DATABASE_TABLE,
            VIA_DISPATCH,
            "each name and job title, joined onto the mapping, and the roster in full so the "
            "people assigned to nothing can be named",
        ),
    ),
    # --- discovery_interviews -----------------------------------------------------------------
    "interview_coordinator": (
        _artefact(
            "interview_scripts",
            "keyed by script_id, which he must carry into the plan - a node label cannot "
            "recover it afterwards",
        ),
        Read(
            "stakeholder_assignments",
            Medium.DATABASE_TABLE,
            VIA_DISPATCH,
            "who is assigned to which node id, for the project - the mapping is a durable "
            "project fact, so it is the same rows on every run",
        ),
        Read(
            "stakeholders",
            Medium.DATABASE_TABLE,
            VIA_DISPATCH,
            "each assigned person's name and job title, joined onto their assignment",
        ),
    ),
    "stakeholder_interviewer": (
        _artefact("interview_plan", "the approved plan, one entry per stakeholder"),
        Read(
            "interview_sessions",
            Medium.DATABASE_TABLE,
            "InterviewSessionTool",
            "session status counts, and every completed session's transcript in the "
            "interviewee's own words",
        ),
        Read(
            "stakeholders",
            Medium.DATABASE_TABLE,
            "InterviewSessionTool",
            "the name each transcript belongs to, joined on when transcripts are collected",
        ),
    ),
    "synthesis_analyst": (
        _artefact("value_chain_tree", "the node labels she anchors insights and themes to"),
        Read(
            "{slug}_interviews",
            Medium.VECTOR_COLLECTION,
            "ChromaQueryTool",
            "interview answers verbatim, each carrying its node, level, relationship, "
            "discipline, elicitation and answer_id. Queried per area rather than whole",
            tier="interviews",
        ),
    ),
    # --- value_design -------------------------------------------------------------------------
    "value_proposition_generator": (
        _artefact("strategic_requirements", "the challenges and opportunities the interviews "
                                            "evidenced"),
        _artefact("value_levers", "the levers, tested or otherwise"),
        _artefact("value_chain_summary", "the chain the propositions are anchored against"),
        _artefact(
            "activity_insights",
            "actors, needs and frustrations per activity. Explicitly optional - the task tells "
            "him to infer activity references from the summary if it is absent",
        ),
    ),
    "portfolio_manager": (
        _artefact("propositions", "the propositions he scores and ranks"),
    ),
    # --- capabilities -------------------------------------------------------------------------
    "enterprise_architect": (
        # No artefact read at all, and that is the honest answer rather than an oversight: his
        # task runs three separate queries over the client's documents and builds the register
        # from those alone. He is the one agent whose input is entirely the client's own material.
        _project_docs(
            "three queries - systems and infrastructure, data entities and ownership, "
            "organisational structure - which are the whole of his input"
        ),
    ),
    "initiative_identifier": (
        _artefact("propositions", "what the initiatives must deliver"),
        _artefact("architecture_register", "the current state the gaps are measured against"),
        _artefact("strategic_requirements", "what each initiative must address"),
    ),
    # --- requirements -------------------------------------------------------------------------
    "requirements_capture": (
        _artefact("initiative_register", "every initiative he must cover"),
        _artefact("architecture_register", "so each requirement is stated against what exists"),
    ),
    "requirements_analyst": (
        _artefact(
            "captured_requirements",
            "the captured set. Her task description calls this 'the interview transcript', "
            "which it has not been since the requirements crew was split - the key is right "
            "and the sentence around it is stale",
        ),
        _project_docs("additional context from the client's documents"),
        _sector_knowledge("sector-standard requirements to compare against"),
    ),
    # --- delivery -----------------------------------------------------------------------------
    "roadmap_generator": (
        _artefact("initiative_register", "what is sequenced into periods"),
        _artefact("propositions", "what realises, and when"),
        _artefact("value_levers", "traced from each proposition's supporting evidence"),
    ),
    # --- business_plan ------------------------------------------------------------------------
    "visual_illustrator": (
        _artefact("value_chain_summary", "the vision illustration"),
        _artefact("value_chain_registry", "L1 and L2 nodes with their entity context"),
        _artefact("propositions", "the propositions illustration"),
        _artefact("architecture_register", "the data, technology and organisation layers"),
        _artefact("roadmap_data", "the sequencing illustration"),
    ),
    "business_plan_generator": (
        _artefact("strategic_requirements", "the case for change"),
        _artefact("requirements_analysis", "the case for change"),
        _artefact("value_levers", "the case for change"),
        _artefact("propositions", "the value propositions section"),
        _artefact("initiative_register", "costs, by complexity score"),
        _artefact("roadmap_data", "periods, the time axis, and benefit realisation"),
    ),
    # --- orchestration ------------------------------------------------------------------------
    "pam": (
        # PAM holds SQLiteStateTool and no task of hers tells her to read with it. Every one of
        # her six tasks dispatches a crew and reports what it did. The empty tuple is what the
        # task descriptions say; the tool she holds is already on `AgentNode.tools`, and
        # inferring a read from a tool is how a declaration becomes a guess.
    ),
}


# A tier the tool offers and no agent's task description asks for.
#
# `ChromaQueryTool` accepts all four tiers from any of the six agents holding it, and the
# organisation store is the one nothing is instructed to read: no task description names the
# organisation tier as the tool's collection argument. That is a live gap rather than a hypothetical
# one - the tier became genuinely *writable* on this branch, so an org_admin can put an
# organisation's strategy and group policy into `org_{org_slug}` today and no agent will draw
# on it until somebody writes the instruction.
#
# Declared here rather than left out, because leaving it out is what the page did: a store with
# no declared reader appeared nowhere on it at all, so a reader looking for "what is shared
# beyond this project" was shown the sector store and the two system tables and nothing about
# the organisation one - and its material is shared with every sibling project whether or not an
# agent has been told to query it. It is deliberately **not** in `AGENT_READS`: that map says
# what an agent is instructed to draw on, and inventing an instruction to make a store visible
# would be the same fabrication `UNRESOLVABLE_READS` exists to avoid in the other direction.
#
# The page renders it with an empty `read_by` and the six holders under `reachable_by`, which is
# exactly the truth. When an agent is instructed to read it, the entry moves into that agent's
# `AGENT_READS` tuple and out of here - `test_no_uninstructed_read_is_also_a_declared_one`
# fails if both hold it.
UNINSTRUCTED_READS: tuple[Read, ...] = (
    Read(
        "org_{org_slug}",
        Medium.VECTOR_COLLECTION,
        "ChromaQueryTool",
        "annual reports, strategy and group policy filed against the organisation rather than "
        "against one engagement. Offered to every agent holding the tool and instructed to "
        "none of them, so nothing draws on it today",
        tier="organisation",
    ),
)


@dataclass(frozen=True)
class UnresolvableRead:
    """A read a task description instructs that the code cannot serve.

    Recorded rather than declared, and rather than deleted. Deleting it would lose the finding;
    declaring it would put a source into `AGENT_READS` that no owner writes, and the guard -
    which exists precisely to catch this - would then be satisfied by the thing it was built to
    refuse.

    None of these fails loudly. `SQLiteStateTool` answers an unknown key with a string beginning
    "Error: no state found", CrewAI hands that back as an ordinary tool result, and the agent
    carries on without the input. That is why all three survived: there is no exception, no log
    line, and no difference in the run's reported status.
    """

    agent_id: str
    source: str
    instructed_via: str
    finding: str


UNRESOLVABLE_READS: tuple[UnresolvableRead, ...] = (
    UnresolvableRead(
        agent_id="value_proposition_generator",
        source="user_journeys",
        instructed_via="SQLiteStateTool",
        finding=(
            "Nothing writes it. `user_journeys` is in no `OUTPUT_OWNERS` entry, so a write to it "
            "would be refused by `check_write`, and no file of that name exists in any project's "
            "outputs directory. The step is the only mention of it in the codebase apart from a "
            "test asserting the step is present. Harmless as it stands - the instruction itself "
            "says to skip it on an error - so the fix is to drop the step, not to invent an "
            "owner."
        ),
    ),
    # `stakeholder_assignments` was here, and is now declared above as a real read. The finding
    # stood exactly as written - the tool could never see the table, so the agent whose task is
    # to find the gaps in the mapping had never seen the mapping - and the fix was the one it
    # named: `build_and_run_crew` now enriches the rows and prepends them to his task, the same
    # route by which they already reached the Interview Coordinator, and his step 2 no longer
    # sends him to `SQLiteStateTool` for them. Recorded here rather than deleted silently,
    # because the entry is the reason the injection exists.
    # `stakeholder_manager` / `interview_sessions` was here. The finding proposed correcting the
    # instruction to use `InterviewSessionTool.get_status`; what happened instead is that the
    # whole of the interview process was returned to the Interview Coordinator, so there is no
    # instruction left to correct and Jordan no longer holds the tool. Recorded rather than
    # deleted silently: an unresolvable read is sometimes evidence that the brief is wrong
    # rather than that the door is missing, and this is the case that showed it.
)


# Read on every agent's behalf by `build_and_run_crew`, and prepended to every task description
# in the crew before it starts. Declared once, and deliberately not folded into `AGENT_READS`:
# it is a property of the dispatch path rather than of any agent, and `build_and_run_agent` - the
# other dispatch, reachable from the API - performs none of it, so an agent run that way reads
# none of this.
CREW_DISPATCH_READS: tuple[Read, ...] = (
    Read(
        "agent_skill_notes",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "reviewer feedback about how each agent in the crew behaves. In the SYSTEM database - "
        "global across engagements, not scoped to this project",
    ),
    Read(
        "skills",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "the approved capabilities in the shared library, selected through "
        "agent_skill_assignments. In the SYSTEM database, and global for the same reason",
    ),
    Read(
        "output_changes",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "open change requests a reviewer raised against this crew's last outputs, in the "
        "reviewer's own words",
    ),
    Read(
        "validation_warnings",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "structural findings this crew is answerable for, recorded by the write hooks",
    ),
    Read(
        "interview_script_ledger",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "scripts a reviewer sent back to the agent rather than to another reviewer",
    ),
    Read(
        "script_reviews",
        Medium.DATABASE_TABLE,
        VIA_DISPATCH,
        "the note that came with each send-back",
    ),
)
