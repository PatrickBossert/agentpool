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

import CrewCarousel from '../components/CrewCarousel'

function renderCarousel(onSelectAgent?: (crewKey: string, agent: string) => void,
                        onSelectCrew: (crewKey: string) => void = () => {}) {
  return render(
    <MemoryRouter>
      <CrewCarousel
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
    </MemoryRouter>,
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
