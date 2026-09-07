# agents/tools/skill_proposal.py
"""SkillProposalTool - an agent proposes the general rule behind a correction it just made.

A reviewer sends work back, the agent revises it, and the lesson evaporates: the note fixed
one artefact, and the rule behind it applies to every artefact that agent will ever produce.
This tool is where the rule is written down. It writes a `pending` row onto the skills queue
through `api.services.skills_service.propose_skill`; `_fetch_skill_notes` in
`api/services/run_service.py` injects `status='approved'` skills alone, so nothing proposed
here reaches any prompt until a human approves it.

**It cannot fail the revision it is attached to, and that is the whole contract of this
module.** The reviewer asked for a revision, not a skill. `_run` therefore catches
`BaseException` and answers the agent in a sentence, whatever happened underneath - a model
that timed out, a database that was locked, or `UnknownProposingAgent` for an agent id
`_SNAKE_TO_DISPLAY` has no entry for. That last one is a refusal Task 1 deliberately made
*raise*, because a proposal filed under a name no approval can reach looks exactly like a
working one; here is where it is swallowed, because by the time it is raised the revision has
already been made and there is nothing left to protect by failing.

Held by every agent a crew dispatches, and by PAM alone among the rest - see the comment on
`tool_map` in `agents/tools/registry.py` for which agents and why. The instruction to use it
is injected only on a run that actually has something sent back to it (`run_service`'s
`_SKILL_PROPOSAL_INSTRUCTION`), so an ordinary run neither proposes nor makes the model call
the deduplication needs.
"""
import logging

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from agents.tools._sync import await_sync

log = logging.getLogger(__name__)

# What the agent is told when the proposal could not be recorded. It says the revision is
# unaffected, because an agent given a bare failure will retry, improvise, or - worst - decide
# its revision did not land either.
_FAILED = (
    "The suggestion could not be recorded. This has no effect on the revision you have "
    "already made, and there is nothing for you to retry or correct - carry on with your task."
)


class SkillProposalToolInput(BaseModel):
    rule: str = Field(
        description=(
            "The general rule behind the correction, in one or two sentences, stated so it "
            "applies to every future piece of work of this kind - not to the one artefact you "
            "just revised. Name the behaviour to follow, not the mistake that was made."
        )
    )
    source_ref: str = Field(
        default="",
        description=(
            "What the correction was made on, so a reviewer can see the evidence: an interview "
            "script id, an output type, or a review id. Optional."
        ),
    )
    title: str = Field(
        default="",
        description="A short name for the rule. Optional - one is derived from the rule if omitted.",
    )


class SkillProposalTool(BaseTool):
    name: str = "SkillProposalTool"
    description: str = (
        "Propose a general behaviour rule for yourself, drawn from a correction a reviewer "
        "just asked you to make. Use it after you have made the revision, never instead of "
        "making it. Propose the rule, not the note: the note was about one piece of work, the "
        "rule is what you should do differently on every future piece of work of that kind. "
        "The suggestion is queued for a human to approve and changes nothing until they do. "
        "One proposal per correction, and none at all if the correction was specific to that "
        "one artefact and generalises to nothing."
    )
    args_schema: type[BaseModel] = SkillProposalToolInput
    slug: str
    agent_name: str

    def _run(self, rule: str, source_ref: str = "", title: str = "") -> str:
        rule = (rule or "").strip()
        if not rule:
            return (
                "No suggestion was recorded: a rule was not supplied. Either state the general "
                "rule behind the correction, or make no proposal at all."
            )
        try:
            # Two separate things, and a power-check showed they are not the same thing.
            #
            # **The module, never the function.** `skills_service.propose_skill` is resolved at
            # call time, so a test patching `api.services.skills_service.propose_skill` reaches
            # it; `from ... import propose_skill` binds this module's own reference at import
            # and the patch misses it silently - the trap CLAUDE.md records four crew tests
            # falling into, and `tests/test_skill_proposal_tool.py` fails against exactly that
            # mutation. That property belongs to the attribute access and to nothing else.
            #
            # **Function-local, for the import cycle.** `skills_service` reaches `run_service`
            # for `_SNAKE_TO_DISPLAY`, and `run_service`'s own comment explains why everything
            # downstream of the crew graph is import-order sensitive. Moving this to module
            # level while keeping the attribute access changes no test, which is how the first
            # draft of this comment came to credit the wrong half with the patchability.
            from api.services import skills_service

            outcome = await_sync(
                skills_service.propose_skill(
                    self.agent_name,
                    rule,
                    self.slug,
                    source_ref.strip() or None,
                    name=title.strip() or None,
                )
            )
        except BaseException:
            # `BaseException`, not `Exception`. A tool whose only job is a nice-to-have must not
            # be the thing that ends a run, and the failures worth surviving here are not all
            # `Exception`s: a `CancelledError` reaching this frame belongs to a timeout inside
            # the comparison, not to the crew. Loud, because a proposal path that is failing on
            # every call is indistinguishable at every later layer from an agent that simply
            # never proposes anything - the queue stays empty either way.
            log.warning(
                "skills: proposal from %s on %s could not be recorded",
                self.agent_name, self.slug, exc_info=True,
            )
            return _FAILED
        return _describe(outcome)


def _describe(outcome: object) -> str:
    """What to tell the agent, from what `propose_skill` says happened.

    Separate from `_run` so it is asserted directly rather than through a mock of the service,
    and defensive about the shape it is handed for `_run`'s reason: this runs after the
    revision, so a `KeyError` on a renamed key would still be a proposal that failed a run.
    """
    if not isinstance(outcome, dict):
        log.warning("skills: propose_skill answered %r, which is not an outcome", type(outcome))
        return _FAILED
    action = outcome.get("action")
    occurrences = outcome.get("occurrences", 1)
    # `approved` is a possible status on a matched row - `_DEDUP_STATUSES` compares against
    # pending and approved both - and the sentence below is still true of it: the increment
    # records the recurrence, it does not re-approve anything and nothing about the agent's
    # instructions moves.
    if action == "incremented":
        return (
            f"Recorded. This restates a rule already suggested for you, so it was counted "
            f"against that one rather than added again - it now has {occurrences} occurrences, "
            f"which is the evidence a reviewer approves from. Nothing has changed in your "
            f"instructions and nothing will until a human approves it."
        )
    if action == "created":
        return (
            "Recorded as a suggestion for a human to review. It changes nothing in your "
            "instructions, on this run or any other, until somebody approves it."
        )
    log.warning("skills: propose_skill reported an unknown action %r", action)
    return _FAILED
