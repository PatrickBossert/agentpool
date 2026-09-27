// ui/src/__tests__/TestInterviewScriptChoice.test.tsx
//
// Choosing which script a rehearsal is conducted from.
//
// The owner is demonstrating this to a client who heads strategy and market development, and the
// one approved script on the live engagement is a van technician's interview. So the control
// offers the committed sample *or* any of the project's active scripts, with its review state
// shown, and the sample is what it opens on.
//
// **Every assertion here is on what the rehearsal is driven with, never on what the dropdown
// renders.** CLAUDE.md records a radio tested as *rendered* and not as *sent*, and this control
// has exactly those two layers: an option can be selected, highlighted and displayed while the
// dialog goes on fetching the default, and the screen looks completely correct. So the tests read
// the request URL the dialog issued, and - one layer further in, because a URL is a promise -
// the question text that is then put to the interviewee and posted to `/test/speak`.
//
// `TestInterviewDialog` is deliberately **not** mocked. `AgentConfigSection.test.tsx` stubs it to
// record its props, which is right for that file's subject and is one layer short of this one's:
// a prop correctly passed to a dialog that ignores it is the defect this file exists to catch.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import AgentConfigSection from '../components/tabs/AgentConfigSection'
import { agentConfigApi } from '../api/agentConfig'
import { projectsApi } from '../api/endpoints'
import { rehearsalApi } from '../api/rehearsal'
import type { AgentConfig } from '../api/agentConfig'

vi.mock('../api/agentConfig', () => ({
  agentConfigApi: { get: vi.fn(), getAll: vi.fn(), put: vi.fn(), uploadImage: vi.fn() },
}))
vi.mock('../api/endpoints', () => ({ projectsApi: { getMyPermissions: vi.fn() } }))
vi.mock('../api/rehearsal', async (importOriginal) => {
  // The sentinel is imported from the real module rather than restated, so a test cannot agree
  // with itself about what "no choice" is spelled as while the product spells it otherwise.
  const actual = await importOriginal<typeof import('../api/rehearsal')>()
  return { ...actual, rehearsalApi: { options: vi.fn() } }
})
vi.mock('../api/voices', () => ({
  voicesApi: { list: vi.fn().mockResolvedValue({ account: [], library: [] }) },
}))
vi.mock('../components/tabs/VoicePicker', () => ({ default: () => null }))

const DEFAULTS = {
  display_name: 'Avery Singh',
  image_url: '/agents/avery-singh.jpg',
  voice_id: 'default-voice-id',
  language: 'en',
  country_code: 'GB',
  model_id: 'eleven_turbo_v2',
}

const NO_OVERRIDES = {
  display_name: null, image_url: null, voice_id: null,
  language: null, country_code: null, model_id: null,
}

function config(): AgentConfig {
  return {
    agent_id: 'stakeholder_interviewer',
    configured: false,
    defaults: DEFAULTS,
    overrides: NO_OVERRIDES,
    resolved: DEFAULTS,
    is_interviewer: true,
    promoted_default_image_url: null,
  }
}

// The scripts the door offers. Two of them, because "the chosen one is served" is only a real
// claim when there was something else to choose - and their questions are distinct so the
// assertion can name which interview actually ran.
// The two node ids are deliberately unalike: `1.2.2` is an L3 activity and `1.F` is an L1
// role node, so an assertion on one cannot pass by matching the other, and neither is a
// substring of a script id.
const OFFERED = [
  {
    script_id: 'SC-005',
    node_id: '1.2.2',
    node_label: 'Portfolio Optimisation and Investment Planning',
    review_status: 'pending',
  },
  {
    script_id: 'SC-014',
    node_id: '1.F',
    node_label: 'ISS Property FM Technicians - Frontline',
    review_status: 'approved',
  },
]

const QUESTION_OF: Record<string, string> = {
  SC_DEFAULT: 'What does the sample script ask?',
  'SC-005': 'How is investment prioritised across the portfolio?',
  'SC-014': 'How do you receive your jobs each morning?',
}

function scriptBody(question: string, label: string) {
  return {
    node_label: label,
    study_objectives: [],
    welcome_message: `Welcome to ${label}.`,
    closing_message: `Thank you, that was ${label}.`,
    sections: [
      {
        title: 'Only Section',
        questions: [
          {
            id: 'Q1',
            text: question,
            follow_up_count: 0,
            probing_instructions: 'Probe.',
            follow_up_branches: [],
            evasion_signals: [],
          },
        ],
      },
    ],
  }
}

/** Every URL the dialog asked for a script with, in order. */
let scriptRequests: string[] = []
/** Every `/test/speak` body, so the question actually put to the interviewee is readable. */
let speakBodies: Record<string, unknown>[] = []

function installFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const href = String(url)
    if (href.includes('/test/script')) {
      scriptRequests.push(href)
      const id = new URL(href, 'http://test').searchParams.get('script_id') ?? ''
      const key = id || 'SC_DEFAULT'
      const label = id ? (OFFERED.find((o) => o.script_id === id)?.node_label ?? id) : 'Sample'
      return new Response(JSON.stringify(scriptBody(QUESTION_OF[key], label)), { status: 200 })
    }
    if (href.includes('/speak')) {
      speakBodies.push(JSON.parse(String(init?.body)))
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    if (href.includes('/elaboration-press')) {
      return new Response(JSON.stringify({ press_text: 'Which one?' }), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  })
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
  // Copied verbatim from `TestInterviewPerInterviewer.test.tsx`'s fake rather than simplified.
  // CLAUDE.md records this branch being bitten twice by a fake more forgiving than the real
  // thing, so the safe direction is the one already reviewed - and the duplication is recorded as
  // a follow-up rather than repaired here, because extracting it means editing two passing files.
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

function installSpeechRecognition() {
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
          results: [Object.assign([{ transcript: 'An answer.' }], { isFinal: true })],
        })
        this.onend?.()
      }, 0)
    }
    stop() { this.onend?.() }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).webkitSpeechRecognition = FakeRecognition
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentConfigSection slug="acme" agentName="Stakeholder Interviewer" />
    </QueryClientProvider>,
  )
}

const chooser = () => screen.getByTestId('rehearsal-script-choice') as HTMLSelectElement
const rehearseButton = () => screen.getByRole('button', { name: /test interview/i })

async function openRehearsal() {
  await userEvent.click(rehearseButton())
  // The device-setup screen is the dialog's first phase, and it renders only once the script has
  // been fetched - so awaiting it is what makes the request assertions below non-racy.
  await screen.findByRole('button', { name: /continue|start|begin/i })
}

/**
 * Walk the dialog's remaining phases until it is actually interviewing.
 *
 * Three phases, not one: setup, then the briefing, then the interview. The interviewer's questions
 * are only posted to `/test/speak` in the third, so a test that stopped at the first would be
 * asserting about a script that had been fetched and never conducted.
 */
async function conductRehearsal() {
  await userEvent.click(screen.getByRole('button', { name: /continue|start|begin/i }))
  await userEvent.click(await screen.findByRole('button', { name: /start test interview/i }))
}

describe('choosing the script a rehearsal is conducted from', () => {
  beforeEach(() => {
    scriptRequests = []
    speakBodies = []
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({ agents: [] } as never)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_administer_project: true,
    } as never)
    vi.mocked(rehearsalApi.options).mockResolvedValue(OFFERED)
    vi.stubGlobal('fetch', installFetch())
    installAudioAndMic()
    installSpeechRecognition()
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

  it('offers the sample first and selected, so it works before Maya has run', async () => {
    renderSection()
    await waitFor(() => expect(chooser()).toBeInTheDocument())
    await waitFor(() => expect(chooser().options.length).toBe(OFFERED.length + 1))

    // First, and the selected one. Both, because a sample that is present but not selected puts
    // a fresh engagement on somebody else's script by default.
    expect(chooser().options[0]).toHaveTextContent(/sample script/i)
    expect(chooser().value).toBe('')
  })

  it('names each script by both ids, its description, and the review state', async () => {
    /**
     * The whole label, asserted exactly. This test earned its keep the day the node id was
     * added: it failed on the character, which is what an exact label assertion is for - a
     * `toContain('SC-005')` would have passed a label that had silently lost half its content.
     */
    renderSection()
    await waitFor(() => expect(chooser().options.length).toBe(OFFERED.length + 1))

    const labels = [...chooser().options].map((o) => o.textContent ?? '')
    expect(labels).toContain(
      '1.2.2 \u00b7 SC-005 - Portfolio Optimisation and Investment Planning (pending)',
    )
    expect(labels).toContain(
      '1.F \u00b7 SC-014 - ISS Property FM Technicians - Frontline (approved)',
    )
  })

  it('does not restrict the list to approved scripts', async () => {
    // The decision, asserted rather than left to the server. The one approved script on the live
    // engagement is a van technician's interview and every script suiting tomorrow's audience is
    // `pending`, so an approved-only list would have offered exactly the wrong one.
    renderSection()
    await waitFor(() => expect(chooser().options.length).toBe(OFFERED.length + 1))

    expect([...chooser().options].map((o) => o.value)).toContain('SC-005')
  })

  it('rehearses the chosen script - asserted on the request, and on the question asked', async () => {
    renderSection()
    await waitFor(() => expect(chooser().options.length).toBe(OFFERED.length + 1))

    await userEvent.selectOptions(chooser(), 'SC-005')
    await openRehearsal()

    // 1. What was asked for.
    expect(scriptRequests).toHaveLength(1)
    const asked = new URL(scriptRequests[0], 'http://test')
    expect(asked.searchParams.get('script_id')).toBe('SC-005')
    expect(asked.searchParams.get('slug')).toBe('acme')

    // 2. What the rehearsal then actually asks. A URL is a promise that something answers, and
    // the dialog could request SC-005 and conduct anything; this is the half a request assertion
    // cannot reach.
    await conductRehearsal()
    await waitFor(() =>
      expect(speakBodies.map((b) => String(b.text)).join('\n'))
        .toContain(QUESTION_OF['SC-005']),
    )
    expect(speakBodies.map((b) => String(b.text)).join('\n'))
      .not.toContain(QUESTION_OF['SC-014'])
  })

  it('rehearses the sample when no choice is made, and sends no script_id at all', async () => {
    // The control, and the arm every caller before the dropdown existed took. Without it the test
    // above passes against a dialog that always sends whatever the select holds - including a
    // dialog that cannot express "the sample" and sends an empty id the server reads as a miss.
    renderSection()
    await waitFor(() => expect(chooser().options.length).toBe(OFFERED.length + 1))

    await openRehearsal()

    expect(scriptRequests).toHaveLength(1)
    const asked = new URL(scriptRequests[0], 'http://test')
    expect(asked.searchParams.has('script_id')).toBe(false)
    expect(asked.searchParams.get('slug')).toBe('acme')

    await conductRehearsal()
    await waitFor(() =>
      expect(speakBodies.map((b) => String(b.text)).join('\n'))
        .toContain(QUESTION_OF.SC_DEFAULT),
    )
  })

  it('still offers the sample when the project has no scripts of its own', async () => {
    vi.mocked(rehearsalApi.options).mockResolvedValue([])
    renderSection()
    await waitFor(() => expect(chooser()).toBeInTheDocument())

    expect(chooser().options).toHaveLength(1)
    expect(chooser().options[0]).toHaveTextContent(/sample script/i)

    await openRehearsal()
    const asked = new URL(scriptRequests[0], 'http://test')
    expect(asked.searchParams.has('script_id')).toBe(false)
  })

  it('says so, and keeps the sample, when the list cannot be loaded', async () => {
    // Not fatal: the rehearsal still works on the sample. A silent empty dropdown would read as
    // "this engagement has no scripts", which is a different and wrong diagnosis.
    vi.mocked(rehearsalApi.options).mockRejectedValue(new Error('door refused'))
    renderSection()

    expect(await screen.findByText(/could not be listed/i)).toBeInTheDocument()
    expect(chooser().options).toHaveLength(1)
    await openRehearsal()
    expect(scriptRequests).toHaveLength(1)
  })
})

// ── The value chain id is shown beside the script id ─────────────────────────

describe('the option names the chain as well as the script', () => {
  beforeEach(() => {
    vi.mocked(agentConfigApi.get).mockResolvedValue(config())
    vi.mocked(agentConfigApi.getAll).mockResolvedValue({ agents: [] } as never)
    vi.mocked(projectsApi.getMyPermissions).mockResolvedValue({
      can_administer_project: true,
    } as never)
    vi.mocked(rehearsalApi.options).mockResolvedValue(OFFERED)
    vi.stubGlobal('fetch', installFetch())
    installAudioAndMic()
    installSpeechRecognition()
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

  it('shows the node id, and shows it before the script id', async () => {
    /**
     * The owner asked for this because `SC-006` says only that it was the sixth script
     * written, while `1.F` says frontline and `0.A` says audit - and a consultant choosing a
     * rehearsal for a particular audience recognises the engagement by its chain.
     *
     * It also brings this control into line with the rest of the product: CLAUDE.md records
     * that a script is shown by its value chain node id, which is how `ScriptReviewRow`
     * labels the approver's view. This dropdown was the one place showing the identity and
     * not the address.
     *
     * Asserted on the **order** rather than on presence, because a label carrying both in the
     * wrong order would satisfy a substring check while burying the thing that was asked for.
     */
    renderSection()
    await waitFor(() => expect(chooser()).toBeInTheDocument())
    const option = await screen.findByRole('option', { name: /Portfolio Optimisation/ })
    expect(option.textContent).toContain('1.2.2')
    expect(option.textContent).toContain('SC-005')
    expect(option.textContent!.indexOf('1.2.2')).toBeLessThan(
      option.textContent!.indexOf('SC-005'),
    )
  })

  it('offers the default without a node id, and does not render a stray separator', async () => {
    /** The control. The committed default belongs to no engagement and has no chain address;
     *  a label reading "· Sample script" would be the separator surviving a missing id. */
    renderSection()
    await waitFor(() => expect(chooser()).toBeInTheDocument())
    const fallback = await screen.findByRole('option', { name: /Sample script/ })
    expect(fallback.textContent).not.toContain('·')
  })
})
