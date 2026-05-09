# SP9c — Initiative Register
## Design Specification
**Date:** 2026-05-09
**Status:** Approved for implementation planning
**Branch base:** `master`
**Working directory:** `/Users/pboagents/Documents/agentpool1`

---

## 1. Scope

Add a "Register" tab to the existing Roadmap page (`/:slug/roadmap`) that shows all initiatives from `roadmap_data` as a grouped, readable table — a complement to the visual timeline and Gantt tabs.

**In scope:**
- `'register'` added to the `Tab` union type in `Roadmap.tsx`
- "Register" button in the existing tab bar (after Gantt)
- `RegisterTable` component (new function in `Roadmap.tsx`)
- Shared `groupBy` state and toggle between Gantt and Register tabs
- `roadmapData` query enabled on both `'gantt'` and `'register'` tabs

**Out of scope:**
- Any new backend endpoint (reuses `GET /projects/{slug}/roadmap-data`)
- New types (all types already in `ui/src/types.ts`)
- Sorting/filtering rows
- Clicking into individual initiatives

---

## 2. Architecture

```
Roadmap.tsx (existing)
  Tab: 'visual' | 'gantt' | 'register'   ← add 'register'
  GroupBy: 'category' | 'value_stream'   ← unchanged

  roadmapData query:
    enabled: !!slug && (tab === 'gantt' || tab === 'register')
    ← was: tab === 'gantt' only

  tab === 'register'
    → GroupByToggle row (same as Gantt)
    → <RegisterTable data={roadmapData} groupBy={groupBy} />

RegisterTable({ data, groupBy })
  groups = groupBy === 'category'
    ? [...new Set(data.initiatives.map(i => i.category))]
    : data.value_streams
  → colSpan group header rows (CATEGORY_COLOURS, same as GanttTable)
  → per initiative: title | value_streams (joined) | period | complexity pill
  → when groupBy === 'value_stream': add Category badge column
```

No new files, no new API methods, no backend changes.

---

## 3. Frontend Changes

### 3.1 `ui/src/pages/Roadmap.tsx`

**Tab type** — extend union:
```typescript
type Tab = 'visual' | 'gantt' | 'register'
```

**Tab bar** — add Register button after Gantt:
```tsx
{(['visual', 'gantt', 'register'] as Tab[]).map((t) => (
  <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
    className={`px-4 py-1.5 text-sm capitalize transition-colors ${
      tab === t ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
    }`}>
    {t}
  </button>
))}
```

**roadmapData query** — enable on both tabs:
```typescript
enabled: !!slug && (tab === 'gantt' || tab === 'register'),
```

**Register tab render** — add after the Gantt block:
```tsx
{tab === 'register' && (
  <div className="bg-surface-card rounded-xl overflow-hidden">
    {/* Controls row — identical to Gantt */}
    <div className="flex items-center px-4 py-3 border-b border-slate-800">
      <span className="text-xs text-slate-500 uppercase tracking-widest">Group by</span>
      <div className="flex rounded-lg overflow-hidden border border-slate-700 ml-3">
        {(['category', 'value_stream'] as GroupBy[]).map((g) => (
          <button key={g} onClick={() => setGroupBy(g)}
            className={`px-3 py-1 text-xs capitalize transition-colors ${
              groupBy === g ? 'bg-brand text-white' : 'text-slate-400 hover:bg-slate-800'
            }`}>
            {g === 'value_stream' ? 'Value Stream' : 'Category'}
          </button>
        ))}
      </div>
    </div>

    {!roadmapData && (
      <p className="text-sm text-slate-500 p-4">
        Initiative register will appear here once initiatives are identified.
      </p>
    )}
    {roadmapData && <RegisterTable data={roadmapData} groupBy={groupBy} />}
  </div>
)}
```

### 3.2 `RegisterTable` component (new function in same file)

```typescript
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
            <th className="px-4 py-2 text-left text-slate-500 font-medium">Initiative</th>
            {groupBy === 'value_stream' && (
              <th className="px-3 py-2 text-left text-slate-500 font-medium">Category</th>
            )}
            <th className="px-3 py-2 text-left text-slate-500 font-medium">Value Streams</th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[90px]">Period</th>
            <th className="px-3 py-2 text-center text-slate-500 font-medium min-w-[80px]">Complexity</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const members =
              groupBy === 'category'
                ? data.initiatives.filter((i) => i.category === group)
                : data.initiatives.filter((i) => i.value_streams.includes(group))
            const colour = groupBy === 'category'
              ? (CATEGORY_COLOURS[group] ?? '#9ca3af')
              : '#6366f1'

            return (
              <Fragment key={group}>
                <tr className="bg-slate-900/60 border-t-2 border-slate-800">
                  <td
                    colSpan={groupBy === 'value_stream' ? 5 : 4}
                    className="px-4 py-1.5 text-xs font-semibold uppercase tracking-widest"
                    style={{ color: colour }}
                  >
                    ● {group.replace(/_/g, ' ')}
                  </td>
                </tr>
                {members.map((initiative) => (
                  <tr key={`${group}-${initiative.title}`} className="border-t border-slate-800">
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
                        style={{ background: CATEGORY_COLOURS[initiative.category] ?? '#9ca3af' }}
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

**Note on `colSpan`:** When `groupBy === 'value_stream'` the table has 5 columns (title + category badge + value_streams + period + complexity). When `groupBy === 'category'` it has 4 columns (no category column). The group header `colSpan` must match.

**Note on `key`:** `initiative.title` alone is not safe as a key inside a grouped view (an initiative can appear in multiple value_stream groups). Use `${group}-${initiative.title}` to guarantee uniqueness.

---

## 4. Testing

This change is entirely in the React layer with no new backend logic. Verify manually:

1. Navigate to `/:slug/roadmap` — tab bar shows "visual | gantt | register"
2. Click "Register" — empty state shown if no roadmap_data
3. With roadmap data present: grouped rows appear, group header colours match Gantt
4. Toggle "Group by: Category | Value Stream" — rows regroup; switching to Gantt preserves the selection
5. Switch between tabs — `groupBy` state is preserved across Gantt ↔ Register tab switches

---

## 5. Notes

- `CATEGORY_COLOURS` is already defined at the top of `Roadmap.tsx` — `RegisterTable` reuses it directly (same file scope).
- The `roadmapDataOutput` variable (used for the Gantt download button) is only needed on the Gantt tab; it is not shown on the Register tab.
- `Fragment` is already imported in `Roadmap.tsx` — no new import needed.
- An initiative can appear in multiple value_stream groups (since `value_streams` is an array). This is intentional — it matches how the Gantt groups by value_stream.
- The complexity pill uses the initiative's `category` colour even when grouped by value_stream, keeping visual consistency with the Gantt.
