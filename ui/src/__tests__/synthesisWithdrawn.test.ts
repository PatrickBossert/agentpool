// ui/src/__tests__/synthesisWithdrawn.test.ts
//
// Synthesis was withdrawn from the interview flow on 4 September 2026, after the first
// completed interview. Two scripted blocks pre-supposed the conversation: `synthesis_prompt`
// summarised what the participant had said before they said it, and `portfolio_options`
// offered three sequencing choices to somebody who had already ruled two of them out.
//
// The code is commented rather than deleted, on instruction, so nothing prevents it being
// uncommented by somebody who does not know why it went. This is that guard.
//
// It is a SOURCE WALK, and its limits are real. It cannot see: a re-implementation under a
// different name, the fields being spoken from another component, or a restoration that is
// deliberate and reviewed - which is the point, since restoring needs the Maya-side change
// too. It asserts that these four fields are not read into the spoken flow HERE.
//
// `peer_referral` is deliberately absent from the list: it survives, because it asks a
// question rather than asserting a conclusion.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SOURCE = join(process.cwd(), 'src', 'pages', 'VoiceInterview.tsx')

const WITHDRAWN = [
  'synthesis_prompt',
  'forward_roadmap',
  'portfolio_options',
  'sponsorship_check',
] as const

/** Lines with the comment marker stripped, so a commented-out call is not a live one. */
function liveLines(src: string): string[] {
  return src
    .split('\n')
    .filter(l => !l.trimStart().startsWith('//'))
}

describe('the withdrawn synthesis stays withdrawn', () => {
  it('speaks none of the four withdrawn fields', () => {
    const live = liveLines(readFileSync(SOURCE, 'utf8'))
    const spoken = WITHDRAWN.filter(field =>
      live.some(l => l.includes(`sc.${field}`) || l.includes(`synthesis_check.${field}`)),
    )
    expect(spoken).toEqual([])
  })

  it('still speaks peer referral, so this is not passing by deleting the block', () => {
    // The control. Without it, removing the whole synthesis_check branch - including the
    // question we chose to keep - would satisfy the assertion above.
    const live = liveLines(readFileSync(SOURCE, 'utf8'))
    expect(live.some(l => l.includes('sc.peer_referral'))).toBe(true)
  })
})
