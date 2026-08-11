// ui/src/__tests__/MayaOutputExtra.test.tsx
// Level carries the tier, perspective carries the role - MayaOutputExtra used to split on two
// hardcoded level sets and render nothing outside them, so a script with an unrecognised level
// vanished with no message and no count.
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import MayaOutputExtra from '../components/tabs/MayaOutputExtra'
import { projectsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getInterviewScripts: vi.fn(),
  },
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('MayaOutputExtra', () => {
  it('renders every script it is given, including one with an unrecognised perspective', async () => {
    // The current two buckets drop anything outside them silently - no message, no count.
    vi.mocked(projectsApi.getInterviewScripts).mockResolvedValue({
      'SC-1': { script_id: 'SC-1', node_id: '1',   level: 'L1', perspective: null, node_label: 'Property', sections: [] },
      'SC-2': { script_id: 'SC-2', node_id: '1.F', level: 'L1', perspective: 'F',  node_label: 'Frontline', sections: [] },
      'SC-3': { script_id: 'SC-3', node_id: '9',   level: 'L3', perspective: 'X',  node_label: 'Odd one',   sections: [] },
    } as never)
    render(<Wrapper><MayaOutputExtra slug="p" /></Wrapper>)
    // Exact text, not a substring match: the perspective badge for SC-2 renders the title
    // "Frontline Worker", which a /Frontline/ substring match would also catch, hiding a
    // false pass if the node_label itself were never rendered.
    expect(await screen.findByText('Property')).toBeInTheDocument()
    expect(await screen.findByText('Frontline')).toBeInTheDocument()
    expect(await screen.findByText('Odd one')).toBeInTheDocument()
  })
})
