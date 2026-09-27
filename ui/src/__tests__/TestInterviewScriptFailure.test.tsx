// ui/src/__tests__/TestInterviewScriptFailure.test.tsx
//
// What a consultant is told when the rehearsal script will not load.
//
// The dialog composed the sentence itself: any 404 rendered `'Smoke-test script not found -
// run discovery_mapping on the smoke-test project first.'`. That outlived the project it named.
// `smoke-test` was archived on the owner's instruction, the door began answering 404, and the
// dialog sent whoever read it to run a crew on a project that no longer existed - advice that
// could not be followed, about a cause that was not the cause.
//
// A message assembled on this side cannot go stale gracefully, because nothing on this side
// knows why the door refused. So the server's `detail` is rendered, and the test drives both
// arms: a refusal that carries one, and a refusal that carries nothing at all.
import { render, screen } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import TestInterviewDialog from '../components/tabs/TestInterviewDialog'

function installFetch(scriptResponse: () => Response) {
  return vi.fn(async (url: string) => {
    if (String(url).includes('/script')) return scriptResponse()
    return new Response('{}', { status: 200 })
  })
}

function renderDialog() {
  return render(
    <TestInterviewDialog
      slug="acme"
      onClose={() => {}}
      agentId="second_interviewer"
      displayName="Laura Nelson"
      imageUrl={null}
    />,
  )
}

describe('a rehearsal script that will not load', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("shows the server's own reason, not a sentence about a project that was deleted", async () => {
    vi.stubGlobal(
      'fetch',
      installFetch(() =>
        new Response(
          JSON.stringify({
            detail: 'the committed rehearsal script could not be read: No such file',
          }),
          { status: 500 },
        ),
      ),
    )

    renderDialog()

    expect(await screen.findByText(/could not be read: No such file/)).toBeInTheDocument()
    // The stale copy, asserted absent by its two distinctive halves. Both, because the sentence
    // could be half-reintroduced - and `discovery_mapping` is the part that told somebody to do
    // something impossible.
    expect(screen.queryByText(/smoke-test/i)).toBeNull()
    expect(screen.queryByText(/discovery_mapping/)).toBeNull()
  })

  it('still says something useful when the refusal carries no body at all', async () => {
    // Every proxy error between the dashboard and the API is this shape. Without the fallback
    // the `await res.json()` throws inside the handler and the dialog reports a JSON parse
    // error, which is a true sentence about the wrong subject.
    vi.stubGlobal('fetch', installFetch(() => new Response('<html>502</html>', { status: 502 })))

    renderDialog()

    expect(await screen.findByText(/Failed to load the interview script \(502\)/)).toBeInTheDocument()
  })
})
