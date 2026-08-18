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
// the banding `agents/graph.py` already computes with Kahn's algorithm and hands over in
// `cluster.crew_bands`, so the picture cannot disagree with the pipeline order the tables show.
//
// **A position on the ring is a band, not a crew.** Two crews that wait on the same thing and on
// nothing of each other's are parallel: `assessment_design` and `stakeholder_management` both
// wait on the value chain, and both feed the interviews. Placing one at position two and the
// other at position three would assert an ordering that no declaration makes - and it is the
// ordering a reader would act on. So each band takes one angle, and the crews in it are stacked
// along that same radius: identical angle, so neither is clockwise of the other, at different
// distances from the centre so they can both be seen. A second PMO and a coding team are
// parallel clusters by definition, and this is the same arithmetic one level in.
//
// The ring is pulled inward by however deep the widest band is, so the outermost crew of every
// band sits exactly where a ring of single crews would - the drawing keeps its envelope, and the
// labels outside it keep their room, whatever the banding turns out to be.
//
// **Labels do not collide, and no force resolves them either.** A crew alone in its band has its
// label radially outward from it, anchored by quadrant - text runs away from the circle on the
// right, towards it on the left - so labels diverge with the nodes rather than crowding a fixed
// side. In a band of several, the outermost crew keeps that outward label, since it has the room;
// the crews stacked behind it would otherwise put their labels on top of it, so theirs step
// sideways instead, perpendicular to the band's own radius.
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
  /**
   * Degrees clockwise from twelve o'clock. The orchestrator, being central, has none.
   *
   * Every crew in a band has the same one - that is what makes them read as parallel.
   */
  angle: number | null
  /**
   * Which band this crew is in, counting clockwise from twelve o'clock. 0 for an orchestrator.
   *
   * Shared by every crew in the band, so it is a position in the pipeline rather than a
   * position in a list: two crews numbered 2 wait on the same thing and on nothing of each
   * other's.
   */
  band: number
  /**
   * Distance from its cluster's centre. Crews in a band are stacked along one radius, so this
   * is what separates them, and it is the only thing that does.
   */
  orbit: number
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
/** How far apart two crews in one band are stacked along their shared radius. */
const BAND_GAP = 58
/** No crew is stacked closer to the centre than this, or it would sit on the orchestrator. */
const MIN_ORBIT = ORCHESTRATOR_RADIUS + CREW_RADIUS + 12
/** How far a label sits from the edge of its own node. */
const LABEL_GAP = 12

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
      band: 0,
      orbit: 0,
      radius: ORCHESTRATOR_RADIUS,
      broken: false,
      dispatched: false,
      labelX: r2(centre.x),
      labelY: r2(centre.y + ORCHESTRATOR_RADIUS + 16),
      labelAnchor: 'middle',
    })

    const dispatched = new Set(cluster.dispatches)
    // The deepest band decides how far the ring is drawn in, so that the outermost crew of
    // every band lands on the radius a ring of single crews would have used.
    const deepest = cluster.crew_bands.reduce((most, band) => Math.max(most, band.length), 1)
    const stack = (deepest - 1) * BAND_GAP
    const bandOrbit = Math.max(MIN_ORBIT + stack / 2, ringRadius - stack / 2)

    cluster.crew_bands.forEach((band, bandIndex) => {
      // Clockwise from twelve o'clock. In SVG, y grows downward, so an increasing angle from
      // -90 degrees runs clockwise - the same direction a reader traces the pipeline. One
      // angle per band, so parallel crews are at the same point in the sweep rather than at
      // consecutive ones.
      const angle = -90 + (360 / cluster.crew_bands.length) * bandIndex
      // Perpendicular to the band's own radius, clockwise. Where a band's labels step aside.
      const sideways = onCircle({ x: 0, y: 0 }, 1, angle + 90)

      band.forEach((crewId, member) => {
        // Symmetric about the band's radius, so the stack grows in both directions and the
        // band stays centred on the sweep. The order within a band is the order the payload
        // gives, and it is not a claim: both crews are at the same angle.
        const orbit = bandOrbit + (member - (band.length - 1) / 2) * BAND_GAP
        const point = onCircle(centre, orbit, angle)
        const outermost = member === band.length - 1
        // The outermost crew of a band has open space beyond the ring, so its label runs
        // outward as every label used to. The crews stacked behind it do not - their label
        // would land on the node in front - so theirs go sideways from their own node instead.
        const labelPoint = outermost
          ? onCircle(centre, orbit + CREW_RADIUS + LABEL_GAP, angle)
          : {
              x: point.x + sideways.x * (CREW_RADIUS + LABEL_GAP),
              y: point.y + sideways.y * (CREW_RADIUS + LABEL_GAP),
            }
        // Anchored by where the label itself ended up rather than by the node's angle, so the
        // rule holds for a label that stepped sideways as well as for one that ran outward.
        const labelCos =
          (labelPoint.x - centre.x) / (Math.hypot(labelPoint.x - centre.x, labelPoint.y - centre.y) || 1)
        const crew = crewsById.get(crewId)
        nodes.push({
          id: crewId,
          kind: 'crew',
          clusterId: cluster.cluster_id,
          label: crew?.display_name ?? crewId,
          x: r2(point.x),
          y: r2(point.y),
          angle: r2(((angle + 90) % 360 + 360) % 360),
          band: bandIndex + 1,
          orbit,
          radius: CREW_RADIUS,
          broken: Boolean(crew?.defect),
          dispatched: dispatched.has(crewId),
          labelX: r2(labelPoint.x),
          labelY: r2(labelPoint.y),
          // Labels run outward: away from the ring on the right, back towards it on the left,
          // and centred top and bottom, so two on opposite sides diverge instead of meeting.
          labelAnchor: Math.abs(labelCos) < 0.25 ? 'middle' : labelCos > 0 ? 'start' : 'end',
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
  })

  const placed = new Map(nodes.map((node) => [node.id, node]))
  const ringOf = new Map<string, { centre: Point; bands: number }>()
  input.clusters.forEach((cluster) => {
    cluster.crew_bands.forEach((band) =>
      band.forEach((crewId) =>
        ringOf.set(crewId, {
          centre: centres.get(cluster.cluster_id)!,
          bands: cluster.crew_bands.length,
        }),
      ),
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
 * Four cases, and each is a reading of the picture rather than a decoration:
 *
 * - **Neighbouring bands, both crews the same distance out** follow the ring itself, so the
 *   pipeline reads as a clockwise flow rather than as a polygon of chords.
 * - **Neighbouring bands at different distances** - one of them stacked in a band of several -
 *   take the same curve generalised: a quadratic through the mid-angle, pushed out by
 *   `1 / cos(half the angle)`, which *is* the arc when the two distances are equal. So a
 *   parallel pair does not draw its two edges in two different idioms.
 * - **Further apart on one ring** cut across, bowed towards the centre in proportion to the arc
 *   they skip, so two long edges over the same ground stay distinguishable.
 * - **Within one band, or between rings** run straight. Two crews in a band share an angle, so
 *   there is no arc between them - only the radius they are stacked along; and a curve between
 *   two cluster centres reads as belonging to one of them.
 */
function edgePath(
  from: PlacedNode,
  to: PlacedNode,
  ringOf: Map<string, { centre: Point; bands: number }>,
): string {
  const ring = ringOf.get(from.id)
  const sameRing = from.clusterId === to.clusterId && ring !== undefined
  const start = { x: from.x, y: from.y }
  const end = { x: to.x, y: to.y }
  const straight = () =>
    line(trim(start, end, from.radius + 2), trim(end, start, to.radius + CLEARANCE))

  if (!sameRing) return straight()

  const { centre, bands } = ring
  const steps = Math.abs(to.band - from.band)
  if (steps === 0) return straight()

  const direction = to.band > from.band ? 1 : -1
  const sweep = direction === 1 ? 1 : 0
  const fromAngle = -90 + (360 / bands) * (from.band - 1)
  const toAngle = -90 + (360 / bands) * (to.band - 1)
  // The angle a node subtends at its own distance from the centre, used to stop the line short
  // of the node it points at. Per end, because the two ends need not be equally far out.
  const degrees = 180 / Math.PI
  const a = onCircle(
    centre, from.orbit, fromAngle + direction * ((from.radius + CLEARANCE) / from.orbit) * degrees,
  )
  const b = onCircle(
    centre, to.orbit, toAngle - direction * ((to.radius + CLEARANCE) / to.orbit) * degrees,
  )

  if (steps === 1 && from.orbit === to.orbit) {
    const radius = from.orbit
    return `M ${r2(a.x)} ${r2(a.y)} A ${r2(radius)} ${r2(radius)} 0 0 ${sweep} ${r2(b.x)} ${r2(b.y)}`
  }

  if (steps === 1) {
    // Clamped at sixty degrees: with only two or three bands the neighbouring angle is wide
    // enough that `1 / cos` runs away, and a control point at infinity draws nothing.
    const half = Math.min(180 / bands, 60)
    const control = onCircle(
      centre,
      ((from.orbit + to.orbit) / 2) / Math.cos((half * Math.PI) / 180),
      (fromAngle + toAngle) / 2,
    )
    return `M ${r2(a.x)} ${r2(a.y)} Q ${r2(control.x)} ${r2(control.y)} ${r2(b.x)} ${r2(b.y)}`
  }

  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  // The further the two crews are apart on the ring, the deeper the chord bows towards the
  // centre - so a long edge and a longer one over the same ground do not lie on top of each other.
  const bow = Math.min(0.72, 0.18 + (steps / bands) * 0.6)
  const control = {
    x: mid.x + (centre.x - mid.x) * bow,
    y: mid.y + (centre.y - mid.y) * bow,
  }
  return `M ${r2(a.x)} ${r2(a.y)} Q ${r2(control.x)} ${r2(control.y)} ${r2(b.x)} ${r2(b.y)}`
}
