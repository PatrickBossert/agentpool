// ui/src/__tests__/DataArchitecturePage.test.tsx
//
// The page renders the declarations it is handed, and holds none of its own.
//
// The page it replaced was hand-typed, so the failure to guard against is not "a field is
// formatted oddly" but "the page shows something the system never said". Every assertion here
// therefore reads a value out of the payload and looks for it on the screen, and the last two
// go the other way: a fact absent from the payload must be absent from the page. The old copy
// named Anthropic forty-four times and Tavily seventeen; a page that still did would pass a
// test that only checked the payload's values were present.
//
// The payload's shape is what api/services/data_architecture_service.py returns, and
// tests/test_data_architecture_page.py is what holds that service to the declarations. The two
// halves meet at the type in ui/src/api/dataArchitecture.ts, which tsc checks.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DataArchitecture from '../pages/DataArchitecture'
import type { DataArchitecture as Model } from '../api/dataArchitecture'

const get = vi.fn()
vi.mock('../api/dataArchitecture', () => ({
  dataArchitectureApi: { get: (slug: string) => get(slug) },
}))
vi.mock('../api/endpoints', () => ({ projectsApi: { list: vi.fn().mockResolvedValue([]) } }))

// Deliberately not the real declarations. Every string here is invented, so anything the page
// displays that is not in this object came from the page itself.
const PAYLOAD: Model = {
  slug: 'northern-water',
  llm_mode: 'sensitive',
  inference: {
    reaches: 'a language model',
    sends: 'every prompt the agent builds',
    destination: 'the local model on this host',
    leaves_deployment: false,
    gated_by_mode: true,
  },
  tools: [
    {
      tool: 'InventedSearchTool',
      reaches: 'a web search service',
      sends: 'the search query the agent composed',
      destination: 'the Invented search API',
      leaves_deployment: true,
      gated_by_mode: false,
      held_by: ['Alex Chen'],
      held_by_ids: ['value_chain_mapper'],
    },
    {
      tool: 'InventedLocalTool',
      reaches: 'nothing outside this deployment',
      sends: 'nothing - it writes to this project only',
      destination: 'nothing outside this deployment',
      leaves_deployment: false,
      gated_by_mode: false,
      held_by: ['Alex Chen'],
      held_by_ids: ['value_chain_mapper'],
    },
  ],
  declared_not_held: [
    {
      tool: 'InventedUnheldTool',
      reaches: 'the automation webhook',
      sends: 'the prompt',
      destination: 'the invented webhook',
    },
  ],
  agents: [
    {
      agent_id: 'value_chain_mapper',
      display_name: 'Alex Chen',
      tier: 'deep',
      crews: ['Invented First', 'Invented Second', 'Invented Third'],
      crew_ids: ['invented_first', 'invented_second', 'invented_third'],
      tools: ['InventedSearchTool', 'InventedLocalTool'],
      writes: ['invented_artefact'],
      destinations: [{ label: 'the Invented search API', leaves_deployment: true }],
      sources: [
        {
          source: 'invented_sector_store',
          medium: 'a Chroma collection',
          via: 'ChromaQueryTool',
          note: 'how this sector usually works',
          shared_beyond_this_project: true,
        },
        {
          source: 'invented_project_artefact',
          medium: 'a JSON artefact in the project outputs directory',
          via: 'SQLiteStateTool',
          note: 'his own ledger',
          shared_beyond_this_project: false,
        },
        {
          source: 'invented_dispatch_table',
          medium: 'a table in a SQLite database',
          // Not a tool: what the dispatch path reads on the agent's behalf. There is no row for
          // it in the egress table, so it must not be rendered as a link to one.
          via: 'build_and_run_crew',
          note: 'handed to him without his asking',
          shared_beyond_this_project: false,
        },
      ],
    },
    // Two agents who hold the query tool without being told to read the shared store. They exist
    // so that reachable_by is genuinely wider than read_by, which is the distinction the sharing
    // panel turns on - and so that every id the payload references has a card to land on.
    // The orchestrator, who is in no crew. She is here for the same reason she is in the real
    // payload: the graph draws her at a centre and links to her card, and a centre with no card
    // is a link that lands nowhere.
    {
      agent_id: 'pam',
      display_name: 'Pamela Reid',
      tier: 'deep',
      crews: [],
      crew_ids: [],
      tools: [],
      writes: [],
      destinations: [],
      sources: [],
    },
    {
      agent_id: 'someone_else',
      display_name: 'Someone Else',
      tier: 'fast',
      crews: ['Invented Second'],
      crew_ids: ['invented_second'],
      tools: ['InventedLocalTool'],
      writes: [],
      destinations: [],
      sources: [],
    },
    {
      agent_id: 'a_third_person',
      display_name: 'A Third Person',
      tier: 'fast',
      crews: ['Invented Second'],
      crew_ids: ['invented_second'],
      tools: ['InventedLocalTool'],
      writes: [],
      destinations: [],
      sources: [],
    },
  ],
  // Three crews, because one cannot show an order, a ring, or an edge. The third waits on the
  // second and reads nothing it writes, which is the sequencing case; the first reaches the third
  // without the third waiting on it, which is the inherited case.
  crews: [
    {
      crew_id: 'invented_first',
      display_name: 'Invented First',
      purpose: 'Builds the invented thing from the invented inputs',
      note: 'An invented note',
      defect: 'An invented defect',
      cluster: 'invented_cluster',
      depends_on: [],
      depends_on_ids: [],
      agents: ['Alex Chen'],
      agent_ids: ['value_chain_mapper'],
      triggers: ['An invented administrator presses an invented button'],
      trigger_ids: ['invented_path'],
    },
    {
      crew_id: 'invented_second',
      display_name: 'Invented Second',
      purpose: 'Takes the invented artefact and invents something further',
      note: '',
      defect: null,
      cluster: 'invented_cluster',
      depends_on: ['Invented First'],
      depends_on_ids: ['invented_first'],
      agents: ['Alex Chen', 'Someone Else', 'A Third Person'],
      agent_ids: ['value_chain_mapper', 'someone_else', 'a_third_person'],
      triggers: ['An invented second way in'],
      trigger_ids: ['invented_dead_path'],
    },
    {
      crew_id: 'invented_third',
      display_name: 'Invented Third',
      purpose: 'Assembles the invented documents',
      note: '',
      defect: null,
      cluster: 'invented_cluster',
      depends_on: ['Invented Second'],
      depends_on_ids: ['invented_second'],
      agents: ['Alex Chen'],
      agent_ids: ['value_chain_mapper'],
      triggers: ['An invented third way in'],
      trigger_ids: ['invented_path'],
    },
  ],
  clusters: [
    {
      cluster_id: 'invented_cluster',
      label: 'Invented Cluster',
      note: 'An invented cluster of invented crews',
      orchestrator_id: 'pam',
      orchestrator: 'Pamela Reid',
      crew_ids: ['invented_first', 'invented_second', 'invented_third'],
      // Deliberately not all three: a centre that could start everything on its ring would let
      // a view drawing one spoke per crew pass.
      dispatches: ['invented_first', 'invented_third'],
    },
  ],
  crew_edges: [
    {
      source: 'invented_first',
      target: 'invented_second',
      kind: 'information',
      artefacts: ['invented_artefact'],
      declared: true,
      crosses_clusters: false,
    },
    {
      source: 'invented_second',
      target: 'invented_third',
      kind: 'sequencing',
      artefacts: [],
      declared: true,
      crosses_clusters: false,
    },
    {
      source: 'invented_first',
      target: 'invented_third',
      kind: 'inherited',
      artefacts: ['invented_artefact'],
      declared: false,
      crosses_clusters: false,
    },
  ],
  dispatch_paths: [
    {
      trigger: 'invented_path',
      label: 'An invented path',
      note: 'An invented path note',
      defect: null,
      injects_dispatch_reads: true,
    },
    {
      trigger: 'invented_dead_path',
      label: 'An invented dead path',
      note: 'An invented dead path note',
      defect: 'This invented path can start nothing',
      injects_dispatch_reads: false,
    },
  ],
  dispatch_reads: [
    {
      source: 'invented_dispatch_table',
      medium: 'a table in a SQLite database',
      via: 'build_and_run_crew',
      note: 'reviewer feedback, global across engagements',
      shared_beyond_this_project: false,
    },
  ],
  shared_sources: [
    {
      source: 'invented_sector_store',
      medium: 'a Chroma collection',
      via: 'InventedQueryTool',
      read_by: ['Alex Chen'],
      read_by_ids: ['value_chain_mapper'],
      reachable_by: ['Alex Chen', 'Someone Else', 'A Third Person'],
      reachable_by_ids: ['value_chain_mapper', 'someone_else', 'a_third_person'],
      handed_to_every_agent: false,
    },
    {
      source: 'invented_system_table',
      medium: 'a table in a SQLite database',
      via: 'build_and_run_crew',
      read_by: [],
      read_by_ids: [],
      reachable_by: [],
      reachable_by_ids: [],
      handed_to_every_agent: true,
    },
  ],
  scope: {
    crew_count: 3,
    agents_in_no_crew: [{ agent_id: 'pam', display_name: 'Pamela Reid' }],
  },
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/data-architecture/northern-water']}>
        <Routes>
          <Route path="/data-architecture/:slug" element={<DataArchitecture />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
  get.mockResolvedValue(PAYLOAD)
})

describe('the generated half of the privacy page', () => {
  it('asks for the engagement in the URL', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(get).toHaveBeenCalledWith('northern-water')
  })

  it('gives every tool a destination, and says what travels to it', async () => {
    renderPage()
    for (const row of PAYLOAD.tools) {
      expect((await screen.findAllByText(row.tool)).length).toBeGreaterThan(0)
      expect(screen.getAllByText(row.destination).length).toBeGreaterThan(0)
      expect(screen.getByText(row.sends)).toBeInTheDocument()
    }
  })

  it('shows the model calls no tool carries', async () => {
    renderPage()
    expect(await screen.findByText(PAYLOAD.inference.destination)).toBeInTheDocument()
    expect(screen.getByText(PAYLOAD.inference.sends)).toBeInTheDocument()
  })

  it('marks what leaves the deployment, and what does not', async () => {
    renderPage()
    expect((await screen.findAllByText(/Leaves this deployment/)).length).toBe(1)
    // The inference row and the local tool: one badge each, and neither of them the search
    // tool's. A page that badged everything the same way would pass a bare "is present" check.
    expect(screen.getAllByText(/Stays on this server/).length).toBe(2)
  })

  it('names a declared tool no agent holds, and says nobody holds it', async () => {
    renderPage()
    await screen.findByText(/Declared, and held by no agent/)
    expect(screen.getByText(/InventedUnheldTool/)).toBeInTheDocument()
  })

  it('warns that a store carrying no project identifier is not this project alone', async () => {
    renderPage()
    expect(await screen.findByText(/Not scoped to this project/)).toBeInTheDocument()
    expect(screen.getAllByText(/invented_sector_store/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Shared beyond this project/)).toBeInTheDocument()
  })

  it('puts a shared table in the same panel as a shared collection', async () => {
    // A table in the deployment's own database is shared in exactly the sense the panel is
    // about. While the flag was asked only of collections it could never appear here, and the
    // two genuinely shared tables surfaced only inside a note several sections below.
    renderPage()
    await screen.findByText(/Not scoped to this project/)
    expect(screen.getByText(/invented_system_table/)).toBeInTheDocument()
    expect(
      screen.getByText(/handed to every agent when a crew is dispatched/),
    ).toBeInTheDocument()
  })

  it('names who can reach a collection, not only who is declared to read it', async () => {
    // The declared readers are half the truth: the collection is an argument to the query
    // tool, so every holder can reach it. A generated row inherits authority, and this one was
    // accurate, specific, and short by half.
    renderPage()
    await screen.findByText(/Not scoped to this project/)
    expect(screen.getByText(/agents instructed to read it/)).toBeInTheDocument()
    expect(screen.getByText(/any of the 3 agents holding that tool can query it/)).toBeInTheDocument()
    expect(screen.getAllByText(/Someone Else/).length).toBeGreaterThan(0)
  })

  it('says once that a collection is named at query time, covering both collections', async () => {
    renderPage()
    expect(
      await screen.findByText(/any agent holding the query tool can reach any collection/),
    ).toBeInTheDocument()
  })

  it('states its own scope, naming the agent the declarations put in no crew', async () => {
    // Scoped to the notice itself. The orchestrator is now named in the cluster summary and on
    // the graph as well, so an unscoped query would pass on any of those three - and the one
    // that matters is the caveat.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const notice = within(document.getElementById('scope')!)
    expect(notice.getByText(/3 crews/)).toBeInTheDocument()
    expect(notice.getByText(/Pamela Reid/)).toBeInTheDocument()
    expect(notice.getByText(/not enumerated below/)).toBeInTheDocument()
  })

  it('keeps the scope statement reachable from wherever a reader lands', async () => {
    // Anchors make it easy to arrive in the middle of this page from a link somebody sent. A
    // caveat that only sits at the top is one such a reader never meets.
    renderPage()
    const nav = within(await screen.findByRole('navigation', { name: /Sections of this page/ }))
    const link = nav.getByRole('link', { name: /What this page covers/ })
    expect(link).toHaveAttribute('href', '#scope')
    expect(link.textContent).toMatch(/3 declared crews/)
  })

  it("renders each crew's purpose, trigger, and defect", async () => {
    const crew = PAYLOAD.crews[0]
    renderPage()
    expect(await screen.findByText(crew.purpose)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(crew.triggers[0]))).toBeInTheDocument()
    expect(screen.getByText(crew.defect!)).toBeInTheDocument()
  })

  it('says which dispatch paths carry the material handed to every agent, and which do not', async () => {
    renderPage()
    await screen.findByText(/An invented path note/)
    expect(screen.getByText(/Carries the material above/)).toBeInTheDocument()
    expect(screen.getByText(/Carries none of the material above/)).toBeInTheDocument()
    expect(screen.getByText(/reviewer feedback, global across engagements/)).toBeInTheDocument()
  })

  it('presents triggers as what can start a crew rather than as who may', async () => {
    // The charter says nothing about authority, and a page that read a trigger as permission
    // would be making a claim about access control out of a claim about wiring.
    renderPage()
    expect(await screen.findByText(/not who may/)).toBeInTheDocument()
  })

  it('holds no destination of its own', async () => {
    // The payload above names no real service. Anything from the retired copy would show here.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    for (const ghost of ['Tavily', "Anthropic's API", 'Chroma Cloud', 'WebFetchTool']) {
      expect(screen.queryAllByText(new RegExp(ghost))).toHaveLength(0)
    }
  })

  it('holds no persona list of its own', async () => {
    // Sixteen of the seventeen personas are absent from this payload, so a page carrying its
    // own list - as the retired one did - would show them anyway.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    for (const persona of ['Maya Patel', 'Casey Liu', 'Finley Cooper']) {
      expect(screen.queryAllByText(new RegExp(persona))).toHaveLength(0)
    }
  })
})

describe('the prose half', () => {
  it('keeps the retention undertakings, apart from the generated table', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Undertakings' })).toBeInTheDocument()
    expect(screen.getByText(/This section is not generated/)).toBeInTheDocument()
    expect(screen.getByText(/ElevenLabs - speech synthesis, nothing kept/)).toBeInTheDocument()
    expect(screen.getByText(/Deepgram - transcription, nothing kept/)).toBeInTheDocument()
    expect(
      screen.getByText(/The skills library is deliberately always hosted/),
    ).toBeInTheDocument()
  })

  // The prose is about a deployment the generated half has just described, so it cannot be
  // rendered blind. The fixture above resolves inference to a local model; a card asserting a
  // contract about Anthropic processing these prompts would contradict the table two sections
  // up, on the one question the page exists to answer.
  it('does not assert an Anthropic inference contract when inference stays on this server', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Undertakings' })
    expect(screen.queryByText(/Anthropic - inference, in flight only/)).toBeNull()
    expect(screen.getByText(/Anthropic - not this engagement's agents/)).toBeInTheDocument()
    // And it does not swing the other way: Anthropic is still reached by the skills library on
    // a sensitive engagement, so the terms are stated rather than dropped.
    expect(screen.getByText(/the skills library below/)).toBeInTheDocument()
  })

  it('asserts it when inference does leave', async () => {
    get.mockResolvedValue({
      ...PAYLOAD,
      llm_mode: 'standard',
      inference: { ...PAYLOAD.inference, leaves_deployment: true },
    })
    renderPage()
    expect(await screen.findByText(/Anthropic - inference, in flight only/)).toBeInTheDocument()
    expect(screen.queryByText(/Anthropic - not this engagement's agents/)).toBeNull()
  })

  it('says that the paths outside the crews were checked against the table', async () => {
    renderPage()
    expect(await screen.findByText(/Paths outside the crews/)).toBeInTheDocument()
  })
})

describe('when the engagement cannot be read', () => {
  it("shows the server's own sentence rather than a generic failure", async () => {
    get.mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: 'Access denied to this project' } },
    })
    renderPage()
    expect(await screen.findByText(/Access denied to this project/)).toBeInTheDocument()
  })
})

// ── The view ──────────────────────────────────────────────────────────────────
//
// Every assertion here reads the payload and looks for the consequence on the drawing. A test
// that checked the SVG had nodes would pass against a picture drawn by hand, which is the exact
// failure this page exists to end - so each one that fixes something about the picture also
// changes the payload and asserts the picture changed with it.

function crewName(id: string): string {
  return PAYLOAD.crews.find((c) => c.crew_id === id)!.display_name
}

describe('the graph view', () => {
  it('draws one node per crew, plus each cluster\'s orchestrator', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    for (const c of PAYLOAD.crews) {
      expect(screen.getByTestId(`node-${c.crew_id}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('node-pam')).toBeInTheDocument()
  })

  it('numbers the ring in the order the payload gives, clockwise', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const positions = PAYLOAD.clusters[0].crew_ids.map((id) =>
      screen.getByTestId(`node-${id}`).getAttribute('data-ring-position'),
    )
    expect(positions).toEqual(['1', '2', '3'])
  })

  it('moves the picture when the declared order moves', async () => {
    // The property the whole view rests on. Reversed, so no crew keeps its place.
    const reversed = [...PAYLOAD.clusters[0].crew_ids].reverse()
    get.mockResolvedValue({
      ...PAYLOAD,
      clusters: [{ ...PAYLOAD.clusters[0], crew_ids: reversed }],
    })
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(screen.getByTestId(`node-${reversed[0]}`)).toHaveAttribute('data-ring-position', '1')
    expect(screen.getByTestId('node-invented_first')).toHaveAttribute('data-ring-position', '3')
  })

  it('draws a spoke only to a crew the orchestrator can start', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    for (const id of PAYLOAD.clusters[0].dispatches) {
      expect(screen.getByTestId(`spoke-${id}`)).toBeInTheDocument()
    }
    expect(screen.queryByTestId('spoke-invented_second')).toBeNull()
  })

  it('distinguishes a flow that carries material from one that carries none', async () => {
    // The reason to derive the edges rather than draw them. An unlabelled arrow would present
    // the sequencing edge as the same relationship as the information one.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(screen.getByTestId('edge-invented_first-invented_second')).toHaveAttribute(
      'data-kind',
      'information',
    )
    expect(screen.getByTestId('edge-invented_second-invented_third')).toHaveAttribute(
      'data-kind',
      'sequencing',
    )
  })

  it('redraws an edge when the declaration behind it changes kind', async () => {
    get.mockResolvedValue({
      ...PAYLOAD,
      crew_edges: PAYLOAD.crew_edges.map((e) =>
        e.target === 'invented_third' && e.declared
          ? { ...e, kind: 'information' as const, artefacts: ['a_newly_shared_artefact'] }
          : e,
      ),
    })
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(screen.getByTestId('edge-invented_second-invented_third')).toHaveAttribute(
      'data-kind',
      'information',
    )
    expect(screen.getAllByText(/a_newly_shared_artefact/).length).toBeGreaterThan(0)
  })

  it('leaves inherited flows off the drawing until asked, and never off the table', async () => {
    // Twelve inherited flows across a ring of nine is a legible finding in a table and an
    // unreadable one on a ring. Hiding them from the drawing may not hide them from the page.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(screen.queryByTestId('edge-invented_first-invented_third')).toBeNull()

    const rows = screen.getAllByRole('row')
    expect(
      rows.some((row) => within(row).queryAllByText(/inherited/i).length > 0),
    ).toBe(true)

    fireEvent.click(screen.getByLabelText(/Show inherited flows/))
    expect(screen.getByTestId('edge-invented_first-invented_third')).toHaveAttribute(
      'data-kind',
      'inherited',
    )
  })

  it('is never the only carrier: every edge is written out below it', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const rows = screen.getAllByRole('row')
    for (const edge of PAYLOAD.crew_edges) {
      const row = rows.find(
        (r) =>
          within(r).queryAllByRole('link', { name: crewName(edge.source) }).length > 0 &&
          within(r).queryAllByRole('link', { name: crewName(edge.target) }).length > 0,
      )
      expect(row, `${edge.source} -> ${edge.target} is missing from the table`).toBeTruthy()
      for (const artefact of edge.artefacts) {
        expect(within(row!).getByText(new RegExp(artefact))).toBeInTheDocument()
      }
    }
    // And the sequencing row says so in words rather than only by a dashed line.
    expect(screen.getByText(/this crew reads none of its outputs/)).toBeInTheDocument()
  })

  it('names each cluster, its orchestrator, and what that orchestrator cannot start', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const summary = within(document.getElementById('cluster-invented_cluster')!)
    expect(summary.getByText(/An invented cluster of invented crews/)).toBeInTheDocument()
    expect(summary.getByText(/can start/)).toBeInTheDocument()
    expect(summary.getByRole('link', { name: 'Invented Second' })).toBeInTheDocument()
  })
})

describe('following a thread through the tables', () => {
  it('has no link that lands nowhere', async () => {
    // The whole of the navigation, checked at once. A href built from a label rather than an id -
    // the mistake the ids exist to prevent - shows up here and nowhere else.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const targets = Array.from(document.querySelectorAll('a[href^="#"]')).map((a) =>
      (a.getAttribute('href') ?? '').slice(1),
    )
    expect(targets.length).toBeGreaterThan(10)
    for (const id of new Set(targets)) {
      expect(document.getElementById(id), `nothing on this page has id "${id}"`).not.toBeNull()
    }
  })

  it('goes from an agent to its crews, its tools, and where they reach', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const card = within(document.getElementById('agent-value_chain_mapper')!)
    expect(card.getByRole('link', { name: 'Invented First' })).toHaveAttribute(
      'href',
      '#crew-invented_first',
    )
    expect(card.getAllByRole('link', { name: 'InventedSearchTool' })[0]).toHaveAttribute(
      'href',
      '#tool-InventedSearchTool',
    )
  })

  it('goes from a crew to its agents, and to how it can be started', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const card = within(document.getElementById('crew-invented_first')!)
    expect(card.getByRole('link', { name: 'Alex Chen' })).toHaveAttribute(
      'href',
      '#agent-value_chain_mapper',
    )
    expect(
      card.getByRole('link', { name: /An invented administrator presses an invented button/ }),
    ).toHaveAttribute('href', '#dispatch-invented_path')
  })

  it('goes from a tool to the agents that hold it', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const row = within(document.getElementById('tool-InventedSearchTool')!)
    expect(row.getByRole('link', { name: 'Alex Chen' })).toHaveAttribute(
      'href',
      '#agent-value_chain_mapper',
    )
  })

  it('keeps the declared readers of a shared store apart from those able to reach it', async () => {
    // The panel's sharpest honesty feature. Navigation must not flatten the two into one list.
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const entry = within(document.getElementById('source-invented_sector_store')!)
    expect(entry.getByText(/declared readers/)).toBeInTheDocument()
    expect(entry.getByText(/agents instructed to read it/)).toBeInTheDocument()
    expect(entry.getByRole('link', { name: 'Someone Else' })).toHaveAttribute(
      'href',
      '#agent-someone_else',
    )
  })

  it('says nothing about who may press a dispatch path, only that it exists', async () => {
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(within(document.getElementById('dispatch')!).getByText(/not who may/)).toBeInTheDocument()
  })
})

describe('the two halves stay apart', () => {
  it('runs no thread between what is generated and what is undertaken', async () => {
    // A reader being able to tell what the system asserts about itself from what a person has
    // promised is most of this page's value, and a link crossing the boundary would blur it.
    renderPage()
    await screen.findByRole('heading', { name: 'Undertakings' })
    const undertakings = document.getElementById('undertakings')!
    expect(undertakings.querySelectorAll('a')).toHaveLength(0)

    // And nothing generated links into the prose either - the nav bar is the only route, and it
    // labels the section as not generated rather than presenting it as one more table.
    const intoProse = Array.from(document.querySelectorAll('a[href="#undertakings"]'))
    expect(intoProse).toHaveLength(1)
    expect(intoProse[0].textContent).toMatch(/not generated/)
  })

  it('keeps an undertaking out of the generated tables, and a derived fact out of the prose', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Undertakings' })
    const undertakings = document.getElementById('undertakings')!

    const promise = screen.getByText(/ElevenLabs - speech synthesis, nothing kept/)
    expect(undertakings.contains(promise)).toBe(true)
    for (const generated of ['flows', 'egress', 'crews', 'agents']) {
      expect(document.getElementById(generated)!.contains(promise)).toBe(false)
    }

    const derived = screen.getByText(PAYLOAD.crews[0].purpose)
    expect(undertakings.contains(derived)).toBe(false)
  })
})
