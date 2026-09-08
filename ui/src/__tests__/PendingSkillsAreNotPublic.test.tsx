// ui/src/__tests__/PendingSkillsAreNotPublic.test.tsx
//
// The rendered half of the same finding `tests/test_pending_skills_are_not_public.py` asserts
// over HTTP. The server now refuses `status=pending` to a non-sysadmin, and these are the two
// places in the product that were asking for it on every login's behalf:
//
// - `Team.tsx`, route `:slug/team` with no `AdminRoute`, rendering `skill.name` for every
//   pending row - and an unnamed proposal's name is `_derive_skill_name`'s first five words of
//   the rule, so the chip alone carried the disclosure.
// - `AgentDetailPanel`'s Skills tab, whose non-admin branch printed `{s.description}` verbatim
//   under "In development", so a reviewer on engagement B read, word for word, the rule an
//   agent wrote about engagement A.
//
// **Asserted as "the request is not made", not as "the text is not on screen."** A component
// that fetched the queue and then filtered it would satisfy a text assertion while still
// putting the material in the browser, where it is in the response body, the query cache, and
// the network tab. The absence of the request is the property; the absence of the text is its
// consequence and is asserted second.
//
// Both controls are here deliberately. A sysadmin must still get the queue in both places, or
// a fix that simply stopped asking would pass every assertion above it.
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import Team from '../pages/Team'
import AgentDetailPanel from '../components/AgentDetailPanel'
import { skillsApi } from '../api/skills'
import type { AgentSkill } from '../api/skills'

const auth = vi.hoisted(() => ({ role: 'reviewer' }))

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    token: 'test-token',
    user: { sub: 'someone', role: auth.role, exp: 9999999999 },
    login: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: {
    getAll: vi.fn().mockResolvedValue({ agents: {} }),
    get: vi.fn(),
    put: vi.fn(),
  },
}))

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getOutputContent: vi.fn().mockResolvedValue({ content: '{}', output_type: 'json' }),
    review: vi.fn(),
    revertOutput: vi.fn(),
    getInterviewScripts: vi.fn().mockResolvedValue({}),
    getSettings: vi.fn().mockResolvedValue({}),
    updateSettings: vi.fn(),
    documents: vi.fn().mockResolvedValue([]),
    getMyPermissions: vi.fn().mockResolvedValue({
      can_review: false, can_approve: false, can_grant_roles: false,
      can_issue_invite_links: false, can_change_platform_tier_settings: false,
      can_administer_project: false, platform_tier_settings: [],
      writable_knowledge_tiers: [],
    }),
  },
  valueChainApi: { get: vi.fn().mockResolvedValue({ model: null }), save: vi.fn(), migrate: vi.fn() },
  interviewsApi: { listSessions: vi.fn().mockResolvedValue({ sessions: [] }) },
}))

vi.mock('../api/agentChat', () => ({
  agentChatApi: {
    getHistory: vi.fn().mockResolvedValue([]),
    clearHistory: vi.fn().mockResolvedValue(undefined),
    send: vi.fn(),
    uploadFile: vi.fn(),
  },
}))

vi.mock('../api/skills', () => ({
  skillsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    extract: vi.fn(),
    extractMany: vi.fn(),
  },
}))

// The rule as the review drove it, and a name of the shape `_derive_skill_name` produces -
// words taken off the front of the rule, so it carries the client. Both are asserted absent,
// because hiding one and not the other hides nothing.
//
// **Not the exact output of that function, and it must not be read as such.** Nothing links
// these two languages, so a comment claiming the correspondence is a claim no test can hold
// (the previous one said "the first five words" of a four-word constant, and was wrong in a
// way nothing could catch). What makes the assertions here mean something is instead local:
// this constant is also the fixture's `name` field, and every absence assertion is paired
// with a presence control using the same constant, so "it did not render" cannot pass because
// the selector never matched anything. The Python-side pin lives where it can be checked -
// `tests/test_pending_skills_are_not_public.py::test_the_derived_name_really_does_carry_the_rule`.
const RULE = "When interviewing Iberdrola's SAP migration staff, never name the Q3 outage."
const PROPOSAL_NAME = "When interviewing Iberdrola's SAP"

const PROPOSAL: AgentSkill = {
  id: 91,
  agents: ['Interaction Designer'],
  name: PROPOSAL_NAME,
  description: RULE,
  source: 'revision',
  source_project: 'confidential-client-engagement',
  source_ref: 'SC-014',
  proposed_by_agent: 'interaction_designer',
  occurrences: 2,
  status: 'pending',
  flag_reason: null,
  flag_suggestion: null,
  created_at: '2026-09-01T09:00:00',
  reviewed_at: null,
  reviewed_by: null,
}

/** Answers whatever status is asked for - so a component that asks, receives. */
function serveSkills() {
  vi.mocked(skillsApi.list).mockReset()
  vi.mocked(skillsApi.list).mockImplementation(async (params?: { status?: string }) =>
    params?.status === 'pending' ? [PROPOSAL] : [],
  )
}

function askedForPending(): boolean {
  return vi.mocked(skillsApi.list).mock.calls.some(
    ([params]) => (params as { status?: string } | undefined)?.status === 'pending',
  )
}

/**
 * A client, optionally already holding the queue in its cache.
 *
 * `['skills', 'pending']` is one key shared by `AdminSkills`, `Team` and the agent panel, so a
 * warm entry is not contrived: anything that fetched it puts it there for everything else
 * mounted under the same client. Seeding it is how the *render* guard gets an assertion of its
 * own - with only a disabled query, `pending` is empty whatever the render does, and removing
 * the render guard changes nothing a test could see.
 */
function makeClient(seeded = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (seeded) qc.setQueryData(['skills', 'pending'], [PROPOSAL])
  return qc
}

function renderTeam(seeded = false) {
  return render(
    <QueryClientProvider client={makeClient(seeded)}>
      <MemoryRouter><Team /></MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderSkillsTab(seeded = false) {
  const qc = makeClient(seeded)
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AgentDetailPanel
          slug="t"
          crewKey="assessment_design"
          crewRun={undefined}
          outputs={[]}
          logs={[]}
          isPipelineActive={false}
          initialTab="skills"
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  auth.role = 'reviewer'
  serveSkills()
})

describe('the Team roll', () => {
  it('does not ask for the review queue on behalf of a reviewer', async () => {
    renderTeam()

    // The approved library is fetched by other surfaces; this page asks for nothing pending.
    await waitFor(() => expect(screen.getByText('Agent Team')).toBeInTheDocument())
    expect(askedForPending()).toBe(false)
    expect(screen.queryByText(PROPOSAL_NAME)).not.toBeInTheDocument()
    expect(screen.queryByText(/Skills in development/)).not.toBeInTheDocument()
  })

  it('draws nothing from a queue already in the cache', async () => {
    // The render guard on its own. The request is not the only way the rows can be present -
    // one query key serves this page, the admin queue and the agent panel.
    renderTeam(true)

    await waitFor(() => expect(screen.getByText('Agent Team')).toBeInTheDocument())
    expect(screen.queryByText(PROPOSAL_NAME)).not.toBeInTheDocument()
    expect(screen.queryByText(/Skills in development/)).not.toBeInTheDocument()
  })

  it('still shows a sysadmin the queue it is theirs to act on', async () => {
    auth.role = 'sysadmin'
    renderTeam()

    await waitFor(() => expect(askedForPending()).toBe(true))
    expect(await screen.findByText(PROPOSAL_NAME)).toBeInTheDocument()
  })
})

describe("the agent panel's Skills tab", () => {
  it('does not ask for the review queue on behalf of a reviewer', async () => {
    renderSkillsTab()

    await waitFor(() => expect(vi.mocked(skillsApi.list)).toHaveBeenCalled())
    expect(askedForPending()).toBe(false)
  })

  it('renders neither the rule nor the name it was derived from, even from a warm cache', async () => {
    // Seeded, so this is the render guard rather than a restatement of the test above. The
    // old non-admin branch printed `s.description` under "In development"; the branch is gone
    // rather than gated, and `isAdmin &&` guards what is left.
    renderSkillsTab(true)

    await waitFor(() => expect(vi.mocked(skillsApi.list)).toHaveBeenCalled())
    expect(screen.queryByText(RULE)).not.toBeInTheDocument()
    expect(screen.queryByText(PROPOSAL_NAME)).not.toBeInTheDocument()
    expect(screen.queryByText(/In development/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Awaiting review/)).not.toBeInTheDocument()
    expect(screen.queryByText(/pending/)).not.toBeInTheDocument()
  })

  it('still shows a sysadmin the proposal awaiting their review', async () => {
    auth.role = 'sysadmin'
    renderSkillsTab()

    await waitFor(() => expect(askedForPending()).toBe(true))
    expect(await screen.findByText(/Awaiting review/)).toBeInTheDocument()
    expect(screen.getByText(PROPOSAL_NAME)).toBeInTheDocument()
  })
})
