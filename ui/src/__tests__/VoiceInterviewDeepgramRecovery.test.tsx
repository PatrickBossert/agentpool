// ui/src/__tests__/VoiceInterviewDeepgramRecovery.test.tsx
//
// Whether Deepgram is asked again after a socket has dropped, and when it stops being asked.
//
// **A file of its own, and that is the point rather than an accident of tidying.** Both
// assertions here count the sockets an interview opens across more than one question, and
// counting sockets is only sound where no other interview is running. `cleanup()` unmounts the
// page but cannot stop one - the interview is an async loop over closures, which this file's
// sibling says in its own `afterEach` - so a previous test's interview goes on listening, opens
// sockets of its own, and fetches its grants from whatever `fetch` stub is installed *now*.
// Neither the socket's index nor the grant it carries can tell those apart from this test's.
//
// That is measured, not feared. Written inside VoiceInterviewKeyterms.test.tsx, "one drop
// latches Deepgram off for the rest of the interview" **survived the mutation that reintroduces
// it** - a stray socket satisfied the assertion - and the same test failed immediately when run
// alone with `-t`. Vitest isolates files, so a file is the unit of isolation available.
import { cleanup, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  FakeSocket,
  SCRIPT_THREE_QUESTIONS,
  SCRIPT_TWO_QUESTIONS,
  completionPosted,
  forgetCompletion,
  installAudioAndMic,
  installFetch,
  installSpeechRecognition,
  installStreaming,
  socketAt,
  startInterview,
} from './support/voiceInterviewFakes'

const OUR_KEYTERMS = ['Renewals CapEx Allocation', 'Iberdrola', 'SP Energy Networks']

describe('asking Deepgram again after a drop', () => {
  beforeEach(() => {
    forgetCompletion()
    vi.restoreAllMocks()
    installAudioAndMic()
  })
  afterEach(() => {
    // Unmount before touching globals, and never restore the real `fetch` - the same reason the
    // sibling file gives: a late `speakText` from an interview that outlived its assertion
    // cannot parse a relative URL in Node.
    cleanup()
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 200 }))
  })

  it('asks Deepgram again on the next question after a single drop', async () => {
    // `deepgramOffRef` used to be latched by the first mid-answer drop, so one transient blip
    // condemned every later answer to a recogniser that has never heard of the client - which
    // is the thing this whole branch exists to fix. Asserted on a **second socket being
    // opened**, which is the only evidence there is that it was asked again.
    installStreaming()
    installSpeechRecognition('and the rest of the sentence.')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }, SCRIPT_TWO_QUESTIONS))

    await startInterview()
    ;(await socketAt(0)).drop()

    const second = await socketAt(1)
    // And it is still the configured socket, not a bare reconnection: the vocabulary is the
    // whole reason asking again is worth anything.
    expect(new URL(second.url).searchParams.getAll('keyterm')).toEqual(OUR_KEYTERMS)
  }, 20000)

  it('stops asking once two sockets have dropped', async () => {
    // The control, and the reason the switch is counted rather than deleted. A deployment whose
    // Deepgram keeps going away must not put the amber notice in front of the participant on
    // every question for the rest of the hour - two is a bad connection, not a bad moment.
    installStreaming()
    installSpeechRecognition('and the rest of the sentence.')
    vi.stubGlobal('fetch', installFetch({
      token: 'jwt', listen_params: { model: 'nova-3', keyterm: OUR_KEYTERMS },
    }, SCRIPT_THREE_QUESTIONS))

    await startInterview()
    ;(await socketAt(0)).drop()
    ;(await socketAt(1)).drop()

    await waitFor(() => expect(completionPosted()).not.toBeNull(), { timeout: 15000 })
    // Three questions and a spoken section rating, two sockets: nothing asked after the second
    // drop.
    expect(FakeSocket.opened).toHaveLength(2)
  }, 20000)
})
