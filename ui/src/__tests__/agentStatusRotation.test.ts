import { describe, it, expect } from 'vitest'

import { getIdleStatus, getRotatedIdleStatus } from '../components/agentStatus'

const KEYS = ['pam', 'discovery', 'value_design', 'architecture', 'delivery']

describe('getRotatedIdleStatus', () => {
  it('matches getIdleStatus when nothing has rotated yet', () => {
    for (const key of KEYS) {
      expect(getRotatedIdleStatus(key, 3, 0)).toBe(getIdleStatus(key, 3))
    }
  })

  it('never repeats an activity back to back - a repeat reads as a missed breath', () => {
    for (const key of KEYS) {
      for (let rotation = 1; rotation < 500; rotation++) {
        expect(getRotatedIdleStatus(key, 0, rotation)).not.toBe(
          getRotatedIdleStatus(key, 0, rotation - 1),
        )
      }
    }
  })

  it('works through every activity before revisiting one', () => {
    const seen = new Set<string>()
    for (let rotation = 0; rotation < 25; rotation++) {
      seen.add(getRotatedIdleStatus('pam', 0, rotation))
    }
    expect(seen.size).toBe(25)
  })

  it('gives different agents different activities from one shared counter', () => {
    const activities = KEYS.map((k) => getRotatedIdleStatus(k, 0, 7))
    expect(new Set(activities).size).toBeGreaterThan(1)
  })

  it('stays cheap at the rotation counts a long-open dashboard reaches', () => {
    // A board left open overnight reaches ~2,880 rotations. This must be constant
    // time - an implementation that walked the history would blow the stack here.
    expect(() => getRotatedIdleStatus('pam', 0, 100_000)).not.toThrow()
  })
})
