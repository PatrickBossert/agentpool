// ui/src/__tests__/TestInterviewEmptyPress.test.tsx
//
// The same defect as VoiceInterviewEmptyPress.test.tsx, in the operator's smoke-test dialog.
// It shares the interview loop's shape but not its code, so fixing one leaves the other
// speaking an empty press: setting the on-screen question to "", playing nothing, then
// listening - and recording an exchange whose question is blank.
//
// Driven through the rendered dialog for the same reason: the bug lived in the branch that
// consumed the press, not in the fetch that returned it.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import TestInterviewDialog from '../components/tabs/TestInterviewDialog'

const SCRIPT = {
  node_label: 'Order Fulfilment',
  study_objectives: [],
  welcome_message: 'Welcome to the test.',
  closing_message: 'Thanks for testing.',
  sections: [
    {
      title: 'Operations',
      questions: [
        {
          id: 'q1',
          text: 'What slows fulfilment down?',
          follow_up_count: 0,
          probing_instructions: 'Ask for specifics.',
          follow_up_branches: [],
          evasion_signals: ['not sure'],
        },
      ],
    },
  ],
}

const EVASIVE_ANSWER = 'I am not sure really'

let spoken: string[] = []

function installFetch(pressText: unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/script')) {
      return new Response(JSON.stringify(SCRIPT), { status: 200 })
    }
    if (url.endsWith('/speak')) {
      spoken.push(JSON.parse(String(init?.body)).text)
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: pressText }), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
}

function installSpeechRecognition(transcript: string) {
  class FakeRecognition {
    continuous = false
    interimResults = false
    lang = ''
    onresult: ((e: unknown) => void) | null = null
    onend: (() => void) | null = null
    onerror: ((e: { error: string }) => void) | null = null

    start() {
      setTimeout(() => {
        this.onresult?.({
          resultIndex: 0,
          results: [Object.assign([{ transcript }], { isFinal: true })],
        })
        // 'no-speech' clears the dialog's recogniser ref, which is what stops onend
        // restarting it - the same handshake the real browser performs on a quiet mic.
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }

    stop() {
      this.onend?.()
    }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).webkitSpeechRecognition = FakeRecognition
}

function installAudioAndMic() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    pause() {}
    play() {
      setTimeout(() => this.onended?.(), 0)
      return Promise.resolve()
    }
  }
  // The dialog's spoken briefing runs through Web Audio so it keeps the user gesture.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).AudioContext = class {
    destination = {}
    async decodeAudioData() { return {} }
    createBufferSource() {
      return {
        buffer: null,
        connect() {},
        onended: null as null | (() => void),
        start(this: { onended: null | (() => void) }) { setTimeout(() => this.onended?.(), 0) },
      }
    }
    createAnalyser() {
      return { fftSize: 0, frequencyBinCount: 8, getByteFrequencyData() {} }
    }
    createMediaStreamSource() { return { connect() {} } }
    async close() {}
  }
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
        { kind: 'audiooutput', deviceId: 'spk-1', label: 'Built-in Output' },
      ],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
}

async function runDialogWithPress(pressText: unknown) {
  spoken = []
  vi.stubGlobal('fetch', installFetch(pressText))
  installSpeechRecognition(EVASIVE_ANSWER)
  installAudioAndMic()

  render(<TestInterviewDialog slug="smoke" onClose={() => {}} />)

  const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
  await userEvent.click(toBriefing)

  const start = await screen.findByRole('button', { name: /start test interview/i })
  await userEvent.click(start)

  await screen.findByText(/test interview complete/i, undefined, { timeout: 5000 })
}

describe('the smoke-test dialog and an empty elaboration press', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('neither speaks it nor records a blank exchange', async () => {
    await runDialogWithPress('')
    expect(spoken).not.toContain('')
    // Avery's spoken briefing is the first utterance and belongs to the ready screen, not
    // to the interview, so the loop's own utterances are taken from after it.
    expect(spoken.slice(1)).toEqual([
      'Welcome to the test.', 'What slows fulfilment down?', 'Thanks for testing.',
    ])
    await waitFor(() => expect(screen.getByText(/exchange.* recorded/i)).toBeInTheDocument())
    expect(screen.getByText(/1 exchange recorded/i)).toBeInTheDocument()
  })

  it('still presses when the press is a real one', async () => {
    await runDialogWithPress('Which step, specifically?')
    expect(spoken).toContain('Which step, specifically?')
    expect(screen.getByText('Which step, specifically?')).toBeInTheDocument()
  })
})
