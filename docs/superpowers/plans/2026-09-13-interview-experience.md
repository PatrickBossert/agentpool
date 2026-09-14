# The last three things a participant meets - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Findings 7, 8 and 9 of the 4 September interview walkthrough: every answer editable, the broken email button replaced by a note, and the recogniser given the project's own vocabulary by finishing a Deepgram path that was built and never connected.

**Spec:** `docs/superpowers/specs/2026-09-13-interview-experience-design.md`

## Global Constraints

- **British English** - `-ise`, `-our`, `-re`, Oxford comma, spaced ` - ` en dash, **never an em dash**.
- **`brand` tokens only**, never `sky-*`/`blue-*`. Lucide icons, **no emoji**. `describeError` imported from `ui/src/utils/describeError.ts`, never copied.
- **Baselines: backend 2980 passed / 2 skipped / 12 deselected, frontend 919 / 99 files, `tsc --noEmit` clean.** Establish all three yourself, twice.
- **Isolate every pytest run**: export `DATABASE_DIR`, `PROJECTS_DIR` and `DATA_DIR` to a private temporary directory. An async fixture needs `@pytest_asyncio.fixture`.
- **Block egress at the socket before running anything that could call out**, and prove the block in both directions - remote refused, loopback still working - so a green suite cannot be the block failing everything closed.
- Power-check each property separately, confirm each mutation **landed**, clear `__pycache__` between mutation and revert, report **which** test caught it.
- Stage explicit paths. **Never `git add -A`.** Write nothing to `data/`. Do not restart the server on :8000.

---

### Task 1: Every answer is editable, and the email promise is withdrawn

**Files:** Modify `ui/src/pages/VoiceInterview.tsx`; Test: extend `ui/src/__tests__/` (new file for the review step)

- [ ] **Step 1: Report what the review step renders today** - the per-answer `Pencil` control, `editingIdx`/`editText`, and the `sendCopy`/`copyEmail` checkbox that posts to `/interviews/{token}/email-transcript`. Say how many answers a real session carries; the 4 September walkthrough had 59.

- [ ] **Step 2: Every answer is an editable field, with no reveal.** Remove the pencil and the single-open-editor state. A participant correcting what the recogniser heard is the last chance to fix it, and an affordance nobody notices is not one.

- [ ] **Step 3: Write the failing test - editable without interaction**

```tsx
it('offers every answer for editing without a click to reveal', async () => {
  renderReview({ answers: threeAnswers })
  // Queried, not hovered. The defect was an affordance that existed and was not found.
  const fields = screen.getAllByRole('textbox', { name: /your answer/i })
  expect(fields).toHaveLength(3)
})
```

- [ ] **Step 4: An edit still reaches the transcript.** The control changed; what it does must not. Assert the corrected text is what is **sent** on submission, not what renders in the box.

- [ ] **Step 5: Replace the email checkbox with the note.** For confidentiality the report is not emailed; it can be copied with the COPY button. Remove `sendCopy`, `copyEmail` and the `email-transcript` post.

- [ ] **Step 6: Write the failing test - the absence of the REQUEST**

```tsx
it('never posts to email-transcript', async () => {
  // Asserted on the request, not on the checkbox. The defect was a post that SUCCEEDED
  // and delivered nothing - `{"sent": true}` to a participant who never received it.
  renderReview(); await finishTheReview()
  expect(fetchCalls().some(c => /email-transcript/.test(c))) .toBe(false)
})
```

- [ ] **Step 7: Frontend suite, `tsc` clean, power-check Steps 3, 4 and 6 separately. Commit.**

---

### Task 2: The recogniser is told the project's own words

**Files:** Modify `api/services/interview_service.py`, `api/routers/interviews.py`, `ui/src/pages/VoiceInterview.tsx`; Test: new `tests/test_interview_keyterms.py`, frontend

**Interfaces:**
- Produces: the token door also answers the project's keyterms, so the client makes one request rather than two.

- [ ] **Step 1: Establish the current path before changing it.** The page uses `webkitSpeechRecognition`; `GET /api/interviews/{session_token}/deepgram-token` exists and **nothing in `ui/src` calls it**. Confirm both, and report what `generate_deepgram_token` returns and what scope it grants. Report Deepgram's current parameter for this - `keywords` and `keyterm` are different features on different models - and say which you are using and why.

- [ ] **Step 2: Build the vocabulary from the project**, not from a list here: `value_chain_ledger` labels and the text of that project's `interview_scripts`. Deduplicate, drop anything too short or too common to boost, and cap it - a vocabulary of everything boosts nothing.

- [ ] **Step 3: Write the failing test - the terms come from the project**

```python
async def test_the_keyterms_are_this_project_s_own_words(...):
    # Two projects with different registries get different keyterms. A hardcoded list
    # would satisfy a single-project assertion perfectly.
    assert "Iberdrola" in await keyterms_for("sp-gs-am")
    assert "Iberdrola" not in await keyterms_for("other-project")
```

- [ ] **Step 4: The client connects to Deepgram with them.** Assert **what is sent on the socket**, not what the helper returns - a helper can be perfect and unused, which is exactly how this path came to exist.

- [ ] **Step 5: A project with no registry and no scripts connects with no keyterms**, rather than failing. The control: without it, a fix that never connected at all would pass Step 3.

- [ ] **Step 6: Decide and state the fallback.** A browser that cannot reach Deepgram, or a deployment whose token door 503s for want of a key, must still let the interview happen or must say clearly that it cannot. Say which you chose. **Do not leave a participant mid-interview with a recogniser that silently stopped.**

- [ ] **Step 7: `agents/egress.py` says what leaves now.** Deepgram was a declared ungated reach carrying nothing, because nothing called it. It now carries a participant's speech. The row changes; the gating does not.

- [ ] **Step 8: Suites twice, frontend and `tsc` clean. Power-check Steps 3, 4 and 5 separately. Commit.**

---

### Task 3: Document it

**Files:** Modify `CLAUDE.md`, `ui/src/pages/Architecture.tsx`

- [ ] **Step 1: The Deepgram entry becomes true.** CLAUDE.md has described an intention: "used in secure mode by decision, both being streamed with no content retention". Say what is now the case, and say plainly that it was built and unconnected until this branch - that is the fourth such finding on this project and the pattern is worth naming once more.

- [ ] **Step 2: Record the rule the vocabulary follows.** Terms come from the project's own material, never from a list in this repository - the same rule the voice work reached after five disagreeing declarations, and a vocabulary of client names has a worse failure mode than a voice id.

- [ ] **Step 3: Correct the Architecture page** if it still describes the access method as something no participant has used.

- [ ] **Step 4: Suites unchanged. Both counts stated. Commit.**

---

## Self-Review

**Spec coverage:** every field editable (1), the email promise withdrawn (1), the recogniser given the project's words (2), the fallback decided (2), egress restated (2), documented (3).

**Placeholder scan:** none. Tasks 1 and 2 each open by establishing the current shape, because finding 9's own premise was wrong and only reading the code showed it.

**Not in scope:** narrowing Deepgram's egress; a project-scoped vocabulary editor; replacing the Web Speech API anywhere but the interview page.
