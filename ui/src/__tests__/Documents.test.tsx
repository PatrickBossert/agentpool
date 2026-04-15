// ui/src/__tests__/Documents.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Documents from '../pages/Documents'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    documents: vi.fn().mockResolvedValue([]),
    uploadDocument: vi.fn().mockResolvedValue({
      id: 1,
      original_name: 'annual-report.pdf',
      filename: 'abc123.pdf',
      content_type: 'application/pdf',
      size_bytes: 1024,
      ingested: false,
      uploaded_at: '2026-04-13T10:00:00',
    }),
    outputs: vi.fn().mockResolvedValue([]),
  },
}))

function Wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/acme-rail/documents']}>
          <Routes>
            <Route path="/:slug/documents" element={<Documents />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Documents', () => {
  it('shows empty state when no documents', async () => {
    render(<Wrapper />)
    expect(await screen.findByText(/no documents/i)).toBeInTheDocument()
  })

  it('renders file upload input', () => {
    render(<Wrapper />)
    expect(screen.getByLabelText(/upload/i)).toBeInTheDocument()
  })
})
