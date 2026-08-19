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
  // Nothing narrowed. The banner's caveat must not render on the engagements that are simply
  // their mode, which is nearly all of them - asserted below rather than left to be noticed.
  withheld_by_project: [],
  inference: {
    reaches: 'a language model',
    sends: 'every prompt the agent builds',
    destination: 'the local model on this host',
    leaves_deployment: false,
    gated_by_grant: true,
  },
  tools: [
    {
      tool: 'InventedSearchTool',
      reaches: 'a web search service',
      sends: 'the search query the agent composed',
      destination: 'the Invented search API',
      leaves_deployment: true,
      gated_by_grant: false,
      held_by: ['Alex Chen'],
      held_by_ids: ['value_chain_mapper'],
    },
    {
      tool: 'InventedLocalTool',
      reaches: 'nothing outside this deployment',
      sends: 'nothing - it writes to this project only',
      destination: 'nothing outside this deployment',
      leaves_deployment: false,
      gated_by_grant: false,
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
          tier: 'sector',
          tier_scope: 'shared by every engagement in this sector, including other clients',
        },
        {
          source: 'invented_project_artefact',
          medium: 'a JSON artefact in the project outputs directory',
          via: 'SQLiteStateTool',
          note: 'his own ledger',
          shared_beyond_this_project: false,
          // An artefact is not in the knowledge store, so it has no tier. Null is the answer,
          // not an unfilled field.
          tier: null,
          tier_scope: null,
        },
        {
          source: 'invented_dispatch_table',
          medium: 'a table in a SQLite database',
          // Not a tool: what the dispatch path reads on the agent's behalf. There is no row for
          // it in the egress table, so it must not be rendered as a link to one.
          via: 'build_and_run_crew',
          note: 'handed to him without his asking',
          shared_beyond_this_project: false,
          tier: null,
          tier_scope: null,
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
      // One crew per band: this payload's three crews run one after another. The parallel case
      // is a payload of its own further down, so that the difference between them is what the
      // picture is asserted to show.
      crew_bands: [['invented_first'], ['invented_second'], ['invented_third']],
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
      tier: null,
      tier_scope: null,
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
      tier: 'sector',
      tier_scope: 'shared by every engagement in this sector, including other clients',
    },
    // Offered to every holder of the query tool and named in no task description: nobody is
    // instructed to read it, and it is not handed to anybody either. The two absences render
    // differently on purpose - "handed to every agent" and "no agent is instructed to read it"
    // are opposite statements, and an empty reader list rendered as a bare list would read as
    // neither.
    {
      source: 'invented_organisation_store',
      medium: 'a Chroma collection',
      via: 'InventedQueryTool',
      read_by: [],
      read_by_ids: [],
      reachable_by: ['Alex Chen', 'Someone Else', 'A Third Person'],
      reachable_by_ids: ['value_chain_mapper', 'someone_else', 'a_third_person'],
      handed_to_every_agent: false,
      tier: 'organisation',
      tier_scope: 'shared by every project of this organisation',
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
      // A table in the deployment's own database is shared for a different reason - it is not a
      // width of the knowledge store - so it carries no tier, and must not be given one.
      tier: null,
      tier_scope: null,
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

  it('badges the processing mode by what is actually granted, not by the mode name alone', async () => {
    // The fixture's own mode is 'sensitive' and its inference stays local - the case the old
    // `llm_mode === 'sensitive' ? 'stays' : 'neutral'` collapse happened to get right. This
    // proves the badge is read off inference.leaves_deployment, not off the mode string: it
    // would have said the same thing for a llm_mode this fixture does not use.
    renderPage()
    expect(await screen.findByText(/Model inference: local/)).toBeInTheDocument()
  })

  it('shows a mode that grants one capability and not the other as two separate badges, never one collapsed tone', async () => {
    // The case the old single Pill could not express, and the reason sovereign (hosted
    // models, a local vector store) was named in the brief as the mode still to come:
    // HOSTED_INFERENCE and CLOUD_VECTOR_STORE are granted independently
    // (api/services/deployment_modes.py), so a mode may open one and keep the other closed.
    // llm_mode itself is left as an untouched string the fixture invents - the page must not
    // be reading meaning out of the name, only out of the two leaves_deployment flags.
    get.mockResolvedValue({
      ...PAYLOAD,
      llm_mode: 'invented-split-mode',
      inference: { ...PAYLOAD.inference, gated_by_grant: true, leaves_deployment: true },
      tools: [
        { ...PAYLOAD.tools[1], tool: 'ChromaQueryTool', gated_by_grant: true, leaves_deployment: false },
        PAYLOAD.tools[0],
      ],
    })
    renderPage()
    expect(await screen.findByText(/Model inference: hosted/)).toBeInTheDocument()
    expect(screen.getByText(/ChromaQueryTool: local/)).toBeInTheDocument()
  })

  it('says a standard engagement holds less than its mode grants, and does not say it of one that does not', async () => {
    // The shape this branch builds: `standard`, forcing local inference, so the model calls
    // stay here while the documents go to Chroma Cloud. A reader sees the mode name and a
    // local inference badge side by side, and the reconciling sentence is the only thing on
    // the page that explains them - without it the badge reads as a rendering bug.
    //
    // The sentence is composed from mode_permits rather than from a condition on a flag name,
    // so a second override is described here without this file changing.
    get.mockResolvedValue({
      ...PAYLOAD,
      llm_mode: 'standard',
      withheld_by_project: [
        { capability: 'HOSTED_INFERENCE', mode_permits: 'may send prompts to a hosted model provider' },
      ],
      inference: { ...PAYLOAD.inference, gated_by_grant: true, leaves_deployment: false },
      tools: [
        { ...PAYLOAD.tools[1], tool: 'ChromaQueryTool', gated_by_grant: true, leaves_deployment: true },
        PAYLOAD.tools[0],
      ],
    })
    renderPage()
    expect(await screen.findByText(/Narrowed for this engagement/)).toBeInTheDocument()
    expect(
      screen.getByText(/may send prompts to a hosted model provider - this project does not/)
    ).toBeInTheDocument()
    // The two badges, still independent: local models over a cloud vector store.
    expect(screen.getByText(/Model inference: local/)).toBeInTheDocument()
    expect(screen.getByText(/ChromaQueryTool: hosted/)).toBeInTheDocument()
  })

  it('does not claim an engagement is narrowed when it holds everything its mode grants', async () => {
    // Guard the guard: a caveat that always rendered would pass the test above.
    renderPage()
    await screen.findByText(/Processing mode/)
    expect(screen.queryByText(/Narrowed for this engagement/)).not.toBeInTheDocument()
    expect(screen.queryByText(/holds less than its mode grants/)).not.toBeInTheDocument()
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

  it('says with whom a shared store is shared, not only that it is shared', async () => {
    // "Not scoped to this project" is true of the sector store and of the organisation store,
    // and they are shared with entirely different people - other clients on this deployment,
    // against this organisation's own sibling projects. The panel heading cannot tell those
    // apart; the tier and its scope sentence are what do.
    renderPage()
    await screen.findByText(/Not scoped to this project/)
    expect(
      screen.getByText(/shared by every engagement in this sector, including other clients/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/shared by every project of this organisation/),
    ).toBeInTheDocument()
  })

  it('says a store nobody is instructed to read is unread, not that it is handed out', async () => {
    // The organisation tier is writable today and named in no task description. An empty
    // reader list rendered as "declared readers: " reads as a rendering fault; rendered as
    // "handed to every agent" it would be the opposite of the truth.
    renderPage()
    await screen.findByText(/Not scoped to this project/)
    const entry = within(document.getElementById('source-invented_organisation_store')!)
    expect(entry.getByText(/which no agent is instructed to read/)).toBeInTheDocument()
    expect(entry.queryByText(/handed to every agent/)).not.toBeInTheDocument()
    // Nobody is told to read it and three people can, which is the whole point of the row.
    expect(entry.getByText(/any of the 3 agents holding that tool can query it/)).toBeInTheDocument()
  })

  it('names who can reach a collection, not only who is declared to read it', async () => {
    // The declared readers are half the truth: the collection is an argument to the query
    // tool, so every holder can reach it. A generated row inherits authority, and this one was
    // accurate, specific, and short by half.
    // Scoped to the sector row rather than to the page: two shared collections now carry this
    // line, and an unscoped query would have started matching the other one's copy.
    renderPage()
    await screen.findByText(/Not scoped to this project/)
    const entry = within(document.getElementById('source-invented_sector_store')!)
    expect(entry.getByText(/agents instructed to read it/)).toBeInTheDocument()
    expect(entry.getByText(/any of the 3 agents holding that tool can query it/)).toBeInTheDocument()
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

/** The circle the page actually drew for a node, read off the SVG rather than off the layout. */
function circleOf(testId: string): { cx: number; cy: number; r: number } {
  const circle = screen.getByTestId(testId).querySelector('circle')!
  const read = (name: string) => Number(circle.getAttribute(name))
  return { cx: read('cx'), cy: read('cy'), r: read('r') }
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
      screen.getByTestId(`node-${id}`).getAttribute('data-band'),
    )
    expect(positions).toEqual(['1', '2', '3'])
  })

  it('moves the picture when the declared order moves', async () => {
    // The property the whole view rests on. Reversed, so no crew keeps its place.
    const reversed = [...PAYLOAD.clusters[0].crew_bands].reverse()
    get.mockResolvedValue({
      ...PAYLOAD,
      clusters: [{ ...PAYLOAD.clusters[0], crew_bands: reversed, crew_ids: reversed.flat() }],
    })
    renderPage()
    await screen.findAllByText(/Invented search API/)
    expect(screen.getByTestId(`node-${reversed[0][0]}`)).toHaveAttribute('data-band', '1')
    expect(screen.getByTestId('node-invented_first')).toHaveAttribute('data-band', '3')
  })

  it('draws two crews in one band at one angle, not at two positions', async () => {
    // The rendered consequence of a band, which is where it has to hold: the layout function
    // agreeing with itself proves nothing about the picture on the page. Same three crews as
    // every other test here - only the banding differs - and the second and third are now
    // parallel, so the drawing must give them the same number and the same bearing from the
    // centre while keeping them apart.
    const parallel = [['invented_first'], ['invented_second', 'invented_third']]
    get.mockResolvedValue({
      ...PAYLOAD,
      clusters: [{ ...PAYLOAD.clusters[0], crew_bands: parallel, crew_ids: parallel.flat() }],
    })
    renderPage()
    await screen.findAllByText(/Invented search API/)

    const second = screen.getByTestId('node-invented_second')
    const third = screen.getByTestId('node-invented_third')
    expect(second.getAttribute('data-band')).toBe('2')
    expect(third.getAttribute('data-band')).toBe('2')
    expect(second.getAttribute('data-angle')).toBe(third.getAttribute('data-angle'))

    // Same bearing, different distance: on one ray from the orchestrator, not on top of each
    // other. Read off the circles the page actually drew rather than off the layout.
    const centre = circleOf('node-pam')
    const a = circleOf('node-invented_second')
    const b = circleOf('node-invented_third')
    const bearing = (p: { cx: number; cy: number }) =>
      Math.atan2(p.cy - centre.cy, p.cx - centre.cx)
    expect(bearing(a)).toBeCloseTo(bearing(b), 3)
    expect(Math.hypot(a.cx - b.cx, a.cy - b.cy)).toBeGreaterThan(a.r + b.r)
  })

  it('redraws the ring when two crews stop being parallel', async () => {
    // The same three crews banded one way and then the other. If the view laid itself out from
    // the flat order - which is identical in both payloads - nothing here would move.
    const parallel = [['invented_first'], ['invented_second', 'invented_third']]
    get.mockResolvedValue({
      ...PAYLOAD,
      clusters: [{ ...PAYLOAD.clusters[0], crew_bands: parallel, crew_ids: parallel.flat() }],
    })
    const { unmount } = renderPage()
    await screen.findAllByText(/Invented search API/)
    const banded = {
      band: screen.getByTestId('node-invented_third').getAttribute('data-band'),
      angle: screen.getByTestId('node-invented_third').getAttribute('data-angle'),
    }
    unmount()

    get.mockResolvedValue(PAYLOAD)
    renderPage()
    await screen.findAllByText(/Invented search API/)
    const sequential = screen.getByTestId('node-invented_third')
    expect(sequential.getAttribute('data-band')).not.toBe(banded.band)
    expect(sequential.getAttribute('data-angle')).not.toBe(banded.angle)
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
