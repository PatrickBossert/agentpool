import { describe, it, expect } from 'vitest'

import { crewStatusLabel } from '../components/agentStatus'

describe('crewStatusLabel', () => {
  it('says Ready when the crew is armed and resting', () => {
    expect(crewStatusLabel('idle', true)).toBe('Ready to run')
  })

  it('says nothing special when the crew is not ready', () => {
    expect(crewStatusLabel('idle', false)).toBeNull()
  })

  it('does not override a running crew', () => {
    expect(crewStatusLabel('running', true)).toBeNull()
  })

  it('does not override a failed crew - a fault outranks readiness', () => {
    expect(crewStatusLabel('failed', true)).toBeNull()
  })
})
