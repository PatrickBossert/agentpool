# Test interview per interviewer - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each interviewer gets a Test interview button on their own configuration section, a voice picker that opens on voices of their sex, and a rehearsal dialog that is theirs rather than Avery's.

**Architecture:** No new door. Two derived fields on two existing responses - `is_interviewer` from `interviewer_agent_ids()` on `GET /projects/{slug}/agents/{agent_id}/config`, and `voice_sex` from `ask_voice_sex` on `GET /projects/{slug}/voices`, the request the picker already makes when it opens. The rehearsal dialog takes an `agentId` and resolves its name and face from the configuration.

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

**Files:** Modify `ui/src/components/tabs/VoicePicker.tsx`, `ui/src/api/voices.ts`, `ui/src/api/agentConfig.ts`; Test: extend `ui/src/__tests__/VoicePicker.test.tsx`

**Interfaces:**
- Consumes: `is_interviewer` from `GET .../agents/{agent_id}/config`, and `voice_sex` from `GET /projects/{slug}/voices` - **two doors, not one.** Task 1's round-1 review moved the sex off the configuration door: that read is made once per agent panel on every render, and a third-party lookup on its happy path was re-paid on every render during an outage, showing "Loading this agent's configuration…" indefinitely - the string from the 7 September incident. The picker's own door opens on a user action where a wait is expected.

- [ ] **Step 1: Report how `VoicePicker` builds its request today**, including `gendersIn()` and where the gender options come from. sp62's final review found the sex options unguarded here once already; read that test before adding to it.

- [ ] **Step 2: Declare `is_interviewer` on `AgentConfig`, and `voice_sex` on the voices response.** Required, not optional - CLAUDE.md records four `ProjectSettings` fields that survived a save only on an untyped spread, and the cost of the fifth is the same. **Send `current_voice_id`** on the listing request; the picker already holds it as `currentVoiceId`, and without it the server answers `voice_sex: null` and the filter never pre-sets.
  - **Type `voice_sex` as `string | null`, never `'male' | 'female' | null`.** The server narrows it to the two actionable labels, but the type is a claim the client would then be free to switch exhaustively over, and ElevenLabs' vocabulary is not ours. Pre-set only when the value is among the options the listing itself offers.
  - **Do not derive the sex from the listing.** The obvious shortcut is to find `currentVoiceId` in `account` and read its `gender`, and it fails **silently for exactly the projects that configured an accent**: the listing is narrowed by `interview_accent`, so a voice of another accent is simply absent, and "not found" is indistinguishable from "no label". This was established in review; do not re-litigate it.

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

### Task 4: An agent portrait is uploaded, not typed - and it is downscaled on the way in

**Files:** Modify `api/routers/agent_config.py`, `requirements.txt`, `ui/src/components/tabs/AgentConfigSection.tsx`, `ui/src/api/agentConfig.ts`; Create `api/services/image_intake.py`; Test: new `tests/test_agent_image_upload.py`, extend `ui/src/__tests__/AgentConfigSection.test.tsx`

Patrick's instruction, 7 September: *"if a new agent image is selected and the configuration is
saved, check the filesize and down-scale it appropriately."* Today `image_url` is a free-text
path with no upload at all, so there is nothing to downscale yet - this task builds both.

**Interfaces:**
- Produces: `POST /projects/{slug}/agents/{agent_id}/image` returning `{"url": "..."}`, and
  `GET /projects/{slug}/agents/{agent_id}/image` serving it **unauthenticated**.
- Produces: `prepare_portrait(data: bytes, content_type: str) -> tuple[bytes, str]` in
  `api/services/image_intake.py` - the downscale, testable without HTTP.

- [ ] **Step 1: Read `upload_branding_image` in `api/routers/projects.py:390` and report what it does, in order.** It is the precedent and this door copies its shape: membership floor first, then `require_project_administration`, then the existence check - *"a caller from outside the engagement must not be able to use this door to learn which slugs exist"* - then content-type allowlist, then size, then **magic-byte verification**, then write. Report each, then follow it. Its `GET` sibling is unauthenticated, and this one must be too: the interview page has no login and CLAUDE.md documents that as one of exactly two deliberate floor exceptions.

- [ ] **Step 2: Declare Pillow in `requirements.txt`.** It is installed at 12.3.0 but only as a transitive dependency of `pdfplumber` and `python-pptx`, so nothing declares it and a resolver that dropped both would take it with them. **Pin it the way its neighbours are pinned.** Do not add any other new dependency.

- [ ] **Step 3: Write the failing test - the downscale, as a pure function**

```python
def test_a_large_portrait_is_downscaled_to_the_longest_side():
    big = Image.new("RGB", (3000, 2000), "white")
    out, ext = prepare_portrait(_encode(big, "JPEG"), "image/jpeg")
    assert Image.open(io.BytesIO(out)).size == (512, 341)   # aspect ratio preserved, not cropped
```

`prepare_portrait` is a pure function over bytes so it can be driven directly - CLAUDE.md
records three guards whose reach could not be established because they only ran against real
inputs. **512 on the longest side**: the largest portrait in the product renders at `w-40`
(160 CSS px, 320 at 2x), so 512 is generous and the file stays small.

- [ ] **Step 4: Do not upscale.** A 200px portrait stays 200px. Assert it separately - a
  `resize` that always runs would pass Step 3 and quietly blur every small image.

- [ ] **Step 5: Honour EXIF orientation, then strip EXIF entirely.** Two properties, two tests.
  A phone photograph carries an orientation flag - ignore it and the portrait is sideways - and
  it carries **GPS coordinates**, which would then be served from an *unauthenticated* page to
  every interview participant. `ImageOps.exif_transpose` first, then save without `exif`.

```python
def test_a_portrait_keeps_no_exif_and_therefore_no_location():
    out, _ = prepare_portrait(_jpeg_with_gps(), "image/jpeg")
    assert not Image.open(io.BytesIO(out)).getexif()
```

- [ ] **Step 6: A ceiling still applies, and it is a refusal.** Downscaling is not a reason to
  accept an unbounded upload - the bytes are read into memory before Pillow sees them. Reject
  above **10 MB** with a 422 naming the limit, and keep the magic-byte check: a decoder pointed
  at a file that is not the type it claims is the part of this door that is a security control.

- [ ] **Step 7: The stored URL is same-origin**, `/api/projects/{slug}/agents/{agent_id}/image`,
  exactly as the branding door stores its own. **This is the half that matters beyond tidiness.**
  sp62's review found that an off-site `image_url` makes every participant's browser reach a
  third party from the unauthenticated interview page, disclosing their IP, user agent and the
  timing of an interview - on an engagement whose documents and inference are on-premises. An
  uploaded portrait has no such reach. Record in the report that the free-text field still
  permits an off-site URL, so this **narrows** the hole rather than closing it, and that closing
  it means retiring the text field once uploads exist for both image fields.

- [ ] **Step 8: The frontend offers an Open… file selector beside the field.** Patrick's
  instruction, 7 September. A visible **"Choose image…"** button that opens the operating
  system's file dialog - a Lucide icon and `brand` tokens, matching the voice picker's
  "Choose…" beside it, because these are the two controls on this section that open something.

  The native `<input type="file">` is styled out of the way rather than shown raw; it stays a
  real focusable input so the keyboard and the accessibility tree still reach it. `accept` is
  set to the same three types the door allows, so the dialog filters to them - **and the server
  still validates**, because `accept` is a convenience the user can defeat by typing a filename.

  Show the **chosen filename and the resulting size** after selection, since the point of this
  task is that a large file quietly becomes a small one - an administrator who is never told it
  happened will upload the same 8 MB photograph again next time.

- [ ] **Step 8b: On save, post the file first, then the configuration with the returned URL.**
  Assert **what is sent**, both calls and **in that order** - a test that asserts the input
  renders is the twelfth of exactly that shape on this project. Drive the failure too: if the
  upload fails the configuration save must not proceed with a stale or empty `image_url`, and
  the administrator must be told which half failed.

- [ ] **Step 9: Suites twice. Power-check each of Steps 3, 4, 5 and 6 separately - for Step 5
  use an image that is BOTH rotated and carries GPS, and confirm the two properties fail
  independently. Commit.**


---

### Task 4c: The first portrait for a faceless agent becomes the deployment's default

**Files:** Modify `api/database.py`, `api/routers/agent_config.py`, `api/services/agent_config_service.py`; Create `api/routers/agent_assets.py`; Test: new `tests/test_agent_default_image.py`

Patrick's instruction, 7 September: portraits stay per project, but *"if no default image exists,
then use the first uploaded image as the default for all future projects."* Runs after Task 4b,
which builds the upload it hooks into.

**Interfaces:**
- Consumes: `prepare_portrait` (Task 4a) and the upload door (Task 4b).
- Produces: `GET /api/agents/{agent_id}/image`, **unauthenticated**.

- [ ] **Step 1: Report the four precedence levels from the spec and where each is read today.**
  Project override, promoted default, built-in asset, initials. Report what currently resolves
  `image_url` and where a level 2 has to be inserted - one place, not two, or the interview page
  and the Setup section will disagree about an agent's face.

- [ ] **Step 2: Add `agent_default_images` to `init_system_db`** - `agent_id` PRIMARY KEY,
  `extension`, `promoted_from_slug`, `promoted_at`. **Do NOT bump `_SCHEMA_VERSION`**: it gates
  *project* databases, `init_system_db` has no version gate and runs on every system connection,
  and bumping it would re-run every project migration for a table in a database it does not
  govern. CLAUDE.md states this rule and states that it is inverted from the project rule.

- [ ] **Step 3: Write the failing test - first wins, and second does not**

```python
async def test_the_second_upload_does_not_displace_the_promoted_default():
    await upload_portrait("project-a", "second_interviewer", _png())      # promotes
    await upload_portrait("project-b", "second_interviewer", _other_png())  # must not
    row = await fetch_agent_default_image("second_interviewer")
    assert row["promoted_from_slug"] == "project-a"
```

**Assert the provenance, not merely that a row exists.** A promotion that overwrote would leave
a row too, and the test would pass against exactly the behaviour it forbids.

- [ ] **Step 4: Claim it with `INSERT OR IGNORE` on `agent_id`, never check-then-write.** The
  window in check-then-write is two clients' portraits racing, and the loser would overwrite the
  winner's file after losing the row. Follow `register_project_if_unregistered`, which is the
  same shape for the same reason. **Write the file only if the claim was won** - `rowcount`
  decides, not a prior `SELECT`.

- [ ] **Step 5: Write the failing test - an agent that already has a face is never promoted
  over.** Upload for `stakeholder_interviewer`, whose built-in `/agents/avery-singh.jpg` exists,
  and assert **no row is created at all**. Without this, a promotion keyed only on "is the table
  empty for this agent" would silently give Avery a new face on every future engagement.

- [ ] **Step 6: Serve it from `GET /api/agents/{agent_id}/image`, unauthenticated**, in a new
  `api/routers/agent_assets.py`. Not from the project it came from: that would tie every
  project's rendering to the continued existence of whichever engagement uploaded first, and
  leak that slug into an unrelated client's markup. **Register the new prefix in BOTH proxies** -
  `Caddyfile` and `vite.config.ts` - or it falls through to the static file server and answers
  the landing page with a **200**. `tests/test_proxy_prefix_coverage.py` enumerates `app.routes`
  and will fail if you forget; read it before adding the route.

- [ ] **Step 7: Resolution honours all four levels, in order.** One test per level, and a fifth
  asserting a project override **beats** a promoted default - the pair is the whole point, and a
  resolver returning the promoted default always would pass four of the five.

- [ ] **Step 8: Suites twice. Power-check Steps 3, 5 and 7 separately - for Step 4, drive two
  concurrent uploads and confirm exactly one row and one file result. Commit.**


---

### Task 5: Document it

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: State the rule.** Who can conduct an interview is answered by `interviewer_agent_ids()` - an identity with a `voice_id` - and both the crew's selection and the rehearsal button read it from there. Record that `is_interviewer` and `voice_sex` are **derived** onto the configuration response rather than stored.

- [ ] **Step 2: Record the decision the sex filter did not reverse.** The picker filters by the sex of the interviewer's *current voice*, never by a table mapping agents to sexes, and say why: a project that gives Avery a female voice has said something, and a table here would contradict it while looking authoritative.

- [ ] **Step 2c: Record the promotion rule and its precedence table**, including the one property that makes it safe - it fills only the promoted-default level, never a built-in asset and never itself - and the one consequence that makes it unusual: this is the only write in the product where an upload on one engagement changes what a different client's engagement displays. Say that replacing a promoted default needs a deletion door that does not exist yet, and is sysadmin-tier when it does.

- [ ] **Step 2b: Record the portrait upload.** An agent image is uploaded and downscaled to 512px on its longest side, EXIF stripped (orientation honoured first), and stored same-origin - so an uploaded portrait cannot reach a third party from the unauthenticated interview page. The free-text field still can, so say the hole is narrowed rather than closed.

- [ ] **Step 3: Record that Laura has no portrait**, that `AgentAvatar` renders initials for any agent without one, and that a real asset is wanted and is not blocked on code.

- [ ] **Step 4: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** the button's audience derived not restated (1, 3), the sex filter from the voice (1, 2), the filter clearable and never empty (2), the dialog de-Averyed (3), the portrait fallback (3), the portrait upload and downscale (4), documented (5).

**Placeholder scan:** none. Tasks 1, 2 and 3 each open by establishing facts from the code, because a brief on this project has been wrong about the codebase more than a dozen times - twice on the immediately preceding branch.

**Type consistency:** `is_interviewer: bool` and `voice_sex: 'male' | 'female' | null` are produced in Task 1 and consumed in 2 and 3, declared required in `AgentConfig`.

**Not in scope:** a portrait asset for Laura; changing Taylor's selection; storing a sex anywhere in this repository.

**One ordering note:** Task 3 could precede Task 2, but the picker is easier to test against a payload that already carries `voice_sex` than against a stub of one.

---

### Task 6: An Agents tab, and Setup keeps only what a crew owns

**Files:** Modify `ui/src/components/AgentDetailPanel.tsx`, `ui/src/components/tabs/CrewSetupSections.tsx`; Test: extend `ui/src/__tests__/AgentDetailPanel*.test.tsx`, new `ui/src/__tests__/AgentsTab.test.tsx`

Patrick's decision, 7 September. Spec section: *Separating agent setup from crew setup*. Runs
after Task 3, which puts the rehearsal button inside `AgentConfigSection` - this task moves the
container, not the button.

- [ ] **Step 1: Report the five sites that know the tab list**, before changing any: the `Tab`
  union (`AgentDetailPanel.tsx:95`), the `isTab` guard (:818), the saved-tab restore (:835), the
  rendered tab array (:1008), and the mount latch (:871). Say what each does and which of them
  fails **silently**.

- [ ] **Step 2: Derive the guard and the restore from one list.** Do not add a sixth
  restatement. A tab missing from `isTab` does not error - it falls back to `output`, so the tab
  works until the user reloads and then forgets where they were, which no rendering test sees.

- [ ] **Step 3: Write the failing test - the reload, not the render**

```tsx
it('is still the Agents tab after a reload', () => {
  // Through the saved-tab restore, because that is the path a missing guard entry breaks.
  // Asserting the tab renders would pass against exactly the defect being prevented.
  localStorage.setItem(TAB_KEY, 'agents')
  renderPanel()
  expect(screen.getByTestId('agents-tab-panel')).toBeVisible()
})
```

- [ ] **Step 4: Add the tab with its own mount latch**, mirroring `setupOpened`. Without it the
  panel fetches every agent's configuration for a tab nobody opened - four requests per crew
  rather than Setup's one, which is the sp62 defect arriving where it costs four times as much.

- [ ] **Step 5: Write the failing test - and the control.** Opening a panel on Output asks for
  no agent configuration; opening Agents asks for it. Both, or a component that never fetched
  would pass the first.

- [ ] **Step 6: The tab opens on the agent clicked in the carousel**, not always the first.
  Assert with a crew whose clicked agent is **not** first - with `[Taylor, Avery, Laura, Casey]`
  and Avery clicked, a component ignoring the selection and a component honouring it differ only
  if the expected agent is not index 0.

- [ ] **Step 7: Move `CrewAgentConfiguration` and `CrewSetupSections` out of Setup into Agents**,
  and move `CREW_SETUP_OVERRIDE`'s three components - `PamSetupTab`, `AlexSetupTab`,
  `MayaSetupTab` - beside the agent each is named after. Setup keeps the crew note, reads and
  produces.

- [ ] **Step 8: Write the failing test - Setup's ABSENCE.** Assert no agent configuration renders
  under Setup, as well as that it renders under Agents. A test that only checks Agents passes
  with both showing it, which is the state this task exists to end.

- [ ] **Step 9: Frontend suite, `tsc` clean. Power-check Steps 3, 5, 6 and 8 separately -
  for Step 3, delete the new entry from the `isTab` derivation and confirm the reload test fails
  while every rendering test still passes. Commit.**


---

### Task 7: A configured name and face reach the places that draw them

**Files:** Modify `api/routers/agent_config.py`, `ui/src/components/agentStatus.ts`; Create `ui/src/hooks/useAgentIdentity.ts`; Modify the nine display sites; Test: new `tests/test_agent_config_bulk.py`, new `ui/src/__tests__/useAgentIdentity.test.tsx`

Reported by Patrick, 7 September: he uploaded a portrait for Jordan on `sp-gs-am`, the door
downscaled and stored it, the configuration row saved `/projects/sp-gs-am/agents/
stakeholder_manager/image`, the URL serves 200 - **and every face on the dashboard was
unchanged.**

The feature is correct at the layer it was built and invisible at the layer it is looked at,
which is this project's most-recorded failure shape arriving in the UI rather than in a test.
**Nine sites draw an agent's face and all nine read `AGENT_AVATAR_IMAGE`**, a static map in
`agentStatus.ts`. Nothing outside `AgentConfigSection` and the interview page's session stamp
reads the configured value.

The same is true of `display_name`: a project that renames an agent sees the new name in the
form it typed it into and the old one everywhere else.

- [ ] **Step 1: List the nine sites before changing any**, with the file and line: `AgentHoverCard`,
  `AgentOutputTab`, `AgentDetailPanel` (×3), `AgentStatusTab`, `CrewAgentsTab`, `Team.tsx`,
  `CrewCarousel` (×2, one of which is PAM's card). Report which of them have a `slug` in scope
  and which do not - `Team.tsx` is the one to check first, because a page listing the roll
  across the deployment may have no project to resolve against.

- [ ] **Step 2: Add `GET /projects/{slug}/agents/config`** - every agent's resolved
  configuration in one response, keyed by `agent_id`. **One request, not eighteen**: the
  existing per-agent door is fine for a form and would be nine renders × eighteen agents here.
  Membership floor only; this is a read, and it answers what the panel already shows.

- [ ] **Step 3: Write the failing test - the bulk door agrees with the single door**

```python
async def test_the_bulk_door_answers_what_the_single_door_answers(...):
    # Same resolution, not a second implementation of it. A separate code path here is a
    # second place for "override beats default" to be got wrong, and the two would diverge
    # silently because nothing compares them.
    for agent_id in interviewer_agent_ids() + ["pam", "stakeholder_manager"]:
        assert bulk["agents"][agent_id] == (await single_door(agent_id))["resolved"]
```

- [ ] **Step 4: Build `useAgentIdentity(slug)`**, returning `(agentName) => { name, imageUrl }`
  with the resolved override first and the static map as the fallback. Keyed by the **display**
  name the front end uses, since that is what all nine sites hold - `AGENT_ID_BY_NAME` in
  `agentStatus.ts` already maps one to the other, so do not add a second mapping.

- [ ] **Step 5: Write the failing test - the fallback and the override, both ways**

An agent with no override renders the static map's image; an agent with one renders the
configured URL. Both, because a hook that ignored the configuration entirely passes the first
and a hook that ignored the fallback passes the second.

- [ ] **Step 6: Replace the nine sites.** Where there is no slug - if `Team.tsx` has none - say
  so and leave it on the static map rather than inventing a project for it.

- [ ] **Step 7: Write the failing test at the site that reported the defect** - the carousel
  face for a project that has configured one. This is the assertion that would have caught the
  bug, and it is worth more than the hook's own test: the hook can be perfect and unused.

- [ ] **Step 8: Suites twice, frontend and `tsc` clean. Power-check each of Steps 3, 5 and 7
  separately. Commit.**


---

### Task 8: Each tab means one thing

**Files:** Modify `ui/src/components/AgentDetailPanel.tsx`, `ui/src/components/tabs/CrewAgentsTab.tsx`, `ui/src/components/AgentStatusTab.tsx`, the six `*SetupTab.tsx` panels, `ui/src/router.tsx`, `ui/src/pages/Runs.tsx`; Test: extend the panel tests, new `ui/src/__tests__/TabClassification.test.tsx`

Patrick's decision, 7 September, after using the tabs. Spec section: *Where a panel belongs: the
rename test*. The classification and the reasoning are there; this is the build.

- [ ] **Step 1: Report what each of the six panels renders, section by section**, before moving
  anything. The spec's table is the decision, not the survey - confirm it against the source and
  say where you disagree. `PamSetupTab` is 1,183 lines and splits across two tabs, so its
  sections are the ones to enumerate most carefully.

- [ ] **Step 2: Move Taylor's two.** The stakeholder list, counts and CSV import to **Status**;
  Interview Invite Rules to **Setup**. These are the two Patrick named.

- [ ] **Step 3: Write the failing test - present on the new tab AND absent from the old**

```tsx
it('shows the stakeholder summary on Status and not on Agents', async () => {
  // Absence is the half that fails silently. A section rendered on BOTH tabs satisfies every
  // "is it there" assertion, and that is exactly the state a careless move leaves behind.
  renderPanel({ crew: 'discovery_interviews' })
  expect(within(statusTab()).getByText(/Stakeholders ·/)).toBeInTheDocument()
  expect(within(agentsTab()).queryByText(/Stakeholders ·/)).toBeNull()
})
```

  Note the tabs render **hidden rather than unmounted**, so `queryByText` at screen level finds
  content on an inactive tab. Scope every assertion with `within(...)` on the tab's own panel or
  the absence half asserts nothing.

- [ ] **Step 4: Move the other four**, per the spec's table: Alex and Jordan wholesale to Setup;
  Maya splits (disciplines to Setup, programme reference to Status); Pam splits (schedule and
  calendar to Setup, milestone statistics and the interview tracker to Status). Avery does not
  move.

- [ ] **Step 5: Keep Pam's milestones on one query.** The schedule editor and the statistics read
  the same rows. Two components sharing one query key is right; two queries is a second fetch
  and two answers that can disagree while one is stale. Assert the request count, not the
  rendering - a duplicated fetch looks identical on screen.

- [ ] **Step 6: Correct the deep links, for the second time.** `router.tsx`'s
  `AssignmentRedirect` and `Runs.tsx`'s "Assign stakeholders" both went `tab=setup` →
  `tab=agents` in Task 6, with a comment explaining why; Jordan's mapping returns to Setup, so
  both links and that comment change again. **Drive them** - a link that lands on the right crew
  and the wrong tab looks like working navigation that simply does not hold what was asked for.

- [ ] **Step 7: The mount latch follows the content.** Whichever tab now pays for a query needs
  the latch that `setupOpened`/`agentsOpened` provide, or a panel opened on Output fetches a
  schedule nobody asked for. Assert it for each tab that gained fetching content.

- [ ] **Step 8: Write the classification as a property**, one test per tab: Agents holds nothing
  scoped to the engagement, Setup nothing scoped to a person, Status nothing editable. Stated as
  a test rather than as a comment, so a seventh panel added later has something to fail against.

- [ ] **Step 9: Frontend suite, `tsc` clean. Power-check Steps 3, 5, 6 and 8 separately. Commit.**

