import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { CrewApprovalRow } from '../components/CrewApprovalRow'

const onSubmit = vi.fn()
const onApprove = vi.fn()

function row(state: 'working' | 'ready' | 'committed', changeCount = 0) {
  return (
    <CrewApprovalRow
      crewName="discovery_mapping"
      state={state}
      changeCount={changeCount}
      onSubmit={onSubmit}
      onApprove={onApprove}
    />
  )
}

beforeEach(() => { onSubmit.mockReset(); onApprove.mockReset() })

describe('CrewApprovalRow', () => {
  it('offers the contributor a way to mark it ready while it is working', () => {
    render(row('working'))
    expect(screen.getByRole('button', { name: /ready for approval/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
  })

  it('offers the approver a way to approve once it is ready', () => {
    render(row('ready'))
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ready for approval/i })).not.toBeInTheDocument()
  })

  it('offers nothing once it is committed', () => {
    render(row('committed'))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('names the outstanding changes on the approve control', () => {
    render(row('ready', 3))
    expect(screen.getByRole('button', { name: /approve/i }).textContent).toContain('3')
  })

  it('does not mention changes on the approve control when there are none', () => {
    render(row('ready', 0))
    expect(screen.getByRole('button', { name: /approve/i }).textContent).not.toContain('0 change')
  })

  it('submits the crew it was given', async () => {
    render(row('working'))
    await userEvent.click(screen.getByRole('button', { name: /ready for approval/i }))
    expect(onSubmit).toHaveBeenCalledWith('discovery_mapping')
  })

  // onSubmit and onApprove reach different endpoints (submissions vs commits), so a
  // wiring mistake that swapped them - or called both - would leave the loop's two acts
  // indistinguishable from the outside. Asserting only that onApprove fired would still
  // pass under such a swap; asserting onSubmit did not is what catches it.
  it('approves the crew it was given, and does not also submit it', async () => {
    render(row('ready'))
    await userEvent.click(screen.getByRole('button', { name: /approve/i }))
    expect(onApprove).toHaveBeenCalledWith('discovery_mapping')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  // The busy-disable behaviour lives in CommitControl (its `busy` state), but it is
  // reached here through CrewApprovalRow's wiring, and that is what an approval-loop
  // regression would actually break - not CommitControl in isolation.
  it('cannot be double-clicked while a submission is in flight', async () => {
    let release: () => void = () => {}
    onSubmit.mockReturnValue(new Promise<void>((r) => { release = r }))
    render(row('working'))
    const button = screen.getByRole('button', { name: /ready for approval/i })
    await userEvent.click(button)
    expect(button).toBeDisabled()
    release()
  })
})
