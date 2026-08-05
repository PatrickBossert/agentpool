// ui/src/components/LineageView.tsx
// What each output was built from, and whether it has been overtaken.
//
// The case this exists for went unnoticed for days: interview scripts built from a value
// chain that had since been approved again, with nothing anywhere saying so.
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileText, HelpCircle, ShieldAlert } from 'lucide-react'

import { projectsApi } from '../api/endpoints'
import type { LineageOutput, LineageResponse } from '../types'

function StateBadge({ output }: { output: LineageOutput }) {
  if (output.state === 'stale') {
    return (
      <span className="flex items-center gap-1 text-xs text-red-600">
        <AlertTriangle size={12} /> stale
      </span>
    )
  }
  if (output.state === 'fresh') {
    return (
      <span className="flex items-center gap-1 text-xs text-emerald-600">
        <CheckCircle2 size={12} /> current
      </span>
    )
  }
  // Unknown is not a failure. Outputs written before lineage existed know nothing about
  // their inputs, and an output built only from documents never will.
  return (
    <span className="flex items-center gap-1 text-xs text-muted">
      <HelpCircle size={12} /> no recorded ancestry
    </span>
  )
}

export default function LineageView({ slug }: { slug: string }) {
  const { data } = useQuery<LineageResponse>({
    queryKey: ['lineage', slug],
    queryFn: () => projectsApi.lineage(slug),
  })

  if (!data) return <p className="text-xs text-muted">Loading lineage…</p>

  const current = data.outputs.filter((o) => o.is_current)

  return (
    <div className="space-y-4">
      <ul className="space-y-1">
        {current.map((o) => (
          <li
            key={o.id}
            data-testid={`lineage-${o.id}`}
            className="rounded-lg bg-surface-card px-4 py-3"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm text-primary truncate">
                  {o.output_type} <span className="text-muted">v{o.version}</span>
                </p>
                <p className="text-xs text-secondary">{o.agent_name}</p>
              </div>
              <StateBadge output={o} />
            </div>

            {o.behind.map((b) => (
              <p key={b.output_type} className="text-xs text-red-600 mt-1">
                built from v{b.built_from} of {b.output_type}, now approved at v{b.approved}
              </p>
            ))}

            {o.document_ids.length > 0 && (
              <p className="text-xs text-secondary mt-1 flex items-center gap-1">
                <FileText size={11} />
                {o.document_ids.map((id) => data.documents[String(id)] ?? `doc ${id}`).join(', ')}
              </p>
            )}
          </li>
        ))}
      </ul>

      {data.blocked_writes.length > 0 && (
        <section data-testid="blocked-writes" className="space-y-1">
          <h3 className="text-xs font-bold text-muted uppercase tracking-widest">
            Blocked writes
          </h3>
          {/* Worded as an upstream finding. An agent reaching for another's artefact is
              usually a correct diagnosis of something missing, not misbehaviour. */}
          <p className="text-xs text-secondary">
            An agent tried to write an output it does not own. This usually means something it
            needed was missing upstream.
          </p>
          {data.blocked_writes.map((b) => (
            <p key={b.id} className="text-xs text-primary flex items-center gap-1">
              <ShieldAlert size={11} className="text-amber-500" />
              {b.agent_name} tried to write {b.key}
              {b.owner ? `, owned by ${b.owner}` : ', which no agent owns'}
            </p>
          ))}
        </section>
      )}
    </div>
  )
}
