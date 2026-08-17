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
import { render, screen } from '@testing-library/react'
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
    },
    {
      tool: 'InventedLocalTool',
      reaches: 'nothing outside this deployment',
      sends: 'nothing - it writes to this project only',
      destination: 'nothing outside this deployment',
      leaves_deployment: false,
      gated_by_mode: false,
      held_by: ['Alex Chen'],
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
      crews: ['Invented Crew'],
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
      ],
    },
  ],
  crews: [
    {
      crew_id: 'invented_crew',
      display_name: 'Invented Crew',
      purpose: 'Builds the invented thing from the invented inputs',
      note: 'An invented note',
      defect: 'An invented defect',
      depends_on: [],
      agents: ['Alex Chen'],
      triggers: ['An invented administrator presses an invented button'],
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
      read_by: ['Alex Chen'],
    },
  ],
  scope: {
    crew_count: 1,
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

  it('states its own scope, naming the agent the declarations put in no crew', async () => {
    renderPage()
    expect(await screen.findByText(/1 crews/)).toBeInTheDocument()
    expect(screen.getByText(/Pamela Reid/)).toBeInTheDocument()
    expect(screen.getByText(/not enumerated below/)).toBeInTheDocument()
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
    expect(await screen.findByText(/Undertakings/)).toBeInTheDocument()
    expect(screen.getByText(/This section is not generated/)).toBeInTheDocument()
    expect(screen.getByText(/ElevenLabs - speech synthesis, nothing kept/)).toBeInTheDocument()
    expect(screen.getByText(/Deepgram - transcription, nothing kept/)).toBeInTheDocument()
    expect(
      screen.getByText(/The skills library is deliberately always hosted/),
    ).toBeInTheDocument()
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
