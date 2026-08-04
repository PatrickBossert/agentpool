// ui/src/__tests__/VoiceInterviewCapture.test.tsx
// An answer that cannot name its question cannot be cited, grouped, or counted. qa_pairs
// carried question text alone, and mixed scripted questions with generated probes,
// pre-scripted branches, and the synthesis block without distinguishing any of them.
import { describe, it, expect } from 'vitest'

import { capturedPair } from '../pages/VoiceInterview'

describe('capturedPair', () => {
  it('gives a scripted question its own id', () => {
    expect(capturedPair('SC-014', 'S3', 2, 'Q?', 'A.')).toEqual({
      question_id: 'SC-014.S3.Q2', question: 'Q?', answer: 'A.', follow_up: 0,
    })
  })

  it('gives a generated probe its parent id with a suffix', () => {
    // A probe is more evidence about one question, not a new one. Its own id would make an
    // interviewee pressed three times read as three questions covered.
    expect(capturedPair('SC-014', 'S3', 2, 'Say more?', 'B.', { kind: 'F', index: 1 }))
      .toEqual({
        question_id: 'SC-014.S3.Q2.F1', question: 'Say more?', answer: 'B.', follow_up: 1,
      })
  })

  it('gives a pre-scripted branch its parent id with a different suffix', () => {
    // Distinguished from a generated probe because one is Maya's design and the other is
    // the interviewer improvising - a reader auditing the instrument needs to tell them apart.
    expect(capturedPair('SC-014', 'S3', 2, 'And?', 'C.', { kind: 'B', index: 2 }))
      .toEqual({
        question_id: 'SC-014.S3.Q2.B2', question: 'And?', answer: 'C.', follow_up: 1,
      })
  })

  it('gives a section-level prompt the section id alone', () => {
    expect(capturedPair('SC-014', 'S3', null, 'Anything missed?', 'D.')).toEqual({
      question_id: 'SC-014.S3', question: 'Anything missed?', answer: 'D.', follow_up: 0,
    })
  })

  it('keeps the five synthesis prompts distinct', () => {
    // They sit after every section and are not questions of any one of them. Giving them a
    // shared pseudo-section id alone would collide all five onto one address.
    const ids = [1, 2, 3, 4, 5].map(n => capturedPair('SC-014', 'SYNTH', n, 'q', 'a').question_id)
    expect(new Set(ids).size).toBe(5)
    expect(ids[0]).toBe('SC-014.SYNTH.Q1')
  })

  it('does not collide across two scripts at the same level', () => {
    // The property the old section-relative Q1.1 scheme lacked: every L2 script emitted it.
    const a = capturedPair('SC-001', 'S1', 1, 'q', 'a').question_id
    const b = capturedPair('SC-002', 'S1', 1, 'q', 'a').question_id
    expect(a).not.toBe(b)
  })
})
