// ui/src/components/ValueChainTable.tsx
import { Sparkles } from 'lucide-react'

export type ValueChainAttribution = 'stated' | 'derived'

export interface ValueChainParty {
  id: string
  label: string
  description?: string
  colour?: string
}

export interface ValueChainSegment {
  id: string
  label: string
  description?: string
}

export interface ValueChainActivity {
  id: string
  segment_id: string
  label: string
  description?: string
  active?: boolean
}

export interface ValueChainContribution {
  activity_id: string
  party_id: string
  column: number
  description?: string
  attribution: ValueChainAttribution
}

export interface ValueChainTask {
  activity_id: string
  party_id: string
  id: string
  description?: string
}

export interface ValueChainProposition {
  id: string
  activity_id: string
  description?: string
}

// Links aren't rendered by this read-only table; keep the shape loose.
export type ValueChainLink = Record<string, unknown>

export interface ValueChainModel {
  model_version: number
  parties: ValueChainParty[]
  segments: ValueChainSegment[]
  activities: ValueChainActivity[]
  contributions: ValueChainContribution[]
  tasks: ValueChainTask[]
  propositions: ValueChainProposition[]
  links: ValueChainLink[]
}

const COLUMN_STEP = 10

// Columns are sparse, assigned in steps of ten. The union of columns actually used by
// lanes in a segment defines a range; every step within that range renders, whether or
// not a contribution occupies it, so a gap between two used columns stays visible rather
// than collapsing away.
function columnRange(usedColumns: number[]): number[] {
  if (usedColumns.length === 0) return []
  const min = Math.min(...usedColumns)
  const max = Math.max(...usedColumns)
  const range: number[] = []
  for (let column = min; column <= max; column += COLUMN_STEP) range.push(column)
  return range
}

export function ValueChainTable({ model }: { model: ValueChainModel }) {
  if (model.segments.length === 0) {
    return (
      <div data-testid="value-chain-empty" className="bg-surface-card rounded-xl p-8 text-center">
        <p className="text-muted text-sm">No value chain has been mapped yet.</p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {model.segments.map((segment) => {
        const activityIds = new Set(
          model.activities.filter((a) => a.segment_id === segment.id).map((a) => a.id),
        )
        const segmentContributions = model.contributions.filter((c) => activityIds.has(c.activity_id))
        const laneIds = Array.from(new Set(segmentContributions.map((c) => c.party_id)))
        const lanes = model.parties.filter((p) => laneIds.includes(p.id))
        const columns = columnRange(segmentContributions.map((c) => c.column))

        return (
          <section key={segment.id}>
            <h3 className="text-sm font-medium text-secondary uppercase tracking-wide mb-3">
              {segment.label}
            </h3>

            {lanes.length === 0 || columns.length === 0 ? (
              <p className="text-muted text-sm italic">No activity has been mapped in this segment yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <tbody>
                    {lanes.map((party) => (
                      <tr key={party.id} className="border-b border-surface">
                        <th
                          scope="row"
                          className="py-2 pr-4 text-left font-medium text-primary whitespace-nowrap align-top"
                        >
                          {party.colour && (
                            <span
                              aria-hidden="true"
                              className="inline-block w-2 h-2 rounded-full mr-2"
                              style={{ backgroundColor: party.colour }}
                            />
                          )}
                          {party.label}
                        </th>
                        {columns.map((column) => {
                          const contribution = segmentContributions.find(
                            (c) => c.party_id === party.id && c.column === column,
                          )
                          const activity = contribution
                            ? model.activities.find((a) => a.id === contribution.activity_id)
                            : undefined

                          return (
                            <td
                              key={column}
                              data-testid={`cell-${party.id}-${column}`}
                              className="py-2 px-3 align-top border-l border-surface min-w-[10rem]"
                            >
                              {contribution && activity && (
                                <div>
                                  <p className="font-medium text-primary">{activity.label}</p>
                                  {contribution.description && (
                                    <p className="text-muted text-xs mt-0.5">{contribution.description}</p>
                                  )}
                                  {contribution.attribution === 'derived' && (
                                    <span className="inline-flex items-center gap-1 text-brand bg-brand/10 px-1.5 py-0.5 rounded text-xs font-medium mt-1">
                                      <Sparkles className="w-3 h-3" aria-hidden="true" />
                                      Derived
                                    </span>
                                  )}
                                </div>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

export default ValueChainTable
