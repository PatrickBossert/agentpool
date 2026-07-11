# Dashboard Redesign + Agent Chat — Design Spec

**Date:** 2026-07-11  
**Sprint:** SP17c (proposed)

---

## Goal

Replace the dark neural-network OrgChart on the Dashboard with a clean white agent grid where every agent has an illustrated avatar, a live status indicator, and a chat button. Add a slide-in chat drawer backed by Claude with per-agent personas and live project data.

## Architecture

Three layers of change:

1. **Theme** — Flip Tailwind config design tokens from dark to light. AppLayout and Dashboard get targeted class fixes. Other pages pick up the updated tokens without further edits.
2. **AgentGrid component** — Replaces `OrgChart.tsx`. Renders agent cards grouped by crew; derives status from the same WebSocket log logic as OrgChart.
3. **AgentChatDrawer component + backend endpoint** — Right-side chat drawer wired to `POST /api/projects/{slug}/agent-chat`, which builds a persona-aware system prompt, fetches live DB context, and streams through Claude Haiku.

---

## 1. Theme Changes

### 1a. Tailwind config (`ui/tailwind.config.js`)

Update the custom token values under `extend.colors`:

| Token | Old value | New value |
|---|---|---|
| `surface` | `#0f172a` | `#f9fafb` |
| `surface-raised` | `#1e293b` | `#ffffff` |
| `surface-card` | `#1e293b` | `#ffffff` |
| `primary` (text) | `#f1f5f9` | `#111827` |
| `secondary` (text) | `#94a3b8` | `#374151` |
| `muted` (text) | `#64748b` | `#6b7280` |
| `brand` / `brand-light` | unchanged | unchanged |

These are referenced as `bg-surface`, `text-primary`, `text-muted`, etc. throughout the codebase. Flipping the values here propagates the light theme to every page that uses semantic tokens.

### 1b. AppLayout (`ui/src/components/AppLayout.tsx`)

The nav bar uses raw `slate-*` classes that won't update from the token change. Replace:
- `border-slate-800` → `border-gray-200`
- `text-slate-400` (nav links) → `text-gray-500`
- `text-slate-200` (hover) → `text-gray-800`
- Project selector text colors: `text-slate-300` → `text-gray-700`, `text-slate-500` → `text-gray-400`

Nav active state stays teal (`text-brand border-brand`). Inactive links: `text-gray-500 border-transparent hover:text-gray-800`.

### 1c. Dashboard (`ui/src/pages/Dashboard.tsx`)

The Dashboard page itself uses raw slate classes for the project header section:
- `text-slate-100` → `text-gray-900`
- `bg-surface-card border border-slate-700` → `bg-white border border-gray-200`
- `text-slate-300` → `text-gray-600`
- `text-slate-400` → `text-gray-400`
- `text-brand` link stays unchanged

---

## 2. AgentGrid Component

**File:** `ui/src/components/AgentGrid.tsx`

Replaces `OrgChart.tsx` entirely on the Dashboard. `OrgChart.tsx` is not deleted — it stays in the codebase but is no longer imported by Dashboard.

### Layout

Crews rendered top-to-bottom. Within each crew, agents rendered in a responsive CSS grid (min 160px per card, max 4 columns).

```
CREW NAME  ● status
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  [avatar]│  │  [avatar]│  │  [avatar]│  │  [avatar]│
│  Agent   │  │  Agent   │  │  Agent   │  │  Agent   │
│  Name    │  │  Name    │  │  Name    │  │  Name    │
│  ● idle  │  │● running │  │● done    │  │  ● idle  │
│  [Chat ↗]│  │  [Chat ↗]│  │  [Chat ↗]│  │  [Chat ↗]│
└──────────┘  └──────────┘  └──────────┘  └──────────┘
```

### Agent Card

Each card is a white rounded-xl shadow-sm panel, ~160px wide. Contents (top to bottom):
- Circular avatar (56×56px) — see §2a
- Agent name (14px semibold, gray-900, centered, wraps to 2 lines max)
- Status dot + label (12px, e.g. `● idle` in gray-400, `● running` in teal-600 with pulse animation)
- "Chat" text button (12px, teal-600, only shown on hover of the card)

Clicking anywhere on the card (or the Chat button specifically) opens the AgentChatDrawer for that agent.

### 2a. Agent Avatars

Avatars are generated inline — no external images or services required.

Each agent's avatar is a circular `<div>` with:
- A two-stop CSS gradient background seeded from the agent name (index 0–19 mapped to 20 predefined gradient pairs in teal/indigo/violet/amber/rose/emerald palette)
- A centered emoji character representing the agent's domain role

Predefined role emojis (one per agent):

| Agent | Emoji |
|---|---|
| Value Chain Mapper | 🗺️ |
| Requirements Capture | 📋 |
| Requirements Analyst | 🔍 |
| Value Lever Analyst | ⚖️ |
| Interview Script Designer | ✍️ |
| Interview Coordinator | 📅 |
| Stakeholder Interviewer | 🎙️ |
| Synthesis Analyst | 🧩 |
| Value Proposition Generator | 💡 |
| Portfolio Manager | 📊 |
| Enterprise Architect | 🏛️ |
| Initiative Identifier | 🎯 |
| Roadmap Generator | 🛣️ |
| Business Plan Generator | 📈 |

### 2b. Status Inference

Reuse the `inferAgentStatuses` and `getCrewStatus` logic already in `OrgChart.tsx`. Export these as standalone helpers from a new `ui/src/components/agentStatus.ts` utility file so AgentGrid can import them without pulling in the full OrgChart.

Crew-level status badge is shown left of the crew name:
- `idle` → gray dot, no label change
- `queued` → gray dot
- `running` → animated teal pulse dot
- `completed` → solid green dot
- `failed` → red dot

### 2c. Run Pipeline Button

Moves from inside OrgChart to the Dashboard project header row (already has the "Export Report" button). Placed as a primary teal button: `▶ Run Pipeline`. Disabled + spinner while `isPipelineActive`. Same mutation as current.

### 2d. Props (AgentGrid)

```typescript
interface AgentGridProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  onAgentChat: (agentName: string) => void
}
```

The `onAgentChat` callback is wired up in Dashboard to open the drawer with the selected agent.

---

## 3. AgentChatDrawer Component

**File:** `ui/src/components/AgentChatDrawer.tsx`

A fixed right-side panel, 420px wide, overlaid on top of page content with a semi-transparent backdrop. Animated slide-in from right using a CSS transition on a `translate-x` class.

### Props

```typescript
interface AgentChatDrawerProps {
  slug: string
  agentName: string | null   // null = closed
  onClose: () => void
}
```

When `agentName` is null, the drawer is closed (no DOM rendered). Opening a different agent resets message history.

### Internal State

```typescript
type Message = { role: 'user' | 'agent'; content: string }

const [messages, setMessages] = useState<Message[]>([])
const [input, setInput] = useState('')
const [loading, setLoading] = useState(false)
```

Message history is ephemeral (React state only, no DB persistence). Closing the drawer clears history.

### Layout

```
┌─────────────────────────────┐
│ [avatar 40px]  Agent Name ✕ │  ← fixed header
├─────────────────────────────┤
│                             │
│  [message bubbles]          │  ← scrollable, flex-col
│                             │
├─────────────────────────────┤
│ [textarea]          [Send]  │  ← fixed footer
└─────────────────────────────┘
```

- User messages: right-aligned, teal-600 background, white text
- Agent messages: left-aligned, gray-100 background, gray-900 text
- Loading: animated "..." dots shown as a fake agent message while waiting
- Enter key submits (Shift+Enter for newline)

### API call

On send, calls `agentChatApi.send(slug, agentName, input, history)` which POSTs to `/api/projects/{slug}/agent-chat`.

**File:** `ui/src/api/agentChat.ts`

```typescript
export const agentChatApi = {
  send: async (
    slug: string,
    agentName: string,
    message: string,
    history: { role: string; content: string }[]
  ): Promise<string> => {
    const res = await fetch(`/api/projects/${slug}/agent-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_name: agentName, message, history }),
    })
    if (!res.ok) throw new Error('Chat request failed')
    const data = await res.json()
    return data.response
  }
}
```

---

## 4. Backend: Agent Chat Endpoint

**File:** `api/routers/agent_chat.py`

Registered in `api/main.py` with prefix `/api/projects`.

### Route

```
POST /api/projects/{slug}/agent-chat
Auth: Bearer token required (get_current_user)
Body: { agent_name: str, message: str, history: list[dict] }
Response: { response: str }
```

### Agent Persona Registry

Defined in `api/services/agent_chat_service.py` as a module-level dict:

```python
AGENT_PERSONAS: dict[str, dict] = {
    "Value Chain Mapper": {
        "role": "You map the organisation's value chain, identifying key processes and interdependencies.",
        "context_type": "outputs",
    },
    "Requirements Capture": {
        "role": "You gather and document stakeholder requirements from discovery interviews.",
        "context_type": "stakeholders",
    },
    "Requirements Analyst": {
        "role": "You analyse captured requirements for consistency, gaps, and priority.",
        "context_type": "outputs",
    },
    "Value Lever Analyst": {
        "role": "You identify the highest-value levers for organisational improvement.",
        "context_type": "outputs",
    },
    "Interview Script Designer": {
        "role": "You design tailored interview scripts for each stakeholder and value chain node.",
        "context_type": "stakeholders",
    },
    "Interview Coordinator": {
        "role": "You coordinate the scheduling and tracking of stakeholder interviews.",
        "context_type": "interview_sessions",
    },
    "Stakeholder Interviewer": {
        "role": "You conduct voice interviews with stakeholders and synthesise their responses.",
        "context_type": "interview_sessions",
    },
    "Synthesis Analyst": {
        "role": "You synthesise interview transcripts into structured findings.",
        "context_type": "interview_sessions",
    },
    "Value Proposition Generator": {
        "role": "You generate value propositions from discovery findings.",
        "context_type": "outputs",
    },
    "Portfolio Manager": {
        "role": "You score and rank initiatives across the six capitals framework.",
        "context_type": "outputs",
    },
    "Enterprise Architect": {
        "role": "You design the enterprise architecture required to deliver the roadmap initiatives.",
        "context_type": "outputs",
    },
    "Initiative Identifier": {
        "role": "You identify and define the key initiatives from the architecture blueprint.",
        "context_type": "outputs",
    },
    "Roadmap Generator": {
        "role": "You sequence initiatives across value streams and time horizons into a delivery roadmap.",
        "context_type": "outputs",
    },
    "Business Plan Generator": {
        "role": "You produce the financial model and business plan narrative.",
        "context_type": "outputs",
    },
}
```

### Context Types

Context is fetched before calling Claude:

- **`stakeholders`** — fetches all stakeholders for the project (name, job_title, organisation, interview_status, interview_invited_at, interview_completed_at)
- **`interview_sessions`** — fetches all stakeholders + interview_sessions (session_token, status, started_at, completed_at, node_label) joined to stakeholder name
- **`outputs`** — fetches the 5 most recent crew run results for the project (crew_name, status, result_json snippet up to 2000 chars)
- **`none`** — no DB context

### System Prompt Template

```
You are {agent_name}, an AI agent within the FutureMomentum platform.

Your role: {role}

Project: {slug}
Today: {date}

{context_block}

Answer the user's question helpfully and concisely. Use bullet points for lists.
If you don't have the data to answer, say so — don't make up details.
```

`context_block` is a formatted text block, e.g.:

```
STAKEHOLDER & INTERVIEW STATUS
-------------------------------
Alice Brown (CFO, Acme Ltd) — interview: completed (2026-07-09)
Bob Smith (Head of Ops, Acme Ltd) — interview: pending (invited 2026-07-08, not yet completed)
Carol Jones (CTO, Acme Ltd) — interview: not started
```

### Claude call

Uses `claude-haiku-4-5-20251001`, `max_tokens=1024`. Conversation history is passed as the `messages` array (system prompt separate).

### Error handling

- Unknown `agent_name` → 404
- DB fetch failure → 500 with generic message
- Anthropic error → 500

---

## 5. File Summary

| Action | File |
|---|---|
| Modify | `ui/tailwind.config.js` |
| Modify | `ui/src/components/AppLayout.tsx` |
| Modify | `ui/src/pages/Dashboard.tsx` |
| Create | `ui/src/components/AgentGrid.tsx` |
| Create | `ui/src/components/AgentChatDrawer.tsx` |
| Create | `ui/src/components/agentStatus.ts` |
| Create | `ui/src/api/agentChat.ts` |
| Create | `api/routers/agent_chat.py` |
| Create | `api/services/agent_chat_service.py` |
| Modify | `api/main.py` (register router) |

---

## 6. Out of Scope

- Persisting chat history to the database
- Streaming responses (single-shot only)
- Redesigning pages other than Dashboard + AppLayout shell
- Changing the OrgChart used in RunDetail or other pages
- Agent authentication / per-user chat isolation beyond existing JWT

---

## 7. Testing

- Unit: `tests/test_agent_chat.py` — mock Anthropic client, test each context_type fetches correct data, test 404 on unknown agent, test system prompt construction
- UI: TypeScript build must be clean (`npx tsc --noEmit`)
- Manual: open chat drawer for a stakeholder-context agent and ask "who hasn't been interviewed" — verify response reflects live DB state
