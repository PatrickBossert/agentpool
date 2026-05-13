# SP12a — Interview Session Monitor

## Overview

SP12a adds a real-time session status panel to the Discovery page's Interviews tab. When `interview_method` is `'agent'`, the consultant sees a live table of all stakeholder interview sessions from the most recent orchestration run — with status badges, copy-URL actions, and the ability to mark sessions as abandoned.

No new page or route. No auto-refresh polling. One new API endpoint. One inline component.

---

## Section 1 — Backend

### New DB helper: `fetch_interview_sessions_for_run`

**File:** `api/database.py`

```python
async def fetch_interview_sessions_for_run(
    conn: aiosqlite.Connection, orchestration_run_id: int
) -> list[aiosqlite.Row]:
```

JOINs `interview_sessions` with `stakeholders` to get `name`. Returns all rows for the given `orchestration_run_id`, all statuses, ordered by `created_at ASC`.

```sql
SELECT
    is_.id,
    is_.stakeholder_id,
    s.name,
    is_.node_label,
    is_.session_token,
    is_.status,
    is_.started_at,
    is_.completed_at,
    is_.created_at
FROM interview_sessions is_
LEFT JOIN stakeholders s ON s.id = is_.stakeholder_id
WHERE is_.orchestration_run_id = ?
ORDER BY is_.created_at ASC
```

### New endpoint: `GET /api/interviews/sessions/{slug}`

**File:** `api/routers/interviews.py`

No authentication — consistent with the rest of the interviews router.

Steps:
1. Look up `project_id` from `slug` (use existing `fetch_project_by_slug` helper)
2. If project not found → 404
3. Find the latest `orchestration_run_id` for the project:
   ```sql
   SELECT id FROM orchestration_runs
   WHERE project_id = ? ORDER BY created_at DESC LIMIT 1
   ```
4. If no orchestration runs → return `{"orchestration_run_id": null, "sessions": [], "summary": {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}}`
5. Fetch sessions via `fetch_interview_sessions_for_run`
6. Build `interview_url` for each session: `f"{settings.frontend_url}/interview/{row['session_token']}"`
7. Compute summary counts
8. Return response

**Response shape:**
```json
{
  "orchestration_run_id": 42,
  "sessions": [
    {
      "id": 1,
      "stakeholder_id": 3,
      "name": "Alice Chen",
      "node_label": "Goods-in Inspection",
      "session_token": "abc-123",
      "status": "completed",
      "interview_url": "http://localhost:5173/interview/abc-123",
      "started_at": "2026-05-13T10:00:00",
      "completed_at": "2026-05-13T10:30:00",
      "created_at": "2026-05-13T09:55:00"
    }
  ],
  "summary": {
    "pending": 2,
    "active": 1,
    "completed": 3,
    "abandoned": 0
  }
}
```

Mark-abandoned uses the existing `PATCH /api/interviews/{session_token}/status` with `{"status": "abandoned"}` — no new endpoint needed.

---

## Section 2 — Frontend

### New types — `ui/src/types.ts`

```typescript
export interface SessionSummary {
  pending: number
  active: number
  completed: number
  abandoned: number
}

export interface InterviewSessionStatus {
  id: number
  stakeholder_id: number
  name: string
  node_label: string
  session_token: string
  status: 'pending' | 'active' | 'completed' | 'abandoned'
  interview_url: string
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface InterviewSessionsResponse {
  orchestration_run_id: number | null
  sessions: InterviewSessionStatus[]
  summary: SessionSummary
}
```

### `InterviewSessionsPanel` — `ui/src/pages/Discovery.tsx`

Inline component (no new file). Renders inside the Interviews tab when `settings.interview_method === 'agent'`.

Uses react-query: `useQuery(['interview-sessions', slug], () => fetch(...).then(r => r.json()))`.

**Summary row** — four count badges:
- Pending → gray
- Active → amber
- Completed → green
- Abandoned → slate

**Sessions table** — columns: Name | Node | Status | Interview URL | Started | Completed | Actions

Status badge colours:
- `pending` → gray
- `active` → amber
- `completed` → teal (brand colour)
- `abandoned` → slate/red

Per-row actions:
- **Copy** button (all rows) — copies `interview_url` to clipboard via `navigator.clipboard.writeText`; briefly shows "Copied!" feedback
- **Abandon** button — only shown for `pending` or `active` rows; calls `PATCH /api/interviews/{token}/status` with `{status: "abandoned"}`; on success, calls `queryClient.invalidateQueries(['interview-sessions', slug])` to refetch

Empty state: if `sessions.length === 0`, show: *"No interview sessions found for the latest pipeline run."*

Loading state: skeleton row or spinner while react-query is fetching.

---

## Section 3 — Files affected

| File | Change |
|---|---|
| `api/database.py` | Add `fetch_interview_sessions_for_run` async helper |
| `api/routers/interviews.py` | Add `GET /api/interviews/sessions/{slug}` |
| `ui/src/types.ts` | Add `SessionSummary`, `InterviewSessionStatus`, `InterviewSessionsResponse` |
| `ui/src/pages/Discovery.tsx` | Add `InterviewSessionsPanel` inline component; render when `interview_method === 'agent'` |
| `tests/test_interviews_router.py` | 2 new tests: sessions endpoint with no runs (empty response), sessions endpoint with data |

---

## Task breakdown (3 tasks)

**Task 1 — Backend:** `fetch_interview_sessions_for_run` DB helper + `GET /api/interviews/sessions/{slug}` endpoint + 2 tests

**Task 2 — Frontend:** TypeScript types + `InterviewSessionsPanel` component + Discovery.tsx wiring

**Task 3 — Final verification:** Full test suite + smoke check
