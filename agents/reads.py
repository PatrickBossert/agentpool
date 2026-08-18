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
the route is what breaks. `interview_sessions` is a real read for the Stakeholder Interviewer,
who reaches it through `InterviewSessionTool`, and an unresolvable one for the Stakeholder
Manager, who is told to reach it through `SQLiteStateTool`. A declaration naming only the source
would record those as the same fact.

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
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    """

    source: str
    medium: Medium
    via: str
    note: str


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
    return Read("{slug}_docs", Medium.VECTOR_COLLECTION, "ChromaQueryTool", note)


def _sector_knowledge(note: str) -> Read:
    return Read(
        "sector_{sector}",
        Medium.VECTOR_COLLECTION,
        "ChromaQueryTool",
        f"{note}. Shared across every engagement in this sector - it carries no slug",
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
            "all active L1, L2 and L3 nodes, which is the full coverage target",
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
    UnresolvableRead(
        agent_id="stakeholder_manager",
        source="stakeholder_assignments",
        instructed_via="SQLiteStateTool",
        finding=(
            "A database table, and `SQLiteStateTool` resolves a key through `current_output_path` "
            "against `agent_outputs`, so it can only ever see an output type. No tool this agent "
            "holds can read the table either - `InterviewSessionTool` has four operations and "
            "none of them touches it. This agent has therefore never known who is assigned to "
            "what, while its whole task is to find the gaps in that. The same table does reach "
            "the Interview Coordinator, injected by `build_and_run_crew`, which is where the fix "
            "would come from."
        ),
    ),
    UnresolvableRead(
        agent_id="stakeholder_manager",
        source="interview_sessions",
        instructed_via="SQLiteStateTool",
        finding=(
            "A database table, unreadable through `SQLiteStateTool` for the same reason - but "
            "this agent already holds `InterviewSessionTool`, whose `get_status` operation "
            "returns exactly the pending/active/completed/abandoned counts step 3 asks for. A "
            "one-line correction to the task description, not a new door."
        ),
    ),
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
