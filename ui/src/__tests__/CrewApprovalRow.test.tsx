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

  it('submits the crew it was given', async () => {
    render(row('working'))
    await userEvent.click(screen.getByRole('button', { name: /ready for approval/i }))
    expect(onSubmit).toHaveBeenCalledWith('discovery_mapping')
  })
})
