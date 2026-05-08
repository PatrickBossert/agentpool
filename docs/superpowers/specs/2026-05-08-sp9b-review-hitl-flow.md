# SP9b — Review / HITL Flow
## Design Specification
**Date:** 2026-05-08
**Status:** Approved for implementation planning
**Branch base:** `master`
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Give the HITL gate mechanism a proper UI. When a crew hits `HumanInputTool._run()` the crew thread blocks, polling SQLite every 5 s until `human_reviews.decision != 'pending'`. Currently there is no way to discover that a gate is open or respond to it from the React UI — the only path is the Chainlit app or an n8n webhook.

**In scope:**
- `GET /projects/{slug}/reviews` — list pending `human_reviews` rows for a project
- `fetch_pending_reviews(conn, project_id)` DB helper
- `get_pending_reviews(slug)` service function
- `HumanReview` TypeScript interface in `ui/src/types.ts`
- `projectsApi.listReviews(slug)` and `projectsApi.resolveReview(slug, id, decision, notes)` in `ui/src/api/endpoints.ts`
- `ui/src/pages/Reviews.tsx` — dedicated page at `/:slug/reviews`
- `ui/src/components/AppLayout.tsx` — "Reviews" nav item with amber count badge
- `ui/src/pages/Dashboard.tsx` — inline panel showing pending count + "Go to Reviews →" link
- `ui/src/router.tsx` — `/:slug/reviews` route
- Backend tests in `tests/test_reviews_api.py`

**Out of scope:**
- Review history (resolved gates) — pending only
- Fixing `agent_outputs.review_status` update bug (separate concern)
- WebSocket push for real-time gate notification
- Multi-reviewer support or reviewer identity

---

## 2. Background: Two Review Concepts

The codebase has two distinct review mechanisms. SP9b touches only the second:

| Concept | Table | Trigger | Blocks crew? | Resolve via |
|---------|-------|---------|-------------|-------------|
| Output review | `agent_outputs.review_status` + `human_reviews.output_id` | Manual (Dashboard ReviewQueue) | No | `POST /projects/{slug}/review` |
| **HITL gate** | `human_reviews.crew_run_id` | `HumanInputTool._run()` | **Yes** — crew polls | `PATCH /projects/{slug}/reviews/{id}` |

HITL gates are inserted by `insert_hitl_review()` in `agents/tools/_db.py` with `decision='pending'` and no `output_id`. They have a `prompt` field containing the crew's question verbatim.

The crew returns `notes if notes else decision` — so the notes field is the actual text passed back to the crew as its input.

---

## 3. Architecture

```
GET /projects/{slug}/reviews
  └─ get_pending_reviews(slug)
       ├─ guard: DB file exists + project exists → 404
       └─ fetch_pending_reviews(conn, project_id)
            SELECT id, prompt, crew_run_id, decision, reviewed_at
            FROM human_reviews
            WHERE project_id_via_crew_run=? AND decision='pending'
            ORDER BY reviewed_at DESC

Frontend (Reviews.tsx):
  useQuery(['reviews', slug], refetchInterval: 5000)
    → HumanReview[]
    → one ReviewCard per item (prompt, notes textarea, Approve/Request Changes)
    → on submit: PATCH /projects/{slug}/reviews/{id}
               → invalidate ['reviews', slug]

Frontend (Dashboard.tsx):
  useQuery(['reviews', slug], refetchInterval: 5000)   ← shared cache key
    → pendingCount = reviews.length
    → show panel if pendingCount > 0

Frontend (AppLayout.tsx):
  useQuery(['reviews', slug], refetchInterval: 5000)   ← shared cache key
    → badge = pendingCount > 0 ? count : hidden
```

---

## 4. Backend Changes

### 4.1 `api/database.py` — new DB helper

`fetch_pending_reviews` needs to join through `crew_runs` to get the project scope since `human_reviews` has no direct `project_id` column:

```python
async def fetch_pending_reviews(
    conn: aiosqlite.Connection, project_id: int
) -> list[dict]:
    """Return pending human_reviews rows for a project, newest first."""
    async with conn.execute(
        """
        SELECT hr.id, hr.prompt, hr.crew_run_id, hr.decision, hr.reviewed_at
        FROM human_reviews hr
        JOIN crew_runs cr ON cr.id = hr.crew_run_id
        WHERE cr.project_id = ? AND hr.decision = 'pending'
        ORDER BY hr.reviewed_at DESC
        """,
        (project_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
```

Note: `human_reviews` rows created without a `crew_run_id` (legacy output reviews) have `crew_run_id IS NULL` — the `JOIN` naturally excludes them.

### 4.2 `api/services/project_service.py` — new service function

```python
async def get_pending_reviews(slug: str) -> list[dict] | None:
    """Return pending HITL reviews for a project. None = project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_pending_reviews(conn, project["id"])
```

Add `fetch_pending_reviews` to the import from `api.database`.

### 4.3 `api/routers/reviews.py` — new GET endpoint

Add after the existing endpoints:

```python
from api.services.project_service import get_pending_reviews

@router.get("/{slug}/reviews")
async def list_pending_reviews(slug: str):
    result = await get_pending_reviews(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

Returns `[]` when the project exists but has no pending reviews.

---

## 5. Frontend Changes

### 5.1 `ui/src/types.ts`

```typescript
export interface HumanReview {
  id: number
  prompt: string
  crew_run_id: number
  decision: string
  reviewed_at: string
}
```

### 5.2 `ui/src/api/endpoints.ts`

Add to `projectsApi`:

```typescript
listReviews: (slug: string): Promise<HumanReview[]> =>
  apiClient.get<HumanReview[]>(`/projects/${slug}/reviews`).then((r) => r.data),

resolveReview: (slug: string, reviewId: number, decision: string, notes: string): Promise<void> =>
  apiClient.patch(`/projects/${slug}/reviews/${reviewId}`, { decision, notes }).then(() => undefined),
```

Import `HumanReview` in the import block.

### 5.3 `ui/src/pages/Reviews.tsx` (new file)

```tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import type { HumanReview } from '../types'

function ReviewCard({ review, slug }: { review: HumanReview; slug: string }) {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const qc = useQueryClient()

  async function resolve(decision: string) {
    setSubmitting(true)
    try {
      await projectsApi.resolveReview(slug, review.id, decision, notes)
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-surface rounded-xl border-l-4 border-amber-500 overflow-hidden">
      <div className="px-4 pt-3 pb-2">
        <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-amber-500/10 text-amber-400 uppercase">
          Pending
        </span>
        <p className="text-xs text-slate-500 mt-1.5">Run #{review.crew_run_id}</p>
      </div>
      <div className="px-4 pb-3">
        <p className="text-sm text-slate-200 leading-relaxed bg-[#0f172a] rounded-md px-3 py-2.5 border border-slate-800">
          {review.prompt}
        </p>
      </div>
      <div className="px-4 pb-4 flex flex-col gap-2.5">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes for the crew (optional) — your text is returned verbatim as the crew's input"
          className="w-full bg-[#0f172a] border border-slate-700 rounded-md text-slate-300 text-sm px-3 py-2 resize-y min-h-[72px] placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
        />
        <div className="flex gap-2 justify-end">
          <button
            disabled={submitting}
            onClick={() => resolve('changes_requested')}
            className="text-xs px-4 py-1.5 rounded-md bg-red-900/60 text-red-300 hover:bg-red-900 disabled:opacity-50 transition-colors"
          >
            Request Changes
          </button>
          <button
            disabled={submitting}
            onClick={() => resolve('approved')}
            className="text-xs px-4 py-1.5 rounded-md bg-emerald-900/60 text-emerald-300 hover:bg-emerald-900 disabled:opacity-50 transition-colors"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Reviews() {
  const { slug } = useParams<{ slug: string }>()

  const { data: reviews = [], isLoading } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Reviews</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
      {!isLoading && reviews.length === 0 && (
        <p className="text-sm text-slate-500">
          No pending reviews — the crew is running autonomously.
        </p>
      )}
      <div className="space-y-4">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} slug={slug!} />
        ))}
      </div>
    </div>
  )
}
```

### 5.4 `ui/src/components/AppLayout.tsx`

The nav is a **horizontal top nav** — each item is a `NavLink` rendered via `navItems.map()`. Add the reviews query and a Reviews entry between Business Plan and Documents.

`useQuery` and `projectsApi` are already imported. Add inside the component body (after the existing `useQuery` call for outputs if present, otherwise alongside the slug guard):

```typescript
const { data: reviews = [] } = useQuery({
  queryKey: ['reviews', slug],
  queryFn: () => projectsApi.listReviews(slug!),
  enabled: !!slug,
  refetchInterval: 5000,
})
const pendingReviewCount = reviews.length
```

Update `navItems` to include Reviews between Business Plan and Documents:

```typescript
const navItems = slug
  ? [
      { to: `/${slug}`, label: 'Dashboard', end: true },
      { to: `/${slug}/value-chain`, label: 'Value Chain' },
      { to: `/${slug}/roadmap`, label: 'Roadmap' },
      { to: `/${slug}/business-plan`, label: 'Business Plan' },
      { to: `/${slug}/reviews`, label: 'Reviews' },
      { to: `/${slug}/documents`, label: 'Documents' },
    ]
  : [{ to: '/', label: 'Dashboard', end: true }]
```

Replace the `navItems.map()` render to show a badge on the Reviews item:

```tsx
{navItems.map((item) => (
  <NavLink
    key={item.to}
    to={item.to}
    end={item.end}
    className={({ isActive }) =>
      `text-sm pb-0.5 border-b-2 transition-colors flex items-center gap-1.5 ${
        isActive
          ? 'text-sky-300 border-sky-300'
          : 'text-slate-400 border-transparent hover:text-slate-200'
      }`
    }
  >
    {item.label}
    {item.label === 'Reviews' && pendingReviewCount > 0 && (
      <span className="bg-amber-500 text-slate-900 text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
        {pendingReviewCount}
      </span>
    )}
  </NavLink>
))}
```

### 5.5 `ui/src/pages/Dashboard.tsx`

Add import and pending panel. The `['reviews', slug]` query is already running in AppLayout so this shares the cache — no extra network request:

```typescript
import { useQuery, useQueryClient } from '@tanstack/react-query'
// (already imported in Dashboard)

const { data: reviews = [] } = useQuery({
  queryKey: ['reviews', slug],
  queryFn: () => projectsApi.listReviews(slug!),
  enabled: !!slug,
  refetchInterval: 5000,
})
const pendingReviewCount = reviews.length
```

Add a panel above the existing Review Queue section:

```tsx
{pendingReviewCount > 0 && (
  <section>
    <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
      Pending Reviews
    </h3>
    <div className="bg-surface rounded-lg border-l-4 border-amber-500 px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="rounded px-2 py-0.5 text-xs font-bold tracking-wide bg-amber-500/10 text-amber-400 uppercase">
          {pendingReviewCount} pending
        </span>
        <p className="text-sm text-slate-400">
          {pendingReviewCount === 1 ? 'A crew is' : 'Crews are'} waiting for your input
        </p>
      </div>
      <Link
        to={`/${slug}/reviews`}
        className="text-xs text-sky-400 hover:text-sky-300 border border-sky-900/40 rounded px-2.5 py-1.5 transition-colors"
      >
        Go to Reviews →
      </Link>
    </div>
  </section>
)}
```

Add `Link` import from `react-router-dom` if not already present.

### 5.6 `ui/src/router.tsx`

```typescript
import Reviews from './pages/Reviews'

// inside children after business-plan:
{ path: ':slug/reviews', element: <Reviews /> },
```

---

## 6. Testing

### `tests/test_reviews_api.py` (new)

Follow the pattern from `test_business_plan_api.py`. Three tests:

1. **`test_list_reviews_returns_pending`** — create project, insert a `crew_runs` row, insert a `human_reviews` row with `decision='pending'`, `GET /projects/{slug}/reviews` → 200 with one item containing the prompt
2. **`test_list_reviews_excludes_resolved`** — same setup but `decision='approved'` → 200 with empty list
3. **`test_list_reviews_unknown_project_404`** — unknown slug → 404

```bash
pytest tests/test_reviews_api.py -v
```

---

## 7. Notes

- The `['reviews', slug]` query key is shared across `Reviews.tsx`, `AppLayout.tsx`, and `Dashboard.tsx` — TanStack Query deduplicates them into a single in-flight request.
- `refetchInterval: 5000` matches the HumanInputTool polling cadence (5 s), so the UI reflects a newly-opened gate within one polling cycle.
- `fetch_pending_reviews` uses an inner JOIN on `crew_runs` — legacy `human_reviews` rows with `crew_run_id IS NULL` are naturally excluded.
- The crew receives `notes if notes else decision` — so submitting with no notes sends the string `"approved"` or `"changes_requested"` to the agent.
- `resolveReview` calls the already-existing `PATCH /projects/{slug}/reviews/{review_id}` endpoint (no new backend code for resolution).
- The Dashboard panel uses `Link` from `react-router-dom` (not `<a>`), consistent with existing navigation.
