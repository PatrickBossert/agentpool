// ui/src/__tests__/ValueChain.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    valueChain: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/value-chain']}>
          <Routes>
            <Route path="/:slug/value-chain" element={<ValueChain />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('ValueChain', () => {
  it('shows empty state heading', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/value chain/i)).toBeInTheDocument()
  })

  it('shows awaiting agents message when no data', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/awaiting/i)).toBeInTheDocument()
  })
})
