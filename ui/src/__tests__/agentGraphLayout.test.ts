// ui/src/__tests__/agentGraphLayout.test.ts
//
// The layout is arithmetic, so it can be asserted exactly - and the properties worth asserting
// are the ones the page is shown to auditors for.
//
// **Determinism first.** A force simulation settles somewhere slightly different on every load;
// this must not. "The third crew clockwise" has to mean the same thing tomorrow, and a screenshot
// in a report has to match the page it came from.
//
// **Derived, not drawn, second.** Every test that fixes a position also changes the input and
// asserts the position moved. A test that only checked today's coordinates would pass against a
// hard-coded table of them, which is the failure this project keeps hitting: a property asserted
// one layer from where it holds.
import { describe, it, expect } from 'vitest'
import { layoutAgentGraph } from '../components/agentGraphLayout'
import type { AgentGraphInput } from '../components/agentGraphLayout'
import type {
  DataArchitectureCluster,
  DataArchitectureCrew,
  DataArchitectureCrewEdge,
} from '../api/dataArchitecture'

function crew(id: string, label: string): DataArchitectureCrew {
  return {
    crew_id: id,
    display_name: label,
    purpose: '',
    note: '',
    defect: null,
    cluster: 'one',
    depends_on: [],
    depends_on_ids: [],
    agents: [],
    agent_ids: [],
    triggers: [],
    trigger_ids: [],
  }
}

function cluster(
  id: string,
  crewIds: string[],
  dispatches: string[],
  orchestrator = 'orch',
): DataArchitectureCluster {
  return {
    cluster_id: id,
    label: `Cluster ${id}`,
    note: '',
    orchestrator_id: orchestrator,
    orchestrator: `Orchestrator ${orchestrator}`,
    crew_ids: crewIds,
    dispatches,
  }
}

const CREWS = ['a', 'b', 'c', 'd'].map((id) => crew(id, `Crew ${id.toUpperCase()}`))

const EDGES: DataArchitectureCrewEdge[] = [
  { source: 'a', target: 'b', kind: 'information', artefacts: ['x'], declared: true, crosses_clusters: false },
  { source: 'b', target: 'c', kind: 'sequencing', artefacts: [], declared: true, crosses_clusters: false },
  { source: 'a', target: 'd', kind: 'inherited', artefacts: ['x'], declared: false, crosses_clusters: false },
]

const ONE: AgentGraphInput = {
  clusters: [cluster('one', ['a', 'b', 'c', 'd'], ['a', 'c'])],
  crews: CREWS,
  edges: EDGES,
}

describe('the radial layout', () => {
  it('draws the same picture from the same declarations', () => {
    expect(layoutAgentGraph(ONE)).toEqual(layoutAgentGraph(ONE))
  })

  it('puts the orchestrator at the centre of its own cluster, not on the ring', () => {
    const layout = layoutAgentGraph(ONE)
    const centre = layout.nodes.find((n) => n.kind === 'orchestrator')!
    expect(centre.id).toBe('orch')
    expect(centre.x).toBe(layout.size / 2)
    expect(centre.y).toBe(layout.size / 2)
    expect(centre.ringPosition).toBe(0)
  })

  it('starts the ring at twelve o\'clock and runs clockwise', () => {
    const layout = layoutAgentGraph(ONE)
    const ring = layout.nodes.filter((n) => n.kind === 'crew')
    const centre = layout.size / 2

    // First at the top: same x as the centre, above it.
    expect(ring[0].x).toBeCloseTo(centre, 1)
    expect(ring[0].y).toBeLessThan(centre)
    // Second a quarter turn clockwise, which in screen coordinates is to the right.
    expect(ring[1].x).toBeGreaterThan(centre)
    expect(ring[1].y).toBeCloseTo(centre, 1)
    // Fourth is to the left, so the sweep went clockwise rather than anticlockwise.
    expect(ring[3].x).toBeLessThan(centre)
    expect(ring.map((n) => n.angle)).toEqual([0, 90, 180, 270])
    expect(ring.map((n) => n.ringPosition)).toEqual([1, 2, 3, 4])
  })

  it('takes the angular order from the order it is given, and not from anything else', () => {
    // The declaration moves and the picture moves with it. Reversed rather than shuffled, so no
    // crew keeps its place: alphabetical, declaration-order and reverse order all disagree here.
    const reversed = layoutAgentGraph({
      ...ONE,
      clusters: [cluster('one', ['d', 'c', 'b', 'a'], ['a', 'c'])],
    })
    const forward = layoutAgentGraph(ONE)
    const top = (l: typeof forward) => l.nodes.find((n) => n.ringPosition === 1)!.id
    expect(top(forward)).toBe('a')
    expect(top(reversed)).toBe('d')
  })

  it('draws a spoke only to a crew the orchestrator can start', () => {
    const layout = layoutAgentGraph(ONE)
    expect(layout.spokes.map((s) => s.crewId)).toEqual(['a', 'c'])
    expect(layout.nodes.filter((n) => n.dispatched).map((n) => n.id)).toEqual(['a', 'c'])
  })

  it('marks a crew that declares a defect', () => {
    const withDefect = layoutAgentGraph({
      ...ONE,
      crews: CREWS.map((c) => (c.crew_id === 'b' ? { ...c, defect: 'cannot run' } : c)),
    })
    expect(withDefect.nodes.filter((n) => n.broken).map((n) => n.id)).toEqual(['b'])
    expect(layoutAgentGraph(ONE).nodes.some((n) => n.broken)).toBe(false)
  })

  it('places every edge it is given, and nothing it is not', () => {
    const layout = layoutAgentGraph(ONE)
    expect(layout.edges.map((e) => e.id)).toEqual(['a->b', 'b->c', 'a->d'])
    for (const edge of layout.edges) expect(edge.path).toMatch(/^M /)
  })

  it('runs neighbouring edges along the ring and distant ones across it', () => {
    // Not decoration: an arc between neighbours is what makes the pipeline read as a clockwise
    // flow rather than as a polygon, and a chord is what keeps a long edge off the ring it skips.
    const layout = layoutAgentGraph(ONE)
    const byId = new Map(layout.edges.map((e) => [e.id, e.path]))
    expect(byId.get('a->b')).toContain(' A ')
    expect(byId.get('a->d')).toContain(' Q ')
  })

  it('carries each edge\'s kind and artefacts through untouched', () => {
    const layout = layoutAgentGraph(ONE)
    for (const edge of layout.edges) {
      const given = EDGES.find((e) => e.source === edge.source && e.target === edge.target)!
      expect(edge.kind).toBe(given.kind)
      expect(edge.artefacts).toEqual(given.artefacts)
    }
  })

  it('places labels away from the ring rather than over it', () => {
    const layout = layoutAgentGraph(ONE)
    const centre = layout.size / 2
    for (const node of layout.nodes.filter((n) => n.kind === 'crew')) {
      const nodeDistance = Math.hypot(node.x - centre, node.y - centre)
      const labelDistance = Math.hypot(node.labelX - centre, node.labelY - centre)
      expect(labelDistance).toBeGreaterThan(nodeDistance + node.radius)
    }
    // And they run outward: the label on the right is left-anchored, the one on the left is
    // right-anchored, so two labels on opposite sides diverge instead of meeting.
    const anchors = layout.nodes.filter((n) => n.kind === 'crew').map((n) => n.labelAnchor)
    expect(anchors).toEqual(['middle', 'start', 'middle', 'end'])
  })
})

describe('a second cluster', () => {
  const TWO: AgentGraphInput = {
    clusters: [
      cluster('one', ['a', 'b'], ['a'], 'orch'),
      cluster('two', ['c', 'd'], ['c'], 'other'),
    ],
    crews: CREWS.map((c) => ({ ...c, cluster: c.crew_id <= 'b' ? 'one' : 'two' })),
    edges: [
      ...EDGES.slice(0, 2),
      { source: 'b', target: 'c', kind: 'information', artefacts: ['y'], declared: true, crosses_clusters: true },
    ],
  }

  it('is a data addition: two centres, neither of them the middle of the page', () => {
    const layout = layoutAgentGraph(TWO)
    const centres = layout.nodes.filter((n) => n.kind === 'orchestrator')
    expect(centres.map((n) => n.id)).toEqual(['orch', 'other'])
    for (const centre of centres) {
      expect(centre.x === layout.size / 2 && centre.y === layout.size / 2).toBe(false)
    }
    // The first cluster still starts at twelve o'clock relative to its own centre.
    const first = layout.nodes.find((n) => n.id === 'a')!
    expect(first.x).toBeCloseTo(centres[0].x, 1)
    expect(first.y).toBeLessThan(centres[0].y)
  })

  it('runs an edge between two clusters straight, and keeps it flagged', () => {
    const layout = layoutAgentGraph(TWO)
    const crossing = layout.edges.find((e) => e.crosses_clusters)!
    expect(crossing.id).toBe('b->c')
    expect(crossing.path).toContain(' L ')
    expect(crossing.path).not.toContain(' A ')
  })

  it('is still the same picture on every load', () => {
    expect(layoutAgentGraph(TWO)).toEqual(layoutAgentGraph(TWO))
  })
})
