// ui/src/__tests__/CrewCarouselBadge.test.tsx
//
// PAM's card showed the project-wide count of pending review gates as though every one of
// them were hers. A gate raised by any crew made PAM read as waiting on the reader, which
// sent them looking for something PAM had never asked for.
//
// The crew cards already scope by crew - waitingCrews is built from each review's
// crew_name - so this only brings PAM's count into line with the rest of the carousel.
import { render, screen } from '@testing-library/react'
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
import type { HumanReview } from '../types'

function review(id: number, crew_name: string): HumanReview {
  return { id, prompt: 'Please review', crew_run_id: id, crew_name, decision: 'pending',
           reviewed_at: '' }
}

function renderCarousel(hitlReviews: HumanReview[]) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>
      <CrewCarousel
        slug="carousel-test"
        crewRuns={[]}
        isPipelineActive={false}
        logs={[]}
        hitlReviews={hitlReviews}
        selectedCrew="PAM"
        onSelectCrew={() => {}}
        onRunCrew={() => {}}
        onRerunCrew={() => {}}
        onRunPipeline={() => {}}
      />
    </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("PAM's awaiting-review badge", () => {
  it("does not count another crew's gate as PAM's", () => {
    renderCarousel([review(1, 'discovery_mapping'), review(2, 'assessment_design')])
    expect(screen.queryByText(/awaiting review/i)).toBeNull()
  })

  it("counts PAM's own gates", () => {
    renderCarousel([review(1, 'discovery_mapping'), review(2, 'PAM')])
    // One, not three: the two belonging to other crews are theirs to answer.
    expect(screen.getByText(/1 awaiting review/i)).toBeInTheDocument()
  })
})
