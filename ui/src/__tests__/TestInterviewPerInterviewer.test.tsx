// ui/src/__tests__/TestInterviewPerInterviewer.test.tsx
//
// The rehearsal dialog belongs to whichever interviewer it was opened for.
//
// It was Avery's in nine places - his photograph in five renders, his name spoken in the
// briefing and again in the speaker test, and his name written on the screen twice. Opening it
// for Laura without touching all nine would greet a consultant as Avery in Laura's voice, which
// is finding 1 of the interview walkthrough exactly: a voice and a face that disagree with the
// person named.
//
// **Every test here uses Laura, never Avery.** Avery is the default at every layer - the
// dialog's old `AVERY_HIRES` constant, and `TestSpeakRequest.agent_id`'s own default of
// `stakeholder_interviewer` - so a test driven with Avery passes against the very hardcoding
// this removes, and would have passed before the change as well as after it.
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import AgentAvatar from '../components/AgentAvatar'
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

const ANSWER = 'I am not sure really'

/** Every `/test/speak` body the dialog sent, in order. */
let speakBodies: Record<string, unknown>[] = []

function installFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/script')) return new Response(JSON.stringify(SCRIPT), { status: 200 })
    if (url.endsWith('/speak')) {
      speakBodies.push(JSON.parse(String(init?.body)))
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (url.endsWith('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: 'Which step, specifically?' }), { status: 200 })
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

/** Laura, with no portrait: the two variables this task moves, driven together. */
function renderDialog(
  props: { agentId: string; displayName: string; imageUrl?: string | null } = {
    agentId: 'second_interviewer',
    displayName: 'Laura Nelson',
  },
) {
  return render(
    <TestInterviewDialog
      slug="acme"
      onClose={() => {}}
      agentId={props.agentId}
      displayName={props.displayName}
      imageUrl={props.imageUrl ?? null}
    />,
  )
}

/**
 * Every face currently on the screen belongs to `name`, and there is at least one.
 *
 * The count is asserted because the loop is otherwise vacuous: a phase that drew no avatar at
 * all - or a selector that stopped matching - would satisfy every `for` body below it and
 * report the dialog as correct.
 */
function everyFaceBelongsTo(name: string, initials: string) {
  const faces = screen.getAllByTestId('agent-avatar')
  expect(faces.length).toBeGreaterThan(0)
  for (const face of faces) {
    const img = face.querySelector('img')
    if (img) {
      expect(img).toHaveAttribute('alt', name)
      expect(img.getAttribute('src') ?? '').not.toMatch(/avery/i)
    } else {
      expect(face).toHaveTextContent(initials)
    }
  }
  expect(screen.queryByText(/Avery/)).toBeNull()
}

describe('an agent with no portrait', () => {
  it("renders initials, never a broken image and never another agent's face", () => {
    render(<AgentAvatar name="Laura Nelson" imageUrl={null} />)
    expect(screen.getByText('LN')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('renders the portrait, named, when there is one', () => {
    // The control. Without it a component that rendered initials unconditionally - and drew no
    // face for anybody - would pass the test above.
    render(<AgentAvatar name="Avery Singh" imageUrl="/agents/avery-singh.jpg" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/agents/avery-singh.jpg')
    expect(screen.getByRole('img')).toHaveAttribute('alt', 'Avery Singh')
    expect(screen.queryByText('AS')).not.toBeInTheDocument()
  })

  it("treats a deliberately cleared portrait as no portrait, not as an empty src", () => {
    // `''` is a project saying "no face for this agent", and `<img src="">` refetches the
    // current document. `useAgentIdentity` keeps the value falsy for exactly this reason.
    render(<AgentAvatar name="Laura Nelson" imageUrl="" />)
    expect(screen.getByText('LN')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})

describe('the rehearsal dialog, opened for one interviewer', () => {
  beforeEach(() => {
    speakBodies = []
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', installFetch())
    installSpeechRecognition(ANSWER)
    installAudioAndMic()
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('greets you as the interviewer it was opened for, and speaks as them', async () => {
    // Asserted on what is SENT, not on what is rendered: the briefing is never printed on the
    // screen, it is posted to /test/speak and heard. A test asserting a rendered greeting would
    // be asserting a thing the product does not do.
    renderDialog()

    const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
    await userEvent.click(toBriefing)
    await screen.findByRole('button', { name: /start test interview/i })

    const briefing = speakBodies.map((b) => String(b.text)).find((t) => /I'm \w+ - and I'll be/.test(t))
    expect(briefing).toMatch(/I'm Laura/)
    expect(briefing).not.toMatch(/Avery/)
  })

  it("sends her own agent_id on every /test/speak, so she is not spoken in Avery's voice", async () => {
    // The server defaults `agent_id` to `stakeholder_interviewer`, so omitting it is not a
    // missing field - it is Laura rehearsing in Avery's configured voice, with a 200 and no
    // warning anywhere.
    renderDialog()

    const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
    await userEvent.click(toBriefing)
    const start = await screen.findByRole('button', { name: /start test interview/i })
    await userEvent.click(start)

    await screen.findByText(/test interview complete/i, undefined, { timeout: 5000 })

    expect(speakBodies.length).toBeGreaterThan(0)
    for (const body of speakBodies) {
      expect(body.agent_id).toBe('second_interviewer')
      // Still the project's, and still no voice of the dialog's own - the two properties
      // TestInterviewPressSlug.test.tsx established, restated here because this change rewrote
      // every one of these bodies.
      expect(body.slug).toBe('acme')
      expect(body.voice_id).toBeUndefined()
    }
  })

  it('names her on the screen wherever it used to name Avery', async () => {
    // Driven with her real portrait - she has had one since 7 September - so the `alt` on the
    // face is assertable alongside the written name. The no-portrait case is the test below.
    renderDialog({
      agentId: 'second_interviewer',
      displayName: 'Laura Nelson',
      imageUrl: '/agents/laura-nelson.jpg',
    })

    // The device-setup screen, then the interview itself, so the assertion is not left to one
    // render that might be the only one repaired.
    expect(await screen.findByAltText('Laura Nelson')).toBeInTheDocument()

    const toBriefing = await screen.findByRole('button', { name: /continue|start|begin/i })
    await userEvent.click(toBriefing)
    const start = await screen.findByRole('button', { name: /start test interview/i })
    await userEvent.click(start)

    expect(await screen.findByText('Laura Nelson')).toBeInTheDocument()
    expect(screen.queryByText(/Avery/)).not.toBeInTheDocument()
  })

  it('draws her initials rather than a stand-in face when she has no portrait', async () => {
    // The failure this replaces was not a blank square - `AVERY_HIRES` was a real file that
    // loaded, so Laura's rehearsal showed Avery's face and looked entirely correct.
    renderDialog()

    expect(await screen.findByText('LN')).toBeInTheDocument()
    for (const img of screen.queryAllByRole('img')) {
      expect(img.getAttribute('src') ?? '').not.toMatch(/avery/i)
    }
  })

  it('is hers at every stage of the rehearsal, not only the first', async () => {
    // The first version of this file asserted the device-setup screen alone, and mutating each
    // of the five renders back to Avery in turn is what exposed it: **four of the five passed
    // while hardcoded** - the ready screen, the interview itself, the completion header and
    // every transcript bubble. That is precisely the state the brief warns is worse than the
    // one it replaces, because a dialog that is Laura's in one place and Avery's in four looks
    // correct to whoever opens it on the screen that was repaired.
    renderDialog()

    // Setup.
    await screen.findByRole('button', { name: /continue|start|begin/i })
    everyFaceBelongsTo('Laura Nelson', 'LN')

    // Ready. `fireEvent`, not `userEvent`, so the briefing is still in flight when the next
    // assertion runs - "… is speaking" renders only while it is, and awaiting the click would
    // flush past the one state that shows it.
    fireEvent.click(screen.getByRole('button', { name: /continue|start|begin/i }))
    expect(await screen.findByText(/Laura is speaking/)).toBeInTheDocument()
    const start = await screen.findByRole('button', { name: /start test interview/i })
    everyFaceBelongsTo('Laura Nelson', 'LN')

    // Interviewing.
    await userEvent.click(start)
    await screen.findByText('Laura Nelson')
    everyFaceBelongsTo('Laura Nelson', 'LN')

    // Complete - the header, and one bubble for every exchange recorded.
    await screen.findByText(/test interview complete/i, undefined, { timeout: 5000 })
    everyFaceBelongsTo('Laura Nelson', 'LN')
    expect(screen.getAllByTestId('agent-avatar').length).toBeGreaterThan(1)
  })

  it('introduces herself in the speaker test too, not only in the briefing', async () => {
    // The sixth hardcoded line, and one the brief's count of six missed: "Hi there, I'm Avery.
    // Your audio is working perfectly." is spoken by a button on the device-setup screen,
    // before the briefing exists. Asserted on the body sent, because it is heard and never
    // written down.
    renderDialog()

    await userEvent.click(await screen.findByRole('button', { name: /play test audio/i }))

    const spoken = speakBodies.map((b) => String(b.text))
    expect(spoken.some((t) => /I'm Laura\./.test(t))).toBe(true)
    expect(spoken.every((t) => !/Avery/.test(t))).toBe(true)
  })

  it("draws the interviewer's own portrait when they have one", async () => {
    // The control for the test above, and the case that has to keep working: Avery has a
    // photograph, and the fallback must not have replaced it with initials for everybody.
    renderDialog({
      agentId: 'stakeholder_interviewer',
      displayName: 'Avery Singh',
      imageUrl: '/agents/avery-singh.jpg',
    })

    const face = await screen.findByAltText('Avery Singh')
    expect(face).toHaveAttribute('src', '/agents/avery-singh.jpg')
    expect(screen.queryByText('AS')).not.toBeInTheDocument()
  })
})
