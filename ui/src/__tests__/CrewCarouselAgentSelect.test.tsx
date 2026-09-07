// ui/src/__tests__/CrewCarouselAgentSelect.test.tsx
//
// Clicking an agent's face in the carousel says which agent the Agents tab should open on.
//
// The seam existed before the caller did: Task 6 built `AgentDetailPanel`'s `initialAgent`
// prop and nothing passed it, so the tab always opened on the crew's first agent - correct
// for Taylor, wrong for the other three, and invisible because "opened on the first" and
// "opened on the one I clicked" are the same screen whenever you click the first.
//
// So the assertions below are all made on an agent that is **not** first in its crew.
// `discovery_interviews` is [Interview Coordinator, Stakeholder Interviewer, Second
// Interviewer, Synthesis Analyst]; every case uses Avery or Laura, never Taylor.
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import CrewCarousel from '../components/CrewCarousel'

// The carousel resolves each agent's name and face against the project's configuration since
// Task 7. Mocked to an empty roll so these tests are still about what they say they are about -
// and so nothing here reaches the network. `CarouselAgentIdentity.test.tsx` is where a
// configured face is driven.
vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { getAll: vi.fn().mockResolvedValue({ agents: {} }) },
}))

function renderCarousel(onSelectAgent?: (crewKey: string, agent: string) => void,
                        onSelectCrew: (crewKey: string) => void = () => {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>
      <CrewCarousel
        slug="carousel-test"
        crewRuns={[]}
        isPipelineActive={false}
        logs={[]}
        hitlReviews={[]}
        selectedCrew="discovery_interviews"
        onSelectCrew={onSelectCrew}
        onSelectAgent={onSelectAgent}
        onRunCrew={() => {}}
        onRerunCrew={() => {}}
        onRunPipeline={() => {}}
      />
    </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('choosing an agent from the carousel', () => {
  it('reports the agent whose face was clicked, and the crew it belongs to', () => {
    const onSelectAgent = vi.fn()
    renderCarousel(onSelectAgent)

    // Avery is second in his crew. A component reporting "the first agent" would pass an
    // assertion made on Taylor and fail this one, which is the whole reason it is Avery.
    fireEvent.click(screen.getByTitle('Configure Avery Singh'))

    expect(onSelectAgent).toHaveBeenCalledWith('discovery_interviews', 'Stakeholder Interviewer')
  })

  it('still selects the crew, because a face is part of its card', () => {
    // The click is deliberately allowed to bubble: clicking anywhere on a card has always
    // meant "select this crew", and a face is somewhere on the card. Asserted because
    // `stopPropagation` is the obvious thing to reach for and would silently take the
    // long-standing behaviour away.
    const onSelectCrew = vi.fn()
    renderCarousel(() => {}, onSelectCrew)

    fireEvent.click(screen.getByTitle('Configure Laura Nelson'))

    expect(onSelectCrew).toHaveBeenCalledWith('discovery_interviews')
  })

  it('renders the faces without a handler at all', () => {
    // The control, and the reason the prop is optional. A card rendered by any other caller -
    // or by a test that does not care - must not need a stub to avoid throwing.
    expect(() => renderCarousel(undefined)).not.toThrow()
    fireEvent.click(screen.getByTitle('Configure Avery Singh'))
    expect(screen.getByTitle('Configure Avery Singh')).toBeInTheDocument()
  })
})

describe('how a four-agent crew lays its faces out', () => {
  // Four faces at `md` do not fit one row - 4×48+18 = 210 against 168px of card - so
  // `flex-wrap` broke them 3+1, which reads as a crew of three with an afterthought. Two per
  // row buys the width back for `lg`, the size a two-agent card already uses.
  //
  // Asserted on the **grid track count**, not on a screenshot: jsdom performs no layout, so
  // "how wide did it end up" is unanswerable here, while "how many columns was it told to
  // use" is exactly the decision under test.
  it('gives a crew of four two columns, not one row of four', () => {
    renderCarousel()
    const row = screen.getByTitle('Configure Avery Singh').parentElement!
    expect(row.style.gridTemplateColumns).toBe('repeat(2, minmax(0, 1fr))')
  })

  it('makes those faces the large size, not the crowded one', () => {
    // The point of the two rows. `w-20` is lg (80px); `w-12` is md (48px), which is what four
    // faces were before and what a regression to a single row would bring back.
    renderCarousel()
    // Selected by the class that carries the size rather than by position: the first
    // descendant div is AgentHoverCard's wrapper, which knows nothing about how big a face is.
    const face = screen
      .getByTitle('Configure Avery Singh')
      .querySelector('[class*="rounded-full"]')!
    expect(face.className).toContain('w-20')
    expect(face.className).not.toContain('w-12')
  })

  it('leaves a two-agent crew exactly as it was', () => {
    // The control, and an honest one about what it can show. `faceColumns` returns the agent
    // count for every size but four, so a two-agent crew asks for two columns both before and
    // after this change - the track count cannot distinguish them. What it CAN show is that a
    // pair is still one row of two large faces, which is the thing a careless "always two
    // columns" rule would leave intact and a careless "always two ROWS" rule would break.
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <CrewCarousel
            slug="carousel-test"
            crewRuns={[]} isPipelineActive={false} logs={[]} hitlReviews={[]}
            selectedCrew="discovery_mapping" onSelectCrew={() => {}}
            onRunCrew={() => {}} onRerunCrew={() => {}} onRunPipeline={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    // Named agents, not an index into everything on screen: the carousel renders EVERY crew's
    // card at once, so `getAllByTitle(/^Configure /)` returns all fourteen faces on the strip.
    // Alex and Morgan are the two in discovery_mapping.
    const alex = screen.getByTitle('Configure Alex Chen')
    const row = alex.parentElement!
    expect(row.style.gridTemplateColumns).toBe('repeat(2, minmax(0, 1fr))')
    expect(row.children).toHaveLength(2)
    expect(row).toContainElement(screen.getByTitle('Configure Morgan Davis'))
    expect(alex.querySelector('[class*="rounded-full"]')!.className).toContain('w-20')
  })
})
