# SP13c — Assessment Phase in Voice Interview

## Overview

Extends the voice interview with an optional structured assessment phase. When a questionnaire template is assigned to the node (via SP13b), the public interview page presents each questionnaire section after the qualitative interview sections complete. For each section, the interviewee rates every statement on a 0–4 maturity scale, then optionally records a voice commentary. Ratings and commentary are saved alongside the transcript and made available to the Synthesis Analyst.

**Depends on:** SP13b (questionnaire included in session response)

---

## Section 1 — Data model

### `ratings_json` column on `interview_sessions`

Migration in `api/database.py` via `_migrate_interview_sessions_ratings`:

```python
async def _migrate_interview_sessions_ratings(conn):
    async with conn.execute("PRAGMA table_info(interview_sessions)") as cur:
        cols = {row["name"] async for row in cur}
    if "ratings_json" not in cols:
        await conn.execute("ALTER TABLE interview_sessions ADD COLUMN ratings_json TEXT")
        await conn.commit()
```

Call this migration inside `get_connection` after `_migrate_interview_sessions`.

### `ratings_json` structure

```json
[
  {
    "section_id": "S1",
    "section_title": "Data Governance",
    "ratings": {
      "S1Q1": 3,
      "S1Q2": 2
    },
    "commentary": "We have some policies but they aren't consistently followed."
  }
]
```

---

## Section 2 — Backend

### DB helper update

**File:** `api/database.py` — `complete_interview_session`

Extend to accept and store `ratings_json`:

```python
async def complete_interview_session(
    conn, session_token, transcript_json, ratings_json=None
) -> None:
    await conn.execute(
        """UPDATE interview_sessions
           SET status='completed', transcript_json=?, ratings_json=?,
               completed_at=datetime('now')
           WHERE session_token=?""",
        (transcript_json, ratings_json, session_token),
    )
    await conn.commit()
```

### Service update

**File:** `api/services/interview_service.py` — `complete_session`

```python
async def complete_session(
    session_token: str,
    qa_pairs: list[dict],
    ratings: list[dict] | None = None,
) -> bool:
    db_path = await _find_session_db(session_token)
    if not db_path:
        return False
    async with aiosqlite.connect(db_path) as conn:
        transcript_json = json.dumps(qa_pairs)
        ratings_json = json.dumps(ratings) if ratings is not None else None
        await complete_interview_session(conn, session_token, transcript_json, ratings_json)
    return True
```

### Endpoint update

**File:** `api/routers/interviews.py` — `CompleteRequest` and `complete_interview`

```python
class CompleteRequest(BaseModel):
    qa_pairs: list[dict]
    ratings: list[dict] | None = None

@router.patch("/{session_token}/complete")
async def complete_interview(session_token: str, body: CompleteRequest):
    success = await complete_session(session_token, body.qa_pairs, body.ratings)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
```

---

## Section 3 — Frontend

### New TypeScript types

**File:** `ui/src/types.ts`

```typescript
export interface SectionRatings {
  section_id: string
  section_title: string
  ratings: Record<string, number>  // question id → 0-4
  commentary: string
}
```

### VoiceInterview.tsx changes

**File:** `ui/src/pages/VoiceInterview.tsx`

#### Phase addition

Add `'assessing'` to the `Phase` type:

```typescript
type Phase = 'loading' | 'ready' | 'interviewing' | 'assessing' | 'complete' | 'error'
```

#### State additions

```typescript
const [questionnaire, setQuestionnaire] = useState<QuestionnaireTemplateSchema | null>(null)
const [sectionRatings, setSectionRatings] = useState<SectionRatings[]>([])
const [currentAssessSection, setCurrentAssessSection] = useState(0)
const [pendingRatings, setPendingRatings] = useState<Record<string, number>>({})
```

#### fetchSession update

After parsing `data`:

```typescript
if (data.questionnaire) setQuestionnaire(data.questionnaire)
```

#### runInterview update

After the closing message is spoken and before submitting, if `questionnaire` is set, transition to assessing phase instead of submitting immediately:

```typescript
if (questionnaire) {
  setPhase('assessing')
  setCurrentAssessSection(0)
  setPendingRatings({})
  return  // submitAssessment() calls complete after all sections
}
// else submit directly
await submitResponses([])
```

#### submitResponses helper

Extract the complete call into a helper that accepts ratings:

```typescript
async function submitResponses(ratings: SectionRatings[]) {
  setStatusMessage('Saving your responses…')
  await fetch(`${BASE}/interviews/${sessionToken}/complete`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      qa_pairs: qaRef.current,
      ratings: ratings.length > 0 ? ratings : undefined,
    }),
  })
  setPhase('complete')
  setStatusMessage('')
  setCurrentQuestion('')
}
```

#### Assessment phase render

When `phase === 'assessing'` and `questionnaire`:

```tsx
const section = questionnaire.sections[currentAssessSection]

return (
  <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
    <div className="max-w-2xl w-full">
      {/* Section header */}
      <div className="mb-6">
        <p className="text-xs text-teal-600 font-medium uppercase tracking-wide mb-1">
          Assessment · Section {currentAssessSection + 1} of {questionnaire.sections.length}
        </p>
        <h2 className="text-xl font-bold text-gray-800">{section.title}</h2>
        {section.description && (
          <p className="text-sm text-gray-500 mt-1">{section.description}</p>
        )}
      </div>

      {/* Questions */}
      <div className="space-y-6 mb-8">
        {section.questions.map(q => (
          <div key={q.id} className="bg-white rounded-xl shadow-sm p-5">
            <p className="text-gray-800 mb-3">{q.text}</p>
            <div className="flex gap-2">
              {[0, 1, 2, 3, 4].map(score => (
                <button
                  key={score}
                  onClick={() => setPendingRatings(r => ({ ...r, [q.id]: score }))}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    pendingRatings[q.id] === score
                      ? 'bg-teal-600 text-white border-teal-600'
                      : 'bg-white text-gray-600 border-gray-200 hover:border-teal-400'
                  }`}
                >
                  {score}
                </button>
              ))}
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
              <span>Not Accounted For</span>
              <span>Optimized</span>
            </div>
          </div>
        ))}
      </div>

      {/* Voice commentary — gated behind all ratings being filled */}
      {allRated ? (
        <div className="bg-white rounded-xl shadow-sm p-5 mb-6">
          <p className="text-sm font-medium text-gray-700 mb-3">
            Any additional commentary for this section? (speak or skip)
          </p>
          {statusMessage && (
            <p className="text-teal-600 text-sm animate-pulse mb-2">{statusMessage}</p>
          )}
          <div className="flex gap-3">
            {!isListening ? (
              <button
                onClick={startCommentary}
                className="bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium py-2 px-4 rounded-lg transition-colors"
              >
                Speak
              </button>
            ) : (
              <button
                onClick={submitAnswer}
                className="bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium py-2 px-4 rounded-full transition-colors"
              >
                ✓ Done
              </button>
            )}
            <button
              onClick={() => advanceSection('')}
              disabled={isListening}
              className="text-sm text-gray-400 hover:text-gray-600 py-2 px-4 disabled:opacity-40"
            >
              Skip
            </button>
          </div>
        </div>
      ) : (
        <p className="text-xs text-gray-400 text-center mb-6">
          Please rate all statements above to continue.
        </p>
      )}
    </div>
  </div>
)
```

#### Commentary helpers

```typescript
async function startCommentary() {
  // Announce section via TTS then listen
  if (sessionData) {
    const { session } = sessionData
    const voiceId = session.voice_config.elevenlabs_voice_id
    const section = questionnaire!.sections[currentAssessSection]
    await speakText(`Any additional commentary on ${section.title}?`, voiceId)
  }
  const commentary = await listenForAnswer()
  advanceSection(commentary)
}

function advanceSection(commentary: string) {
  const section = questionnaire!.sections[currentAssessSection]
  const completed: SectionRatings = {
    section_id: section.id,
    section_title: section.title,
    ratings: { ...pendingRatings },
    commentary,
  }
  const updated = [...sectionRatings, completed]
  setSectionRatings(updated)

  if (currentAssessSection + 1 < questionnaire!.sections.length) {
    setCurrentAssessSection(i => i + 1)
    setPendingRatings({})
  } else {
    // All sections done — submit
    submitResponses(updated)
  }
}
```

Compute `allRated` before the render:

```typescript
const allRated = section.questions.every(q => pendingRatings[q.id] !== undefined)
```

The commentary card (Speak/Skip buttons) only renders when `allRated` is true. Until then, a helper text "Please rate all statements above to continue." is shown instead.

---

## Section 4 — Files affected

| File | Change |
|---|---|
| `api/database.py` | `_migrate_interview_sessions_ratings` + `complete_interview_session` updated |
| `api/services/interview_service.py` | `complete_session` accepts `ratings` param |
| `api/routers/interviews.py` | `CompleteRequest` + `complete_interview` updated |
| `ui/src/types.ts` | `SectionRatings` type |
| `ui/src/pages/VoiceInterview.tsx` | Assessment phase UI, state, helpers |
| `tests/test_interviews_router.py` | 2 new tests: complete with ratings, assessing phase flow |

---

## Task breakdown (2 tasks)

**Task 1 — Backend:** DB migration + `complete_interview_session` update + service + endpoint + 2 tests

**Task 2 — Frontend:** `SectionRatings` type + assessment phase state + render + `submitResponses` helper + `startCommentary` + `advanceSection`
