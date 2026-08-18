# agents/charter.py
"""What each crew is for, and what can start it.

The two facts the graph was still missing. `_CREW_AGENT_NAMES` says who runs in a crew and
`CREW_DEPENDENCIES` says what it waits on, but nothing said what a crew is **for** - the labels
are two or three words - and nothing anywhere enumerated the ways a crew can be started. Slice
1's rule holds: a fact a registry already owns is read, never restated, so the agents, the
dependencies and the display name are absent from this file and come from the graph.

## Why triggers are declared here rather than derived

Three dispatch paths reach a crew, and no two of them agree about which crews they can reach.
Nothing in the code holds them together, and each is enumerable only by reading a different
module - one an `elif` ladder, one an approval graph, and one a set of CrewAI task descriptions.
`DISPATCH_PATHS` below names each path and where it lives; `CREW_CHARTER` says which of them can
start each crew. `tests/test_crew_charter.py` derives every one of those sets from the code that
implements it and holds this declaration equal to it, so what is written here is checked rather
than believed.

The extensibility reason for declaring them at all: a crew outside this application - technical
requirements handed to a coding-agent crew - is a graph entry whose dispatch is a webhook rather
than a factory. That is expressible only if "what starts this crew" is a field.

## "Can start" is not "will start"

`Trigger.APPROVAL_CASCADE` is a capability, not a schedule. `start_ready_downstream` reaches a
crew only once every crew it depends on has been committed, and the graph already carries that
condition as `CrewNode.depends_on` - so this file states the capability and does not restate the
gate. A crew whose only trigger is `APPROVAL_CASCADE` therefore starts on an approval and never
on its own.

Nothing is time-triggered. `scheduler_service` runs one job, `pam_daily_report`, which computes a
report and emails a link; no handler in `JOB_REGISTRY` reaches a crew dispatcher, and
`test_no_scheduled_job_starts_a_crew` keeps it that way. There is no `Trigger` for the clock
because there is nothing for it to describe, and inventing one would put a reassuring row on the
page for a mechanism that does not exist.

## A path can exist and be broken, and this must be able to say so

**`Charter.defect`** says that of a crew: no path can start it, because every path funnels
through the same call in `build_and_run_crew`. `requirements` carried one - that call passed it
three arguments its factory does not take, and raised `TypeError` before an agent was built -
until the call site was corrected. No crew declares one now, and the guard below is what keeps
that honest in both directions: it derives the truth from the call sites and the factory
signatures, so a defect that is fixed and left declared fails, and a new one that is introduced
and not declared fails too.

**`DispatchPath.defect`** says it of a path instead, and is currently declared by none. It was
written for `CHAINLIT_CONSOLE`, a second dispatch ladder that had never learned about two crew
renames or about crew factories ceasing to take `llm_mode`, so all five of its branches raised.
That console is gone, and with it the per-branch derivation that held its prose to the code. The
field is kept, because a crew dispatched by webhook rather than by factory is the extensibility
case this file exists for and such a path can break on its own - but
`test_no_dispatch_path_declares_a_defect_nothing_derives` refuses a defect written here until
something derives it, so the field cannot go back to carrying an unchecked claim. Today a broken
path is a broken crew, and `Charter.defect` is where that belongs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Trigger(Enum):
    """One way a crew can be started. The value is the id; the prose is on `DispatchPath`."""

    REST_RUN = "rest_run"
    APPROVAL_CASCADE = "approval_cascade"
    PAM_ORCHESTRATION = "pam_orchestration"


@dataclass(frozen=True)
class DispatchPath:
    """One dispatch path, and where in the code it is.

    `entrypoint` and `dispatcher` are what make a named trigger checkable rather than decorative:
    the entrypoint is the function - or class - that starts a crew, and `dispatcher` is the name
    its body must call to do it. The guard resolves the entrypoint out of its module's source and
    fails if either has moved, so a trigger can only be named for a path that genuinely exists.

    Resolved by parsing the module file rather than importing it, for the reason
    `agents/graph.py` and `agents/egress.py` already parse rather than import: a dispatch
    module pulls in the crew factories and reads settings at module scope, and a path whose
    module is merely heavy to import must not look absent.

    `doors` are the outside-facing handlers a request arrives at before it reaches the
    entrypoint. They are a separate field because the door and the dispatcher are rarely the same
    function and a reader needs the door: `POST /projects/{slug}/commits` is what an approver
    presses, and `start_ready_downstream` is what it eventually reaches.
    """

    trigger: Trigger
    label: str
    doors: tuple[str, ...]
    entrypoint: str
    dispatcher: str
    note: str
    defect: str | None = None


# Keyed on the trigger, so a charter naming a trigger with no path here cannot resolve.
DISPATCH_PATHS: dict[Trigger, DispatchPath] = {
    Trigger.REST_RUN: DispatchPath(
        trigger=Trigger.REST_RUN,
        label="An administrator starts one crew from the dashboard",
        doors=("api/routers/run.py:run_crew",),
        entrypoint="api/routers/run.py:run_crew",
        dispatcher="dispatch_crew",
        note=(
            "`POST /projects/{slug}/run` with a crew name. The name is an unconstrained string - "
            "`RunRequest.crew` is `str | None` with no enumeration - so this path offers every "
            "crew in the graph, and an unknown name reaches `build_and_run_crew`'s final `else`. "
            "A request naming neither a crew nor an agent is refused with 400 rather than "
            "defaulting, so this path starts nothing that was not asked for. "
            "One of the two inbound HTTP doors, and the only one that starts a single crew: the "
            "other is `/orchestrate`, which is the orchestration path's door. "
            "`req.agent` on the same endpoint starts a single agent rather than a crew, which is "
            "not a crew dispatch and carries none of the feedback the crew path injects"
        ),
    ),
    Trigger.APPROVAL_CASCADE: DispatchPath(
        trigger=Trigger.APPROVAL_CASCADE,
        label="An approver commits the crew above, and this one starts",
        doors=("api/routers/commits.py:create_commit",),
        entrypoint="api/services/autostart_service.py:start_ready_downstream",
        dispatcher="dispatch_crew",
        note=(
            "Reached after the commit is recorded, never before, and only for crews directly "
            "below the one committed - so a crew that no other crew depends on is unreachable "
            "this way, and `discovery_mapping`, which nothing precedes, can never start here. "
            "Readiness is a state rather than a transition, so a later re-approval re-runs the "
            "crew below"
        ),
    ),
    Trigger.PAM_ORCHESTRATION: DispatchPath(
        trigger=Trigger.PAM_ORCHESTRATION,
        label="Pamela runs the pipeline, and dispatches this crew as one of her steps",
        doors=(
            "api/routers/orchestrate.py:orchestrate_project",
            "api/routers/assignment.py:advance_orchestration",
        ),
        entrypoint="agents/tools/run_crew.py:RunCrewTool",
        dispatcher="build_and_run_crew",
        note=(
            "Two doors for one path, because the orchestration is two-phase: `/orchestrate` "
            "starts phase 1, and confirming the stakeholder assignments advances it to phase 2. "
            "Both build a PAM crew whose tasks each call `RunCrewTool`, which is the thing that "
            "actually dispatches. PAM is the only path that sets `orchestration_run_id` on the "
            "`crew_runs` row, which is why one crew is hers alone. Her tool's description is "
            "generated from the whole graph, so she is offered all nine crews while her tasks "
            "name six - the other three are reachable only if she improvises, and one of those "
            "three cannot be built at all"
        ),
    ),
}


@dataclass(frozen=True)
class Charter:
    """What one crew is for, and what can start it.

    `purpose` is prose because nothing derives it, and it is written for the reader of the
    privacy page rather than for a developer: it says what the crew does with the client's
    material, which "Assessment Design" does not. It is deliberately not the docstring of the
    crew factory - four of the nine have none, and two of the rest document their arguments.

    `defect` is `None` for a crew that runs. When it is set, every trigger in `triggers` is
    nominal: the path exists, and taking it fails. It is per crew rather than per trigger
    because the case it was written for is a mismatch inside `build_and_run_crew`, which every
    path goes through - a per-trigger field would invite the same sentence to be written three
    times and to disagree with itself.
    """

    purpose: str
    triggers: tuple[Trigger, ...]
    note: str = ""
    defect: str | None = None


CREW_CHARTER: dict[str, Charter] = {
    "discovery_mapping": Charter(
        purpose=(
            "Builds the value chain - the organisation's activities as a tree, every node "
            "carrying a permanent id - and the value levers hung on it. It reads the documents "
            "the client uploaded and the sector knowledge base to do so. Everything downstream "
            "anchors to those ids, which is why this crew runs first and why no other crew may "
            "rewrite the chain"
        ),
        triggers=(Trigger.REST_RUN, Trigger.PAM_ORCHESTRATION),
        note=(
            "No approval can start it: nothing precedes it, so it is never downstream of a "
            "commit"
        ),
    ),
    "assessment_design": Charter(
        purpose=(
            "Writes one interview script per active value chain activity, so that every part of "
            "the organisation the chain names has an instrument designed to examine it. Coverage "
            "is checked on every write and the gaps are reported back into the next run, so the "
            "set converges over several runs rather than in one"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE),
    ),
    "stakeholder_management": Charter(
        purpose=(
            "Reports which activities and roles have nobody assigned to speak for them, so the "
            "gaps in the interview programme are visible before the interviews begin"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE),
    ),
    "discovery_interviews": Charter(
        purpose=(
            "Plans the interview programme, conducts it, and synthesises the answers into themes "
            "and strategic requirements, each anchored to the value chain node the insight came "
            "from. The interviewees' own words are what this crew works from"
        ),
        triggers=(Trigger.PAM_ORCHESTRATION,),
        note=(
            "Pamela's alone, and not by convention: `build_and_run_crew` refuses it unless the "
            "`crew_runs` row carries an `orchestration_run_id`, and hers is the only path that "
            "sets one. It also refuses it unless the project's `interview_method` is 'agent'. "
            "`_PAM_DISPATCHED_ONLY` in `autostart_service` records the first of those, but the "
            "reason is a property of `build_and_run_crew` and binds the REST path just as much"
        ),
    ),
    "value_design": Charter(
        purpose=(
            "Turns the challenges the interviews evidenced, and the value levers, into value "
            "propositions - then scores and ranks them into a portfolio"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE, Trigger.PAM_ORCHESTRATION),
    ),
    "capabilities": Charter(
        purpose=(
            "Records the current architecture - systems, data entities and organisational "
            "structure - from the client's own documents alone, and identifies the initiatives "
            "that would close the gap between that and the propositions"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE, Trigger.PAM_ORCHESTRATION),
    ),
    "requirements": Charter(
        purpose=(
            "Captures the requirements each initiative implies, stated against what already "
            "exists, then analyses the whole set for completeness, consistency and conflict"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE),
    ),
    "delivery": Charter(
        purpose=(
            "Sequences the initiatives into a roadmap - the periods, the time axis, and when "
            "each proposition's benefit is realised"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE, Trigger.PAM_ORCHESTRATION),
        note=(
            "Needs the project's value streams and stakeholder groups set first. "
            "`REQUIRED_CONFIG_KEYS` is checked by the approval path before it inserts a run, so "
            "an approval reports the crew as waiting on its configuration instead of starting a "
            "run certain to fail"
        ),
    ),
    "business_plan": Charter(
        purpose=(
            "Assembles the business plan and its illustrations - the case for change, the "
            "propositions, the costs by complexity, and the roadmap - into the documents a board "
            "reads"
        ),
        triggers=(Trigger.REST_RUN, Trigger.APPROVAL_CASCADE, Trigger.PAM_ORCHESTRATION),
        note=(
            "Has never completed a real run. It only became buildable when "
            "`visual_illustrator` was registered as an agent; before that its factory raised "
            "before its first task. Treat its first run as an experiment"
        ),
    ),
}


# Crew names a dispatch path offers that are not crews. Recorded rather than tidied away,
# because each one is a dispatch that reports a result while having done nothing - the exact
# failure `agents/graph.py` exists to end - and because the guard that holds every offered name
# against the graph needs somewhere honest to put them.
#
# Two entries left with the Chainlit console: `discovery` and `architecture`, the pre-rename
# names of `requirements` and `capabilities`. No dispatch path offers either now, and the guard
# fails on a stale entry as readily as on an unrecorded name.
NOT_A_CREW: dict[str, str] = {
    "questionnaire_builder": (
        "An alias `build_and_run_crew` still accepts for `assessment_design`, kept for stored "
        "`crew_runs` rows in other environments. It builds the right crew, so it is harmless - "
        "but it is a tenth name the REST path answers to and no registry knows"
    ),
}
