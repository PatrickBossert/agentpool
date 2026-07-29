import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import CommitControl from '../components/CommitControl'
import { CommitRow } from '../components/ReviewQueue'
import { commitsApi } from '../api/endpoints'

vi.mock('../api/endpoints', () => ({
  commitsApi: {
    changeCount: vi.fn(),
  },
}))

const onCommit = vi.fn()

beforeEach(() => onCommit.mockReset())

describe('CommitControl', () => {
  it('names how many changes it is committing over', () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={3} onCommit={onCommit} />)
    expect(screen.getByRole('button', { name: /commit/i }).textContent).toContain('3')
  })

  it('does not mention changes when there are none', () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    expect(screen.getByRole('button', { name: /commit/i }).textContent).not.toContain('0 change')
  })

  it('commits the crew it was given', async () => {
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button', { name: /commit/i }))
    expect(onCommit).toHaveBeenCalledWith('discovery_mapping')
  })

  it('cannot be clicked twice while a commit is in flight', async () => {
    let release: () => void = () => {}
    onCommit.mockReturnValue(new Promise<void>((r) => { release = r }))
    render(<CommitControl crewName="discovery_mapping" changeCount={0} onCommit={onCommit} />)
    const button = screen.getByRole('button', { name: /commit/i })
    await userEvent.click(button)
    expect(button).toBeDisabled()
    release()
  })
})

// CommitRow decides, from its own change-count query, whether a crew needs a row at
// all - a crew can be committed more than once (the backend has no uniqueness
// constraint on approval_commits), so "already committed" must not permanently hide a
// crew that has produced new outputs since. Tested directly against CommitRow rather
// than through ReviewQueue: ReviewQueue also needs readiness and committed-crews
// queries wired up just to reach this decision, which would only obscure what is
// actually under test here.
function renderRow(props: { crew: string; committed: boolean }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CommitRow slug="acme-rail" crew={props.crew} committed={props.committed} onCommit={onCommit} />
    </QueryClientProvider>,
  )
}

describe('CommitRow', () => {
  beforeEach(() => {
    vi.mocked(commitsApi.changeCount).mockReset()
  })

  it('renders for a crew that has never been committed', async () => {
    vi.mocked(commitsApi.changeCount).mockResolvedValue(0)
    renderRow({ crew: 'discovery_mapping', committed: false })
    expect(await screen.findByRole('button', { name: /commit/i })).toBeInTheDocument()
  })

  it('renders for a committed crew that has accumulated new changes', async () => {
    vi.mocked(commitsApi.changeCount).mockResolvedValue(2)
    renderRow({ crew: 'discovery_mapping', committed: true })
    const button = await screen.findByRole('button', { name: /commit/i })
    expect(button.textContent).toContain('2')
  })

  it('renders nothing for a committed crew with no changes since its last commit', async () => {
    vi.mocked(commitsApi.changeCount).mockResolvedValue(0)
    const { container } = renderRow({ crew: 'discovery_mapping', committed: true })
    await waitFor(() => expect(commitsApi.changeCount).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
