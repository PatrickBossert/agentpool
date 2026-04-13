// ui/src/__tests__/Roadmap.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Roadmap from '../pages/Roadmap'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    roadmap: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/roadmap']}>
          <Routes>
            <Route path="/:slug/roadmap" element={<Roadmap />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Roadmap', () => {
  it('renders Visual and Gantt tabs', () => {
    render(<Wrapper />)
    expect(screen.getByRole('tab', { name: /visual/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /gantt/i })).toBeInTheDocument()
  })

  it('switches to Gantt tab on click', async () => {
    render(<Wrapper />)
    await userEvent.click(screen.getByRole('tab', { name: /gantt/i }))
    expect(screen.getByRole('tab', { name: /gantt/i })).toHaveAttribute('aria-selected', 'true')
  })
})
