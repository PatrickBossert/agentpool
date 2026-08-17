# The agent and crew graph - design

**Date:** 2026-08-17
**Status:** draft for review
**Scope:** the model and its first slice. Enforcement is sequenced second, deliberately.

## Why

Three things are true of this system today and all three have the same cause.

**Descriptions of it rot.** `RunCrewTool`'s description tells PAM it can run `discovery` and
`architecture` - neither exists - and omits four crews that do. An unknown crew name makes
`build_and_run_crew` return an empty string, so a dispatch that did nothing reports as a result.
`ui/src/pages/Architecture.tsx` is 705 hand-maintained lines describing the same system.

**The same fact is written many times.** Nine crew→agent maps, four disagreeing crew-label maps,
six persona lists, three `OUTPUT_TYPE_LABELS`. `crews_enabled` is editable in settings and read
by no dispatch path. `llm_mode="fallback"` is silently identical to `"standard"`.

**The secure-mode guarantee is narrower than it reads.** CLAUDE.md states it absolutely: every
agent including PAM routes locally on a sensitive project, no fallback. But `llm_mode` gates
only the model and Chroma. Ungated: the n8n HITL webhook and `SlackNotifyTool`, which post
agent-authored text (a review prompt, a notification message) and a link back to the dashboard -
not the artefact itself, though the text can quote client material; an unguarded `WebFetchTool`;
and Tavily search. ElevenLabs, Deepgram and Resend are
also ungated and were separately accepted by decision. `DataArchitecture.tsx`, the audit page,
is hand-typed, stale, and omits `WebFetchTool` entirely.

The cause is that no artefact owns these relationships. Each is restated wherever it is needed,
and nothing compares the restatements.

## What the graph is

**One declared model that the system reads, rather than a document describing it.** Every
existing list either derives from it or is deleted. The picture an auditor looks at is a
consequence of the model, not a parallel artefact.

It answers four questions the code currently answers only in fragments:

| Question | Today |
|---|---|
| Which agents are in this crew? | Nine maps, five stale |
| What does this agent read and write? | Writes: derivable from `OUTPUT_OWNERS`. **Reads: English inside task descriptions, three already wrong** |
| What external service can this agent reach? | **Nowhere** |
| What can start this crew? | Four dispatch paths, none enumerated together |

## The model

**Agent** - the permanent record of one agent.

- `agent_id` - permanent, never displayed as a label, never reused. The current snake_case keys
  become the ids: no filename encodes an agent name, so the standing filename-family rule does
  not apply, and the migration is ~290 plain column values across seven tables.
- `display_name`, `image`, `default_voice` - mutable, and the reason the id exists.
- `tier` (`fast`/`deep`), `tools`, `domain module`.
- `reads` and `writes` - artefact types, with the storage medium each uses.
- `egress` - which external services its tools can reach.

**Crew** - purpose, its agents, its dependencies, what triggers it.

**Agent × project** - per-engagement overrides: voice, accent, image, display name. This
generalises what already exists rather than inventing it: interviewer identity today is
`voice_config` on the session plus three per-project `brand_interviewer_*` fields.

## Identity: a permanent id with a mutable name

Agent names are currently keys, labels, **and** stored values. Renaming one would silently
orphan its past outputs rather than fail.

This project has reached the same answer twice already and written it down both times: a script
is identified by `script_id`, which is never displayed; the value chain's ids are "a permanent
contract - the ledger may grow and may retire, but may never redefine or forget". This is the
third instance, and the cheapest of the three to fix, because it is being fixed before the
stored rows matter.

Two snags to resolve in the migration: `pam_report_job.py` writes `agent_name='PAM'` where every
other writer uses a snake key (18 rows and growing), and `agent_skill_assignments` is keyed on
**display** names - the mutable half.

**What the id does not fix**, and must not be claimed to: prose in one agent's prompt naming
another; `elif` ladders importing agent modules by name; nine frontend maps keyed on the label;
`OUTPUT_OWNERS`' one-writer-per-output rule; and crews being fixed-arity straight lines.

## Derived, declared, and deleted

**Derived** - already machine-readable, and the graph must read these rather than restate them:
`tool_map` and `AGENT_TIER` (17 agents, held equal by the only cross-registry guard in the
codebase), `CREW_DEPENDENCIES`, `_CREW_AGENT_NAMES`, `OUTPUT_OWNERS` (which inverts free to give
agent→writes), the validators, and the standalone-dispatch eligibility list.

**Declared** - genuinely absent, and written down next to the code it describes: an agent's
**reads**, each tool's **egress**, each crew's **purpose and triggers**, and the per-project
overrides.

**Egress is declared per tool, and its destination resolved through `llm_mode` at read time.**
Decided 2026-08-17. `ChromaQueryTool` reaches Chroma Cloud on a standard project and a local
instance on a sensitive one - same tool, different destination. One declaration per tool, with
the mode dependency living in the resolver, rather than a declaration per tool per mode: the
latter can express it too, but doubles the surface and invites the two halves to drift, which is
the disease this design treats. `get_llm_for_agent` already solves the equivalent problem the
same way.

The declaration must therefore say what a tool reaches *in principle* - "a vector store", "the
public internet", "an LLM" - and the resolver says which one, for this project. A tool whose
destination does not vary simply resolves to the same answer in every mode.

**Deleted** - the restatements. `RunCrewTool`'s description is generated. `Architecture.tsx` and
`DataArchitecture.tsx` render from the graph. The stale crew→agent and crew-label maps go.
`crews_enabled` goes, per the decision to park it: all crews, no toggle.

## Descriptive first, enforced second

Egress and reads are **declared** in the first slice and **not** enforced.

The second slice makes them load-bearing - a sensitive project refuses a crew whose agent holds
a tool with undeclared or disallowed egress, enforced the way `check_write` already refuses an
undeclared output key.

Declaring first is deliberate: it will reveal how many currently-running paths would break, and
that list is worth seeing before committing to fail them. This project has run both experiments
already - `check_write` enforces and is why a script id can never be redefined; coverage
validation reports and is why coverage took several runs to converge. Both were right for what
they bought.

## Extensibility

The reason for the model rather than a diagram: a crew outside this application - technical
requirements passed to a coding-agent crew - needs a crew's inputs, outputs and triggers
expressed well enough to be wired to. Those are exactly the declared fields above. An external
crew is then a graph entry whose dispatch is a webhook rather than a factory.

Not in this slice. But the model must not make it harder, which means a crew's contract cannot
be "whatever the Python factory happens to do".

## Testing

The guard is the point. A model nothing checks is the artefact that just failed.

- **Every declared edge resolves** - every agent named by a crew exists; every artefact type
  read by someone is written by someone; every tool named has an egress declaration. The sp43
  route-coverage test is the pattern: enumerate from the code, assert the declaration covers it.
- **Every generated description matches its source** - the `RunCrewTool` regression, made
  impossible rather than merely fixed.
- **The two-layer override resolves correctly** - a per-project voice wins, the default applies
  where there is no override, and an override for an unknown agent is refused rather than
  ignored.
- **No test may assert a graph fact against a constant written in the same change.** This
  project's recorded failure mode is a test that verifies a property one layer from where it
  holds; a graph is unusually easy to test against itself.

## Review is a link, not a payload

Decided 2026-08-17. **Content review is a message push carrying a link and a token that brings
the reviewer to the content on the server.** No confidential document is pushed outward, on any
channel. This is the same mechanism the invite loop already proves - a single-use, address-bound
token redeemed against the server - and it resolves the sharpest egress question by design
rather than by gating.

Precision on what leaves today, because it is narrower than first reported: `HumanInputTool`
posts `review_id`, `prompt`, `project_slug`, `run_id` and a `review_url` pointing back at the
dashboard. It does **not** send the artefact. `SlackNotifyTool` posts an agent-authored
`message`. Both are agent-authored text that can quote client material - real egress, but not
documents leaving.

## n8n is removed

Decided 2026-08-17. This application is a custom-built state machine and workflow; n8n holds no
state, makes no decisions, and its whole footprint is three things:

| Thing | What removal costs |
|---|---|
| `HumanInputTool`'s notification | Nothing structural - it is fire-and-forget inside `except Exception: pass`, and the review loop polls the database while the human answers in the UI |
| `SlackNotifyTool` | The tool, which is wholly n8n-dependent and already listed in known issues as needing manual channel invitation |
| `POST /projects/{slug}/orchestrate` | Nothing - it is **inbound**. n8n can call it; so can anything. The endpoint stays |

The `except Exception: pass` around the only outbound call is the evidence: nobody silences a
load-bearing dependency. The system already works when n8n is absent.

Removal is therefore deletion plus building the notification actually wanted - the link-and-token
push above, which replaces both tools with one mechanism. Also removed: the `n8n_webhook_url`
setting, the docker-compose service, and its credentials in `.env.example`.

The graph makes this safe rather than brave: "which agents reach n8n" becomes a declared fact to
check against, instead of grep-and-hope.

## Sequencing

1. Identity split and the derived core; `RunCrewTool` generated; stale maps deleted.
2. Declared reads, egress, purposes and triggers. `DataArchitecture.tsx` renders from the graph.
3. Per-project overrides, with the interviewer voices as the first consumer.
3a. **The graph viewer**, in the Data Architecture & Privacy section, rendering from the graph.
   Sequenced after (2) deliberately: that page is what a client is shown to explain where their
   data goes, so a generated view of structure without egress would read as authoritative while
   omitting the only question the page exists to answer. Decided 2026-08-17.
   **The page also becomes administrator-only.** It is currently public by omission rather than
   by design - nothing public links to it, its only link sits inside `ProtectedRoute`, and
   `/architecture` beside it is already guarded.
4. **n8n removed**, and the link-and-token review push built to replace its two notifications.
   Sequenced here because (2) is what proves the footprint is only those two tools.
5. Enforcement, once the breakage list from (2) and (4) is known - and materially smaller,
   because the review path no longer needs an exception.

## Out of scope

Agent authoring - creating a new agent's persona through the graph rather than as a module -
stays out. A second interviewer does **not** need it: the interviewee never talks to a CrewAI
agent, the live interview being a browser loop, so a second voice is per-project override work,
not a new agent. Where the code/data line finally falls is the decision this design defers, and
`interaction_designer.py` is the case that will force it: its persona does not separate cleanly.
