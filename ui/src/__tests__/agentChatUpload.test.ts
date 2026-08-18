// ui/src/__tests__/agentChatUpload.test.ts
//
// Task 2a gave the chat upload dialog a tier picker; this proves the client function the
// picker calls actually puts the chosen tier on the wire, rather than merely accepting the
// argument. Same axios-adapter technique as client.test.ts - the transport is swapped for one
// that records the real, fully-assembled request, because a test that mocks agentChatApi
// itself would only prove the mock was called and nothing about what left the browser.
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import { apiClient } from '../api/client'
import { agentChatApi } from '../api/agentChat'

describe('agentChatApi.uploadFile puts the declared tier on the wire', () => {
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
          doc_id: 1, filename: 'stored.pdf', original_name: 'brief.pdf',
          is_image: false, knowledge_tier: 'project',
        },
        status: 201, statusText: 'Created', headers: {}, config,
      } as AxiosResponse)
    }
    return captured
  }

  const file = new File(['hello'], 'brief.pdf', { type: 'application/pdf' })

  it('defaults to the project tier when the caller declares none', async () => {
    const captured = captureUpload()

    await agentChatApi.uploadFile('acme-rail', 'stakeholder_manager', file)

    expect(apiClient.getUri(captured.config!)).toContain('/projects/acme-rail/agent-chat/upload')
    const form = captured.config!.data as FormData
    expect(form.get('tier')).toBe('project')
    expect(form.get('agent_name')).toBe('stakeholder_manager')
    expect((form.get('file') as File).name).toBe('brief.pdf')
  })

  it('sends whatever tier the caller declares, not a value this function invents', async () => {
    const captured = captureUpload()

    await agentChatApi.uploadFile('acme-rail', 'stakeholder_manager', file, 'organisation')

    const form = captured.config!.data as FormData
    expect(form.get('tier')).toBe('organisation')
  })

  it('never silently upgrades the tier - sector goes out as sector, not project', async () => {
    const captured = captureUpload()

    await agentChatApi.uploadFile('acme-rail', 'stakeholder_manager', file, 'sector')

    const form = captured.config!.data as FormData
    expect(form.get('tier')).toBe('sector')
  })
})
