// ui/src/__tests__/DiscoveryReviewExtra.test.tsx
//
// The two ledgers on `discovery_mapping`'s Output tab: that they are registered where a
// reviewer will find them, that each wire row is mapped to what its own kind shows, and that
// the surface says what actually clears a send-back.
//
// The last of those is Task 3's third handoff, and it is a statement about the code rather
// than a nicety: `register_nodes_sync` and `register_levers_sync` stamp `last_version` on
// every id a write names, and both agents re-emit their whole set every run. So the ledger
// can tell "the agent has written since the reviewer read this" and cannot tell "the agent
// addressed the note". A surface implying otherwise has a reviewer reading a cleared
// send-back as evidence of a correction that may never have been made.
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'

import DiscoveryReviewExtra, { leverAsItem, nodeAsItem }
  from '../components/tabs/DiscoveryReviewExtra'
import { CREW_OUTPUT_EXTRA, CREW_OUTPUT_EDITOR } from '../components/AgentDetailPanel'
import { projectsApi } from '../api/endpoints'
import type { LeverLedgerRow, NodeLedgerRow } from '../types'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getNodeLedger: vi.fn(),
    getLeverLedger: vi.fn(),
    getMyPermissions: vi.fn(),
    reviewNode: vi.fn().mockResolvedValue({}),
    reviewLever: vi.fn().mockResolvedValue({}),
  },
  inboundRepliesApi: {},
  agentChatApi: {},
}))

// The identity hook fetches this project's agent configuration; the panel and the note both
// read a name out of it, so it is stubbed rather than left to a network call that returns
// undefined and takes the first name with it.
vi.mock('../hooks/useAgentIdentity', () => ({
  useAgentIdentity: () => (displayName: string) => ({
    name: displayName === 'Value Chain Mapper' ? 'Alex Chen' : 'Morgan Reid',
    imageUrl: null,
  }),
}))

const NODE: NodeLedgerRow = {
  node_id: '3.3.3', label: 'Mains renewal planning', level: 'L3', active: 1,
  review_status: 'pending', review_return_to: null, reviewed_at_version: null,
  last_version: 3, last_author: 'value_chain_mapper', review_count: 0,
}

const LEVER: LeverLedgerRow = {
  lever_id: 'LV-001', title: 'Risk-based capital prioritisation', status: 'contradicted',
  review_status: 'pending', review_return_to: null, reviewed_at_version: null,
  last_version: 3, last_author: 'value_lever_analyst', review_count: 0,
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.mocked(projectsApi.getNodeLedger).mockReset().mockResolvedValue([NODE])
  vi.mocked(projectsApi.getLeverLedger).mockReset().mockResolvedValue([LEVER])
  vi.mocked(projectsApi.getMyPermissions).mockReset()
    .mockResolvedValue({ can_review: true, can_approve: true } as never)
  vi.mocked(projectsApi.reviewNode).mockReset().mockResolvedValue({})
  vi.mocked(projectsApi.reviewLever).mockReset().mockResolvedValue({})
})

// ── Registration ───────────────────────────────────────────────────────────────

it('is the review surface registered for discovery_mapping', () => {
  expect(CREW_OUTPUT_EXTRA.discovery_mapping).toBe(DiscoveryReviewExtra)
})

it('does not displace the crew\'s editor', () => {
  // CREW_OUTPUT_EXTRA and CREW_OUTPUT_EDITOR are different registers and discovery_mapping is
  // the one crew in both: StructureTab is where the value chain is read and changed, and this
  // is where a conclusion about one node or one lever is recorded. Registering the review
  // surface as the editor would have replaced the thing a reviewer needs to read first.
  expect(CREW_OUTPUT_EDITOR.discovery_mapping).toBeDefined()
  expect(CREW_OUTPUT_EDITOR.discovery_mapping).not.toBe(DiscoveryReviewExtra)
})

// ── What each kind shows ───────────────────────────────────────────────────────

it('maps a node to its id, its label, and its level', () => {
  expect(nodeAsItem(NODE)).toMatchObject({
    item_id: '3.3.3', label: 'Mains renewal planning', meta: 'L3',
  })
})

it('maps a lever to its id, its title, and its hypothesis status', () => {
  // `status` is the lever's own state and is not its review state - the interviews decide one
  // and a human decides the other. Showing only the review state would hide the fact that the
  // interviews have already contradicted the lever a reviewer is about to approve.
  expect(leverAsItem(LEVER)).toMatchObject({
    item_id: 'LV-001', label: 'Risk-based capital prioritisation', meta: 'contradicted',
  })
})

it('maps a node with no recorded level to an empty meta rather than to the string null', () => {
  expect(nodeAsItem({ ...NODE, level: null }).meta).toBe('')
})

it('renders both ledgers, each showing its own kind of identity', async () => {
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  expect(await screen.findByText('3.3.3')).toBeInTheDocument()
  expect(await screen.findByText('LV-001')).toBeInTheDocument()
  expect(screen.getByText('L3')).toBeInTheDocument()
  expect(screen.getByText('contradicted')).toBeInTheDocument()
})

// ── What actually clears a send-back ───────────────────────────────────────────

it('says that any run clears a send-back, not only one that addressed it', async () => {
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  const note = await screen.findByTestId('clearing-note-node')
  expect(note).toHaveTextContent(/any run clears the send-back/i)
  expect(note).toHaveTextContent(/whether or not the note was addressed/i)
})

it('says it for the lever ledger too, where it is equally true', async () => {
  // register_levers_sync stamps last_version on every id it names, exactly as the node one
  // does, so the lever half is not the weaker claim it might look like. A note on one section
  // does not explain the other - an assertion scoped to a container is not an assertion about
  // its contents, and the same holds for an explanation.
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  const note = await screen.findByTestId('clearing-note-lever')
  expect(note).toHaveTextContent(/any run clears the send-back/i)
})

it('names each ledger\'s own agent in its note, from this project\'s identity', async () => {
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  expect(await screen.findByTestId('clearing-note-node')).toHaveTextContent(/Alex/)
  expect(await screen.findByTestId('clearing-note-lever')).toHaveTextContent(/Morgan/)
  expect(screen.getByTestId('clearing-note-node')).not.toHaveTextContent(/Morgan/)
})

// ── Approving from the list ────────────────────────────────────────────────────

it('approves a node through the node door and a lever through the lever door', async () => {
  vi.mocked(projectsApi.getNodeLedger).mockResolvedValue([{ ...NODE, review_count: 1 }])
  vi.mocked(projectsApi.getLeverLedger).mockResolvedValue([{ ...LEVER, review_count: 1 }])
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)

  const approves = await screen.findAllByRole('button', { name: /approve/i })
  expect(approves).toHaveLength(2)
  await userEvent.click(approves[0])
  await waitFor(() => expect(projectsApi.reviewNode).toHaveBeenCalled())
  expect(vi.mocked(projectsApi.reviewNode).mock.calls[0].slice(1))
    .toEqual(['3.3.3', { decision: 'approved' }])
  expect(projectsApi.reviewLever).not.toHaveBeenCalled()

  await userEvent.click(approves[1])
  await waitFor(() => expect(projectsApi.reviewLever).toHaveBeenCalled())
  expect(vi.mocked(projectsApi.reviewLever).mock.calls[0].slice(1))
    .toEqual(['LV-001', { decision: 'approved' }])
})

it('offers no approve to somebody who is not an approver', async () => {
  vi.mocked(projectsApi.getMyPermissions).mockResolvedValue(
    { can_review: true, can_approve: false } as never)
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  await screen.findByText('3.3.3')
  expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
})

// ── Failure and emptiness are different things ─────────────────────────────────

it('tells a failed fetch apart from an empty ledger', async () => {
  vi.mocked(projectsApi.getNodeLedger).mockRejectedValue(new Error('boom'))
  vi.mocked(projectsApi.getLeverLedger).mockResolvedValue([])
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  expect(await screen.findByText(/could not load this review ledger/i)).toBeInTheDocument()
  // The lever ledger loaded and is empty, so its section renders nothing at all - including
  // no error. An empty ledger and a failed fetch rendering identically leaves no way to tell
  // "could not load" from "nothing to review".
  expect(screen.queryByTestId('clearing-note-lever')).not.toBeInTheDocument()
})

it('renders nothing for a crew that has produced neither nodes nor levers', async () => {
  vi.mocked(projectsApi.getNodeLedger).mockResolvedValue([])
  vi.mocked(projectsApi.getLeverLedger).mockResolvedValue([])
  render(<Wrapper><DiscoveryReviewExtra slug="p" /></Wrapper>)
  await waitFor(() => expect(projectsApi.getNodeLedger).toHaveBeenCalled())
  expect(screen.queryByTestId('clearing-note-node')).not.toBeInTheDocument()
  expect(screen.queryByText(/value chain node review/i)).not.toBeInTheDocument()
})
