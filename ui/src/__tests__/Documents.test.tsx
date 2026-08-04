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
    // Match the copy in full - a looser /no documents/i stopped matching when
    // the word "source" was added, and would silently start matching the
    // Value Chain page's own empty state if these tests are ever shared.
    expect(await screen.findByText(/no source documents uploaded yet/i)).toBeInTheDocument()
  })

  it('renders file upload input', () => {
    render(<Wrapper />)
    expect(screen.getByLabelText(/upload/i)).toBeInTheDocument()
  })

  it('shows the reason a document failed to ingest', async () => {
    // This document said "pending ingestion" through three permanent failures, because
    // `ingested: false` was the only state the row could hold and the reason lived in a
    // server log. A reader had no way to tell "not started" from "will never succeed".
    const { projectsApi } = await import('../api/endpoints')
    vi.mocked(projectsApi.documents).mockResolvedValueOnce([{
      id: 3, project_id: 1, filename: 'd89a.pdf',
      original_name: 'SPUK_2025_Annual_Accounts.pdf', file_path: 'x',
      content_type: 'application/pdf', size_bytes: 1505860,
      ingested: false, ingest_status: 'failed',
      ingest_error: "ChromaDB upsert failed: Quota exceeded: 'Number of records'",
      uploaded_at: '2026-08-04T11:23:14',
    }])

    render(<Wrapper />)

    expect(await screen.findByText(/ingestion failed/i)).toBeInTheDocument()
    expect(screen.getByTestId('ingest-error-3')).toHaveTextContent(/Quota exceeded/)
    // The distinction the whole change exists for.
    expect(screen.queryByText(/pending ingestion/i)).not.toBeInTheDocument()
  })

  it('still shows pending for a document that has not been ingested yet', async () => {
    // The other half: a genuinely waiting document must not be dressed up as a failure.
    const { projectsApi } = await import('../api/endpoints')
    vi.mocked(projectsApi.documents).mockResolvedValueOnce([{
      id: 4, project_id: 1, filename: 'new.pdf', original_name: 'Just uploaded.pdf',
      file_path: 'x', content_type: 'application/pdf', size_bytes: 2048,
      ingested: false, ingest_status: 'pending', ingest_error: null,
      uploaded_at: '2026-08-04T11:30:00',
    }])

    render(<Wrapper />)

    expect(await screen.findByText(/pending ingestion/i)).toBeInTheDocument()
    expect(screen.queryByText(/ingestion failed/i)).not.toBeInTheDocument()
  })
})
