// ui/src/__tests__/ValueChain.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import ValueChain from '../pages/ValueChain'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    valueChain: vi.fn().mockResolvedValue([]),
  },
  valueChainApi: {
    get: vi.fn().mockRejectedValue(
      Object.assign(new Error('Not Found'), { response: { status: 404 }, isAxiosError: true }),
    ),
    save: vi.fn(),
    migrate: vi.fn(),
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
    // Query the heading by role: the page body now also says "Value Chain Mapper"
    // and "each value chain node", so a bare text match finds three elements.
    expect(await screen.findByRole('heading', { name: 'Value Chain' })).toBeInTheDocument()
  })

  it('offers to migrate the existing diagram when no model has been saved', async () => {
    render(<Wrapper />)
    // The page opens on the Setup tab and only switches to Structure by itself once
    // outputs exist, so with none the empty state has to be navigated to.
    await userEvent.click(await screen.findByRole('button', { name: 'Structure' }))
    expect(
      await screen.findByRole('button', { name: /migrate from the existing diagram/i }),
    ).toBeInTheDocument()
  })
})
