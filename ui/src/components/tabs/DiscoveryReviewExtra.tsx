// ui/src/components/tabs/DiscoveryReviewExtra.tsx
// The review surfaces for `discovery_mapping`: one ledger per agent, on the Output tab.
//
// Registered against the **crew** in CREW_OUTPUT_EXTRA, because that is what that register is
// keyed on - and `discovery_mapping` holds two agents, so this is one component showing two
// ledgers rather than two components. The injection underneath it is per *agent*
// (`_pending_discovery_revisions`), which is the asymmetry to keep in mind: a reviewer sees
// both ledgers on one tab, and a send-back on one of them reaches exactly one agent.
//
// It sits beside StructureTab, not instead of it. StructureTab is the crew's registered
// CREW_OUTPUT_EDITOR and is where the value chain is read and edited; this is where a
// conclusion about one node or one lever is recorded. Per-node editing of the model is
// deliberately not here - it has its own editor and its own workflow.
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { projectsApi } from '../../api/endpoints'
import { useAgentIdentity } from '../../hooks/useAgentIdentity'
import { describeError } from '../../utils/describeError'
import { ItemReviewRow, type ReviewableItem } from './ItemReviewRow'
import { ItemReviewPanel, type ItemKind } from './ItemReviewPanel'
import type { LeverLedgerRow, NodeLedgerRow } from '../../types'

// The display names CREW_AGENTS holds for this crew, which is also the key useAgentIdentity
// is looked up by. Named here rather than indexed out of CREW_AGENTS by position: [0] and [1]
// would silently swap the two ledgers' agents if that array were ever reordered, and the two
// ledgers are exactly the thing that must not be crossed.
const AGENT_OF: Record<ItemKind, string> = {
  node: 'Value Chain Mapper',
  lever: 'Value Lever Analyst',
}

/** A node as the shared row draws it: the id, what it means, and its level. */
export function nodeAsItem(row: NodeLedgerRow): ReviewableItem {
  return {
    item_id: row.node_id,
    label: row.label,
    meta: row.level ?? '',
    review_status: row.review_status,
    reviewed_at_version: row.reviewed_at_version,
    last_version: row.last_version,
    review_count: row.review_count,
  }
}

/** A lever as the shared row draws it: the id, its title, and its hypothesis status.
 *
 *  `status` is the lever's own state - untested, contradicted, confirmed - and not its review
 *  state. The two are separate columns on the server for the reason they are separate fields
 *  here: the interviews decide one and a human decides the other, and showing only the review
 *  state would hide the fact that the interviews have already contradicted the lever a
 *  reviewer is about to approve. */
export function leverAsItem(row: LeverLedgerRow): ReviewableItem {
  return {
    item_id: row.lever_id,
    label: row.title,
    meta: row.status,
    review_status: row.review_status,
    reviewed_at_version: row.reviewed_at_version,
    last_version: row.last_version,
    review_count: row.review_count,
  }
}

function LedgerSection(
  { slug, kind, title, items, failed, canApprove, canReview, agentName, unit, onChanged }: {
    slug: string
    kind: ItemKind
    title: string
    items: ReviewableItem[]
    failed: boolean
    canApprove: boolean
    canReview: boolean
    agentName: string
    /** What this agent rebuilds on every run, in the sentence below - "value chain" reads
     *  wrongly for levers and "set of levers" reads wrongly for the chain. */
    unit: string
    onChanged: () => void
  },
) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const open = openId ? items.find((i) => i.item_id === openId) : undefined

  function handleApprove(itemId: string) {
    setError(null)
    const record = kind === 'node' ? projectsApi.reviewNode : projectsApi.reviewLever
    record(slug, itemId, { decision: 'approved' })
      .then(onChanged)
      .catch((err) => setError(describeError(err, 'Could not approve that item.')))
  }

  function closePanel() {
    setOpenId(null)
    onChanged()
  }

  if (!failed && items.length === 0) return null

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{title}</p>
      {/* What actually clears a send-back, said plainly rather than left to be discovered.
          `register_nodes_sync` and `register_levers_sync` stamp `last_version` on every id a
          write names, and both agents re-emit their whole set every run - so the ledger can
          tell "the agent has written since the reviewer read this" and cannot tell "the agent
          addressed the note". A surface that implied otherwise would have a reviewer treating
          a cleared send-back as evidence the correction was made. */}
      <p data-testid={`clearing-note-${kind}`}
         className="text-[11px] text-muted leading-relaxed">
        Sending an item back reaches {agentName} on the next run of this crew. {agentName}{' '}
        rebuilds the whole {unit} every run, so any run clears the send-back - whether or not
        the note was addressed. Re-read the item afterwards rather than reading a cleared
        send-back as evidence it was.
      </p>
      {failed ? (
        // Distinct from "no rows": an empty ledger and a failed fetch rendering identically
        // leaves no way to tell "could not load" from "nothing to review".
        <p className="text-[11px] text-red-600">Could not load this review ledger.</p>
      ) : (
        <div>
          {items.map((item) => (
            <ItemReviewRow
              key={item.item_id}
              item={item}
              onOpen={setOpenId}
              onApprove={handleApprove}
              canApprove={canApprove}
            />
          ))}
        </div>
      )}
      {error && <p className="text-[11px] text-red-600">{error}</p>}
      {open && (
        <ItemReviewPanel
          slug={slug}
          kind={kind}
          item={open}
          agentName={agentName}
          canReview={canReview}
          onClose={closePanel}
        />
      )}
    </div>
  )
}

export default function DiscoveryReviewExtra({ slug }: { slug: string }) {
  const qc = useQueryClient()
  const identity = useAgentIdentity(slug)

  const { data: nodes, isError: nodesFailed } = useQuery({
    queryKey: ['node-ledger', slug],
    queryFn: () => projectsApi.getNodeLedger(slug),
  })
  const { data: levers, isError: leversFailed } = useQuery({
    queryKey: ['lever-ledger', slug],
    queryFn: () => projectsApi.getLeverLedger(slug),
  })
  // Undefined while loading collapses into "not permitted" below - a missing Approve button
  // while permissions are in flight, never a disabled one that becomes clickable.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug),
  })

  // First name only, and read from this project's own agent identity rather than written out:
  // a persona is renameable per project, and a hard-coded 'Alex' is a second registry free to
  // drift from the one the rest of the product reads.
  const firstName = (displayName: string) =>
    identity(displayName).name.split(' ')[0] || displayName

  return (
    <div className="space-y-4">
      <LedgerSection
        slug={slug}
        kind="node"
        title="Value Chain Node Review"
        items={(nodes ?? []).map(nodeAsItem)}
        failed={nodesFailed}
        canApprove={!!permissions?.can_approve}
        canReview={!!permissions?.can_review}
        agentName={firstName(AGENT_OF.node)}
        unit="value chain"
        onChanged={() => qc.invalidateQueries({ queryKey: ['node-ledger', slug] })}
      />
      <LedgerSection
        slug={slug}
        kind="lever"
        title="Value Lever Review"
        items={(levers ?? []).map(leverAsItem)}
        failed={leversFailed}
        canApprove={!!permissions?.can_approve}
        canReview={!!permissions?.can_review}
        agentName={firstName(AGENT_OF.lever)}
        unit="set of levers"
        onChanged={() => qc.invalidateQueries({ queryKey: ['lever-ledger', slug] })}
      />
    </div>
  )
}
