# Per-project agent configuration and interviewer selection - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every agent gets a name, image and voice configurable per project, overriding the defaults that run today. A second interviewer, Laura Nelson, joins the discovery interviews team, and Taylor chooses between the interviewers by a project setting - always male, always female, or random - stamping the choice on the session so it never changes underneath a participant.

**Architecture:** A `project_agent_config` table keyed on `(project_id, agent_id)`, where `agent_id` is the permanent id `agents/identity.py` already separates from the mutable display name. Resolution is override-then-default. The resolved voice is **stamped** on `interview_sessions.voice_config` at creation and read from there, never re-derived.

**Spec:** `docs/superpowers/specs/2026-09-04-agent-config-and-interviewer-selection-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced en dash ` - `, never an em dash. Participant-facing copy.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, no emoji. `describeError` from `ui/src/utils/describeError.ts`.
- **Python 3.13** via `./venv/bin/python`. No ORM - raw SQL in `api/database.py`.
- **`project_agent_config` is a PROJECT table**: a new `_migrate_*` bumps `_SCHEMA_VERSION` in the same change and joins the block `get_connection` runs; add the columns to `CREATE TABLE` and to fixtures. Guard the migration with `PRAGMA table_info` and skip *itself* rather than the block.
- **Baselines:** backend **2365 passed, 2 skipped, 12 deselected**; frontend **666**; `tsc --noEmit` clean. Establish both from HEAD yourself - counts in documents here have been stale seven times.
- **Power-check each property separately**, confirm each mutation **landed**, and check **which** test caught it.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the servers on :8000 or :3000. **No real ElevenLabs calls in tests.**

---

### Task 1: Configuration exists, and defaults still win when it is absent

**Files:** Modify `api/database.py`; Create `api/services/agent_config_service.py`, `tests/test_agent_config.py`

**Interfaces:**
- Produces: `resolve_agent_config(slug, agent_id) -> dict` returning `display_name`, `image_url`, `voice_id`, `language`, `country_code`, each an override or the default. Tasks 2-5 consume it.

- [ ] **Step 1: Report the current defaults before changing anything.** `agents/identity.py` holds display names and images. The voice default is `DEFAULT_VOICE_CONFIG` in `ui/src/pages/VoiceInterview.tsx` - **a hardcoded `21m00Tcm4TlvDq8ikWAM`, which is ElevenLabs' stock "Rachel", a female voice, used for an interviewer described everywhere as male.** Report where each default lives and say which are wrong.

- [ ] **Step 2: Add the table.**

```sql
CREATE TABLE IF NOT EXISTS project_agent_config (
    project_id    INTEGER NOT NULL,
    agent_id      TEXT NOT NULL,
    display_name  TEXT,
    image_url     TEXT,
    voice_id      TEXT,
    language      TEXT,
    country_code  TEXT,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, agent_id)
);
```

Every column but the key is nullable, and **NULL means "use the default"** rather than "empty". A blank string and an absent value are different things here; say in the docstring which is which.

- [ ] **Step 3: Write the failing test - the control first**

```python
async def test_a_project_with_no_configuration_resolves_every_default():
    cfg = await resolve_agent_config(slug, "stakeholder_interviewer")
    assert cfg["display_name"] == "Avery Singh"
```

**This is the control, and it must come first.** Without it, an implementation that resolved nothing at all would pass every override test below by returning the override and failing silently everywhere else.

- [ ] **Step 4: Write the resolver.** Override wins where present, default otherwise, per field - so a project may set a voice without setting a name.

- [ ] **Step 5: Correct Avery's default voice** to a male ElevenLabs voice, and move it out of the component into the same place the other defaults live. A default that contradicts the persona is the defect that produced this whole task.

- [ ] **Step 6: Suites twice. Power-check the resolver's override arm and its default arm separately. Commit.**

---

### Task 2: Laura Nelson

**Files:** Modify `agents/identity.py`, `agents/model_registry.py`, `agents/crews/discovery_interviews_crew.py`, `agents/tools/registry.py`; Create her agent module; Test: new

- [ ] **Step 1: Read how `stakeholder_interviewer` is declared end to end and report the list.** She needs everything he has: an identity entry, a tier, a crew registration, a tool list, and an entry in `_SNAKE_TO_DISPLAY`. **`tests/test_skill_proposal.py` enumerates `_CREW_AGENT_NAMES` against that map** and will fail if she is missing from it - which is the guard working, not an obstacle.

- [ ] **Step 2: Add her with a permanent `agent_id`** distinct from Avery's, display name "Laura Nelson", tier **`fast`** - the same job as Avery, so the same tier.

- [ ] **Step 3: Write the failing test** - both interviewers resolve their own default voice, and the two voices differ.

- [ ] **Step 4: She shares Avery's task and tools.** She is a second voice, not a second brief. If you find yourself writing a second interviewing prompt, stop and report it - divergent interviewing instructions would make transcripts incomparable, which is Casey's problem later.

- [ ] **Step 5: Suites twice. Commit.**

---

### Task 3: Taylor chooses, and the choice is recorded

**Files:** Modify `api/models.py`, `api/services/` (the selection), `agents/tools/interview_session_tool.py`; Test: new

- [ ] **Step 1: Add the setting.** `interviewer_selection` on `ProjectSettings`: `always_male | always_female | random`, defaulting to `random`. It is **not** platform-tier - it decides tone, not where data goes.

- [ ] **Step 2: Write the failing tests**

```python
def test_always_female_never_yields_the_male_interviewer(): ...
def test_random_is_stamped_once_and_does_not_change_on_re_read(): ...
```

The second is the one that matters. **A random choice that is re-rolled on every read gives a participant a different interviewer each time they open their link.** Stamping it at creation is what makes it stable - the same argument as the voice.

- [ ] **Step 3: Stamp the resolved voice on the session.** `interview_sessions.voice_config` is written at creation from `resolve_agent_config`, and the interview reads the session's copy. **Never re-derive it**: a project's configuration may change between an invite being issued and the interview being taken, and the transcript must say which voice actually conducted it. This is the rule sp57 learned with `client_documents.knowledge_collection`.

- [ ] **Step 4: Assert what reaches the synthesis call**, not what the table holds. A stamped value nothing speaks with is the same defect one layer along.

- [ ] **Step 5: Suites twice. Power-check the stamping and the selection separately. Commit.**

---

### Task 4: The voices list and preview

**Files:** Create the voices endpoint; Modify `api/services/interview_service.py`; Test: new

- [ ] **Step 1: Add a project-scoped door listing available voices** from `GET https://api.elevenlabs.io/v1/voices`. The codebase calls only text-to-speech today, so this is a **new outbound path**. Return id, name, labels and preview URL.

- [ ] **Step 2: Preview speaks a fixed sample line** in the selected voice, through the existing `synthesise`. It must not touch any session.

- [ ] **Step 3: Tests make no real calls.** Stub the transport and assert the request that would go out - the existing interview tests show the pattern.

- [ ] **Step 4: Record the egress.** CLAUDE.md lists ElevenLabs as an ungated reach; this widens what is sent from interview text to a voice listing, which carries no client material. Say so rather than leaving the table stale.

- [ ] **Step 5: Suites twice. Commit.**

---

### Task 5: The Setup section

**Files:** Modify `ui/src/components/tabs/CrewSetupSections.tsx` and the per-agent Setup tabs; Test: frontend

- [ ] **Step 1: Report what each Setup tab does today**, and note that `AverySetupTab` is **`localStorage`-backed** under `agentpool-avery-voice-config`. That is the defect this task replaces, not a pattern to follow: settings that never reach the server never reach an interview.

- [ ] **Step 2: One shared section, not seven copies.** Name, image, voice - rendered for every agent from its `agent_id`. A per-agent copy is a rule in seven places.

- [ ] **Step 3: The voice picker offers what the server lists**, with regional variants and a preview button. **Never restate the list in TypeScript.**

- [ ] **Step 4: Show the default when nothing is set**, and make clear it is a default rather than a saved value - an administrator needs to know whether they are looking at a choice or an inheritance. sp58's platform-URL panel is the precedent.

- [ ] **Step 5: Assert what is SENT, not what renders.** Twelve tests across recent branches passed without testing what they were named for.

- [ ] **Step 6: Frontend suite, `tsc` clean, power-check, commit.**

---

### Task 6: Document it

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: State the rule.** Agent configuration keys on the **permanent `agent_id`**; name, image and voice are data. This is what that separation was for.

- [ ] **Step 2: State the stamping rule and why**, beside the existing `knowledge_collection` material it repeats: a session records the voice that conducted it, because a re-derived address moves underneath the thing it points at.

- [ ] **Step 3: Record what is still `localStorage`.** Avery's interviewing preferences - style, depth, follow-up persistence, silence tolerance - have the same defect and have never reached an interview. Name them as owing the same fix rather than leaving the next reader to find out by testing.

- [ ] **Step 4: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** configuration table and resolution (1), Avery's wrong default corrected (1), Laura Nelson (2), selection setting and stamping (3), voices list and preview (4), the Setup section (5), documentation (6).

**Placeholder scan:** none. Tasks 1, 2 and 5 each open by establishing facts from the code.

**Type consistency:** `resolve_agent_config(slug, agent_id) -> dict` is defined in Task 1 and consumed in 2, 3 and 5.

**Not in scope:** Avery's other interviewing preferences; voice cloning; matching an interviewer to a stakeholder by any attribute other than the male/female/random setting.

**One ordering note:** Task 4 could precede Task 3, but the picker in Task 5 is easier to build against a resolver that already works than against a list with nothing to select for.
