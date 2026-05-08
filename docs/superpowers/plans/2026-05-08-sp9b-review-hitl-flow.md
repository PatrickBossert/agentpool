# SP9b — Review / HITL Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give HITL gates a proper UI — a dedicated `/reviews` page where the user can see pending crew checkpoints (with prompt text) and respond to unblock the crew.

**Architecture:** Add `GET /projects/{slug}/reviews` endpoint returning pending `human_reviews` rows (joined through `crew_runs` for project scope). The frontend polls this at 5 s via a shared TanStack Query cache key used in three places: the Reviews page, the top-nav badge, and a Dashboard inline panel.

**Tech Stack:** FastAPI + aiosqlite (backend), React + TanStack Query v5 + React Router v6 + Tailwind (frontend), pytest + httpx AsyncClient (tests).

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `api/database.py` | Modify | Add `fetch_pending_reviews` helper |
| `api/services/project_service.py` | Modify | Add `get_pending_reviews` service function |
| `api/routers/reviews.py` | Modify | Add `GET /{slug}/reviews` endpoint |
| `tests/test_reviews_api.py` | Create | 3 tests for the new endpoint |
| `ui/src/types.ts` | Modify | Add `HumanReview` interface |
| `ui/src/api/endpoints.ts` | Modify | Add `listReviews` and `resolveReview` methods |
| `ui/src/pages/Reviews.tsx` | Create | Dedicated reviews page |
| `ui/src/components/AppLayout.tsx` | Modify | Reviews nav item with amber badge |
| `ui/src/pages/Dashboard.tsx` | Modify | Pending reviews inline panel |
| `ui/src/router.tsx` | Modify | Add `/:slug/reviews` route |

---

## Task 1: Backend — DB helper, service, endpoint, and tests

**Files:**
- Modify: `api/database.py` (add after `update_review` at line ~279)
- Modify: `api/services/project_service.py` (add import + function)
- Modify: `api/routers/reviews.py` (add import + endpoint)
- Create: `tests/test_reviews_api.py`

### Context

`human_reviews` has no direct `project_id` column. Pending HITL rows always have `crew_run_id` set (legacy output-review rows have `crew_run_id IS NULL`). So scoping to a project requires a JOIN through `crew_runs`.

The existing `PATCH /{slug}/reviews/{review_id}` endpoint already resolves reviews — no changes needed there. We only add the `GET` listing endpoint.

- - -

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reviews_api.py`:

```python
import pytest
from pathlib import Path
from api.config import get_settings
from api.database import get_connection, fetch_project, insert_crew_run

SLUG = "rev-test"
PROJECT = {"client_slug": SLUG, "llm_mode": "standard", "sector": "rail"}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _insert_pending_review(prompt: str, decision: str = "pending") -> None:
    """Insert a crew_run then a human_review row for testing."""
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="TestCrew", status="running"
        )
        await conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (run_id, decision, prompt),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_list_reviews_returns_pending(client):
    await client.post("/projects", json=PROJECT)
    await _insert_pending_review("Please review the value chain diagram.")
    resp = await client.get(f"/projects/{SLUG}/reviews")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["prompt"] == "Please review the value chain diagram."
    assert data[0]["decision"] == "pending"
    assert "crew_run_id" in data[0]
    assert "id" in data[0]


@pytest.mark.asyncio
async def test_list_reviews_excludes_resolved(client):
    await client.post("/projects", json=PROJECT)
    await _insert_pending_review("Check architecture.", decision="approved")
    resp = await client.get(f"/projects/{SLUG}/reviews")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_reviews_unknown_project_404(client):
    resp = await client.get("/projects/no-such-project/reviews")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reviews_api.py -v
```

Expected: 3 failures — `404 Not Found` or `AttributeError` because the endpoint doesn't exist yet.

- [ ] **Step 3: Add `fetch_pending_reviews` to `api/database.py`**

Add after `update_review` (after line 279):

```python
async def fetch_pending_reviews(
    conn: aiosqlite.Connection, project_id: int
) -> list[dict]:
    """Return pending HITL human_reviews rows for a project, newest first.

    Joins through crew_runs because human_reviews has no direct project_id.
    Rows with crew_run_id IS NULL (legacy output reviews) are excluded by the JOIN.
    """
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

- [ ] **Step 4: Add `get_pending_reviews` to `api/services/project_service.py`**

Add `fetch_pending_reviews` to the existing import block at lines 8–18:

```python
from api.database import (
    get_connection,
    get_db_path,
    insert_project,
    fetch_project,
    fetch_crew_runs,
    fetch_latest_orchestration_run,
    fetch_agent_outputs,
    list_projects,
    update_project_config,
    fetch_pending_reviews,
)
```

Add the service function after `get_financial_summary` (at the end of the file):

```python
async def get_pending_reviews(slug: str) -> list[dict] | None:
    """Return pending HITL reviews for a project. Returns None if project not found."""
    if not get_db_path(slug).exists():
        return None
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_pending_reviews(conn, project["id"])
```

- [ ] **Step 5: Add `GET /{slug}/reviews` to `api/routers/reviews.py`**

Add import at the top of the existing import from `api.database`:

```python
from api.database import get_connection, get_db_path, fetch_project, insert_review, update_review
from api.services.project_service import get_pending_reviews
```

Add the new endpoint after `resolve_hitl_review`:

```python
@router.get("/{slug}/reviews")
async def list_pending_reviews(slug: str):
    result = await get_pending_reviews(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return result
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_reviews_api.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
pytest tests/ -v --ignore=tests/integration -x -q 2>&1 | tail -20
```

Expected: all tests passing (same count as before this task).

- [ ] **Step 8: Commit**

```bash
git add api/database.py api/services/project_service.py api/routers/reviews.py tests/test_reviews_api.py
git commit -m "feat(sp9b): add GET /projects/{slug}/reviews endpoint for pending HITL gates"
```

---

## Task 2: Frontend — types and API layer

**Files:**
- Modify: `ui/src/types.ts` (add `HumanReview` after the `Review` interface at line ~74)
- Modify: `ui/src/api/endpoints.ts` (add two methods before the closing `}` at line ~80)

- - -

- [ ] **Step 1: Add `HumanReview` to `ui/src/types.ts`**

Add after the existing `Review` interface (after line 79):

```typescript
export interface HumanReview {
  id: number
  prompt: string
  crew_run_id: number
  decision: string
  reviewed_at: string
}
```

- [ ] **Step 2: Add API methods to `ui/src/api/endpoints.ts`**

First, add `HumanReview` to the existing import line at the top of the file. The current import is:

```typescript
import type { AgentOutput, FinancialSummary, OutputContent, Project, ProjectSettings, RoadmapData } from '../types'
```

Change it to:

```typescript
import type { AgentOutput, FinancialSummary, HumanReview, OutputContent, Project, ProjectSettings, RoadmapData } from '../types'
```

Then add two methods before the closing `}` of `projectsApi` (after `financialSummary` at line ~79):

```typescript
  listReviews: (slug: string): Promise<HumanReview[]> =>
    apiClient.get<HumanReview[]>(`/projects/${slug}/reviews`).then((r) => r.data),

  resolveReview: (slug: string, reviewId: number, decision: string, notes: string): Promise<void> =>
    apiClient
      .patch(`/projects/${slug}/reviews/${reviewId}`, { decision, notes })
      .then(() => undefined),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/endpoints.ts
git commit -m "feat(sp9b): add HumanReview type and listReviews/resolveReview API methods"
```

---

## Task 3: Frontend — Reviews page, nav badge, Dashboard panel, route

**Files:**
- Create: `ui/src/pages/Reviews.tsx`
- Modify: `ui/src/components/AppLayout.tsx` (add reviews query + nav badge)
- Modify: `ui/src/pages/Dashboard.tsx` (add pending reviews panel)
- Modify: `ui/src/router.tsx` (add route)

### Context

`AppLayout.tsx` renders a horizontal top nav from a `navItems` array. Each item is `{ to, label, end? }`. We'll extend the type to include an optional `badge?: number` and conditionally render it in the map. The badge style is amber to distinguish it from other UI signals.

`Dashboard.tsx` already imports `useQuery` from TanStack Query. The `['reviews', slug]` query key is shared — TanStack Query deduplicates concurrent fetches, so all three consumers (Reviews page, AppLayout, Dashboard) share one in-flight request.

- - -

- [ ] **Step 1: Create `ui/src/pages/Reviews.tsx`**

```tsx
// ui/src/pages/Reviews.tsx
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
        <p className="text-sm text-slate-200 leading-relaxed bg-[#0f172a] rounded-md px-3 py-2.5 border border-slate-800 whitespace-pre-wrap">
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

- [ ] **Step 2: Update `ui/src/components/AppLayout.tsx`**

Add the reviews query inside `AppLayout` (after the `projects` query at line ~16):

```typescript
const { data: reviews = [] } = useQuery({
  queryKey: ['reviews', slug],
  queryFn: () => projectsApi.listReviews(slug!),
  enabled: !!slug,
  refetchInterval: 5000,
})
const pendingReviewCount = reviews.length
```

Replace the `navItems` array (lines 27–35) to add Reviews between Business Plan and Documents, and add an optional `badge` field:

```typescript
type NavItem = { to: string; label: string; end?: boolean; badge?: number }

const navItems: NavItem[] = slug
  ? [
      { to: `/${slug}`, label: 'Dashboard', end: true },
      { to: `/${slug}/value-chain`, label: 'Value Chain' },
      { to: `/${slug}/roadmap`, label: 'Roadmap' },
      { to: `/${slug}/business-plan`, label: 'Business Plan' },
      { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
      { to: `/${slug}/documents`, label: 'Documents' },
    ]
  : [{ to: '/', label: 'Dashboard', end: true }]
```

Replace the `NavLink` inside `navItems.map()` (lines 43–58) to render the badge:

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
    {item.badge !== undefined && (
      <span className="bg-amber-500 text-slate-900 text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
        {item.badge}
      </span>
    )}
  </NavLink>
))}
```

- [ ] **Step 3: Update `ui/src/pages/Dashboard.tsx`**

Add the reviews query after the existing `outputs` query (around line 25). `useQuery` is already imported:

```typescript
const { data: reviews = [] } = useQuery({
  queryKey: ['reviews', slug],
  queryFn: () => projectsApi.listReviews(slug!),
  enabled: !!slug,
  refetchInterval: 5000,
})
const pendingReviewCount = reviews.length
```

Add `Link` to the existing `react-router-dom` import (line 2):

```typescript
import { Link, useNavigate, useParams } from 'react-router-dom'
```

Find the section that renders the "Review Queue" heading in Dashboard. Add the pending reviews panel **above** it (the pending panel goes first since HITL gates are more urgent than static output reviews):

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

- [ ] **Step 4: Add route to `ui/src/router.tsx`**

Add the import after the `BusinessPlan` import (line 13):

```typescript
import Reviews from './pages/Reviews'
```

Add the route inside `children` after `':slug/business-plan'` (line 38):

```typescript
{ path: ':slug/business-plan', element: <BusinessPlan /> },
{ path: ':slug/reviews', element: <Reviews /> },
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Reviews.tsx ui/src/components/AppLayout.tsx ui/src/pages/Dashboard.tsx ui/src/router.tsx
git commit -m "feat(sp9b): Reviews page, nav badge, Dashboard panel, and route"
```
