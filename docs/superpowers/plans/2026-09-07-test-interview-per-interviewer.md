# Test interview per interviewer - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each interviewer gets a Test interview button on their own configuration section, a voice picker that opens on voices of their sex, and a rehearsal dialog that is theirs rather than Avery's.

**Architecture:** No new door. `GET /projects/{slug}/agents/{agent_id}/config` gains two derived fields - `is_interviewer` from `interviewer_agent_ids()` and `voice_sex` from `ask_voice_sex` - and the frontend reads both. The rehearsal dialog takes an `agentId` and resolves its name and face from the configuration.

**Spec:** `docs/superpowers/specs/2026-09-07-test-interview-per-interviewer-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced ` - ` en dash, **never an em dash**.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, **no emoji**. `describeError` imported from `ui/src/utils/describeError.ts`, never copied.
- **Python 3.13** via `./venv/bin/python`. Raw SQL only, no ORM.
- **Never restate a voice fact in TypeScript** - not the voice list, not the accents, not which voice is which sex. Task 4 of sp62 built a Python source guard for this and it does **not** walk TypeScript, so it will not catch you.
- **No agent-to-sex table anywhere.** `interviewer_selection.py` refuses one in writing; the sex comes from the resolved voice.
- Baseline: backend **2574 passed, 2 skipped, 12 deselected**; frontend **708 passed / 84 files**, summary ending at `Duration` with **no `Errors` block** - check for that block, not only the pass count. `tsc --noEmit` clean. Establish both from HEAD yourself.
- **Power-check each property separately**, confirm each mutation **landed** by reading the file back, clear `__pycache__` between mutation and revert, and report **which** test caught it.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. **Do not restart the server on :8000** - it was restarted on 7 September and is serving current code. **No real ElevenLabs calls**; the branch had one real egress incident and a socket-level block is the established way to be sure.

---

### Task 1: The configuration says who can interview, and what sex their voice is

**Files:** Modify `api/routers/agent_config.py`, `api/services/agent_config_service.py`; Test: extend `tests/test_agent_config.py`

**Interfaces:**
- Produces: two new keys on the `GET .../agents/{agent_id}/config` response - `is_interviewer: bool` and `voice_sex: str | None`. Tasks 2 and 3 consume both.

- [ ] **Step 1: Read `interviewer_agent_ids()` and `ask_voice_sex` first and report what each answers.** `interviewer_agent_ids()` is in `api/services/interviewer_selection.py` and its rule is "an identity with a `voice_id`". `ask_voice_sex` is in `api/services/voice_metadata.py` and returns a `VoiceSexAnswer` distinguishing **three** cases: a sex, a voice the provider gave no sex for, and no voice at all. Report the three and how they differ - Step 4 turns on it.

- [ ] **Step 2: Add `is_interviewer`**, derived by asking `interviewer_agent_ids()` whether it contains this `agent_id`. **Import the function; do not copy its rule.** A second `if identity.voice_id` here is the fifth-declaration defect in a new place.

- [ ] **Step 3: Write the failing test - the derivation, not the answer**

```python
async def test_is_interviewer_follows_the_selection_roster_rather_than_a_list_here(monkeypatch):
    # Asserted against a MONKEYPATCHED roster, not against Avery and Laura. A test naming the
    # two real interviewers passes against a hardcoded pair, which is the thing being avoided.
    monkeypatch.setattr(agent_config_service, "interviewer_agent_ids", lambda: ["pam"])
    assert (await resolve_agent_config_with(...))["is_interviewer"] is False   # for Avery
```

- [ ] **Step 4: Add `voice_sex`, and let the three cases stay three.** Only a provider-answered sex becomes a value; a voice with no sex label and an agent with no voice both answer `None`. **Do not collapse them into one branch** - Task 2 pre-sets a filter from this field, and an unanswerable lookup must open the picker unfiltered rather than empty.

- [ ] **Step 5: Write the failing tests - one per case, three tests**

Each of the three `ask_voice_sex` outcomes gets its own test with a stubbed answer. One test cannot witness all three, and the branch that matters is the one that stays `None` for two different reasons.

- [ ] **Step 6: No real provider call.** Stub `ask_voice_sex` at the name `agent_config_service` looks it up under, not where it is defined - CLAUDE.md records four crew tests that patched the definition site while the module held its own reference.

- [ ] **Step 7: Suites twice. Power-check: make `is_interviewer` always `True` and confirm Step 3's test fails; make `voice_sex` return a sex for the no-voice case and confirm the third test of Step 5 fails. Commit.**

---

### Task 2: The picker opens on the right voices, and lets you leave

**Files:** Modify `ui/src/components/tabs/VoicePicker.tsx`, `ui/src/api/agentConfig.ts`; Test: extend `ui/src/__tests__/VoicePicker.test.tsx`

**Interfaces:**
- Consumes: `voice_sex` from Task 1.

- [ ] **Step 1: Report how `VoicePicker` builds its request today**, including `gendersIn()` and where the gender options come from. sp62's final review found the sex options unguarded here once already; read that test before adding to it.

- [ ] **Step 2: Declare `is_interviewer` and `voice_sex` in the `AgentConfig` type.** Required, not optional - CLAUDE.md records four `ProjectSettings` fields that survived a save only on an untyped spread, and the cost of the fifth is the same.

- [ ] **Step 3: Write the failing test - assert what is SENT**

```ts
it('opens filtered to the interviewer\'s own sex', async () => {
  // The assertion is on the query the picker SENDS. A filter applied to the rendered list
  // looks identical on screen and is a different feature.
  renderPicker({ voice_sex: 'female' })
  await waitFor(() => expect(voicesApi.list).toHaveBeenCalled())
  expect(vi.mocked(voicesApi.list).mock.calls[0][1]).toMatchObject({ gender: 'female' })
})
```

- [ ] **Step 4: Pre-set the filter from `voice_sex`.** A value pre-sets it; `null` does not.

- [ ] **Step 5: Write the control - clearing the filter shows both sexes.** Without this, a picker that hardcoded a permanent filter passes Step 3. Drive the clear and assert the *next* request carries no gender.

- [ ] **Step 6: Write the failing test for the unanswerable case** - `voice_sex: null` sends no gender and renders voices. **Never an empty list**: that is indistinguishable from an account with no voices.

- [ ] **Step 7: Frontend suite, `tsc` clean. Power-check by hardcoding the filter to `'male'` and confirming Step 5 fails; then by ignoring `voice_sex` entirely and confirming Step 3 fails. Commit.**

---

### Task 3: The rehearsal is the interviewer's own, and a missing face is initials

**Files:** Modify `ui/src/components/tabs/TestInterviewDialog.tsx`, `ui/src/components/tabs/AgentConfigSection.tsx`, `ui/src/components/tabs/AverySetupTab.tsx`; Create `ui/src/components/AgentAvatar.tsx`; Test: new `ui/src/__tests__/TestInterviewPerInterviewer.test.tsx`, extend `ui/src/__tests__/AgentConfigSection.test.tsx`

- [ ] **Step 1: Report every hardcoded reference to Avery in `TestInterviewDialog.tsx`.** There are at least six - `AVERY_HIRES` in five renders and the greeting `"Hi, I'm Avery — and I'll be your interviewer today."` List them all before changing any; a missed one is a dialog that is Laura's in five places and Avery's in the sixth.

- [ ] **Step 2: Build `AgentAvatar`** - renders `image_url` when there is one, and initials from the display name when there is not. **Laura has no portrait and her resolved `image_url` is `null`**, so without this she renders broken. The fallback belongs to the component, not to Laura: fourteen other agents have no per-project image either.

- [ ] **Step 3: Write the failing test - initials, not a broken image and not somebody else's face**

```tsx
it('renders initials when an agent has no image, never another agent\'s face', () => {
  render(<AgentAvatar name="Laura Nelson" imageUrl={null} />)
  expect(screen.getByText('LN')).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})
```

- [ ] **Step 4: The dialog takes `agentId`, `displayName` and `imageUrl`**, and uses them for the greeting and every portrait. Send `agent_id` on the `/test/speak` calls - the door already accepts it and defaults to Avery, so omitting it is how Laura would rehearse in Avery's voice.

- [ ] **Step 5: Write the failing test - and use Laura, not Avery**

```tsx
it('greets you as the interviewer it was opened for, and speaks as them', async () => {
  // Laura specifically. Avery is the default at every layer - the dialog's old constant, the
  // server's agent_id default - so a test using him passes against the hardcoding this removes.
  renderDialog({ agentId: 'second_interviewer', displayName: 'Laura Nelson' })
  expect(await screen.findByText(/I'm Laura/)).toBeInTheDocument()
  expect(fetchBody('/test/speak').agent_id).toBe('second_interviewer')
})
```

- [ ] **Step 6: Render the button in `AgentConfigSection` when `is_interviewer` is true**, and remove Avery's Setup tab button so there is one route rather than two. Label it "Test interview", Lucide icon, `brand` tokens.

- [ ] **Step 7: Write the failing test - the button follows the payload**

```tsx
it('offers a test interview for an interviewer and not for anybody else', async () => {
  // Driven from is_interviewer on the payload, both ways. Asserting only the true case passes
  // against a component that always renders the button.
})
```

- [ ] **Step 8: Frontend suite, `tsc` clean. Power-check each of Steps 3, 5 and 7 separately, and confirm which test caught each. Commit.**

---

### Task 4: Document it

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: State the rule.** Who can conduct an interview is answered by `interviewer_agent_ids()` - an identity with a `voice_id` - and both the crew's selection and the rehearsal button read it from there. Record that `is_interviewer` and `voice_sex` are **derived** onto the configuration response rather than stored.

- [ ] **Step 2: Record the decision the sex filter did not reverse.** The picker filters by the sex of the interviewer's *current voice*, never by a table mapping agents to sexes, and say why: a project that gives Avery a female voice has said something, and a table here would contradict it while looking authoritative.

- [ ] **Step 3: Record that Laura has no portrait**, that `AgentAvatar` renders initials for any agent without one, and that a real asset is wanted and is not blocked on code.

- [ ] **Step 4: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** the button's audience derived not restated (1, 3), the sex filter from the voice (1, 2), the filter clearable and never empty (2), the dialog de-Averyed (3), the portrait fallback (3), documented (4).

**Placeholder scan:** none. Tasks 1, 2 and 3 each open by establishing facts from the code, because a brief on this project has been wrong about the codebase more than a dozen times - twice on the immediately preceding branch.

**Type consistency:** `is_interviewer: bool` and `voice_sex: 'male' | 'female' | null` are produced in Task 1 and consumed in 2 and 3, declared required in `AgentConfig`.

**Not in scope:** a portrait asset for Laura; changing Taylor's selection; storing a sex anywhere in this repository.

**One ordering note:** Task 3 could precede Task 2, but the picker is easier to test against a payload that already carries `voice_sex` than against a stub of one.
