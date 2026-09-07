# api/services/skills_service.py
"""LLM helpers for the agent skills library.

**Two doors, and they route differently. Which one a helper is on is decided by whether it has
a project, and there is no default:**

| Door | Helpers | Model |
|------|---------|-------|
| The global library, reached from the admin skills page | `check_specificity`, `extract_skill`, `extract_skills_many` | hosted Haiku, on every deployment |
| An agent's proposal, made on one engagement | `propose_skill` -> `find_duplicate_skill` | whatever that project's mode binds to the `fast` tier |

The first is the documented always-hosted exception, and it survives because both halves of
its justification still hold there: the library is global across engagements, those endpoints
carry no slug, and there is therefore no `llm_mode` to route by.

**Neither half held for the second door, which is why it moved.** `propose_skill` takes the
slug - it is the provenance a reviewer sorts the queue on - so a mode was available to route
by all along; and the text is no longer reviewer feedback about an agent's behaviour but the
agent's own generalisation from a correction made on a named engagement, which is free to
name the client, its people, or its systems in the course of stating the rule. The exemption
was written about the door rather than about the data, and it outlived the data changing.

So `find_duplicate_skill` goes through `project_completion` in `api/services/llm_client.py`,
like every other non-crew call on this codebase. It takes the slug as its first argument, not
as a keyword with a default: CLAUDE.md's rule is that a forgotten slug must never become a
silent hosted call, and an optional parameter falling back to hosted is exactly that. Never
build a provider client here for a project's material.

`propose_skill` is the write door onto the skills queue, used by an agent that has just
revised its work and wants the general rule behind the correction remembered. It asks the
project's model one question - "is this the same rule as one we already hold?" - and
**everything else about it is deterministic**: the naming, the insert, the increment. The
model is asked for a judgement, never for a side effect, and a model that is unreachable,
unconfigured, slow, or incoherent degrades to "not a duplicate" rather than failing the run
the proposal is attached to.
"""
from __future__ import annotations

import asyncio
import json
import logging

from anthropic import AsyncAnthropic
from api.config import get_settings
from api.services import llm_client

log = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"

# The comparison's own budget, imposed here because `project_completion` has none of its own
# and both of the clients behind it are sized for a caller that is waiting: the Anthropic SDK
# defaults to 600 seconds and two retries, and the shared local client to 120. This path runs
# inside a crew run, attached to a revision that is already finished, so twenty seconds is the
# whole of it - `asyncio.wait_for`, the same way the elaboration press bounds its own call.
_COMPARISON_TIMEOUT_SECONDS = 20.0

# A judgement about two short sentences. `deep` would put the comparison on the same model the
# agent's own work runs on, which is a great deal of machinery for "do these say the same
# thing", and on a sensitive project it would contend with the agent for a loaded local model -
# see docs/runbook-local-models.md on OLLAMA_MAX_LOADED_MODELS.
_COMPARISON_TIER = "fast"


async def propose_skill(
    agent_name: str,
    description: str,
    source_project: str,
    source_ref: str | None,
    *,
    name: str | None = None,
) -> dict:
    """Record a skill an agent proposes, and return what happened.

    The queue an agent writes into. The proposal is stored `status='pending'`, and
    `_fetch_skill_notes` in `api/services/run_service.py` injects `status='approved'` skills
    alone - so nothing proposed here reaches any prompt until a human approves it. That is
    the whole safety argument for letting an agent propose freely, and it is asserted against
    what reaches the prompt rather than against what the table holds
    (`tests/test_skill_proposal.py`).

    `agent_name` is the snake id the crews dispatch by - `interaction_designer`. It is
    resolved to the role name `agent_skill_assignments` is keyed by before the assignment is
    written, because that is the name `_fetch_skill_notes` looks the skill up under; storing
    the snake id would file a proposal that no approval could ever inject.

    A near-duplicate of a rule this agent already holds is **not** a second row. A match is the
    second occurrence of the same rule, which is the evidence a reviewer approves from, so it
    increments `occurrences` on the row already there and records the new provenance beside it.
    Both the approved skills and the pending suggestions are candidates: the second occurrence
    of a rule nobody has approved yet is exactly what the queue needs to sort on.

    `source_project` is the engagement the correction was made on. It is provenance a reviewer
    sorts the queue on **and** the slug the comparison is routed by, so it is required and
    raises when blank rather than being allowed to mean "no project". A proposal whose slug
    went missing has no mode to honour, and the two things it could quietly become - a hosted
    comparison, or a hosted-by-default fallback - are exactly what CLAUDE.md's seam rule
    forbids. Raising is safe here in the way it would not be deeper down: the only production
    caller is `SkillProposalTool`, whose whole contract is that nothing it does can fail the
    run.

    It is **stripped once and the stripped form is what is both routed on and filed**. An
    earlier version routed `find_duplicate_skill` on the stripped slug and wrote the caller's
    original into `skills` and `skill_occurrences`, so a slug carrying stray whitespace was
    two spellings of one fact: the key the mode was read from, and the provenance the queue
    groups by, could disagree. Not reachable through today's only caller, which passes the
    run's own slug - but a fact with two spellings is what this file argues against elsewhere.

    Returns `{"action", "skill_id", "status", "occurrences", "name", "agent"}`, where `action`
    is `"created"` or `"incremented"` - which is why this returns what happened rather than an
    id.
    """
    from api.database import get_system_connection, insert_skill, record_skill_occurrence

    slug = (source_project or "").strip()
    if not slug:
        raise ValueError(
            "propose_skill requires the project the correction was made on: the rule the agent "
            "wrote is that engagement's material, and which model may compare it is a property "
            "of the project. Defaulting would route a sensitive project's content to a hosted "
            "model."
        )
    role = _role_name_for(agent_name)
    skill_name = (name or "").strip() or _derive_skill_name(description)
    # Read, compare, write - and **no connection is held across the comparison**, which is a
    # network call. An earlier version held one and justified it as closing the window in
    # which two proposals of the same rule each find no duplicate and each create a row.
    # That justification was false: `get_system_connection` opens a fresh connection per
    # call, so two overlapping proposals hold two of them and no transaction spans the read
    # and the write either way. The window is real, it is open, and it is accepted - the
    # failure is a second pending row a reviewer can see and merge, and closing it properly
    # would mean re-reading the candidates under `BEGIN IMMEDIATE` and re-running the model
    # call when they have changed, which is a second network call to avoid a benign row.
    async with get_system_connection() as conn:
        candidates = await _rules_already_held(conn, role)

    match_id = await find_duplicate_skill(slug, description, candidates)

    async with get_system_connection() as conn:
        if match_id is not None:
            occurrences = await record_skill_occurrence(
                conn,
                skill_id=match_id,
                description=description,
                source_project=slug,
                source_ref=source_ref,
                proposed_by_agent=agent_name,
                bump=True,
            )
            # `next(..., None)`, never a bare `next`. A generator that finds nothing raises
            # StopIteration, which inside an async function surfaces as `RuntimeError:
            # coroutine raised StopIteration` - **after** the row above has already been
            # incremented, so the run dies having half-done the write. A proposal must never
            # be able to fail the revision it is attached to, and that includes the paths
            # nothing can currently reach.
            held = next((c for c in candidates if int(c["id"]) == match_id), None)
            if occurrences and held is not None:
                return {
                    "action": "incremented",
                    "skill_id": match_id,
                    "status": held["status"],
                    "occurrences": occurrences,
                    "name": held["name"],
                    "agent": role,
                }
            # Either the row went between the read and the write - a delete from another
            # process, genuinely reachable now the comparison no longer runs inside the
            # read's connection - or the match was not among the candidates that were read,
            # which the guard in `find_duplicate_skill` should already have refused. Both are
            # worth a line: the second means that guard has been bypassed.
            log.warning(
                "skills: matched skill %s could not be counted (row gone, or not among the "
                "candidates read); creating a proposal for %s instead", match_id, role,
            )

        skill_id = await insert_skill(
            conn,
            name=skill_name,
            description=description,
            source="revision",
            source_project=slug,
            source_ref=source_ref,
            proposed_by_agent=agent_name,
            # Never anything else. An approved proposal is injected into every future run of
            # this agent, on every engagement.
            status="pending",
            agents=[role],
        )
        occurrences = await record_skill_occurrence(
            conn,
            skill_id=skill_id,
            description=description,
            source_project=slug,
            source_ref=source_ref,
            proposed_by_agent=agent_name,
            # The `skills` row already counts this one - `occurrences` defaults to 1.
            bump=False,
        )
    return {
        "action": "created",
        "skill_id": skill_id,
        "status": "pending",
        "occurrences": occurrences or 1,
        "name": skill_name,
        "agent": role,
    }


# The statuses a proposal is compared against. `rejected` is deliberately absent: a human has
# already refused that rule, and incrementing a rejected row would file the evidence where the
# queue does not look - the recurrence would be recorded and invisible. A re-proposal of a
# refused rule becomes a fresh pending row, which is the only place a reviewer will see it.
_DEDUP_STATUSES = ("pending", "approved")


async def _rules_already_held(conn, role: str) -> list[dict]:
    """The candidate rules a proposal is compared against, for one agent.

    Keyed on the **role name** (`Interaction Designer`), never the snake id, because that is
    what `agent_skill_assignments` holds - a lookup by snake id would find no candidates
    ever, and the recurrence signal would silently never fire while proposals kept
    accumulating and the feature kept appearing to work.
    """
    from api.database import fetch_skills

    held: list[dict] = []
    for status in _DEDUP_STATUSES:
        held.extend(await fetch_skills(conn, agent_name=role, status=status))
    return held


async def find_duplicate_skill(
    slug: str, description: str, candidates: list[dict]
) -> int | None:
    """Return the id of the candidate stating the same rule as `description`, or None.

    By meaning, not by text. The two ways of saying "the welcome carries privacy, the framing
    carries purpose" share barely a word, and a string comparison would call them distinct -
    at which point the second occurrence is filed as a fresh guess and the evidence the queue
    sorts on never accumulates.

    **Routed by the project, on `slug`.** The rule being compared was written by an agent about
    work it did on that engagement, so it is that engagement's material and goes wherever that
    engagement's material is allowed to go - the local model on a sensitive project, hosted
    Haiku on a standard one. `slug` is the first positional argument and there is no default:
    the module docstring says why an optional one would be the defect rather than the
    convenience.

    Both directions of error are guarded, and they are not symmetric. Calling two distinct
    rules the same **loses a rule**, which is worse than a duplicate row a reviewer can see and
    reject, so the prompt insists on same *behaviour* rather than same subject, and every
    failure - no key, a refusal, unparseable JSON, an id that was never offered, a project with
    no model configured for this tier, a model that will not answer inside the budget -
    resolves to None and a new row.

    `LocalModelUnavailable` is deliberately among those. It is the standing state of a
    sensitive project whose `deep` tier is configured and whose `fast` tier is not: its crews
    run and its comparisons cannot be made. Refusing the proposal outright would throw away the
    lesson to protect a deduplication; degrading records it, un-deduplicated, and says so in the
    log every time. **Nothing here ever answers by sending the text somewhere the project's
    grants refuse** - that is the one failure this must not have, and it is why the degradation
    is to "not a duplicate" rather than to a hosted retry.
    """
    if not candidates:
        return None
    offered = {int(c["id"]): c for c in candidates}
    try:
        reply = await asyncio.wait_for(
            llm_client.project_completion(
                slug,
                _COMPARISON_TIER,
                messages=[{
                    "role": "user",
                    "content": json.dumps({
                        "proposed": description,
                        "held": [
                            {"id": int(c["id"]), "name": c.get("name"),
                             "description": c.get("description")}
                            for c in candidates
                        ],
                    }, indent=2),
                }],
                max_tokens=256,
                system=(
                    "You compare a proposed behaviour rule for an AI agent against the rules that "
                    "agent is already held to, and decide whether the proposal states one of them "
                    "again in different words.\n\n"
                    "Two rules are the same when following either one produces the same behaviour. "
                    "Wording, length, and word choice are irrelevant - a rule restated with no "
                    "shared vocabulary is still the same rule.\n\n"
                    "Two rules about the same subject are NOT the same rule unless they instruct "
                    "the same behaviour. 'The welcome carries privacy' and 'the welcome names the "
                    "interviewer' are both about the welcome and are different rules. When in "
                    "doubt, answer null: a duplicate a reviewer can see costs less than two "
                    "distinct rules merged into one.\n\n"
                    "The input is JSON: `proposed` is the new rule, `held` is the list of rules "
                    "already held, each with an `id`.\n\n"
                    "Respond with valid JSON only, no other text:\n"
                    '{"match_id": <the id of the rule the proposal restates, or null>, '
                    '"reason": "one sentence"}'
                ),
            ),
            timeout=_COMPARISON_TIMEOUT_SECONDS,
        )
        answer = json.loads(_strip_code_fences(reply.strip()))
        match_id = answer.get("match_id")
    except Exception:
        # Loud, and still "not a duplicate". The direction is right - a comparison must never
        # fail the revision it is attached to - but silence is not, because a comparator that
        # is failing on every call is indistinguishable at every later layer from one that is
        # working and finding nothing: `occurrences` stays 1 either way, which is also what a
        # healthy new queue looks like. This line is the only thing that can tell them apart.
        log.warning("skills: duplicate comparison failed, treating as new", exc_info=True)
        return None
    if match_id is None:
        return None
    try:
        match_id = int(match_id)
    except (TypeError, ValueError):
        log.warning("skills: duplicate comparison answered a non-numeric id %r", match_id)
        return None
    # Never an id that was not offered. A hallucinated one would increment an unrelated
    # skill - the one failure of this comparison that is silent at every later layer.
    if match_id not in offered:
        log.warning(
            "skills: duplicate comparison answered id %s, which was not among the %d offered",
            match_id, len(offered),
        )
        return None
    return match_id


def _strip_code_fences(raw_text: str) -> str:
    """Unwrap ```` ```json ```` fencing, if the model wrapped its JSON in it.

    One copy, two callers. `extract_skills_many` has defended against this since it was
    written, because this model does it; `find_duplicate_skill` asks for bare JSON in exactly
    the same way and needs exactly the same defence. A second copy would be free to drift, and
    the drift is invisible: a fenced reply the comparator cannot parse turns recurrence - the
    whole point of the duplicate check - off permanently, and looks like a queue with no
    duplicates in it.
    """
    if not raw_text.startswith("```"):
        return raw_text
    inner = raw_text.split("```")[1]
    if inner.startswith("json"):
        inner = inner[4:]
    return inner.strip()


class UnknownProposingAgent(ValueError):
    """A proposal named an agent that resolves to no skills-table name.

    Raised rather than guessed, and a caller that must not fail - `SkillProposalTool` - is the
    right place to swallow it. See `_role_name_for`.
    """


def _role_name_for(agent_name: str) -> str:
    """Map a snake agent id to the role name `agent_skill_assignments` is keyed by.

    Imported from `run_service` rather than restated, because that map is what
    `_fetch_skill_notes` reads with - a second copy here would be free to drift, and a
    proposal filed under a name the injection does not look up is invisible rather than
    wrong. The import is function-local for the reason `run_service`'s own imports are:
    everything downstream of the crew graph is import-order sensitive.

    **Three cases, and the third refuses.** A known snake id resolves; a name that is already
    a role name is returned unchanged, which is the admin door's vocabulary and must not be
    mangled; anything else raises `UnknownProposingAgent`.

    The passthrough used to cover the third case too, and it re-opened the exact trap this
    design devotes a section to. `visual_illustrator` is dispatched by the `business_plan`
    crew and was in no map, so its proposal was filed under the snake id, reported `created`
    with an id, approvable in the queue, approved - and injected into nothing, for ever. An id
    that cannot be resolved is one whose proposal nobody can ever action, and inventing a name
    for it produces a row that looks exactly like a working one. Refusing is loud; guessing is
    not.
    """
    from api.services.run_service import _SNAKE_TO_DISPLAY

    if agent_name in _SNAKE_TO_DISPLAY:
        return _SNAKE_TO_DISPLAY[agent_name]
    if agent_name in set(_SNAKE_TO_DISPLAY.values()):
        return agent_name
    raise UnknownProposingAgent(
        f"{agent_name!r} is neither an agent id nor a skills-library role name, so a proposal "
        f"filed under it could never be injected into any prompt. Add it to _SNAKE_TO_DISPLAY "
        f"in api/services/run_service.py."
    )


def _derive_skill_name(description: str) -> str:
    """A title for a proposal that arrived with a rule and no name.

    Deterministic on purpose: naming is not worth a model call on a path that must not fail
    the run it is attached to. A caller with a better title passes `name`.
    """
    first_line = description.strip().split("\n")[0]
    words = first_line.split()[:5]
    derived = " ".join(words).rstrip(".,;:-").strip()
    return derived or "Proposed Agent Skill"


async def check_specificity(description: str) -> dict:
    """Return {is_specific, reason, suggestion}.

    is_specific=True means the description mentions client-specific details
    (org names, people, suppliers, contracts) that would make it unsuitable
    for reuse across projects.
    """
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=(
            "You review skill descriptions for an AI agent skill library used across multiple "
            "client engagements. Determine whether the description contains client-specific "
            "references — organisation names, people, products, systems, suppliers, contracts, "
            "or locations — that would make it unsuitable for reuse in a different client context.\n\n"
            "Respond with valid JSON only, no other text:\n"
            '{"is_specific": true/false, "reason": "why it is specific or null", '
            '"suggestion": "reworded generic version or null"}'
        ),
        messages=[{"role": "user", "content": f"Skill description to check: {description!r}"}],
    )
    try:
        return json.loads(resp.content[0].text.strip())
    except Exception:
        return {"is_specific": False, "reason": None, "suggestion": None}


async def extract_skills_many(raw_input: str) -> list[dict]:
    """Return [{name, description}] — one entry per distinct skill identified in raw_input."""
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=(
            "You analyse free-form text submitted by a user who wants to teach an AI agent new skills. "
            "The text may be a mix of feature requests, observations, outputs, and process descriptions. "
            "Extract the distinct, reusable, transferable skills embedded in the text.\n\n"
            "NAMING RULES — the name must:\n"
            "- Be 3–5 words, title-cased\n"
            "- Capture the specific capability (e.g. 'Governance Layer Interview Design', 'Data Maturity Probing', 'Authority Boundary Flagging')\n"
            "- Never be generic ('Skill from input', 'New skill', 'Agent skill')\n\n"
            "DESCRIPTION RULES — each description must:\n"
            "- Be 1–3 sentences in imperative voice ('Do X. Never Y. Before Z, check W.')\n"
            "- Be generic — remove all client names, project names, and specific organisations\n"
            "- Be self-contained and actionable\n\n"
            "Extract between 1 and 5 distinct skills. "
            "Return valid JSON only — no markdown, no commentary, no code fences:\n"
            '[{"name": "Specific Capability Name", "description": "Imperative instruction."}, ...]'
        ),
        messages=[{"role": "user", "content": f"Extract skills from this input:\n\n{raw_input}"}],
    )
    # Strip markdown code fences if the model wraps the JSON. `find_duplicate_skill` calls the
    # same helper - this defence was written here first and belongs to both.
    raw_text = _strip_code_fences(resp.content[0].text.strip())
    try:
        result = json.loads(raw_text)
        if isinstance(result, list):
            return result
        return [result]
    except Exception:
        # Last-resort fallback: derive a name from the first meaningful phrase
        first_line = raw_input.strip().split("\n")[0][:60].strip()
        name = " ".join(first_line.split()[:5]).rstrip(".,;:-")
        return [{"name": name or "New Agent Skill", "description": raw_input[:300]}]


async def extract_skill(raw_input: str) -> dict:
    """Return {name, description} extracted from reviewer feedback text."""
    client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=256,
        system=(
            "Extract a transferable skill lesson from reviewer feedback about an AI agent's work. "
            "The skill should be generic (no client-specific details) and imperative "
            "(what the agent should do or avoid in future).\n\n"
            "Respond with valid JSON only:\n"
            '{"name": "3-5 word title", "description": "1-2 sentences in imperative voice"}'
        ),
        messages=[{"role": "user", "content": f"Reviewer feedback:\n{raw_input}"}],
    )
    try:
        return json.loads(resp.content[0].text.strip())
    except Exception:
        return {"name": "Skill from feedback", "description": raw_input[:200]}


# Baseline skills seeded from the hardcoded AGENT_SKILLS in agentStatus.ts.
# agents is a list — a skill can be shared across multiple agents.
# No icons (those are UI-only).
BASELINE_SKILLS: list[dict] = [
    # PAM
    {"agents": ["PAM"], "name": "Pipeline Orchestration", "description": "Dispatch crews in strict dependency order: Discovery → Value Chain → Interaction Design → Stakeholder Management → Interview Coordination → Synthesis → Value Propositions → Portfolio → Architecture → Initiatives → Roadmap → Business Plan. Never start a phase until all its upstream prerequisites have been reviewed and approved."},
    {"agents": ["PAM"], "name": "Phase Gating", "description": "Produce a clear, self-contained summary at the end of each phase naming what was produced and what a reviewer needs to validate. Do not wait for a response - the platform records the output for review and releases downstream work when an approver commits it."},
    {"agents": ["PAM"], "name": "Schedule Management", "description": "At every orchestration step, compare current progress against the milestone plan. If slippage exceeds one day, flag it with a specific corrective action and a named owner before continuing."},
    {"agents": ["PAM"], "name": "Status Reporting", "description": "When producing a status report, cover all six dimensions in order: RAG health, schedule, per-crew progress, risks, issues, and next actions. Never omit a dimension — an incomplete status report is worse than no report."},
    {"agents": ["PAM"], "name": "Risk Management", "description": "Before each crew dispatch, scan for engagement risks across five areas: knowledge gaps, stakeholder coverage, schedule slippage, review backlogs, and interview completion. Rate every risk and provide a mitigation before continuing."},
    {"agents": ["PAM"], "name": "Issue Management & Escalation", "description": "For each active issue, generate a specific escalation recommendation that names an owner, an action, and a deadline. Never report an issue without a resolution path — an issue without a recommendation is noise, not an escalation."},
    {"agents": ["PAM"], "name": "State Awareness", "description": "Before any orchestration decision, read the full project state — run history, review statuses, stakeholder counts, milestone dates, and interview completions. Never act on assumptions or knowledge from a previous run."},
    {"agents": ["PAM"], "name": "Decision Intelligence", "description": "Apply this rule when deciding whether to proceed: if the output is approved, proceed; if it is pending review, hold; if review is overdue by more than 24 hours, escalate. Never infer approval from silence."},
    # Value Chain Mapper
    {"agents": ["Value Chain Mapper"], "name": "Value Chain Analysis", "description": "Decompose the organisation using Porter's Value Chain: map L1 value streams first, then L2 process stages within each stream, then L3 activities. Assign n.n.n IDs immediately on creation — never produce an unnumbered activity."},
    {"agents": ["Value Chain Mapper"], "name": "Stable ID Registry", "description": "Write every ID assignment to value_chain_registry.json before producing any other output. If removing an activity, mark it inactive rather than deleting it — IDs must never be reassigned or reused."},
    {"agents": ["Value Chain Mapper", "Requirements Analyst"], "name": "Document Ingestion", "description": "Before producing any output, read all uploaded client documents in full. Capture exact terminology the client uses — do not paraphrase. Flag every named system, process, or entity for inclusion in the analysis."},
    {"agents": ["Value Chain Mapper", "Value Lever Analyst", "Requirements Analyst", "Enterprise Architect"], "name": "Web Search", "description": "Validate your outputs against peer organisations and published benchmarks. Cite the source and date for every external data point — never assert a benchmark without attribution."},
    {"agents": ["Value Chain Mapper", "Value Lever Analyst", "Requirements Analyst", "Enterprise Architect"], "name": "Semantic Search", "description": "Query the vector knowledge base before making any claim about the organisation. If relevant prior outputs exist, ground your work in them rather than starting from first principles."},
    # The Value Chain Mapper emits the structured model, not a rendering - this skill would
    # tell it to write a diagram alongside it, which is what the model replaced. The
    # Enterprise Architect stays: that agent legitimately still produces diagrams.
    {"agents": ["Enterprise Architect"], "name": "Diagram Rendering", "description": "Produce a valid Mermaid diagram alongside every JSON output. Validate the syntax before writing the file — a diagram with syntax errors must not be included in the output."},
    # Human Review Gate — shared across all agents that gate on human approval
    {"agents": [
        "Value Chain Mapper", "Interaction Designer", "Stakeholder Manager",
        "Requirements Capture", "Requirements Analyst", "Value Lever Analyst",
        "Interview Coordinator", "Stakeholder Interviewer", "Synthesis Analyst",
        "Value Proposition Generator", "Portfolio Manager", "Enterprise Architect",
        "Initiative Identifier", "Roadmap Generator", "Business Plan Generator",
    ], "name": "Human Review Gate", "description": "At the end of every work phase, write a summary of what was produced and what the reviewer needs to validate, then finish. Approval is recorded outside the run, so there is nothing to wait for."},
    # Interaction Designer
    {"agents": ["Interaction Designer"], "name": "Interview Script Design", "description": "Write one interview script per active L1 and L2 node. L1 scripts must ask strategic 'why' questions aimed at GMs; L2 scripts must ask operational 'how' questions aimed at process managers. Number all questions with n.n.n IDs — never produce an unnumbered question."},
    {"agents": ["Interaction Designer"], "name": "Maturity Questionnaire Design", "description": "For each node, write a five-point maturity questionnaire where level 1 is ad hoc and level 5 is optimised and continuously improving. Align every level descriptor to the configured framework — no descriptor may be written without a traceable standard clause."},
    {"agents": ["Interaction Designer"], "name": "Coherent Instrument Design", "description": "Design scripts and questionnaires as a paired set for each node. Before finalising, confirm the interview questions and maturity descriptors cover the same capability dimensions — never submit a set where a topic appears in one instrument but not the other."},
    {"agents": ["Interaction Designer"], "name": "Standards Grounding", "description": "Before writing any instrument content, retrieve the configured framework standards from the project setup. Every question and maturity descriptor must be traceable to a specific standard clause or principle — reject content that cannot be traced."},
    {"agents": ["Interaction Designer"], "name": "Template Auto-Assignment", "description": "On completing the instrument set, publish each script and questionnaire as a named template and assign it to its value chain node by n.n.n ID. Confirm the assignment in the output before ending the run — unassigned templates are incomplete."},
    # Stakeholder Manager
    {"agents": ["Stakeholder Manager"], "name": "Coverage Analysis", "description": "Calculate stakeholder coverage at L1, L2, and L3 separately. List every node with zero assigned stakeholders explicitly — never aggregate gaps or describe them vaguely. A coverage report without a node-level breakdown is incomplete."},
    {"agents": ["Stakeholder Manager"], "name": "Communication Management", "description": "Draft communications in escalating urgency: invitation, then first reminder, then second reminder, then re-engagement escalation. Match the tone to the stakeholder's level — never send an escalation tone to a first-time contact."},
    {"agents": ["Stakeholder Manager"], "name": "Engagement Planning", "description": "Write the engagement plan to stakeholder_engagement_plan.json with a specific next action for every stakeholder. A plan entry without a named next action is incomplete — every stakeholder must have a clear instruction."},
    {"agents": ["Stakeholder Manager"], "name": "Interview Session Tracking", "description": "Before sending any communication, check interview session status. Never send a reminder to a stakeholder who has already completed their session — check completion status every time, without exception."},
    # Requirements Capture
    {"agents": ["Requirements Capture"], "name": "Requirements Elicitation", "description": "Ask the project team structured questions to surface requirements, constraints, and priorities. Record only what the team explicitly states, using their exact wording — never infer requirements or paraphrase what was said."},
    {"agents": ["Requirements Capture"], "name": "State Management", "description": "Write all captured requirements to the project state store in structured JSON before ending the session. Do not rely on conversation history — write every requirement out explicitly and confirm the write before finishing."},
    # Requirements Analyst
    {"agents": ["Requirements Analyst"], "name": "Requirements Analysis", "description": "Read all captured requirements and all uploaded documents before identifying any gap or conflict. Ground every finding in evidence — never assert a gap without citing what is missing and why it matters."},
    # Value Lever Analyst
    {"agents": ["Value Lever Analyst"], "name": "Value Lever Identification", "description": "Validate every identified value lever against at least one published benchmark or industry dataset before submitting it. Cite the source and date — never assert an impact estimate without external evidence."},
    # Interview Coordinator
    {"agents": ["Interview Coordinator"], "name": "Interview Session Management", "description": "Create a session for each assigned stakeholder and generate a unique interview link. Produce a scheduling plan that groups sessions by value stream and staggers timing to avoid conflicting demands on the same stakeholder group."},
    # Stakeholder Interviewer
    {"agents": ["Stakeholder Interviewer"], "name": "Live Interview Facilitation", "description": "Follow the interview script in sequence. If a response is ambiguous, ask one clarifying question before moving on. Mark a section complete only when a substantive answer has been recorded — never mark a section complete with a blank or single-word response."},
    # Synthesis Analyst
    {"agents": ["Synthesis Analyst"], "name": "Theme Extraction", "description": "Read all completed transcripts before identifying any theme. Only flag a theme if it appears across multiple transcripts — single-respondent observations belong in 'individual perspectives', not in cross-cutting themes. Never extrapolate a theme from one voice."},
    # Value Proposition Generator
    {"agents": ["Value Proposition Generator"], "name": "Proposition Structuring", "description": "Structure every proposition with three mandatory components: problem statement, proposed intervention, and expected benefit. Map each to the specific value chain node it addresses. A proposition missing any component must not be submitted."},
    # Portfolio Manager
    {"agents": ["Portfolio Manager"], "name": "IIRC Six Capitals Scoring", "description": "Score every initiative across all eight capital dimensions before ranking anything. Never skip a dimension — if data is insufficient, assign a score of 0 and note the gap explicitly in the output."},
    {"agents": ["Portfolio Manager"], "name": "Portfolio Ranking", "description": "Rank initiatives by composite score. Where two initiatives share the same composite score, use lower implementation complexity as the tiebreaker — prefer the simpler initiative."},
    # Enterprise Architect
    {"agents": ["Enterprise Architect"], "name": "Architecture Design", "description": "Design the target architecture from the initiative portfolio, not from first principles. Map every architectural component to at least one initiative it enables — never include an element that cannot be linked to a portfolio initiative."},
    # Initiative Identifier
    {"agents": ["Initiative Identifier"], "name": "Initiative Decomposition", "description": "Decompose the architecture into initiatives with defined scope, outputs, and dependencies. Every initiative must either name its dependencies explicitly or state that it is independent — no initiative may have an undefined dependency status."},
    # Roadmap Generator
    {"agents": ["Roadmap Generator"], "name": "Roadmap Sequencing", "description": "Sequence initiatives so all dependencies are resolved before each initiative begins. If circular dependencies exist, flag them immediately and halt — never silently reorder to avoid a dependency conflict."},
    {"agents": ["Roadmap Generator"], "name": "Roadmap Rendering", "description": "Generate the HTML roadmap and roadmap_data.json in the same run. A roadmap HTML file without a corresponding JSON data file is an incomplete output — both are required."},
    # Business Plan Generator
    {"agents": ["Business Plan Generator"], "name": "Financial Modelling", "description": "Calculate NPV, IRR, and payback period using the configured financial assumptions. If any required assumption is missing, stop and request it from the project team — never substitute a default value for a client engagement."},
    {"agents": ["Business Plan Generator"], "name": "Business Plan Narrative", "description": "Write the narrative in this order: executive summary, strategic context, value chain findings, initiative portfolio, financial model, roadmap. Never reorder sections or combine them — section order is mandated by the output standard."},
    {"agents": ["Business Plan Generator"], "name": "Word Export", "description": "Generate the Word document and confirm its file path in the output. If generation fails, report the error explicitly — never report success without verifying the file exists on disk."},
    {"agents": ["Business Plan Generator"], "name": "PowerPoint Export", "description": "Condense the business plan to executive decision points only. Never include raw data tables in the slide deck — summarise everything to headline numbers and key insights at board level."},
]
