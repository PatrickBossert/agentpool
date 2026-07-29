import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CommitControl from '../components/CommitControl'

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
