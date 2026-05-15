# SP10f — Interview Script Designer + Voice Interviews

## Overview

SP10f adds two capabilities to the Discovery Interviews Crew:

1. **Interview Script Designer** — a new CrewAI agent that produces one rich, structured interview script per value chain node, incorporating corporate context (discovery brief, value chain summary, sector). Scripts include thematic sections, per-question follow-up branches, probing instructions, and evasion signals.

2. **Voice Interview Interface** — a public browser-based voice interview page where stakeholders hear questions spoken by an ElevenLabs voice matched to their locale, respond via microphone (transcribed by Deepgram), and receive a dynamic elaboration press from a single LLM call when their answer is thin or evasive. The interview is script-driven for speed and predictability; only the elaboration press is dynamically generated.

The crew grows from three agents to four:

```
Interview Script Designer
        ↓  writes interview_scripts (keyed by node_label)
Interview Coordinator
        ↓  writes interview_plan (stakeholder → node_label + session_token + voice_config)
Stakeholder Interviewer
        ↓  creates DB sessions, presents URLs, waits for transcripts
Synthesis Analyst
        ↓  writes activity_insights, requirements, value_levers (unchanged)
```

---

## Section 1 — Interview Script Designer agent

**File:** `agents/discovery/interview_script_designer.py`

**Role:** Reads discovery context and produces one structured interview script per value chain node that has stakeholder assignments. Scripts are node-scoped — all stakeholders assigned to the same node share the same script, personalised only at delivery (voice, name, greeting).

**Inputs (read via SQLiteStateTool):**
- `value_chain_tree` — node labels and hierarchy
- `value_chain_summary` — approved value chain narrative (corporate context)

**Injected into task description:**
- Discovery brief (same pattern as current Interview Coordinator)
- Stakeholder assignments block (node_label → list of job titles)

**Output — `interview_scripts`:**

A JSON object keyed by `node_label`. Each value is a script object:

```json
{
  "node_label": "Goods-in Inspection",
  "level": "L3",
  "research_brief": "2-3 sentences on the purpose of this interview for this node",
  "study_objectives": [
    "Identify biggest pain points at this stage of the lifecycle",
    "Understand data requirements and where current data falls short"
  ],
  "welcome_message": "Hi [name], thank you for joining this interview...",
  "closing_message": "Thank you for your time and insights...",
  "sections": [
    {
      "title": "Role & Context",
      "questions": [
        {
          "id": "Q1",
          "text": "Tell me about your role — what are you responsible for day-to-day?",
          "follow_up_count": 2,
          "probing_instructions": "Probe for day-to-day responsibilities, decision authority, and team interfaces.",
          "follow_up_branches": [
            "Could you walk me through a specific example of that?",
            "What does that look like on a typical day?"
          ],
          "evasion_signals": ["not sure", "it varies", "it's fine", "I don't know", "hard to say"]
        }
      ]
    }
  ]
}
```

**Script structure guidelines the agent follows:**
- 4–6 thematic sections per script (e.g. Role & Context, Current Process & Pain Points, Data & Decision-Making, Tools & Systems, Modernisation Priorities)
- 2–4 questions per section; 8–14 questions total
- Each question has 1–3 pre-generated follow-up branches and a set of evasion signals
- Welcome and closing messages are warm, professional, and reference the engagement purpose
- Research brief and study objectives are tailored to the node's position in the value chain

**HITL:** Presents all scripts (one per node) for consultant approval. Up to 3 revision cycles.

**Saves:** `interview_scripts` via SQLiteStateTool.

---

## Section 2 — Updated Interview Coordinator

**File:** `agents/discovery/interview_coordinator.py` (modified)

The Coordinator's role narrows significantly. It no longer designs questions — that is now the Script Designer's job. The Coordinator maps each stakeholder to their node's script and generates the session plan.

**Task steps:**
1. Read `interview_scripts` from SQLiteStateTool
2. Receive stakeholder assignments (injected in task description): `[{stakeholder_id, name, job_title, node_label, preferred_language, country_code}]`
3. For each stakeholder, look up their node's script and produce a session entry:
   ```json
   {
     "stakeholder_id": 1,
     "name": "Alice Chen",
     "node_label": "Goods-in Inspection",
     "session_token": "<uuid4>",
     "voice_config": {
       "language": "en",
       "country_code": "NZ",
       "elevenlabs_voice_id": "<voice-id-for-en-NZ>"
     }
   }
   ```
4. Write `interview_plan` (array of session entries) via SQLiteStateTool
5. HITL: present plan for approval. Up to 3 revision cycles.

**Voice config** is resolved at plan time using the `voiceLocale` lookup (language + country_code → ElevenLabs voice ID). This keeps the browser page simple — it just reads `voice_id` from the session and uses it.

---

## Section 3 — Updated Stakeholder Interviewer

**File:** `agents/discovery/stakeholder_interviewer.py` (modified)

No longer conducts interviews via HumanInputTool. Operates in three phases:

**Phase 1 — Create sessions**
1. Read `interview_plan` from SQLiteStateTool
2. Use `InterviewSessionTool(operation='create', sessions=[...])` to insert one `interview_sessions` DB row per stakeholder (status: `pending`)
3. Produce formatted interview URL list: `https://<host>/interview/<session_token>`
4. Use HumanInputTool: *"Interview sessions are live. Please share these links with your stakeholders:\n\n[URL list]\n\nReply 'ready' when all interviews are complete, or 'partial' to proceed with whoever has responded."*

**Phase 2 — Wait for completion**
5. On consultant reply, use `InterviewSessionTool(operation='get_status')` to see pending / active / completed / abandoned counts
6. If any sessions are still pending/active and consultant replied 'ready', flag the discrepancy and ask again

**Phase 3 — Collect transcripts**
7. Use `InterviewSessionTool(operation='get_transcripts')` to retrieve all completed transcripts
8. Write `interview_transcripts` via SQLiteStateTool in the same format as before:
   ```json
   [
     {
       "stakeholder_id": 1,
       "name": "Alice Chen",
       "node_labels": ["Goods-in Inspection"],
       "qa_pairs": [{"question": "...", "answer": "..."}]
     }
   ]
   ```

Synthesis Analyst is unchanged — it reads `interview_transcripts` and produces the three downstream outputs.

---

## Section 4 — InterviewSessionTool

**File:** `agents/tools/interview_session_tool.py`

A CrewAI tool wrapping the `interview_sessions` DB table with four operations:

| operation | inputs | what it does |
|---|---|---|
| `create` | `sessions: list[dict]` | Inserts one row per stakeholder; returns formatted URL list |
| `get_status` | — | Returns counts: pending, active, completed, abandoned |
| `get_transcripts` | — | Returns list of completed `{stakeholder_id, name, node_label, transcript_json}` |
| `mark_abandoned` | `session_tokens: list[str]` | Sets listed sessions to abandoned |

The tool reads `slug` and `orchestration_run_id` from its constructor (injected at crew creation time via registry, same pattern as SQLiteStateTool).

---

## Section 5 — DB migration

**Table: `interview_sessions`**

```sql
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    orchestration_run_id INTEGER REFERENCES orchestration_runs(id),
    stakeholder_id INTEGER NOT NULL REFERENCES stakeholders(id),
    node_label TEXT NOT NULL,
    session_token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    transcript_json TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Status values: `pending` | `active` | `completed` | `abandoned`

DB helper functions added to `api/database.py`:
- `insert_interview_session(conn, project_id, orchestration_run_id, stakeholder_id, node_label, session_token) -> int`
- `fetch_interview_session(conn, session_token) -> Row`
- `fetch_interview_sessions_status(conn, orchestration_run_id) -> dict`
- `fetch_interview_transcripts(conn, orchestration_run_id) -> list[Row]`
- `update_interview_session_status(conn, session_token, status)`
- `complete_interview_session(conn, session_token, transcript_json)`

---

## Section 6 — Voice interview page and API

### Browser — `ui/src/pages/VoiceInterview.tsx`

Public route: `/interview/:sessionToken` — no authentication required.

**Interview flow:**
1. Load session + script: `GET /api/interviews/:sessionToken`
2. Request short-lived Deepgram token: `GET /api/interviews/:sessionToken/deepgram-token`
3. Set status to active: `PATCH /api/interviews/:sessionToken/status` (`{status: "active"}`)
4. Speak welcome message via ElevenLabs (server proxy)
5. For each section → each question:
   a. Speak question text via `POST /api/interviews/:sessionToken/speak`
   b. Activate microphone; stream to Deepgram browser SDK using short-lived token
   c. End-of-speech detected → finalise transcript
   d. **Answer quality check:** if `word_count < 20` OR any `evasion_signals` match:
      - Call `POST /api/interviews/:sessionToken/elaboration-press` with `{question_text, response_text, probing_instructions}`
      - Receive dynamic press text → speak it → record response → append both to qa_pairs
   e. Otherwise: select next pre-scripted follow-up branch → speak → record → append
   f. After `follow_up_count` follow-ups, move to next question
6. Speak closing message
7. `PATCH /api/interviews/:sessionToken/complete` with full `{qa_pairs}` transcript
8. Show thank-you screen

**Voice locale mapping — `ui/src/utils/voiceLocale.ts`:**

A lookup table mapping `{language, country_code}` → ElevenLabs voice ID. Initial entries cover: `en/GB`, `en/US`, `en/AU`, `en/NZ`, `en/CA`, `fr/FR`, `de/DE`, `es/ES`. Easily extended. Falls back to `en/GB` if no match found.

### Server — `api/routers/interviews.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/interviews/:sessionToken` | None | Load session metadata + script JSON |
| GET | `/api/interviews/:sessionToken/deepgram-token` | None | Generate short-lived Deepgram streaming token |
| POST | `/api/interviews/:sessionToken/speak` | None | Proxy text → ElevenLabs TTS → return audio blob |
| POST | `/api/interviews/:sessionToken/elaboration-press` | None | LLM call → return dynamic press text |
| PATCH | `/api/interviews/:sessionToken/status` | None | Set status=active on first interaction |
| PATCH | `/api/interviews/:sessionToken/complete` | None | Write transcript JSON, set status=completed |

**No authentication** on any interview endpoint — session tokens (UUID4) serve as the access credential. The token is unguessable and single-use per stakeholder.

### `api/services/interview_service.py`

- `get_session_with_script(session_token)` — loads session from DB, reads `interview_scripts` from project SQLiteStateTool store, extracts script for `node_label`
- `generate_deepgram_token()` — calls Deepgram API to issue a short-lived streaming token
- `speak(text, voice_id)` — calls ElevenLabs TTS API, returns audio bytes
- `elaboration_press(question_text, response_text, probing_instructions, stakeholder_name)` — single LLM call with a tight prompt: *"You are a polite but insistent interviewer. The participant has given an insufficient answer. Generate one natural follow-up question (max 2 sentences) that presses for elaboration without being confrontational."* Returns text only.
- `complete_session(session_token, qa_pairs)` — writes transcript, sets status=completed

---

## Section 7 — Crew factory update

**File:** `agents/crews/discovery_interviews_crew.py` (modified)

`create_discovery_interviews_crew` grows to four agents:

```python
def create_discovery_interviews_crew(
    slug: str,
    run_id: int,
    llm_mode: str,
    sector: str,
    stakeholder_assignments: list[dict],
    discovery_brief: str = "",
    llm: LLM | None = None,
    hitl_tool=None,
) -> Crew:
```

`discovery_brief` is now injected as a parameter (read from project config in `run_service.py`) so the Script Designer can incorporate it without reading a separate state key.

Task sequence: `t0 (script_designer) → t1 (coordinator, context=[t0]) → t2 (interviewer, context=[t1]) → t3 (analyst, context=[t2])`

**Registry additions (`agents/tools/registry.py`):**
- `interview_script_designer`: `[SQLiteStateTool, HumanInputTool]`
- `interview_coordinator`: add `InterviewSessionTool`
- `stakeholder_interviewer`: add `InterviewSessionTool`

---

## Section 8 — Files affected

| File | Change |
|---|---|
| `agents/discovery/interview_script_designer.py` | **New** — agent + task factory |
| `agents/tools/interview_session_tool.py` | **New** — DB-backed tool with 4 operations |
| `api/routers/interviews.py` | **New** — 6 endpoints |
| `api/services/interview_service.py` | **New** — service layer |
| `ui/src/pages/VoiceInterview.tsx` | **New** — public voice interview page |
| `ui/src/utils/voiceLocale.ts` | **New** — locale → voice ID lookup table |
| `tests/test_interview_script_designer.py` | **New** — agent task description tests |
| `tests/test_interview_session_tool.py` | **New** — tool operation tests |
| `tests/test_interview_service.py` | **New** — service + endpoint tests |
| `api/database.py` | Add `interview_sessions` table migration + 6 DB helpers |
| `agents/crews/discovery_interviews_crew.py` | 4-agent crew; Script Designer prepended; `discovery_brief` param |
| `agents/discovery/interview_coordinator.py` | Narrowed task — maps stakeholders to scripts; generates voice_config |
| `agents/discovery/stakeholder_interviewer.py` | Three-phase task — create sessions, HITL wait, collect transcripts |
| `agents/tools/registry.py` | Add `interview_script_designer`; add `InterviewSessionTool` to coordinator + interviewer |
| `api/services/run_service.py` | Pass `discovery_brief` to `create_discovery_interviews_crew` |
| `api/main.py` | Register interviews router |
| `ui/src/App.tsx` | Add public `/interview/:sessionToken` route (no auth guard) |
| `ui/src/types.ts` | Add `InterviewSession`, `InterviewScript`, `InterviewQuestion`, `VoiceConfig` types |
| `.env.example` | Add `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY` |

**New Python dependency:** `elevenlabs`
**New npm dependency:** `@deepgram/sdk`
