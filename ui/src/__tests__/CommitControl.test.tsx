// ui/src/__tests__/CommitControl.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'
import CommitControl from '../components/CommitControl'

function axiosError(status: number, detail?: string) {
  return new AxiosError(
    'Request failed',
    String(status),
    { headers: new AxiosHeaders() },
    {},
    {
      status,
      statusText: '',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data: detail ? { detail } : {},
    },
  )
}

describe('CommitControl', () => {
  // A rejection used to be console.error'd only - the button just re-enabled itself
  // with no sign anything went wrong, so an approver would click it again and get
  // the same silent failure. It must now say something, next to the control.
  it('surfaces a 409 from the mid-run guard inline', async () => {
    const onCommit = vi.fn().mockRejectedValue(axiosError(409, 'A crew run is in progress.'))
    render(<CommitControl crewName="discovery" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button'))
    expect(await screen.findByRole('alert')).toHaveTextContent('A crew run is in progress.')
  })

  it('surfaces a 403 from the permission rule inline', async () => {
    const onCommit = vi.fn().mockRejectedValue(axiosError(403, 'Only an approver may commit this crew’s output'))
    render(<CommitControl crewName="discovery" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/only an approver/i)
  })

  it('shows nothing extra, and no stale error, on a successful commit', async () => {
    const onCommit = vi.fn().mockResolvedValue(undefined)
    render(<CommitControl crewName="discovery" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears a previous failure once a retry succeeds', async () => {
    const onCommit = vi.fn()
      .mockRejectedValueOnce(axiosError(409, 'A crew run is in progress.'))
      .mockResolvedValueOnce(undefined)
    render(<CommitControl crewName="discovery" changeCount={0} onCommit={onCommit} />)
    await userEvent.click(screen.getByRole('button'))
    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
