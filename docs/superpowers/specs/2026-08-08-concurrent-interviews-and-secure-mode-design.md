# Concurrent interviews and secure mode - design

**Date:** 2026-08-08
**Status:** agreed, ready for planning
**Sub-project:** B of two. A (staggered invite dispatch) follows and is specified separately.

## Why

A corporate campaign sends 50-300 interview invites and collects them over about ten working
days. People answer when it suits them - lunchtimes and breaks - so arrivals cluster. Peak
concurrency works out at roughly 10-20 simultaneous sessions:

```
300 invites / 10 working days        = 30 completions per day
half of them inside a 90-minute peak = 15 starts in 90 minutes
an interview runs about 30 minutes   = 15 x (30/90) ~ 5 concurrent, call it 10-20 pessimistically
```

Twenty concurrent sessions is a small number for a stateless API. Nothing here is about scale.
It is about four defects that only appear when interviews overlap, and one that only appears
when a project is marked sensitive. No test in the repository has ever run two interview
sessions at once.

## What the interview actually is

Worth stating, because it is not what the agent layer implies. The live interview is conducted
entirely in the browser (`ui/src/pages/VoiceInterview.tsx`) against stateless REST endpoints.
The whole script is shipped to the client, answers accumulate in JavaScript memory, and a single
`PATCH /complete` posts the lot at the end.

Avery, the Stakeholder Interviewer, does not conduct interviews. He creates the session rows,
then blocks on `HumanInputTool` in a `time.sleep(5)` loop for up to 24 hours waiting for a
consultant to type "ready". Nothing notifies the crew when a session finishes.

So concurrency is an API and database problem, not an agent problem. That is the good news:
stateless code is where concurrency is cheapest to make sound.

## The defects

### 1. A completing session freezes every other session

`index_answers` is a synchronous function making a network call to Chroma. It is called from
`record_answers`, which is called from `complete_session` inside its open SQLite connection:

```
complete_session -> async with aiosqlite.connect(db) as conn:
    record_answers(conn, ...) -> index_answers(slug, rows)   # sync, blocking, on the event loop
```

It holds the database connection and blocks the event loop. Measured with Chroma unreachable:
**3.66 s per completion**, and every other request in the process waits:

```
as called today                with the same call in a thread
  interviewee 1: 2.75s           interviewee 1: 0.02s
  interviewee 2: 2.75s           interviewee 2: 0.02s
  interviewee 3: 2.75s           interviewee 3: 0.02s
```

The comment above the call says a Chroma outage "must cost the session nothing - failing here
would lose an interview". That is true of the data: the SQLite rows are the system of record and
`index_answers` never raises. The reasoning is about the failing session in isolation. The cost
was never to that session's data; it was to everyone else's latency - and completions cluster at
the end of a break, exactly when others are mid-question.

### 2. Every question spoken pays a new TLS handshake

`speak` and `elaboration_press` are correctly async - `httpx.AsyncClient` and `AsyncAnthropic`,
both awaited - which is why a single interview feels responsive and why that responsiveness
survives concurrency. But both construct a fresh client per call. Measured against a real host:

```
new client per call :  478 ms     <- today
shared client       :  264 ms
avoidable           :  213 ms per utterance (1.8x)
```

### 3. The same 300 strings are synthesised thousands of times

Every interviewee on a script hears identical questions. The live model has 16 scripts and 300
distinct question texts. A 300-person campaign makes roughly 5,700 TTS calls for 300 distinct
strings.

This also carries an external risk that no code change removes: ElevenLabs caps concurrent
requests by plan tier, in single digits on lower tiers. Twenty simultaneous interviews all
synthesising speech can sit above that and take 429s.

### 4. A retried completion doubles the corpus

`interview_answers` has no uniqueness on `(session_id, question_id)` and is append-only by
design. A second `PATCH /complete` - two browser tabs, a retry, a flaky connection - writes the
entire answer set again. Casey then synthesises from a corpus with duplicates, and nothing
reports it.

### 5. Secure mode does not reach the interview

`get_crew_llm` is referenced in nine files: `agents/llm.py`, seven crew factories, and
`run_service.py`. None of them is an interview file. The interview path contains no reference to
`llm_mode`, `sensitive`, `LOCAL_LLM` or `llamacpp`.

A project marked sensitive therefore still sends the most confidential material in the system -
what employees say about their own organisation - to external services:

| Hop | What leaves | Decision |
|---|---|---|
| Anthropic, `elaboration_press` | the question **and the verbatim answer** | must route to the local LLM |
| Chroma Cloud, `index_answers` | every answer row | must use a local Chroma instance |
| Deepgram, STT | the interviewee's speech | **stays** - streamed, no content retention |
| ElevenLabs, TTS | the questions | **stays** - streamed, no content retention |

Deepgram and ElevenLabs remain in secure mode by decision. Moving them to local services is
future work and explicitly not a requirement now.

### Lesser items, fixed in passing

- `GET /api/interviews/sessions/{slug}` has no auth and returns every `session_token` for a
  project. Tokens are the sole credential for the entire public interview API.
- Two of three interview URL builders omit the `/dashboard` basename and use `frontend_url`,
  which is unset and defaults to `localhost:3000`. Only `campaign_service` builds a working
  link. The emailed link is the whole mechanism for sub-project A.
- `session_token` is generated by Taylor's prompt ("Generate a UUID4"). The uniqueness of the
  sole access credential should not depend on a language model.
- `get_connection` runs `init_db` plus 27 `_migrate_*` functions on every open, about 4.2 ms,
  and a single request opens several connections.

## The design

### Move expensive work off the moment a human is waiting

The unifying idea. Two variants of the same fault: work on the request path that blocks
(defect 1) and work on the request path that repeats (defect 3).

**Threading.** `index_answers` moves out of the SQLite connection and onto `asyncio.to_thread`.
The rows are committed before indexing, which the existing comment already assumes. Chroma
failure remains silent to the interviewee and still never raises.

**A speech cache** at `data/tts_cache/`, keyed `sha256(voice_id + "\x00" + text)`, storing the
audio bytes. `speak` consults it before calling ElevenLabs. Only elaboration presses, which are
dynamic, reach the provider on the request path.

**A pre-warm entry point** - `prewarm_script_audio(slug, script_id, voice_id)` - which
synthesises a script's questions and populates the cache. Sub-project A calls it when an invite
is released, minutes to days before the interviewee clicks. This is the hinge between the two
sub-projects and the reason B is built first: A plugs into it rather than duplicating it.

With the cache warm, scripted playback makes no network call at all, and the ElevenLabs
concurrency ceiling stops being reachable, because synthesis happens at the dispatch rate we
control rather than the clicking rate we do not.

### Make the database safe for overlap

`get_connection` sets `PRAGMA journal_mode=WAL` and an explicit `busy_timeout`. Today it is
`journal_mode=delete`, where writers block readers on one project file, and completions are the
heavy writes.

`interview_answers` gains `UNIQUE(session_id, question_id)`, and `insert_interview_answer`
becomes an upsert. `PATCH /complete` returns success without rewriting when the session is
already `completed`. The constraint is the real fix; the status guard is courtesy.

Migrations are memoised per process and slug, so the 27 functions run once rather than on every
connection.

### Reuse connections

Module-level `httpx.AsyncClient` and `AsyncAnthropic` singletons, created at import and closed
on application shutdown.

### Route secure mode

**Secure mode is a property of a project, not of a deployment.** One server runs sensitive and
standard projects side by side, and each must be handled according to its own `llm_mode`. Every
switch below therefore resolves from `projects.llm_mode` for the slug in hand, and no switch may
be a process-wide setting or an environment variable. A component that cannot see which project
it is serving cannot make this decision, which is why two signatures change below.

`get_chroma_client()` becomes `get_chroma_client(slug)`. It reads `projects.llm_mode` and
returns `HttpClient` for a sensitive project even when `CHROMA_API_KEY` is set. The switch lives
inside the factory because it has four callers - `index_answers`, `ingest_service`,
`chat_retrieval_service` and the agent-side `ChromaQueryTool` - and the rule applies to all of
them, not only to interviews.

This is the one place where the existing architecture actively resisted the requirement:
`get_chroma_client()` took no arguments and read a single global `CHROMA_API_KEY`, so a
process-wide client could not honour a per-project rule however carefully it was configured.
Passing the slug is what makes the guarantee expressible at all.

`elaboration_press` gains a `slug` parameter and routes through `llm_mode`: the local model at
`LLAMACPP_BASE_URL` when sensitive, Haiku otherwise. The session endpoint derives the slug from
`_find_session_db`, since the slug is the database filename. `POST /test/elaboration-press`
carries no client data and stays on the standard path.

**A press budget.** A local model serves far fewer parallel requests than a hosted API and
generates more slowly - a follow-up that takes under a second on Haiku may take several seconds
locally, plus queueing. The press sits on the request path with a human waiting. So
`elaboration_press` takes a timeout, and on expiry the endpoint returns "no press" rather than an
error. The interview continues to the next scripted question.

This is a deliberate trade. An elaboration press is an enhancement, not part of the instrument:
a missed one costs some depth on a single answer, while a ten-second silence costs the
interviewee's confidence in the whole conversation. Skipped presses are counted and logged so a
consistently over-budget local model is visible rather than merely quiet.

The budget is **configurable in Avery's settings**, because the right value depends on the model
behind it: a few seconds is generous for Haiku and mean for a local model on modest hardware.
Per-agent configuration in this codebase lives in `projects.config_json` alongside
`interview_method` and the `brand_interviewer_*` keys, edited on the Settings page, so the budget
follows that pattern rather than introducing an agent-settings table for one value:

```
config key : elaboration_press_timeout_seconds
default    : 8
surfaced   : ui/src/pages/Settings.tsx, beside Interview Method
```

The default applies when the key is absent, so existing projects need no migration.

### The lesser items

One `interview_url(session_token)` helper, built from `public_url` and the `/dashboard`
basename, replacing all three call sites. `GET /sessions/{slug}` moves behind `require_any_auth`.
`session_token` is generated in `InterviewSessionTool` with `uuid.uuid4()`, and Taylor's task
stops asking for one.

## Testing

The concurrency harness is the centre of this: N simultaneous sessions against one project,
asserting no lock errors, no duplicate answer rows, and that a completing session does not delay
another session's next question. Written against the endpoints, because that is the layer that
would break.

CLAUDE.md records six occasions where a test verified a property one layer away from where it
holds. Three assertions here are deliberately placed at the layer that would actually fail:

- **Duplicate submission** is driven through `PATCH /complete` twice, not by calling
  `record_answers` twice. The constraint is on the table, but the guard is in the endpoint.
- **Head-of-line blocking** is measured as another session's latency while one completes, not by
  asserting `to_thread` was called. A test that asserts the call site cannot tell whether the
  loop was actually freed.
- **Secure routing** asserts the base URL the request was sent to for a project whose `llm_mode`
  is `sensitive`, not that `get_crew_llm` was called. The defect being fixed is precisely that a
  correct-looking mode helper existed and the interview path never consulted it.
- **The press timeout setting** is asserted as *persisted and read back*, not as rendered.
  CLAUDE.md's list already contains "a radio tested as rendered, not as sent", and this is the
  same control on the same page. The test changes the value, saves, and asserts the timeout the
  endpoint actually applies.
- **Per-project isolation** is asserted with two projects in one process - one sensitive, one
  standard - interleaved. The sensitive one must reach the local model and a local Chroma while
  the standard one reaches Haiku and the cloud, in the same test. A per-deployment
  implementation passes every single-project test and fails only this one, so it is the test
  that distinguishes the requirement from the thing that merely looks like it.

Cache tests cover a miss then a hit, that a hit makes no provider call, and that two concurrent
misses on the same key do not corrupt the file. Pre-warm is tested for idempotency, since A will
call it once per invite and invites can be retried.

Secure-mode tests use a stub local endpoint; no test requires a running model, and none requires
Chroma.

## Out of scope

Local STT and local TTS. Deepgram and ElevenLabs remain in secure mode by decision, on the
grounds that both are streamed with no content retention. Recorded here so a future reader knows
it was decided rather than missed.

Avery's 24-hour `HumanInputTool` block and the crew's ignorance of session completion are real
and untouched. Neither affects interviewee experience, which is what this sub-project is for.

Sub-project A - the dispatch queue, cohort ordering, daily quota, send window and pre-warm
trigger - is specified separately and built after this.
