// ui/src/components/AgentGraphView.tsx
//
// The agent graph as a picture: each orchestrator at a centre, its crews on a ring around it in
// pipeline order, clockwise from twelve o'clock.
//
// **One position on the ring is one band, and a band can hold more than one crew.** Crews that
// wait on the same thing and on nothing of each other's run in parallel, and are drawn at the
// same angle, stacked along it - because putting them at consecutive positions would assert an
// ordering between them that no declaration makes.
//
// **It carries no fact of its own.** Every node, every edge, every label and every arrow comes
// out of `GET /projects/{slug}/data-architecture` - the same answer the tables on this page are
// drawn from, resolved for the same engagement in the same processing mode. Positions come from
// `agentGraphLayout.ts`, which is trigonometry over the order the graph already computes. There
// is no simulation, no layout library, and nothing placed by hand, so the same declarations draw
// the same picture on every load.
//
// **And it is never the only carrier of anything.** Everything drawn here is also written out
// underneath it, in the flows table and in the crew section - because a reader who cannot use a
// diagram must not be a reader who is missing something, and because a picture that alone knew a
// fact would drift from the tables the moment one of them changed.
//
// Three edge kinds, and the distinction is the reason the edges are derived rather than drawn.
// `CREW_DEPENDENCIES` says a crew waits on another; it does not say whether anything travels.
// Two of the nine declared edges hand over no artefact at all, and presenting those as
// identical to the seven that do would tell a reader material passes between two crews when none
// does. It is also what found a dependency declared against the wrong crew: an empty arrow into
// a crew that was reading its real input from somewhere else entirely.
import { useId, useState } from 'react'
import { AlertTriangle, GitBranch } from 'lucide-react'
import type { DataArchitecture } from '../api/dataArchitecture'
import { layoutAgentGraph } from './agentGraphLayout'
import type { PlacedEdge } from './agentGraphLayout'

type Kind = PlacedEdge['kind']

// Stroke and prose per edge kind, in one place, so the legend and the drawing cannot disagree
// about what a line means.
const EDGE_STYLE: Record<Kind, { stroke: string; dash?: string; width: number; legend: string }> = {
  information: {
    stroke: 'stroke-brand-dark',
    width: 2,
    legend: 'Waits on it, and reads an artefact it wrote - material passes',
  },
  sequencing: {
    stroke: 'stroke-muted',
    dash: '2 5',
    width: 1.5,
    legend: 'Waits on it, and reads nothing it wrote - ordering only, no material passes',
  },
  inherited: {
    stroke: 'stroke-brand-light',
    dash: '6 4',
    width: 1.5,
    legend:
      'Reads an artefact it wrote without waiting on it directly - the ordering comes from further back in the chain',
  },
}

const MARKER_FILL: Record<Kind, string> = {
  information: 'fill-brand-dark',
  sequencing: 'fill-muted',
  inherited: 'fill-brand-light',
}

const KINDS: Kind[] = ['information', 'sequencing', 'inherited']

export function AgentGraphView({ data }: { data: DataArchitecture }) {
  // Off by default. Eleven inherited flows across a ring of nine crews is a legible finding in
  // the table below and an unreadable one on the ring, and hiding them costs no fact: the table
  // lists every edge whatever this is set to. Toggling changes which edges are drawn and never
  // where anything sits, so the picture stays comparable with itself.
  const [showInherited, setShowInherited] = useState(false)
  const markerPrefix = useId()

  const layout = layoutAgentGraph({
    clusters: data.clusters,
    crews: data.crews,
    edges: data.crew_edges,
  })
  const drawn = layout.edges.filter((e) => showInherited || e.kind !== 'inherited')
  const crewLabel = new Map(data.crews.map((c) => [c.crew_id, c.display_name]))

  if (layout.nodes.length === 0) return null

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="text-xs text-muted leading-relaxed max-w-2xl">
          Each orchestrator sits at a centre with the crews it owns around it, clockwise from the
          top in the order the pipeline runs them. Two crews at the same number and the same
          angle are parallel - they wait on the same work and on nothing of each other's - and
          are stacked along one radius rather than drawn one after the other. A spoke from the
          centre is a crew that orchestrator can start itself; a crew with no spoke is reachable
          only by one of the other dispatch paths below. Nothing here is placed by hand, so this
          is the same picture on every load.
        </p>
        <label className="flex items-center gap-2 text-xs text-secondary whitespace-nowrap">
          <input
            type="checkbox"
            checked={showInherited}
            onChange={(e) => setShowInherited(e.target.checked)}
            className="accent-brand-dark"
          />
          Show inherited flows
        </label>
      </div>

      <div className="rounded-lg border border-surface-border bg-surface-raised p-2 overflow-x-auto">
        <svg
          role="img"
          aria-label="The agent graph: each orchestrator at a centre with its crews around it"
          viewBox={`0 0 ${layout.size} ${layout.size}`}
          className="w-full h-auto max-w-[720px] mx-auto block"
        >
          <defs>
            {KINDS.map((kind) => (
              <marker
                key={kind}
                id={`${markerPrefix}-${kind}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" className={MARKER_FILL[kind]} />
              </marker>
            ))}
          </defs>

          {layout.spokes.map((spoke) => (
            <path
              key={spoke.id}
              data-testid={`spoke-${spoke.crewId}`}
              d={spoke.path}
              fill="none"
              strokeWidth={1}
              strokeDasharray="1 4"
              className="stroke-brand-light"
            />
          ))}

          {drawn.map((edge) => (
            <path
              key={edge.id}
              data-testid={`edge-${edge.source}-${edge.target}`}
              data-kind={edge.kind}
              data-crosses-clusters={edge.crosses_clusters ? 'true' : 'false'}
              d={edge.path}
              fill="none"
              strokeWidth={edge.crosses_clusters ? EDGE_STYLE[edge.kind].width + 1.5 : EDGE_STYLE[edge.kind].width}
              strokeDasharray={EDGE_STYLE[edge.kind].dash}
              markerEnd={`url(#${markerPrefix}-${edge.kind})`}
              className={EDGE_STYLE[edge.kind].stroke}
            >
              <title>
                {`${crewLabel.get(edge.source) ?? edge.source} to ${
                  crewLabel.get(edge.target) ?? edge.target
                }: ${
                  edge.artefacts.length > 0
                    ? edge.artefacts.join(', ')
                    : 'nothing travels - ordering only'
                }`}
              </title>
            </path>
          ))}

          {layout.nodes.map((node) => (
            <a
              key={node.id}
              href={node.kind === 'crew' ? `#crew-${node.id}` : `#agent-${node.id}`}
              data-testid={`node-${node.id}`}
              data-band={node.band}
              data-angle={node.angle ?? ''}
            >
              <title>
                {node.kind === 'crew'
                  ? `${node.label} - band ${node.band} clockwise from the top`
                  : `${node.label} - orchestrator`}
              </title>
              <circle
                cx={node.x}
                cy={node.y}
                r={node.radius}
                strokeWidth={node.kind === 'orchestrator' ? 2 : 1.5}
                strokeDasharray={node.broken ? '4 3' : undefined}
                className={
                  node.kind === 'orchestrator'
                    ? 'fill-brand-light stroke-brand-dark'
                    : node.broken
                      ? 'fill-red-50 stroke-red-400'
                      : 'fill-surface stroke-brand'
                }
              />
              <text
                x={node.x}
                y={node.y + 4}
                textAnchor="middle"
                className="fill-primary text-[12px] font-semibold"
              >
                {node.kind === 'orchestrator' ? '•' : node.band}
              </text>
              <text
                x={node.labelX}
                y={node.labelY}
                textAnchor={node.labelAnchor}
                className="fill-secondary text-[11px] font-medium"
              >
                {node.label}
              </text>
            </a>
          ))}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1">
        {KINDS.map((kind) => (
          <span key={kind} className="flex items-center gap-2 text-[11px] text-muted">
            <svg width="30" height="8" aria-hidden="true" className="flex-shrink-0">
              <line
                x1="0"
                y1="4"
                x2="30"
                y2="4"
                strokeWidth={EDGE_STYLE[kind].width}
                strokeDasharray={EDGE_STYLE[kind].dash}
                className={EDGE_STYLE[kind].stroke}
              />
            </svg>
            <span className="capitalize font-semibold text-secondary">{kind}</span> -{' '}
            {EDGE_STYLE[kind].legend}
          </span>
        ))}
        <span className="flex items-center gap-2 text-[11px] text-muted">
          <AlertTriangle size={11} className="text-red-500" />
          A crew drawn with a broken outline declares a defect - a flow through it does not happen
        </span>
      </div>
    </div>
  )
}

/**
 * Every edge in the graph, written out.
 *
 * The picture's companion rather than its caption. It is what keeps the view from being the only
 * carrier of anything: a reader who cannot use the diagram loses nothing, and the two cannot
 * drift because they are rendered from the same array.
 */
export function CrewFlowTable({ data }: { data: DataArchitecture }) {
  const label = new Map(data.crews.map((c) => [c.crew_id, c.display_name]))
  return (
    <div className="overflow-x-auto rounded-lg border border-surface-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-surface border-b border-surface-border">
            <th className="text-left px-4 py-2.5 font-semibold text-muted">From</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">To</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">Relationship</th>
            <th className="text-left px-4 py-2.5 font-semibold text-muted">What travels</th>
          </tr>
        </thead>
        <tbody>
          {data.crew_edges.map((edge) => (
            <tr key={`${edge.source}->${edge.target}`} className="border-t border-surface-border">
              <td className="px-4 py-2.5">
                <a href={`#crew-${edge.source}`} className="text-brand-dark hover:underline">
                  {label.get(edge.source) ?? edge.source}
                </a>
              </td>
              <td className="px-4 py-2.5">
                <a href={`#crew-${edge.target}`} className="text-brand-dark hover:underline">
                  {label.get(edge.target) ?? edge.target}
                </a>
              </td>
              <td className="px-4 py-2.5 text-secondary">
                <span className="inline-flex items-center gap-1 font-medium capitalize">
                  <GitBranch size={11} className="text-muted" />
                  {edge.kind}
                </span>
                <span className="block text-muted">{EDGE_STYLE[edge.kind].legend}</span>
                {edge.crosses_clusters && (
                  <span className="block text-amber-800">Between two clusters</span>
                )}
              </td>
              <td className="px-4 py-2.5 text-secondary">
                {edge.artefacts.length > 0 ? (
                  <span className="font-mono">{edge.artefacts.join(', ')}</span>
                ) : (
                  <span className="text-muted">Nothing - this crew reads none of its outputs</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
