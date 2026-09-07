# agents/egress.py
"""What each tool reaches, and - for what this project is granted - where that actually is.

The question this exists to answer is an auditor's: **on this engagement, what leaves the
building?** Nothing in the codebase declared it before, so the only way to answer was to read
sixteen tool modules, and `ui/src/pages/DataArchitecture.tsx` - the page a client is shown -
was hand-typed and demonstrably incomplete: it names Anthropic forty-four times, lists "Web
fetch" as a tool two agents hold, and gives that tool no destination anywhere - neither agent's
external-services row mentions one, and the page's external-services table has no row for it.

Two layers, because "what it reaches" and "where that is" are different facts:

- `TOOL_EGRESS` declares what a tool reaches **in principle** - a vector store, a search
  service, any address the agent names, or nothing. One entry per tool
  class, keyed on the class name, because that is the only identity the graph can read out of
  `tool_map` without importing sixteen modules.
- `resolve_egress(tool_name, grants)` answers **where that is for this project**.
  `ChromaQueryTool` reaches a vector store either way; on a project granted
  `CLOUD_VECTOR_STORE` that store is Chroma Cloud and on one that is not it is the Chroma on
  this host. One declaration, with the project dependency in the resolver.

  **The resolver derives that dependency; it does not restate it.** `_mode_key` used to answer
  `"sensitive" if llm_mode == "sensitive" else "standard"` - the equality test the routing code
  was making, typed out a second time by hand, with a docstring saying as much. So a mode added
  to `api/models.py` and wired into the routing would have been collapsed to "standard" here,
  and the auditor's page would have reported egress that was not happening or, worse, missed
  egress that was. The resolver reads the capabilities the project holds, per reach, exactly as
  the routing sites do.

  **It is handed the resolved capabilities, not a mode name and not a slug.** A mode is not the
  last word on this codebase: `projects.force_local_inference` removes `HOSTED_INFERENCE` from
  whatever the mode grants, so a `standard` engagement can run on local models while its
  documents stay in Chroma Cloud, and `permits(mode, capability)` - the *declared* question -
  answers "Anthropic" for exactly that project. Asking it here reported an egress that was not
  happening, on the one page whose job is being right about where client material goes.

  A `frozenset[Capability]` rather than the slug, deliberately, and this module's purity is the
  argument: it opens no database and knows no project, which is why it can be asserted as a
  table. A slug would put a synchronous, fail-closed, cached database read inside the
  declaration - a second one, beside `api/services/chroma_client.py`'s - and would leave the
  declared question reachable, since a caller holding a slug can always resolve it to a mode by
  the short path. A set that has already been narrowed cannot be un-narrowed. Resolve it with
  `api.services.deployment_modes.project_grants(slug)` at the caller.

**What this module does not do is gate anything.** It declares. A declaration whose honest
content is "reaches the public internet, on a sensitive engagement, with no mode check" is
worth having precisely because it is uncomfortable, and three rows below read exactly that:

| Reach | Standard | Sensitive |
|-------|----------|-----------|
| `VECTOR_STORE` | Chroma Cloud | the Chroma on this host |
| `INFERENCE` | Anthropic's API | the local model on this host |
| `WEB_SEARCH` | Tavily | **Tavily** |
| `PUBLIC_WEB` | any address the agent names | **any address the agent names** |

There was a fifth reach, `AUTOMATION_WEBHOOK`, resolving in both modes to the n8n webhook and
onward to Slack as n8n was configured. Two tools declared it: `SlackNotifyTool`, and
`HumanInputTool`, which posted every review prompt - carrying whatever excerpt of its output
the agent chose to quote - before it began polling. n8n is retired, both those posts are gone,
`SlackNotifyTool` with them, and `HumanInputTool` now reaches nothing. The reach is removed
rather than left with no members, because an enum member no tool names is a destination a
reader has to rule out by searching.

CLAUDE.md states the secure-mode guarantee in absolute terms - every agent including PAM routes
locally on a sensitive project, no fallback. That is true of the **model**, and of **Chroma**,
and of nothing else: `llm_mode` is consulted in `get_llm_for_agent` and in `get_chroma_client`,
and in no tool that reaches out on its own. Whether the last two rows should be gated is a
later question; this module's job is to stop the answer depending on who read which file.

`INFERENCE` is the one reach that is not a tool's. Every agent runs on a model whether or not
it holds a single tool, so an egress set assembled from tools alone would omit the largest
thing that leaves the building - which is how the privacy page would have gone from naming
Anthropic forty-four times to not at all. `agent_destinations` adds it for every agent.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from api.services.deployment_modes import Capability

_TOOLS_DIR = Path(__file__).parent / "tools"

# The two extremes of what a project can be granted, and the only two sets this module names
# for itself. Neither is a mode: `frozenset(Capability)` is every capability there is, so a
# caller that forgets to resolve a project over-reports rather than under-reports **by
# construction** rather than because `standard` happens to be the fullest mode today.
#
# They exist so the "does anything move this?" derivation below can ask the question without
# naming a mode. `is_gated_by_grant` used to compare `"standard"` against `"sensitive"`, which
# read as a question about modes and answered one about grants.
ALL_GRANTS: frozenset[Capability] = frozenset(Capability)
NO_GRANTS: frozenset[Capability] = frozenset()


class Reach(Enum):
    """The kind of thing a tool reaches, with no host in it.

    A concrete host cannot be declared here: it is a property of the project, not of the tool,
    and writing one in would put the mode dependency in seventeen places instead of one.
    """

    NOTHING = "nothing outside this deployment"
    VECTOR_STORE = "a vector store"
    WEB_SEARCH = "a web search service"
    PUBLIC_WEB = "any web address the agent names"
    INFERENCE = "a language model"
    # The one reach where the request is not made by this deployment at all. See
    # `PARTICIPANT_IMAGE_EGRESS` below for why that difference is worth a member of its own
    # rather than being folded into `PUBLIC_WEB`.
    PARTICIPANT_BROWSER = "any web address an administrator configures, fetched by the participant"


@dataclass(frozen=True)
class Destination:
    """Where a reach actually goes for one project, and whether that is off this deployment.

    `leaves_deployment` is the auditor's column, and it is deliberately pessimistic where the
    honest answer is "it depends on a deployment setting": a vector store on a standard project
    is Chroma Cloud when `CHROMA_API_KEY` is set and the local Chroma when it is not, and this
    reports the first, because "may leave" has to read as "leaves" on a page a client relies on.
    """

    label: str
    leaves_deployment: bool


@dataclass(frozen=True)
class Egress:
    """One tool's declaration: what it reaches, and what of the client's material goes with it.

    `sends` is prose because nothing derives it. It is the sentence an auditor reads, so it says
    what actually travels rather than naming the mechanism - a tool that posts "the prompt" is
    posting whatever excerpt of the client's output the agent chose to quote in it.
    """

    reaches: Reach
    sends: str


_NOTHING_LEAVES = Egress(
    reaches=Reach.NOTHING,
    sends="nothing - it reads and writes this project's own database and outputs directory",
)


# Keyed on the tool's class name. `agents/graph.py` reads an agent's tools as class names out of
# `tool_map`'s source, so the class name is the one identity both sides already share.
TOOL_EGRESS: dict[str, Egress] = {
    # --- Reaches nothing: the project's own database, and files under projects/<slug>/ --------
    "SQLiteStateTool": _NOTHING_LEAVES,
    "MermaidRenderTool": Egress(
        reaches=Reach.NOTHING,
        sends="nothing - it writes the diagram to outputs/ and records the version",
    ),
    "ExcelOutputTool": Egress(
        reaches=Reach.NOTHING, sends="nothing - openpyxl writes the workbook locally"
    ),
    "WordOutputTool": Egress(
        reaches=Reach.NOTHING, sends="nothing - python-docx writes the document locally"
    ),
    "PowerPointOutputTool": Egress(
        reaches=Reach.NOTHING, sends="nothing - python-pptx writes the deck locally"
    ),
    "HtmlRoadmapTool": Egress(
        reaches=Reach.NOTHING,
        sends=(
            "nothing - the HTML it writes is self-contained, with no script, font, or style "
            "loaded from anywhere when the file is opened"
        ),
    ),
    "FinancialModelTool": Egress(
        reaches=Reach.NOTHING, sends="nothing - openpyxl writes the model locally"
    ),
    "DeriveRegistryTool": Egress(
        reaches=Reach.NOTHING,
        sends="nothing - it derives the registry from the current tree on disk",
    ),
    "InterviewSessionTool": Egress(
        reaches=Reach.NOTHING,
        sends=(
            "nothing - it writes interview_sessions rows and returns the participant links it "
            "builds from PUBLIC_URL. Sending those links is the campaign service's job, not "
            "this tool's, and that path goes out through Resend"
        ),
    ),
    "RunCrewTool": Egress(
        reaches=Reach.NOTHING,
        sends=(
            "nothing of its own - it writes a crew_runs row and dispatches a crew. Every agent "
            "in that crew carries its own egress, so PAM reaches everything its crews reach"
        ),
    ),
    # Here since n8n was retired, and the one row in this block that moved. It used to post the
    # review prompt - carrying whatever excerpt of its output the agent chose to quote - to the
    # automation webhook before the polling loop started, on every gated step, with no mode
    # check. That post is gone and nothing replaced it, so a gate now waits on the database
    # alone and notifies nobody. `agents/tools/human_input.py` says so at the top of the module,
    # because a reader arriving at this row would otherwise read a reassuring "nothing" without
    # learning that the reassurance is the absence of a notification rather than a safer one.
    "HumanInputTool": Egress(
        reaches=Reach.NOTHING,
        sends=(
            "nothing - it writes the review to this project's database and polls that database "
            "until a human decides. No notification is sent, on any channel, to anyone"
        ),
    ),
    # --- Reaches a vector store: the only tool egress `llm_mode` currently moves --------------
    "ChromaQueryTool": Egress(
        reaches=Reach.VECTOR_STORE,
        sends=(
            "the query text the agent composed, and it receives back the client's documents and "
            "interview answers in their own words"
        ),
    ),
    "DocumentIngestionTool": Egress(
        reaches=Reach.VECTOR_STORE,
        sends=(
            "the full text of every document under the project's docs/ directory, in chunks, "
            "for embedding"
        ),
    ),
    # --- Reaches out regardless of mode -------------------------------------------------------
    "TavilySearchTool": Egress(
        reaches=Reach.WEB_SEARCH,
        sends=(
            "the search query the agent composed. Nothing constrains what that query names, and "
            "no mode check stands between it and Tavily, so a sensitive project's organisation "
            "name reaches a third party as soon as an agent decides to search for it"
        ),
    ),
    "WebFetchTool": Egress(
        reaches=Reach.PUBLIC_WEB,
        sends=(
            "a GET to whatever address the agent named, from this server, with a browser "
            "user-agent. There is no allowlist, no mode check, and no record of the request"
        ),
    ),
}


# The reach every agent has, held by no tool, and the one sentence `TOOL_EGRESS` has nowhere to
# put. It is an `Egress` rather than a bare string so that a renderer treats the largest thing
# that leaves the building exactly as it treats a tool's row - `reaches` and `sends`, resolved
# through the same `(reach, mode)` table - instead of writing its own sentence beside a table it
# is otherwise reading. It is deliberately outside `TOOL_EGRESS`: that dict is held equal to the
# tool classes on disk, and inference is not a tool.
INFERENCE_EGRESS = Egress(
    reaches=Reach.INFERENCE,
    sends=(
        "every prompt the agent builds - its task description, the artefacts, interview "
        "answers and document excerpts it quotes, and the client's own words inside them - "
        "and it receives the model's reply"
    ),
)


# The reach that belongs to no agent and no tool, and is not made by this server.
#
# Two `ProjectSettings`-adjacent fields are rendered into `<img src>` on the interview page:
# `projects.brand_header_image_url`, written through `PATCH /{slug}/settings` and free text
# since it existed, and `project_agent_config.image_url`, which had **no production writer at
# all** until sp62's Setup section made the column live. Both are plain strings and neither is
# fetched by this deployment - they are handed to the participant's browser, which fetches them.
#
# That is why this is its own `Reach` rather than `PUBLIC_WEB`. `WebFetchTool` reaches the open
# web *from this server*, with this server's address; here the request is made by a person's
# browser, so what is disclosed is **theirs** - their IP, their user agent, and the fact that an
# interview is happening right now - and the interview page is one of the two doors CLAUDE.md
# documents as having no floor at all, because a participant has no login. Folding the two
# together would have made the auditor's answer to "whose address leaves?" wrong for one of them.
#
# It is ungated, on every mode, including `sensitive`. That is the finding rather than an
# omission, exactly as the Tavily and open-web rows below are: an engagement whose documents and
# inference this project keeps on the premises will still point its participants' browsers at
# whatever host an administrator typed. `agents/deployment_modes.EGRESS_GRANTS` is deliberately
# not extended for it - a capability nothing consults would read as a gate that is not there.
#
# `api/routers/agent_config.py` refuses a scheme a browser must not render (`javascript:`,
# `data:`) and deliberately permits off-site `http`/`https`, because the older of the two fields
# has always permitted it and closing one half would leave an operator unable to tell which. The
# real fix is a same-origin upload path serving **both** fields, and it is its own task; this row
# exists so that until then the reach is written down rather than implicit.
#
# **This is a declaration and nothing renders it yet.** `data_architecture()` assembles the
# privacy page from agents and the tools they hold, and this reach is neither - attributing it to
# an agent would be false. Surfacing it to the auditor is part of the same follow-up task.
PARTICIPANT_IMAGE_EGRESS = Egress(
    reaches=Reach.PARTICIPANT_BROWSER,
    sends=(
        "nothing of the client's material, and the participant's own connection: the interview "
        "page renders projects.brand_header_image_url and project_agent_config.image_url as "
        "<img src>, so if either names an off-site host, every participant's browser discloses "
        "its IP address, its user agent and the timing of an interview in progress to that host"
    ),
)


_NOWHERE = Destination(label="nothing outside this deployment", leaves_deployment=False)
_PARTICIPANT_IMAGE_HOST = Destination(
    label="any address an administrator configures, reached by the participant's browser",
    leaves_deployment=True,
)
_TAVILY = Destination(label="Tavily's search API", leaves_deployment=True)
_ANY_ADDRESS = Destination(label="any address the agent names", leaves_deployment=True)

# Which egress grant moves each reach. A reach absent from this table is not moved by anything
# the project is granted, and that is the finding rather than an omission: Tavily and the open
# web are reached on every project, by tools that ask nothing before reaching them.
#
# This is not a second copy of `EGRESS_GRANTS`. That table says what a *mode* is permitted to
# do; this one says which permission a *reach* depends on. The mode-to-capability mapping
# exists once, in `api/services/deployment_modes.py`, and this module derives from it - which
# is the whole point of the change that introduced it. Before, `_mode_key` re-stated the
# `== "sensitive"` test that `get_chroma_client` and `get_llm_for_agent` were making, by hand,
# and its docstring said so.
_REACH_GRANT: dict[Reach, Capability] = {
    Reach.VECTOR_STORE: Capability.CLOUD_VECTOR_STORE,
    Reach.INFERENCE: Capability.HOSTED_INFERENCE,
}


# `(reach, granted)` to a concrete destination, where `granted` is whether the project holds the
# capability `_REACH_GRANT` names for that reach. Both answers are written out for every reach,
# including the three whose two entries are the same object - an implicit "and otherwise the
# same" would make an ungated path look like an omission, and it is the opposite: it is the
# finding.
#
# **Keyed on the grant and not on the project**, which is what lets the two badges on the privacy
# page be independent. A per-project boolean could not express a project running local models
# over a cloud vector store - the shape `force_local_inference` produces today, and the mirror of
# the deferred sovereign mode. Do not collapse it back.
#
# The same object, not two with differently-worded labels. A destination is a place, and whether
# a grant moves it is derivable - `_is_gated` compares the two columns, which is precisely "no
# grant stands between this tool and that place". Wording the ungated rows differently would have
# hidden that behind a string comparison, and it did: the first draft of this table appended
# " - not gated on mode" to those labels and broke both the derivation and the guarantee that the
# granted column is always the fuller answer.
_DESTINATION: dict[tuple[Reach, bool], Destination] = {
    (Reach.NOTHING, True): _NOWHERE,
    (Reach.NOTHING, False): _NOWHERE,
    (Reach.VECTOR_STORE, True): Destination(
        label="Chroma Cloud, when CHROMA_API_KEY is set - otherwise the Chroma on this host",
        leaves_deployment=True,
    ),
    (Reach.VECTOR_STORE, False): Destination(
        label="the Chroma on this host", leaves_deployment=False
    ),
    (Reach.INFERENCE, True): Destination(
        label="Anthropic's API", leaves_deployment=True
    ),
    (Reach.INFERENCE, False): Destination(
        label="the local model on this host", leaves_deployment=False
    ),
    (Reach.WEB_SEARCH, True): _TAVILY,
    (Reach.WEB_SEARCH, False): _TAVILY,
    (Reach.PUBLIC_WEB, True): _ANY_ADDRESS,
    (Reach.PUBLIC_WEB, False): _ANY_ADDRESS,
    # The same object in both columns, like the two rows above it, and for the same reason: no
    # grant stands between a configured image address and the participant's browser, so
    # `_is_gated` derives `False` rather than a reader inferring it from two wordings.
    (Reach.PARTICIPANT_BROWSER, True): _PARTICIPANT_IMAGE_HOST,
    (Reach.PARTICIPANT_BROWSER, False): _PARTICIPANT_IMAGE_HOST,
}


def _destination(reach: Reach, grants: frozenset[Capability]) -> Destination:
    """Where `reach` actually goes for a project holding these grants.

    Per reach, not per project: a single "is this project the strict one" answer could not
    express a project that keeps its vector store on the premises while running hosted models,
    which is exactly the shape the deferred sovereign mode has - and its mirror, a project
    forcing local inference over Chroma Cloud, is a shape that exists today. Asking each reach
    for its own grant means both are described correctly on the privacy page by resolving the
    project's capabilities and nowhere else.

    A reach with no entry in `_REACH_GRANT` is treated as ungranted. That is the containing
    direction - the ungranted column is never the wider destination - and for the three reaches
    that have no grant today both columns are the same object anyway, so it changes no answer
    while a new gated reach is being wired up.
    """
    grant = _REACH_GRANT.get(reach)
    return _DESTINATION[(reach, grant is not None and grant in grants)]


def resolve_egress(tool_name: str, grants: frozenset[Capability]) -> Destination:
    """Where this tool reaches for a project holding these grants.

    Raises `KeyError` for a tool with no declaration rather than assuming it reaches nothing.
    `get_llm_for_agent` raises for an unregistered agent for the same reason: a default here
    would answer "nothing leaves" for a tool nobody has read yet, which is the one wrong answer
    that cannot be noticed.

    An empty grant set, by contrast, does not raise - it resolves to the on-premises column
    everywhere, which is what the routing code does with an undeclared mode too. The declaration
    must agree with the routing even when the routing is refusing something.
    """
    return _destination(TOOL_EGRESS[tool_name].reaches, grants)


def _is_gated(reach: Reach) -> bool:
    """Whether what a project is granted moves where `reach` goes.

    The two extremes, so the answer is "a grant decides this" rather than "these two particular
    modes disagree about it". The distinction stopped being academic when
    `force_local_inference` landed: on a `standard` project holding it, the *mode* moves the
    model calls nowhere at all, and a badge derived from two mode names would have gone on
    saying it did.
    """
    return _destination(reach, ALL_GRANTS) != _destination(reach, NO_GRANTS)


def is_gated_by_grant(tool_name: str) -> bool:
    """Whether what this project is granted moves where this tool reaches.

    Derived from the resolver rather than declared beside the tool, so a tool that is gated
    later cannot keep a stale `False` next to it. False for a tool that reaches nothing, which is
    the honest answer - there is nothing there for a grant to move.
    """
    return _is_gated(TOOL_EGRESS[tool_name].reaches)


def inference_is_gated_by_grant() -> bool:
    """The same question for the reach no tool carries, so the page need not ask it by hand.

    It was two `inference_destination` calls in `api/services/data_architecture_service.py`,
    naming two modes - the second copy of a derivation that belongs here beside the table it
    reads.
    """
    return _is_gated(Reach.INFERENCE)


def inference_destination(grants: frozenset[Capability]) -> Destination:
    """Where the agent's own model calls go. Not a tool, and held by every agent.

    Cross-checked against `get_llm_for_agent` in `tests/test_agent_egress.py`. It is no longer a
    second statement of that module's rule - both now resolve `HOSTED_INFERENCE` for the project
    rather than for its mode - but the cross-check stays, because "the page and the router
    consult the same table" and "the page says what the router does" are still two different
    claims.
    """
    return _destination(Reach.INFERENCE, grants)


def agent_destinations(
    tool_names: tuple[str, ...], grants: frozenset[Capability]
) -> tuple[Destination, ...]:
    """Everywhere one agent's work can reach on this project: its tools' destinations, plus its own.

    Sorted by label so the tuple is stable to compare and to display, and de-duplicated because
    four tools reaching the same place is one destination for an auditor.

    `Reach.NOTHING` resolves to a destination that is the absence of one, so it is left out
    rather than listed: an agent whose every tool stays local carries its inference destination
    alone, and that is the honest set. Enforcement, when it comes, wants `resolve_egress` per
    tool rather than this union - a set cannot say which tool put a member in it.
    """
    destinations = {inference_destination(grants)}
    for tool_name in tool_names:
        destination = resolve_egress(tool_name, grants)
        if destination != _NOWHERE:
            destinations.add(destination)
    return tuple(sorted(destinations, key=lambda d: d.label))


def tool_classes_on_disk() -> frozenset[str]:
    """Every tool class defined under `agents/tools/`, read from the source.

    A guard drawn from the graph's tool lists alone would only ever see the classes `tool_map`
    names, so a tool class that exists and is declared but reaches no agent would be invisible
    to it - which is how `ChainlitHumanInputTool` stayed declared, and substituted in at run
    time, without any comparison mentioning it. Comparing the declaration with the classes that
    actually exist on disk closes that without an exception list, and it also catches the next
    tool written but not yet declared.

    Read by parsing rather than importing, for `agents/graph.py`'s reason: importing the
    package pulls in every tool module, one of which builds its description from the graph.
    Two passes, so that a subclass of a tool class defined in another file is still recognised.
    """
    modules = {
        path: ast.parse(path.read_text(), filename=str(path))
        for path in sorted(_TOOLS_DIR.glob("*.py"))
    }
    found: set[str] = set()
    for _ in range(2):
        for tree in modules.values():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {
                    base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    for base in node.bases
                }
                if "BaseTool" in bases or bases & found:
                    found.add(node.name)
    return frozenset(found)
