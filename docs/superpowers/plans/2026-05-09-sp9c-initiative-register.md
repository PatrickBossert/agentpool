# SP9c Initiative Register Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Register" tab to the Roadmap page that shows all initiatives as a category-grouped (or value-stream-grouped) table, reusing the existing `roadmap_data` query and `groupBy` toggle.

**Architecture:** Pure frontend change — one file (`ui/src/pages/Roadmap.tsx`). Extends the `Tab` union, adds a third tab button, adds a `RegisterTable` component function (same file, same pattern as `GanttTable`), and widens the `roadmapData` query `enabled` condition to cover the new tab. No backend, no new types, no new API methods.

**Tech Stack:** React 18, TypeScript, TanStack Query v5, Tailwind CSS

---

## Context for the implementer

`ui/src/pages/Roadmap.tsx` is 249 lines. It currently has:
- `type Tab = 'visual' | 'gantt'` (line 10)
- `type GroupBy = 'category' | 'value_stream'` (line 11)
- `CATEGORY_COLOURS` map (lines 13–17): `enabling → #3b82f6`, `operating_model → #f59e0b`, `business_change → #22c55e`
- `roadmapData` query with `enabled: !!slug && tab === 'gantt'` (line 51)
- Tab bar rendering `['visual', 'gantt']` (line 59)
- Gantt tab block (lines 121–173) with a Group By toggle and `<GanttTable>`
- `GanttTable` function (lines 178–249) — study this as the pattern for `RegisterTable`

The `Fragment` import is already present (line 4). The `Initiative` and `RoadmapData` types are already imported from `../types` (line 8).

---

### Task 1: Add Register tab to Roadmap.tsx

**Files:**
- Modify: `ui/src/pages/Roadmap.tsx`

This is a pure-frontend change. There are no Python tests. Verification is manual (steps below).

- [ ] **Step 1: Extend the Tab type and tab bar**

In `ui/src/pages/Roadmap.tsx`, make these two edits:

**Edit 1** — line 10, extend Tab union:
```typescript
// Before:
type Tab = 'visual' | 'gantt'

// After:
type Tab = 'visual' | 'gantt' | 'register'
```

**Edit 2** — line 59, add 'register' to the tab bar array:
```tsx
// Before:
{(['visual', 'gantt'] as Tab[]).map((t) => (

// After:
{(['visual', 'gantt', 'register'] as Tab[]).map((t) => (
```

- [ ] **Step 2: Widen the roadmapData query to cover the register tab**

Line 51 in `ui/src/pages/Roadmap.tsx`:
```typescript
// Before:
enabled: !!slug && tab === 'gantt',

// After:
enabled: !!slug && (tab === 'gantt' || tab === 'register'),
```

- [ ] **Step 3: Add the Register tab render block**

After the closing `)}` of the Gantt tab block (after line 173, which ends `{tab === 'gantt' && (`), add the following block. Insert it between the end of the Gantt block and the closing `</div>` of the page:

```tsx
      {tab === 'register' && (
        <div className="bg-surface-card rounded-xl overflow-hidden">
          {/* Controls row — same Group By toggle as Gantt */}
          <div className="flex items-center px-4 py-3 border-b border-slate-800">
            <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
            <div className="flex rounded-lg overflow-hidden border border-slate-700 ml-3">
              {(['category', 'value_stream'] as GroupBy[]).map((g) => (
                <button
                  key={g}
                  onClick={() => setGroupBy(g)}
                  className={`px-3 py-1 text-xs capitalize transition-colors ${
                    groupBy === g ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  {g === 'value_stream' ? 'Value Stream' : 'Category'}
                </button>
              ))}
            </div>
          </div>

          {/* Empty state */}
          {!roadmapData && (
            <p className="text-sm text-slate-500 p-4">
              Initiative register will appear here once initiatives are identified.
            </p>
          )}

          {/* Register table */}
          {roadmapData && <RegisterTable data={roadmapData} groupBy={groupBy} />}
        </div>
      )}
```

- [ ] **Step 4: Add the RegisterTable component function**

After the closing `}` of the `GanttTable` function (after line 249), add this new function at the end of the file:

```tsx
function RegisterTable({ data, groupBy }: { data: RoadmapData; groupBy: GroupBy }) {
  const groups =
    groupBy === 'category'
      ? [...new Set(data.initiatives.map((i) => i.category))]
      : data.value_streams

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900">
            <th className="px-4 py-2 text-left text-slate-500 font-medium min-w-[200px]">
              Initiative
            </th>
            {groupBy === 'value_stream' && (
              <th className="px-3 py-2 text-left text-slate-500 font-medium">Category</th>
            )}
            <th className="px-3 py-2 text-left text-slate-500 font-medium">Value Streams</th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">
              Period
            </th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[80px]">
              Complexity
            </th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i) => i.category === group)
                : data.initiatives.filter((i) => i.value_streams.includes(group))
            const colour =
              groupBy === 'category' ? (CATEGORY_COLOURS[group] ?? '#9ca3af') : '#6366f1'
            const colSpan = groupBy === 'value_stream' ? 5 : 4

            return (
              <Fragment key={group}>
                <tr className="bg-slate-900/60 border-t-2 border-slate-800">
                  <td
                    colSpan={colSpan}
                    className="px-4 py-1.5 text-xs font-semibold uppercase tracking-widest"
                    style={{ color: colour }}
                  >
                    ● {group.replace(/_/g, ' ')}
                  </td>
                </tr>
                {members.map((initiative: Initiative) => (
                  <tr
                    key={`${group}-${initiative.title}`}
                    className="border-t border-slate-800"
                  >
                    <td className="px-4 py-2 text-slate-300">{initiative.title}</td>
                    {groupBy === 'value_stream' && (
                      <td className="px-3 py-2">
                        <span
                          className="rounded px-2 py-0.5 text-xs font-medium"
                          style={{
                            background: `${CATEGORY_COLOURS[initiative.category] ?? '#9ca3af'}20`,
                            color: CATEGORY_COLOURS[initiative.category] ?? '#9ca3af',
                          }}
                        >
                          {initiative.category.replace(/_/g, ' ')}
                        </span>
                      </td>
                    )}
                    <td className="px-3 py-2 text-slate-400">
                      {initiative.value_streams.join(', ')}
                    </td>
                    <td className="px-3 py-2 text-center text-slate-400">{initiative.period}</td>
                    <td className="px-3 py-2 text-center">
                      <span
                        className="rounded px-2 py-0.5 text-xs font-bold text-white"
                        style={{
                          background: CATEGORY_COLOURS[initiative.category] ?? '#9ca3af',
                        }}
                      >
                        {initiative.complexity_score}
                      </span>
                    </td>
                  </tr>
                ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 5: Type-check the frontend**

```bash
cd /Users/pboagents/Documents/agentpool1/ui
npm run type-check 2>&1 | head -40
```

Expected: no errors. If `npm run type-check` is not a script, use:
```bash
npx tsc --noEmit 2>&1 | head -40
```

- [ ] **Step 6: Manual verification**

Start the dev server if not already running:
```bash
cd /Users/pboagents/Documents/agentpool1/ui && npm run dev
```

Check these in the browser on a project that has roadmap data:

1. Navigate to `/:slug/roadmap` — tab bar shows **Visual | Gantt | Register**
2. Click **Register** — if no roadmap data, empty state reads "Initiative register will appear here once initiatives are identified."
3. With roadmap data: rows appear grouped by category, group headers coloured blue/amber/green (matching the Gantt)
4. Toggle **Group by → Value Stream** — rows regroup by value stream (indigo `#6366f1` headers); a Category badge column appears
5. Switch to **Gantt** tab — Group By selection is preserved
6. Switch back to **Register** — Group By still preserved

- [ ] **Step 7: Commit**

```bash
cd /Users/pboagents/Documents/agentpool1
git add ui/src/pages/Roadmap.tsx
git commit -m "feat: add Initiative Register tab to Roadmap page (SP9c)"
```
