// ui/src/__tests__/agentPortraitUpload.test.ts
//
// `agentConfigApi.uploadImage` - what actually leaves the browser.
//
// `AgentConfigSection.test.tsx` mocks the whole client, so it proves the section calls this
// function in the right order with the right file and proves nothing about the request. Same
// axios-adapter technique as `agentChatUpload.test.ts` and `client.test.ts`: the transport is
// swapped for one that records the fully-assembled request, because a test that mocked the api
// object would only ever demonstrate that the mock was called.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { agentConfigApi } from '../api/agentConfig'

describe('agentConfigApi.uploadImage puts the portrait on the wire', () => {
  const realAdapter = apiClient.defaults.adapter

  afterEach(() => {
    apiClient.defaults.adapter = realAdapter
  })

  function captureUpload(): { config: AxiosRequestConfig | null } {
    const captured: { config: AxiosRequestConfig | null } = { config: null }
    apiClient.defaults.adapter = (config: AxiosRequestConfig) => {
      captured.config = config
      return Promise.resolve({
        data: {
          url: '/api/projects/acme-rail/agents/stakeholder_interviewer/image',
          bytes: 74_000,
          original_bytes: 8_200_000,
        },
        status: 200, statusText: 'OK', headers: {}, config,
      } as AxiosResponse)
    }
    return captured
  }

  const file = new File(['a photograph'], 'avery.jpg', { type: 'image/jpeg' })

  it('posts the file to this agent on this project', async () => {
    const captured = captureUpload()

    await agentConfigApi.uploadImage('acme-rail', 'stakeholder_interviewer', file)

    expect(captured.config!.method).toBe('post')
    expect(apiClient.getUri(captured.config!)).toContain(
      '/projects/acme-rail/agents/stakeholder_interviewer/image',
    )
    const form = captured.config!.data as FormData
    expect((form.get('file') as File).name).toBe('avery.jpg')
  })

  it('sends an origin-relative URL, never a host of its own', async () => {
    // `API_BASE` is '' on purpose so every call goes to whatever origin served the page. This
    // used to be the literal http://localhost:8000 across the client, which sent every request
    // to the viewer's own machine and bypassed both proxies - and a portrait upload is a door
    // where that would look like an intermittent failure rather than a configuration one.
    const captured = captureUpload()

    await agentConfigApi.uploadImage('acme-rail', 'stakeholder_interviewer', file)

    expect(apiClient.getUri(captured.config!)).not.toMatch(/^https?:\/\//)
  })

  it('answers the URL and both sizes the door reported, unaltered', async () => {
    // The section renders these three, and it renders them to say a large file quietly became
    // a small one. A client that dropped the sizes would leave that sentence unsayable.
    captureUpload()

    const result = await agentConfigApi.uploadImage('acme-rail', 'stakeholder_interviewer', file)

    expect(result.url).toBe('/api/projects/acme-rail/agents/stakeholder_interviewer/image')
    expect(result.bytes).toBe(74_000)
    expect(result.original_bytes).toBe(8_200_000)
  })

  it('sends the file as a multipart body and not as JSON', async () => {
    // The request body is the FormData itself, which is what makes `UploadFile = File(...)`
    // on the door reachable at all. A client that stringified it would answer 422 from
    // FastAPI's own validation, with a sentence about a missing field rather than about a
    // photograph - and no test that mocks this function could see it.
    //
    // The Content-Type header is deliberately **not** asserted: axios decides it from the body
    // at transport time and jsdom's FormData is not the browser's, so what is recorded here is
    // an artefact of the environment rather than a property of this code.
    const captured = captureUpload()

    await agentConfigApi.uploadImage('acme-rail', 'stakeholder_interviewer', file)

    expect(captured.config!.data).toBeInstanceOf(FormData)
    expect(typeof captured.config!.data).not.toBe('string')
  })
})
