// ui/src/__tests__/InterviewTemplateEditor.test.tsx
//
// The editor used to be opened with nodeLabel and read/wrote
// /interview-scripts/{node_label} - a key the artefact was never actually keyed by. Fixed to
// take scriptId and route on that instead. Asserted on the request URLs actually sent, not on
// what the component renders: CLAUDE.md records this project's own recurring failure mode as
// "tested as rendered, not as sent" - a title in a heading proves nothing about which id a
// PATCH goes out under. Follows the pattern in TestInterviewPressSlug.test.tsx.
//
// Also covers the two defects the request-body assertion made visible in review: "Add
// Section" building a section with no section_id/discipline/question_intent/elicitation (the
// validator refuses that on every save), and a save failure collapsing the server's actual
// explanation into a fixed "Save failed." string.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import InterviewTemplateEditor from '../components/InterviewTemplateEditor'

const getMock = vi.fn()
const patchMock = vi.fn()

vi.mock('../api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => getMock(...args),
    patch: (...args: unknown[]) => patchMock(...args),
  },
}))

const SCRIPT = {
  script_id: 'SC-001',
  node_id: '1.2',
  node_label: 'Old Node Label',
  level: 'L2',
  relationship: 'internal',
  welcome_message: 'Welcome',
  closing_message: 'Thanks',
  sections: [
    {
      section_id: 'S1', title: 'Opening', discipline: 'commercial',
      question_intent: 'evidence', elicitation: 'unprompted', questions: [],
    },
  ],
}

function renderEditor(overrides: Partial<{ scriptId: string; nodeLabel: string }> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <InterviewTemplateEditor
        slug="proj-1"
        scriptId={overrides.scriptId ?? 'SC-001'}
        nodeLabel={overrides.nodeLabel ?? 'Old Node Label'}
        activityId="1.2"
        onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('InterviewTemplateEditor - routes and saves by script_id, not node_label', () => {
  beforeEach(() => {
    getMock.mockReset()
    patchMock.mockReset()
    getMock.mockResolvedValue({ data: SCRIPT })
    patchMock.mockResolvedValue({ data: { ok: true, templates_updated: 1 } })
  })

  it('GETs the script keyed by scriptId, never by the displayed node label', async () => {
    // node_label deliberately does not equal scriptId here - a component that still built
    // its URL from nodeLabel would send a request this test can catch, not just render a
    // heading that happens to say the right thing.
    renderEditor({ scriptId: 'SC-001', nodeLabel: 'A Completely Different Display Title' })

    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1))
    expect(getMock.mock.calls[0][0]).toBe('/projects/proj-1/interview-scripts/SC-001')
  })

  it('PATCHes the same script_id URL on save', async () => {
    renderEditor()
    await screen.findByDisplayValue('Welcome')

    await userEvent.click(await screen.findByRole('button', { name: /save & sync template/i }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    expect(patchMock.mock.calls[0][0]).toBe('/projects/proj-1/interview-scripts/SC-001')
  })

  it('a newly added section is sent with the fields the validator requires', async () => {
    renderEditor()
    await screen.findByDisplayValue('Welcome')

    await userEvent.click(screen.getByRole('button', { name: /\+ add section/i }))
    await userEvent.click(screen.getByRole('button', { name: /save & sync template/i }))

    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1))
    const sentSections = (patchMock.mock.calls[0][1] as { script: typeof SCRIPT }).script.sections
    expect(sentSections).toHaveLength(2)
    const added = sentSections[1]
    expect(added.section_id).toBeTruthy()
    expect(added.section_id).not.toBe(sentSections[0].section_id)
    // Inherited from the one existing section rather than a hardcoded guess, since
    // discipline is a project-specific closed list this component is never given.
    expect(added.discipline).toBe('commercial')
    expect(added.question_intent).toBe('evidence')
    expect(added.elicitation).toBe('unprompted')
  })

  it('surfaces the server error detail on a failed save rather than a fixed string', async () => {
    patchMock.mockRejectedValue(
      Object.assign(new Error('Unprocessable'), {
        isAxiosError: true,
        response: {
          status: 422,
          data: { detail: "script SC-001 has no node_id - anchor it to a value chain node" },
        },
      }),
    )
    renderEditor()
    await screen.findByDisplayValue('Welcome')

    await userEvent.click(screen.getByRole('button', { name: /save & sync template/i }))

    // The message is rendered twice - once inline in the body, once in the footer - so
    // this asserts at least one, rather than assuming uniqueness the component doesn't
    // promise.
    await waitFor(() => {
      expect(screen.getAllByText(/anchor it to a value chain node/i).length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/^save failed\.?$/i)).not.toBeInTheDocument()
  })
})
