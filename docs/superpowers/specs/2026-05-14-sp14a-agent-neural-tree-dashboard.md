# SP14a — Neural Agent Tree Dashboard

## Overview

Replaces the existing horizontal crew-card OrgChart with a high-tech vertical neural spine layout. Every agent in every crew is always visible with live status indicators. The PAM orchestrator becomes a full-width top bar containing an EKG heartbeat animation and the Run Pipeline button. A log strip sits below the spine. The overall effect is a system that feels alive — present and pulsing even when no pipeline is running.

---

## Section 1 — Layout

### Dashboard.tsx

Replace the two-column grid with a single full-width OrgChart panel. Remove `InfoCard` from the layout beside the OrgChart. The OrgChart now owns the Run Pipeline button and status display.

**Before:**
```tsx
<section className="grid grid-cols-[1fr_320px] gap-4 items-start">
  <div className="bg-surface-card border border-slate-700 rounded-xl p-4">
    <OrgChart ... />
  </div>
  <InfoCard ... />
</section>
```

**After:**
```tsx
<section>
  <OrgChart
    crewRuns={crewRuns}
    isPipelineActive={isPipelineActive}
    logs={logs}
    interviewBadge={interviewBadge}
    onCrewClick={handleCrewClick}
    onRun={() => runMutation.mutate()}
    isRunPending={runMutation.isPending}
    lastRun={lastRun}
    orch={orch}
  />
</section>
```

`InfoCard` is no longer rendered. The component file is left in place but unused (out of scope to delete).

### OrgChart overall structure

```
┌─────────────────────────────────────────────────────────┐
│  PAM BAR: ◈ PAM · ORCHESTRATOR  [EKG] [status] [▶ RUN] │
├────────────┬──────────────┬────────────────────────────-┤
│  LEFT COL  │   SPINE      │  RIGHT COL                  │
│  Discovery │   │ particle │  Value Design               │
│            │   │ flow     │                             │
│  Architect │   │          │  Delivery                   │
│            │   ↓          │                             │
│  Biz Plan  │              │                             │
├─────────────────────────────────────────────────────────┤
│  LOG STRIP: last 3 log lines                            │
└─────────────────────────────────────────────────────────┘
```

---

## Section 2 — PAM Bar

A horizontal bar spanning the full width of the card. Always rendered.

**Contents (left to right):**
1. Animated `◈` icon (teal, `animate-pamPulse`)
2. Label: `PAM · ORCHESTRATOR` in uppercase monospace, teal
3. EKG waveform: 7 `div` bars of fixed heights `[3, 9, 5, 13, 4, 7, 3]px`, each with `animate-ekg` staggered by `animation-delay: calc(var(--i) * 100ms)`. Always animating.
4. Status text (right of EKG, left of button):
   - Pipeline running → `● DISCOVERY RUNNING` (blinking, teal) — uses active crew name
   - Last run completed → `✓ COMPLETED` (green)
   - Last run failed → `✗ FAILED` (red)
   - Never run → empty
5. Run Pipeline button (right-aligned):
   - Idle: `▶ Run Pipeline` — teal background
   - Pending: `Running…` — disabled, muted
   - Active: button hidden (pipeline already running)

---

## Section 3 — Neural Spine

### Spine element

A `2px` wide vertical element with a `linear-gradient(to bottom, #19d4e8, #19d4e820)` background. Height is `auto` (stretches to match the taller of the two columns).

### Particle flow

Three absolutely-positioned circular orbs (`8×8px`, `border-radius: 50%`, `background: #19d4e8`, `box-shadow: 0 0 10px #19d4e8, 0 0 20px #19d4e840`) animate from `top: 0` to `top: 100%` with `opacity: 0→1→1→0`.

- Base duration: `3s linear infinite`
- Stagger: `animation-delay: 0s`, `1s`, `2s`
- Only rendered when `isPipelineActive` is true OR when `crewRuns.length > 0` (has ever run)
- When truly idle (never run): spine renders but no particles

### Column layout

```
Left column:   Discovery · Architecture · Business Plan
Right column:  Value Design (offset top: align with Architecture) · Delivery
```

Right column uses `padding-top` to create the interleave offset — approximately the height of one crew card.

---

## Section 4 — Crew Nodes

### Structure

```tsx
<div className={`crew-node ${status}`}>
  {/* Header */}
  <div className="crew-head">
    <Icon />
    <span className="name">DISCOVERY</span>
    <StatusBadge status={status} isActive={isActive} />
  </div>
  {/* Agent list — always rendered */}
  <div className="agent-list">
    {agents.map((agent, idx) => (
      <AgentRow key={agent} name={agent} status={agentStatus[idx]} />
    ))}
  </div>
</div>
```

### Crew card states

| State | Border | Background | Glow |
|---|---|---|---|
| `idle` (never run) | `border-slate-800` | `bg-surface` | none |
| `queued` (pipeline active, not yet reached) | `border-slate-700` | `bg-surface-card` | none |
| `running` | `border-brand` | `bg-brand/5` | `animate-crewGlow` + scanline sweep |
| `completed` | `border-brand-green/50` | `bg-brand-green/5` | none |
| `failed` | `border-red-500/50` | `bg-red-500/5` | none |

Active crew additionally renders:
- Top-edge scanline: `::before` pseudo — `2px` tall gradient stripe sweeping `left→right` every `2s`
- Breathing glow: `box-shadow` alternates between `0 0 16px #19d4e840` and `0 0 28px #19d4e870` on a `3s` sine

### Correct CREW_AGENTS map

```typescript
export const CREW_AGENTS: Record<CrewName, string[]> = {
  discovery: [
    'Value Chain Mapper',
    'Requirements Capture',
    'Requirements Analyst',
    'Value Lever Analyst',
  ],
  discovery_interviews: [
    'Interview Script Designer',
    'Interview Coordinator',
    'Stakeholder Interviewer',
    'Synthesis Analyst',
  ],
  value_design: ['Value Proposition Generator', 'Portfolio Manager'],
  architecture: ['Enterprise Architect', 'Initiative Identifier'],
  delivery: ['Roadmap Generator'],
  business_plan: ['Business Plan Generator'],
}
```

`discovery_interviews` is shown as a secondary card beneath the Discovery card (indented, connected by a short branch line) only when a `crew_run` with `crew_name === 'discovery_interviews'` exists in `crewRuns`. Otherwise hidden.

### Agent row states

Each agent row: `2px × 14px` vertical bar + name in monospace `text-[10px]`.

| Agent state | Bar | Name colour |
|---|---|---|
| `running` | teal, `animate-agentPulse` (opacity 1→0.4 at 0.8s) | `text-slate-100 font-semibold` |
| `completed` | solid `brand-green` | `text-slate-500` |
| `queued` | `bg-slate-800` | `text-slate-700` |
| `idle` (pipeline inactive) | `bg-slate-900` | `text-slate-800` |

Agent status inference logic (unchanged from current `inferAgentStatuses`): scan logs for agent name mentions, mark all before last-mentioned as `completed`, last-mentioned as `running`, rest as `queued`.

When crew is not active (`isActive === false`):
- If crew status is `completed` → all agents show `completed`
- Otherwise → all agents show `idle`

---

## Section 5 — Log Strip

A dark strip below the spine (`bg-slate-950`, `rounded-b-xl`). Shows the last 3 entries from the `logs` WebSocket array. Each line is `text-[11px] font-mono`.

- Most recent line: `text-brand/70`
- Older lines: `text-slate-700`

Hidden when `logs.length === 0`.

---

## Section 6 — Tailwind keyframes

Add to `tailwind.config.js` under `theme.extend`:

```js
keyframes: {
  ekg: {
    '0%, 100%': { opacity: '0.25' },
    '50%': { opacity: '1' },
  },
  crewGlow: {
    '0%, 100%': { boxShadow: '0 0 16px #19d4e840, 0 0 40px #19d4e815' },
    '50%': { boxShadow: '0 0 28px #19d4e870, 0 0 60px #19d4e830' },
  },
  agentPulse: {
    '0%, 100%': { opacity: '1' },
    '50%': { opacity: '0.35' },
  },
  particleFlow: {
    '0%':   { top: '-4px', opacity: '0' },
    '10%':  { opacity: '1' },
    '90%':  { opacity: '1' },
    '100%': { top: 'calc(100% - 4px)', opacity: '0' },
  },
  scanline: {
    '0%':   { transform: 'translateX(-100%)' },
    '100%': { transform: 'translateX(100%)' },
  },
  pamPulse: {
    '0%, 100%': { opacity: '1' },
    '50%':      { opacity: '0.6' },
  },
},
animation: {
  ekg:          'ekg 1.6s ease-in-out infinite',
  crewGlow:     'crewGlow 3s ease-in-out infinite',
  agentPulse:   'agentPulse 0.8s ease-in-out infinite',
  particleFlow: 'particleFlow 3s linear infinite',
  scanline:     'scanline 2s linear infinite',
  pamPulse:     'pamPulse 2s ease-in-out infinite',
},
```

---

## Section 7 — Files affected

| File | Change |
|---|---|
| `ui/src/components/OrgChart.tsx` | Full rewrite — neural spine layout, correct agents, always-on list, new props (`onRun`, `isRunPending`, `lastRun`, `orch`) |
| `ui/src/pages/Dashboard.tsx` | Remove `InfoCard` from main layout, pass new props to OrgChart |
| `ui/tailwind.config.js` | Add 6 keyframes + animation tokens |

---

## Task breakdown (2 tasks)

**Task 1 — Tailwind tokens + OrgChart rewrite:** Add keyframes/animations to `tailwind.config.js`. Rewrite `OrgChart.tsx` with PAM bar, neural spine, crew nodes (correct agents, always-on list, all states), log strip. No backend changes.

**Task 2 — Dashboard.tsx wiring:** Remove two-column grid, remove InfoCard from layout, pass `onRun`/`isRunPending`/`lastRun`/`orch` to OrgChart. Smoke-test in browser.
