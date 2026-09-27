// ui/src/__tests__/VoiceInterviewPortrait.test.tsx
//
// The interviewer's face, and the address the browser would actually fetch for it.
//
// Finding 1 of the 17 September live interview: the participant met an empty circle where the
// interviewer should have been. `GET /api/interviews/{token}` answered
// `interviewer_image_url: '/agents/avery-singh.jpg'` - a path into `ui/public`, which Vite
// serves under the app's `/dashboard` base - so the `<img>` 404ed silently. **This is the
// fourth piece of work that trap has caught and the first to reach a participant.**
//
// Two things about how it is asserted here, and both are the reason it shipped:
//
//  - **The assertion is on the address, not on the field.** A test that read the server's
//    string back out of the DOM passes against exactly the defect - the string was correct and
//    unfetchable. So the bundled case is resolved and then checked against the **file on
//    disk**, in `ui/public`, which is the only thing that can distinguish "an address" from
//    "an address that answers".
//
//  - **Both arms, in both directions.** A resolver that prefixed everything would break the
//    project-override and promoted-default cases, which are already real addresses; one that
//    prefixed nothing is today's bug. Each case below has its opposite beside it.
import { existsSync } from 'node:fs'
import { join } from 'node:path'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, it, expect, afterEach, vi } from 'vitest'

import VoiceInterview, { interviewerPortraitSrc } from '../pages/VoiceInterview'
import { AGENT_AVATAR_IMAGE } from '../components/agentStatus'

/** The built-in portrait as the *server* holds it - `AGENT_IDENTITY.image`, unprefixed. */
const BUNDLED = '/agents/avery-singh.jpg'
/** A portrait uploaded onto this engagement. Already an address the deployment answers on. */
const PROJECT_OVERRIDE = '/projects/sp-gs-am/agents/stakeholder_interviewer/image'
/** The deployment's promoted default, served from its own door. Also already an address. */
const PROMOTED = '/api/agents/stakeholder_interviewer/image'

describe('the address the page fetches for the interviewer', () => {
  it('puts the app base back on a bundled portrait, and leaves a served one alone', () => {
    // Read off `import.meta.env` rather than written out, because the base is a build setting
    // and a test that hardcoded `/dashboard` would be asserting `vite.config.ts` rather than
    // the join. It is non-vacuous either way: under vitest it resolves to `/dashboard/` too,
    // so the mutation that prefixes nothing - which is today's bug - fails here.
    const base = import.meta.env.BASE_URL.replace(/\/+$/, '')
    expect(interviewerPortraitSrc(BUNDLED, 'bundled')).toBe(`${base}${BUNDLED}`)

    // The controls. Both are addresses the server already answers on and must arrive verbatim.
    expect(interviewerPortraitSrc(PROJECT_OVERRIDE, 'served')).toBe(PROJECT_OVERRIDE)
    expect(interviewerPortraitSrc(PROMOTED, 'served')).toBe(PROMOTED)
  })

  it('leaves the address alone when the server named no source', () => {
    // A response from a deployment that predates the field. Unchanged behaviour rather than a
    // guess: prefixing on an absence would break every served address the moment one arrived
    // without the label.
    expect(interviewerPortraitSrc(PROJECT_OVERRIDE, undefined)).toBe(PROJECT_OVERRIDE)
  })

  it('answers nothing for an interviewer with no portrait, whatever the source says', () => {
    // A legitimate state - `AGENT_IDENTITY.image` is nullable - and it must stay falsy, because
    // that is what reaches the initials rather than an `<img src="">`, which resolves against
    // the current document and fetches the page itself.
    expect(interviewerPortraitSrc('', 'bundled')).toBe('')
    expect(interviewerPortraitSrc(undefined, 'served')).toBe('')
  })

  it('resolves a bundled portrait onto a file that is actually in the served directory', () => {
    // **The assertion the page could not make.** Everything above is about a string; this is
    // about whether anything answers it. `ui/public` is what Vite serves under the base, so a
    // resolved bundled address with the base stripped back off must name a file that exists -
    // and every one of the eighteen agents is checked, because the defect was found by reading
    // one agent's default and the next session could stamp any of them.
    const base = import.meta.env.BASE_URL.replace(/\/+$/, '')
    const drawn = Object.values(AGENT_AVATAR_IMAGE)
    expect(drawn.length).toBeGreaterThan(0)

    for (const withBase of drawn) {
      // `AGENT_AVATAR_IMAGE` is the front end's copy, already carrying the base; the server
      // hands over the same file without it. Strip, resolve, and look on disk.
      const asServerHoldsIt = withBase.slice(base.length)
      const resolved = interviewerPortraitSrc(asServerHoldsIt, 'bundled')
      expect(resolved).toBe(withBase)
      expect(existsSync(join(__dirname, '..', '..', 'public', asServerHoldsIt))).toBe(true)
    }
  })
})

// ---------------------------------------------------------------------------------------
// The page, driven. The resolver being right is not the same as the page using it.
// ---------------------------------------------------------------------------------------

const VOICE = { elevenlabs_voice_id: 'V', language: 'en', country_code: 'GB', model_id: 'm' }

const SESSION = {
  id: 1, stakeholder_id: 1, node_label: 'Order Fulfilment',
  session_token: 'tok', status: 'pending', voice_config: VOICE,
}

const SCRIPT = {
  script_id: 'SC-014', node_label: 'Order Fulfilment', level: 'L2',
  research_brief: '', study_objectives: [], welcome_message: 'Welcome.',
  sections: [{
    section_id: 'S1', title: 'Operations',
    questions: [{
      id: 'q1', text: 'Question one?', follow_up_count: 0,
      probing_instructions: '', follow_up_branches: [], evasion_signals: [],
    }],
  }],
  closing_message: 'Thank you.',
}

/**
 * Everything the interview loop reaches once it starts.
 *
 * Installed for every case rather than only the one that clicks Start: `cleanup()` unmounts the
 * page and **cannot stop the interview** - it is an async loop over closures - so a case that
 * starts one leaves it running through whatever stubs the next case installs. The recogniser
 * answers at once so the one-question script runs to its end inside the test that began it.
 */
function installTheRestOfTheInterview() {
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
        this.onerror?.({ error: 'no-speech' })
        this.onend?.()
      }, 0)
    }
    stop() { this.onend?.() }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = FakeRecognition
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).Audio = class {
    onended: (() => void) | null = null
    onerror: (() => void) | null = null
    play() { setTimeout(() => this.onended?.(), 0); return Promise.resolve() }
  }
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
}

function renderWithBranding(branding: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/interviews/tok')) {
      return new Response(
        JSON.stringify({
          session: SESSION, script: SCRIPT, branding, speech_policy: 'browser_permitted',
        }),
        { status: 200 },
      )
    }
    if (url.endsWith('/speak')) {
      return new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })
    }
    return new Response('{}', { status: 200 })
  }))
  installTheRestOfTheInterview()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      enumerateDevices: async () => [
        { kind: 'audioinput', deviceId: 'mic-1', label: 'Built-in Microphone' },
      ],
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    },
  })
  render(
    <MemoryRouter initialEntries={['/interview/tok']}>
      <Routes>
        <Route path="/interview/:sessionToken" element={<VoiceInterview />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('the face a participant meets', () => {
  it('draws a bundled portrait at an address under the app base', async () => {
    renderWithBranding({
      header_image_url: '', primary_color: '#0d9488', text_color: '#1f2937',
      interviewer_image_url: BUNDLED,
      interviewer_image_source: 'bundled',
      interviewer_name: 'Avery Singh',
      interviewer_tagline: '',
    })

    const base = import.meta.env.BASE_URL.replace(/\/+$/, '')
    const portrait = await screen.findByTestId('interviewer-portrait')
    // `getAttribute`, not `src`: jsdom resolves the property against the document origin, so
    // reading `.src` would compare an absolute URL and hide a missing base behind the host.
    expect(portrait.getAttribute('src')).toBe(`${base}${BUNDLED}`)
  })

  it('draws a served portrait exactly as the server handed it over', async () => {
    // The control. A page that prefixed unconditionally would break every engagement that has
    // uploaded a portrait, which is the repair turning into the same bug for other people.
    renderWithBranding({
      header_image_url: '', primary_color: '#0d9488', text_color: '#1f2937',
      interviewer_image_url: PROJECT_OVERRIDE,
      interviewer_image_source: 'served',
      interviewer_name: 'Avery Singh',
      interviewer_tagline: '',
    })

    const portrait = await screen.findByTestId('interviewer-portrait')
    expect(portrait.getAttribute('src')).toBe(PROJECT_OVERRIDE)
  })

  it('shows the interviewer initials rather than an empty circle when the portrait fails', async () => {
    // **The state that actually reached the participant.** A truthy address that 404s satisfies
    // every "is there a URL?" test, including `AgentAvatar`'s, so the fallback has to be keyed
    // on the load failing rather than on the field being absent.
    renderWithBranding({
      header_image_url: '', primary_color: '#0d9488', text_color: '#1f2937',
      interviewer_image_url: '/agents/nothing-here.jpg',
      interviewer_image_source: 'served',
      interviewer_name: 'Avery Singh',
      interviewer_tagline: '',
    })

    const portrait = await screen.findByTestId('interviewer-portrait')
    // jsdom does not load images, so the browser's failure is delivered by hand. The assertion
    // is about what the page does with it, which is the part the browser was not going to do.
    fireEvent.error(portrait)

    await waitFor(() => expect(screen.getByTestId('interviewer-initials')).toHaveTextContent('AS'))
    expect(screen.queryByTestId('interviewer-portrait')).toBeNull()
  })

  it('carries the resolved address onto the interviewing screen as well', async () => {
    // Two screens draw this face, and the ready screen alone was right in one place and wrong
    // in the other for the whole of sp62 - a screen looks correct from its first frame.
    renderWithBranding({
      header_image_url: '', primary_color: '#0d9488', text_color: '#1f2937',
      interviewer_image_url: BUNDLED,
      interviewer_image_source: 'bundled',
      interviewer_name: 'Avery Singh',
      interviewer_tagline: '',
    })

    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))

    const base = import.meta.env.BASE_URL.replace(/\/+$/, '')
    await waitFor(() => {
      expect(screen.getByTestId('interviewer-portrait').getAttribute('src'))
        .toBe(`${base}${BUNDLED}`)
    })

    // Settle the interview inside the test that started it. A completion arriving later is not
    // evidence about anything - and worse, it posts through the next case's `fetch` stub.
    await screen.findByText(/thank you/i, {}, { timeout: 5000 })
  })
})
