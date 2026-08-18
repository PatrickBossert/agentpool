// ui/src/__tests__/JordanAssignment.test.tsx
//
// What Jordan's Setup tab actually sends.
//
// The recurring failure on this project is a test that verifies a property one layer from
// where it holds, and this surface has the exact shape that invites one: a control can be
// found, a chip can be counted, and none of that says anything about the request. The page
// this replaces is the proof - it rendered a tree, saved without error, and wrote
// `stakeholder_node_assignments` keyed on 'L2:Some Label', a table no agent has ever read.
// Every assertion below is therefore made against the request the transport is handed, via
// axios's own adapter extension point (the pattern in client.test.ts), so the whole chain
// runs: the component, endpoints.ts, both interceptors, and the URL and body that go out.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, it, expect } from 'vitest'

import JordanSetupTab, { buildTree } from '../components/tabs/JordanSetupTab'
import { AGENT_SETUP_SECTION } from '../components/tabs/CrewSetupSections'
import { apiClient } from '../api/client'
import type { Stakeholder, ValueChainRegistryActivity } from '../types'

// The live registry's own shape, trimmed: `0` and its role nodes carry no parent_id at all,
// while `1.1` and below do. Both arms of buildTree's parent resolution are exercised by it.
const ACTIVITIES: ValueChainRegistryActivity[] = [
  { id: '0',     label: 'Group Services UK',        level: 'L0', active: true },
  { id: '0.A',   label: 'Audit',                    level: 'L0', active: true },
  { id: '0.S',   label: 'Corporate Services Frontline', level: 'L0', active: true },
  { id: '1',     label: 'Property',                 level: 'L1', active: true },
  { id: '1.F',   label: 'Property Frontline',       level: 'L1', active: true, parent_id: '1' },
  { id: '1.1',   label: 'Strategic Planning',       level: 'L2', active: true, parent_id: '1' },
  { id: '1.1.1', label: 'Asset Hierarchy',          level: 'L3', active: true, parent_id: '1.1' },
  { id: '1.1.2', label: 'Regulatory Compliance',    level: 'L3', active: false, parent_id: '1.1' },
]

function person(id: number, name: string, job_title = 'Analyst'): Stakeholder {
  return { id, name, job_title, entity: 'GS UK', organisation: 'GS UK', level: 'L3' } as Stakeholder
}

const PEOPLE = [person(7, 'Rhona Baird'), person(8, 'Callum Innes'), person(9, 'Fiona Muir')]

interface Sent {
  url: string
  method: string
  body: unknown
}

/**
 * Stands in for the network. GETs are served from the fixtures; every request is recorded,
 * so an assertion can read the POST body exactly as it left the browser.
 */
function serveApi(options: { assignments?: { stakeholder_id: number; node_id: string }[]; runs?: unknown[] } = {}) {
  const sent: Sent[] = []
  apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
    const url = new URL(apiClient.getUri(config), 'http://localhost')
    const method = (config.method ?? 'get').toUpperCase()
    sent.push({
      url: url.pathname,
      method,
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })

    let data: unknown = {}
    if (url.pathname === '/projects/acme/assignment' && method === 'GET') {
      data = { assignments: options.assignments ?? [], stakeholders: PEOPLE }
    } else if (url.pathname === '/projects/acme/value-chain-registry') {
      data = { schema_version: 1, activities: ACTIVITIES }
    } else if (url.pathname === '/projects/acme/runs') {
      data = options.runs ?? []
    } else if (url.pathname === '/projects/acme/assignment' && method === 'POST') {
      data = { saved: Array.isArray(config.data) ? config.data.length : 0 }
    }
    return Promise.resolve({ data, status: 200, statusText: 'OK', headers: {}, config } as AxiosResponse)
  }
  return sent
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JordanSetupTab slug="acme" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Reveal a node at any depth: a live filter expands the tree onto its matches. */
async function findNode(user: ReturnType<typeof userEvent.setup>, nodeId: string) {
  const filter = await screen.findByLabelText('Filter activities')
  await user.clear(filter)
  await user.type(filter, nodeId)
  return screen.findByLabelText(`Assign a stakeholder to ${nodeId}`)
}

async function assign(user: ReturnType<typeof userEvent.setup>, nodeId: string, name: string) {
  await user.click(await findNode(user, nodeId))
  await user.click(await screen.findByLabelText(`Assign ${name}`))
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /save assignments/i }))
}

function posted(sent: Sent[]): Sent[] {
  return sent.filter((s) => s.method === 'POST')
}

const realAdapter = apiClient.defaults.adapter

afterEach(() => {
  apiClient.defaults.adapter = realAdapter
})

describe('what Jordan\'s Setup tab sends', () => {
  it('cites the value chain node id, not a level-and-label key', async () => {
    const user = userEvent.setup()
    const sent = serveApi()
    renderTab()

    await assign(user, '1.1.1', 'Rhona Baird')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].url).toBe('/projects/acme/assignment')
    expect(posted(sent)[0].body).toEqual([{ stakeholder_id: 7, node_id: '1.1.1' }])
    // The retired table's key shape. 'L3:Asset Hierarchy' would satisfy any assertion made
    // about what the screen shows, and no agent could resolve it.
    expect(JSON.stringify(posted(sent)[0].body)).not.toContain('L3:')
  })

  it('sends the organisation and its role nodes by their real ids', async () => {
    // The page this replaces invented a virtual 'L0:Governance' node that appears in no
    // registry, and `0.A` (audit) and `0.S` (corporate services frontline) - the people
    // CLAUDE.md calls the hardest to place - could not be assigned at all.
    const user = userEvent.setup()
    const sent = serveApi()
    renderTab()

    await assign(user, '0.A', 'Rhona Baird')
    await assign(user, '0', 'Callum Innes')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].body).toEqual([
      { stakeholder_id: 7, node_id: '0.A' },
      { stakeholder_id: 8, node_id: '0' },
    ])
    expect(JSON.stringify(posted(sent)[0].body)).not.toContain('Governance')
  })

  it('sends every person on an activity that several people speak for', async () => {
    // Many-to-many is the point, not a duplicate to be collapsed: frontline and corporate
    // services activities carry several people by design.
    const user = userEvent.setup()
    const sent = serveApi()
    renderTab()

    await assign(user, '1.F', 'Rhona Baird')
    await assign(user, '1.F', 'Callum Innes')
    await assign(user, '1.F', 'Fiona Muir')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].body).toEqual([
      { stakeholder_id: 7, node_id: '1.F' },
      { stakeholder_id: 8, node_id: '1.F' },
      { stakeholder_id: 9, node_id: '1.F' },
    ])
  })

  it('sends one person against every activity they speak for', async () => {
    const user = userEvent.setup()
    const sent = serveApi()
    renderTab()

    await assign(user, '1.1', 'Rhona Baird')
    await assign(user, '1.1.1', 'Rhona Baird')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].body).toEqual([
      { stakeholder_id: 7, node_id: '1.1' },
      { stakeholder_id: 7, node_id: '1.1.1' },
    ])
  })

  it('sends the mapping without the assignment already stored being lost', async () => {
    const user = userEvent.setup()
    const sent = serveApi({ assignments: [{ stakeholder_id: 9, node_id: '0.S' }] })
    renderTab()

    await assign(user, '1.1.1', 'Rhona Baird')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    // A whole-mapping replace: anything left out of this body is deleted server-side, so
    // the row that was already there has to be in it.
    expect(posted(sent)[0].body).toEqual([
      { stakeholder_id: 9, node_id: '0.S' },
      { stakeholder_id: 7, node_id: '1.1.1' },
    ])
  })

  it('sends an empty list when the last assignment is removed', async () => {
    // Not a malformed request: unassigning the last person is an edit, and a surface that
    // cannot express it leaves a wrong mapping impossible to clear.
    const user = userEvent.setup()
    const sent = serveApi({ assignments: [{ stakeholder_id: 7, node_id: '1.1.1' }] })
    renderTab()

    await user.click(await screen.findByLabelText('Remove Rhona Baird from 1.1.1'))
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].body).toEqual([])
  })

  it('saves with no orchestration run in existence, which is the defect it fixes', async () => {
    // The mapping used to be an event inside a run: the page was routed only off a run
    // parked in `awaiting_assignment`, so it could not be made before the first run and the
    // crew that needs it ran without it.
    const user = userEvent.setup()
    const sent = serveApi({ runs: [] })
    renderTab()

    expect(screen.queryByRole('button', { name: /begin discovery interviews/i })).toBeNull()
    await assign(user, '1.1.1', 'Rhona Baird')
    await save(user)

    await waitFor(() => expect(posted(sent)).toHaveLength(1))
    expect(posted(sent)[0].body).toEqual([{ stakeholder_id: 7, node_id: '1.1.1' }])
  })

  it('will not advance a waiting run while the mapping on screen is unsaved', async () => {
    // Advancing sends the crew the *stored* rows. An edit still sitting in the browser
    // would be silently absent from the interview programme it was made for.
    const user = userEvent.setup()
    serveApi({ runs: [{ id: 12, status: 'awaiting_assignment', crew_runs: [] }] })
    renderTab()

    const advance = await screen.findByRole('button', { name: /begin discovery interviews/i })
    expect(advance).toBeEnabled()

    await assign(user, '1.1.1', 'Rhona Baird')
    expect(screen.getByRole('button', { name: /begin discovery interviews/i })).toBeDisabled()
  })

  it('does not send anything until Save is pressed', async () => {
    // The old page auto-saved on a 400ms debounce, so a mis-drop was written before it
    // could be undone. Nothing here reaches the server until it is asked to.
    const user = userEvent.setup()
    const sent = serveApi()
    renderTab()

    await assign(user, '1.1.1', 'Rhona Baird')

    expect(posted(sent)).toHaveLength(0)
  })
})

describe('the activity tree the assignments are made against', () => {
  it('nests the organisation-level role nodes under the organisation', () => {
    // `0.A` and `0.S` declare no parent_id in the real registry. Left as roots they sit
    // loose at the top of an 86-node list, which is where audit and corporate services
    // frontline would be looked for last.
    const roots = buildTree(ACTIVITIES)
    expect(roots.map((n) => n.id)).toEqual(['0', '1'])
    expect(roots[0].children.map((n) => n.id)).toEqual(['0.A', '0.S'])
  })

  it('keeps the registry\'s own parent when it declares one', () => {
    const property = buildTree(ACTIVITIES).find((n) => n.id === '1')!
    expect(property.children.map((n) => n.id)).toEqual(['1.1', '1.F'])
  })

  it('leaves a retired activity out', () => {
    const flat = JSON.stringify(buildTree(ACTIVITIES))
    expect(flat).toContain('1.1.1')
    expect(flat).not.toContain('1.1.2')
  })
})

describe('where the assignment surface lives', () => {
  it('is registered against Jordan, the agent whose crew needs it', () => {
    expect(AGENT_SETUP_SECTION['Stakeholder Manager']).toBe(JordanSetupTab)
  })
})
