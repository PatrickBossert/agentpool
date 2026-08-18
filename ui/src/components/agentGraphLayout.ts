// ui/src/components/agentGraphLayout.ts
//
// Where every node and every edge of the agent graph goes, computed rather than settled.
//
// **Why this is trigonometry and not a force simulation.** What was asked for is an orchestrator
// at the centre with a clockwise flow of activity around it, and that is a radial layout by
// description. A force simulation would settle somewhere slightly different on every load, and
// would spend its whole run fighting the angular order it was told to keep. This page is shown to
// clients and auditors: "the third crew clockwise" has to mean the same thing tomorrow as it does
// today, and a screenshot taken in a report has to match the page it was taken from.
//
// So there is no simulation and no layout library. Nine crews on a circle is `cos` and `sin`, and
// the only ordering decision - which crew is where on the ring - is not made here at all. It is
// the order `agents/graph.py` already computes with Kahn's algorithm and hands over in
// `cluster.crew_ids`, so the picture cannot disagree with the pipeline order the tables show.
//
// **Labels do not collide, and no force resolves them either.** Each label is placed radially
// outward from its node and anchored by quadrant - text runs away from the circle on the right,
// towards it on the left - so labels diverge with the nodes rather than crowding a fixed side.
//
// **Nothing here reads a declaration.** Every input is a value from
// `GET /projects/{slug}/data-architecture`; this module decides coordinates and nothing else. A
// node placed by hand or an edge labelled by hand would make the picture a second declaration,
// which is the failure the whole data-architecture page exists to end.
import type {
  DataArchitectureCluster,
  DataArchitectureCrew,
  DataArchitectureCrewEdge,
} from '../api/dataArchitecture'

export interface AgentGraphInput {
  clusters: DataArchitectureCluster[]
  crews: DataArchitectureCrew[]
  edges: DataArchitectureCrewEdge[]
}

export interface AgentGraphOptions {
  /** Square side of the drawing surface, in user units. */
  size?: number
}

export interface PlacedNode {
  /** The crew id, or the orchestrator's agent id. Both are permanent, so both make stable keys. */
  id: string
  kind: 'orchestrator' | 'crew'
  clusterId: string
  label: string
  x: number
  y: number
  /** Degrees clockwise from twelve o'clock. The orchestrator, being central, has none. */
  angle: number | null
  /** Position on the ring, counting clockwise from twelve o'clock. 0 for an orchestrator. */
  ringPosition: number
  radius: number
  /** True when this crew declares a defect: a flow through it is a flow that does not happen. */
  broken: boolean
  /** True when the cluster's own orchestrator can start this crew. */
  dispatched: boolean
  /** Where the label sits, and which way it runs. */
  labelX: number
  labelY: number
  labelAnchor: 'start' | 'middle' | 'end'
}

export interface PlacedEdge extends DataArchitectureCrewEdge {
  /** `source` and `target` again, joined - a stable React key that cannot collide. */
  id: string
  path: string
}

export interface PlacedSpoke {
  id: string
  clusterId: string
  crewId: string
  path: string
}

export interface AgentGraphLayout {
  size: number
  nodes: PlacedNode[]
  edges: PlacedEdge[]
  spokes: PlacedSpoke[]
}

const CREW_RADIUS = 26
const ORCHESTRATOR_RADIUS = 34
/** How far an edge stops short of the node it points at, so the arrowhead stays visible. */
const CLEARANCE = 7

/** Two decimals, so the same input yields a byte-identical path string on every call. */
function r2(value: number): number {
  return Math.round(value * 100) / 100
}

interface Point {
  x: number
  y: number
}

function onCircle(centre: Point, radius: number, degrees: number): Point {
  const radians = (degrees * Math.PI) / 180
  return { x: centre.x + radius * Math.cos(radians), y: centre.y + radius * Math.sin(radians) }
}

/** Move `from` towards `to` by `distance`, so an edge stops at the rim rather than the centre. */
function trim(from: Point, to: Point, distance: number): Point {
  const dx = to.x - from.x
  const dy = to.y - from.y
  const length = Math.hypot(dx, dy) || 1
  return { x: from.x + (dx / length) * distance, y: from.y + (dy / length) * distance }
}

function line(from: Point, to: Point): string {
  return `M ${r2(from.x)} ${r2(from.y)} L ${r2(to.x)} ${r2(to.y)}`
}

/**
 * The whole picture, for one or many clusters.
 *
 * Cluster centres are themselves radial: one cluster sits in the middle of the surface, and
 * several sit on a ring of their own, evenly spaced and starting at twelve o'clock. Nothing here
 * asks how many clusters there are and branches on the answer beyond that single radius, which is
 * what makes a second PMO a data change rather than a rewrite.
 */
export function layoutAgentGraph(
  input: AgentGraphInput,
  options: AgentGraphOptions = {},
): AgentGraphLayout {
  const size = options.size ?? 720
  const surface: Point = { x: size / 2, y: size / 2 }
  const clusterCount = input.clusters.length
  // With one cluster the whole surface is its own; with several, each takes an equal share and
  // sits far enough out that the rings do not overlap.
  const clusterRing = clusterCount > 1 ? size * 0.27 : 0
  const ringRadius = clusterCount > 1 ? size * 0.13 : size * 0.31

  const crewsById = new Map(input.crews.map((crew) => [crew.crew_id, crew]))
  const nodes: PlacedNode[] = []
  const spokes: PlacedSpoke[] = []
  const centres = new Map<string, Point>()

  input.clusters.forEach((cluster, clusterIndex) => {
    const centre =
      clusterCount > 1
        ? onCircle(surface, clusterRing, -90 + (360 / clusterCount) * clusterIndex)
        : surface
    centres.set(cluster.cluster_id, centre)

    nodes.push({
      id: cluster.orchestrator_id,
      kind: 'orchestrator',
      clusterId: cluster.cluster_id,
      label: cluster.orchestrator,
      x: r2(centre.x),
      y: r2(centre.y),
      angle: null,
      ringPosition: 0,
      radius: ORCHESTRATOR_RADIUS,
      broken: false,
      dispatched: false,
      labelX: r2(centre.x),
      labelY: r2(centre.y + ORCHESTRATOR_RADIUS + 16),
      labelAnchor: 'middle',
    })

    const dispatched = new Set(cluster.dispatches)
    cluster.crew_ids.forEach((crewId, index) => {
      // Clockwise from twelve o'clock. In SVG, y grows downward, so an increasing angle from
      // -90 degrees runs clockwise - the same direction a reader traces the pipeline.
      const angle = -90 + (360 / cluster.crew_ids.length) * index
      const point = onCircle(centre, ringRadius, angle)
      const labelPoint = onCircle(centre, ringRadius + CREW_RADIUS + 12, angle)
      const cos = Math.cos((angle * Math.PI) / 180)
      const crew = crewsById.get(crewId)
      nodes.push({
        id: crewId,
        kind: 'crew',
        clusterId: cluster.cluster_id,
        label: crew?.display_name ?? crewId,
        x: r2(point.x),
        y: r2(point.y),
        angle: r2(((angle + 90) % 360 + 360) % 360),
        ringPosition: index + 1,
        radius: CREW_RADIUS,
        broken: Boolean(crew?.defect),
        dispatched: dispatched.has(crewId),
        labelX: r2(labelPoint.x),
        labelY: r2(labelPoint.y),
        // Labels run outward: away from the ring on the right, back towards it on the left, and
        // centred top and bottom. Nine of them never meet, with no collision pass at all.
        labelAnchor: Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end',
      })

      if (dispatched.has(crewId)) {
        spokes.push({
          id: `${cluster.cluster_id}:${crewId}`,
          clusterId: cluster.cluster_id,
          crewId,
          path: line(
            trim(centre, point, ORCHESTRATOR_RADIUS + 2),
            trim(point, centre, CREW_RADIUS + CLEARANCE),
          ),
        })
      }
    })
  })

  const placed = new Map(nodes.map((node) => [node.id, node]))
  const ringOf = new Map<string, { centre: Point; count: number }>()
  input.clusters.forEach((cluster) => {
    cluster.crew_ids.forEach((crewId) =>
      ringOf.set(crewId, {
        centre: centres.get(cluster.cluster_id)!,
        count: cluster.crew_ids.length,
      }),
    )
  })

  const edges: PlacedEdge[] = input.edges
    .filter((edge) => placed.has(edge.source) && placed.has(edge.target))
    .map((edge) => {
      const from = placed.get(edge.source)!
      const to = placed.get(edge.target)!
      return { ...edge, id: `${edge.source}->${edge.target}`, path: edgePath(from, to, ringOf) }
    })

  return { size, nodes, edges, spokes }
}

/**
 * One edge's `d`, chosen by where its two crews sit rather than by what kind of edge it is.
 *
 * Three cases, and each is a reading of the picture rather than a decoration:
 *
 * - **Neighbours on one ring** follow the ring itself, so the pipeline reads as a clockwise flow
 *   rather than as a polygon of chords.
 * - **Further apart on one ring** cut across, bowed towards the centre in proportion to the arc
 *   they skip, so two long edges over the same ground stay distinguishable.
 * - **Different rings** - a flow between clusters - run straight, because a curve between two
 *   centres reads as belonging to one of them.
 */
function edgePath(
  from: PlacedNode,
  to: PlacedNode,
  ringOf: Map<string, { centre: Point; count: number }>,
): string {
  const ring = ringOf.get(from.id)
  const sameRing = from.clusterId === to.clusterId && ring !== undefined
  const start = { x: from.x, y: from.y }
  const end = { x: to.x, y: to.y }

  if (!sameRing) {
    return line(
      trim(start, end, from.radius + 2),
      trim(end, start, to.radius + CLEARANCE),
    )
  }

  const { centre, count } = ring
  const steps = Math.abs(to.ringPosition - from.ringPosition)
  const radius = Math.hypot(start.x - centre.x, start.y - centre.y)
  // The angle a node subtends at the centre, used to stop the arc short of the node it points at.
  const clear = ((from.radius + CLEARANCE) / radius) * (180 / Math.PI)
  const sweep = to.ringPosition > from.ringPosition ? 1 : 0
  const direction = sweep === 1 ? 1 : -1
  const fromAngle = -90 + (360 / count) * (from.ringPosition - 1)
  const toAngle = -90 + (360 / count) * (to.ringPosition - 1)

  if (steps === 1) {
    const a = onCircle(centre, radius, fromAngle + direction * clear)
    const b = onCircle(centre, radius, toAngle - direction * clear)
    return `M ${r2(a.x)} ${r2(a.y)} A ${r2(radius)} ${r2(radius)} 0 0 ${sweep} ${r2(b.x)} ${r2(b.y)}`
  }

  const a = onCircle(centre, radius, fromAngle + direction * clear)
  const b = onCircle(centre, radius, toAngle - direction * clear)
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  // The further the two crews are apart on the ring, the deeper the chord bows towards the
  // centre - so a long edge and a longer one over the same ground do not lie on top of each other.
  const bow = Math.min(0.72, 0.18 + (steps / count) * 0.6)
  const control = {
    x: mid.x + (centre.x - mid.x) * bow,
    y: mid.y + (centre.y - mid.y) * bow,
  }
  return `M ${r2(a.x)} ${r2(a.y)} Q ${r2(control.x)} ${r2(control.y)} ${r2(b.x)} ${r2(b.y)}`
}
