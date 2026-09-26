// ui/src/components/ReviewDialog.tsx
import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ValidationWarnings from './ValidationWarnings'
import { X, Check, PauseCircle, Download, XCircle, Lock } from 'lucide-react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { projectsApi } from '../api/endpoints'
import { describeError } from '../utils/describeError'
import { CREW_LABELS } from './agentStatus'
import { CREW_OUTPUT_TYPE } from './crewOutputs'
import type { HumanReview, AgentOutput } from '../types'

// Re-exported so existing importers of CREW_OUTPUT_TYPE from this file keep working now that
// it lives in crewOutputs.ts, shared with the agent panel's Output tab.
export { CREW_OUTPUT_TYPE }

/** Strip 'Please review…' header and 'Reply approved…' footer from HITL prompts. */
function stripHitlBoilerplate(prompt: string): string {
  const lines = prompt.trim().split('\n')
  let start = 0
  let end = lines.length
  if (lines[0]?.toLowerCase().startsWith('please review')) start = 1
  while (start < end && !lines[start]?.trim()) start++
  while (end > start && !lines[end - 1]?.trim()) end--
  const last = lines[end - 1] ?? ''
  if (last.toLowerCase().includes('reply') && last.toLowerCase().includes('approved')) end--
  while (end > start && !lines[end - 1]?.trim()) end--
  return lines.slice(start, end).join('\n').trim()
}

function MarkdownBody({ text }: { text: string }) {
  const raw = marked.parse(text, { async: false }) as string
  const html = DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
  return (
    <div
      className="prose prose-sm max-w-none text-gray-800 [&_ul]:mt-1 [&_li]:my-0.5 [&_p]:my-1"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

const MERMAID_TYPES = new Set(['value_chain', 'architecture', 'roadmap'])

// ── SVG download helper ───────────────────────────────────────────────────────

function downloadSvg(container: HTMLDivElement | null, filename: string) {
  const svgEl = container?.querySelector('svg')
  if (!svgEl) return
  const serialized = new XMLSerializer().serializeToString(svgEl)
  const blob = new Blob([serialized], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Thumbnail view ────────────────────────────────────────────────────────────

export function MermaidThumbnail({ content, id, filename }: { content: string; id: string; filename: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ref.current) return
    let cancelled = false

    ;(async () => {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'strict' })
        const fenceMatch = content.match(/```(?:mermaid)?\s*([\s\S]+?)```/)
        const diagram = fenceMatch ? fenceMatch[1].trim() : content.trim()
        const { svg } = await mermaid.render(`mermaid-thumb-${id}-${Date.now()}`, diagram)
        if (cancelled || !ref.current) return
        // text/html parser handles <br> in foreignObject; image/svg+xml (strict XML) does not
        const htmlDoc = new DOMParser().parseFromString(svg, 'text/html')
        const svgEl = htmlDoc.querySelector('svg')
        if (!svgEl) throw new Error('No SVG in Mermaid output')
        ref.current.replaceChildren(svgEl)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    })()

    return () => { cancelled = true }
  }, [content, id])

  if (error) return (
    <pre className="text-xs text-red-600 whitespace-pre-wrap bg-red-50 p-3 rounded-lg border border-red-200 overflow-x-auto">
      {content}
    </pre>
  )

  return (
    <div className="relative overflow-x-auto rounded-lg border border-gray-200 bg-white p-2 group/thumb">
      <div ref={ref} />
      {!error && (
        <button
          onClick={e => { e.stopPropagation(); downloadSvg(ref.current, filename) }}
          title="Download SVG"
          className="absolute top-2 right-2 opacity-0 group-hover/thumb:opacity-100 transition-opacity bg-white/90 hover:bg-white border border-gray-200 rounded-md px-2 py-1 text-[10px] font-medium text-gray-600 hover:text-gray-900 shadow-sm flex items-center gap-1"
        >
          <span className="flex items-center gap-1"><Download size={10} />SVG</span>
        </button>
      )}
    </div>
  )
}

// ── Full-height lightbox with pan/zoom canvas ─────────────────────────────────

const ZOOM_STEP = 0.25
const MIN_ZOOM = 0.25
const MAX_ZOOM = 4.0

export function DiagramLightbox({ content, outputId, filename, onClose }: {
  content: string
  outputId: string
  filename: string
  onClose: () => void
}) {
  const svgRef    = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef   = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  // Refs mirror state so the non-React wheel listener always sees current values
  const zoomRef   = useRef(1.0)
  const panRef    = useRef({ x: 16, y: 16 })

  const [error,    setError]    = useState<string | null>(null)
  const [zoom,     setZoom]     = useState(1.0)
  const [pan,      setPan]      = useState({ x: 16, y: 16 })
  const [dragging, setDragging] = useState(false)

  // Keep refs in sync with state
  useEffect(() => { zoomRef.current = zoom }, [zoom])
  useEffect(() => { panRef.current  = pan  }, [pan])

  useEffect(() => {
    if (!svgRef.current) return
    let cancelled = false
    ;(async () => {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'strict' })
        const fenceMatch = content.match(/```(?:mermaid)?\s*([\s\S]+?)```/)
        const diagram = fenceMatch ? fenceMatch[1].trim() : content.trim()
        const { svg } = await mermaid.render(`mermaid-lb-${outputId}-${Date.now()}`, diagram)
        if (cancelled || !svgRef.current) return
        const htmlDoc = new DOMParser().parseFromString(svg, 'text/html')
        const svgEl = htmlDoc.querySelector('svg')
        if (!svgEl) throw new Error('No SVG in Mermaid output')
        // Mermaid often emits width="100%" which collapses inside an absolute
        // wrapper with no explicit size. Pin to viewBox pixel dimensions so
        // zoom=1 renders at 1 SVG unit = 1 CSS pixel (genuinely 100%).
        const vbParts = svgEl.getAttribute('viewBox')?.split(/[\s,]+/).map(parseFloat)
        const vbW = vbParts?.[2] ?? 0
        const vbH = vbParts?.[3] ?? 0
        if (vbW > 0 && vbH > 0) {
          svgEl.setAttribute('width',  String(vbW))
          svgEl.setAttribute('height', String(vbH))
        } else {
          svgEl.removeAttribute('width')
          svgEl.removeAttribute('height')
        }
        svgEl.style.cssText = 'display:block;max-width:none'
        svgRef.current.replaceChildren(svgEl)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    })()
    return () => { cancelled = true }
  }, [content, outputId])

  // Non-passive wheel listener — reads from refs, never stale
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    function onWheel(e: WheelEvent) {
      e.preventDefault()
      const z = zoomRef.current
      const p = panRef.current
      const delta = e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, +(z + delta).toFixed(2)))
      const rect  = el!.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const scale = next / z
      const newPan = { x: mx - scale * (mx - p.x), y: my - scale * (my - p.y) }
      setZoom(next)
      setPan(newPan)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  function onMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return
    e.preventDefault()
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y }
    setDragging(true)
  }
  function onMouseMove(e: React.MouseEvent) {
    if (!dragRef.current) return
    setPan({
      x: dragRef.current.panX + e.clientX - dragRef.current.startX,
      y: dragRef.current.panY + e.clientY - dragRef.current.startY,
    })
  }
  function onMouseUp() { dragRef.current = null; setDragging(false) }

  // Button zoom — reads current values directly, no updater nesting
  function zoomStep(delta: number) {
    const z    = zoomRef.current
    const p    = panRef.current
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, +(z + delta).toFixed(2)))
    if (canvasRef.current) {
      const { width, height } = canvasRef.current.getBoundingClientRect()
      const cx = width / 2
      const cy = height / 2
      const scale = next / z
      setPan({ x: cx - scale * (cx - p.x), y: cy - scale * (cy - p.y) })
    }
    setZoom(next)
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-[60]" onClick={onClose} />
      <div className="fixed inset-4 z-[60] flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 flex-shrink-0">
          <p className="text-sm font-semibold text-gray-700">Output diagram</p>
          <div className="flex items-center gap-3">
            <p className="text-[10px] text-gray-400 select-none">Scroll to zoom · drag to pan</p>
            <div className="flex items-center gap-1 border border-gray-200 rounded-lg overflow-hidden">
              <button onClick={() => zoomStep(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM}
                className="px-2.5 py-1 text-sm font-bold text-gray-600 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                aria-label="Zoom out">−</button>
              <span className="px-2 text-xs font-medium text-gray-500 border-x border-gray-200 min-w-[3.5rem] text-center">
                {Math.round(zoom * 100)}%
              </span>
              <button onClick={() => zoomStep(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM}
                className="px-2.5 py-1 text-sm font-bold text-gray-600 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                aria-label="Zoom in">+</button>
            </div>
            <button
              onClick={() => downloadSvg(svgRef.current, filename)}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-600 hover:text-gray-900 transition-colors"
            >
              <Download size={12} /> Download SVG
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
              <X size={14} />
            </button>
          </div>
        </div>
        {/* Canvas */}
        <div
          ref={canvasRef}
          className="flex-1 min-h-0 overflow-hidden relative"
          style={{ cursor: dragging ? 'grabbing' : 'grab' }}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          {error
            ? <pre className="text-xs text-red-600 whitespace-pre-wrap p-4">{content}</pre>
            : <div
                style={{
                  position: 'absolute',
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  transformOrigin: '0 0',
                }}
              >
                <div ref={svgRef} />
              </div>
          }
        </div>
      </div>
    </>
  )
}

// ── Content preview ───────────────────────────────────────────────────────────

export function OutputPreview({ slug, output }: { slug: string; output: AgentOutput }) {
  const [lightboxOpen, setLightboxOpen] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['output-content', slug, output.id],
    queryFn: () => projectsApi.getOutputContent(slug, output.id),
  })

  if (isLoading) return (
    <div className="animate-pulse h-24 rounded-lg bg-gray-100 flex items-center justify-center">
      <span className="text-xs text-gray-400">Loading output…</span>
    </div>
  )

  if (isError || !data) return (
    <p className="text-xs text-red-500 italic">Could not load output content.</p>
  )

  if (MERMAID_TYPES.has(output.output_type)) {
    const svgFilename = `${output.output_type}-v${output.version}.svg`
    return (
      <>
        <div
          role="button"
          tabIndex={0}
          onClick={() => setLightboxOpen(true)}
          onKeyDown={e => e.key === 'Enter' && setLightboxOpen(true)}
          className="relative group cursor-zoom-in rounded-lg"
          title="Click to enlarge"
        >
          <MermaidThumbnail content={data.content} id={String(output.id)} filename={svgFilename} />
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity rounded-lg bg-black/10 pointer-events-none">
            <span className="bg-white/90 text-gray-700 text-xs font-medium px-3 py-1 rounded-full shadow">
              Click to enlarge ⤢
            </span>
          </div>
        </div>
        {lightboxOpen && (
          <DiagramLightbox
            content={data.content}
            outputId={String(output.id)}
            filename={svgFilename}
            onClose={() => setLightboxOpen(false)}
          />
        )}
      </>
    )
  }

  try {
    const parsed = JSON.parse(data.content)
    return (
      <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto max-h-72 overflow-y-auto font-mono leading-relaxed">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    )
  } catch {
    return (
      <pre className="text-xs text-gray-700 whitespace-pre-wrap break-words bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto max-h-72 overflow-y-auto leading-relaxed">
        {data.content}
      </pre>
    )
  }
}

// ── ReviewDialog ──────────────────────────────────────────────────────────────

type ReviewIntent = 'change_request' | 'correction' | 'skill'

// Declared (not cast) so a typo'd intent fails to compile rather than shipping a value the
// API will 422 on.
//
// That comment used to end "- handleSubmit's try/finally has no catch, so a rejected request
// would otherwise vanish silently from the reviewer's point of view", and it was describing a
// live defect rather than guarding against one: neither handler had a catch, so *every*
// refusal vanished, not only a 422 on a typo'd intent. An owner on a live engagement clicked
// Approve, the door answered 403 "Only a reviewer or approver may resolve a review", the
// promise rejected, `finally` reset the spinner, and the dialog sat there unchanged. CLAUDE.md
// calls this shape out by name - quoting a rule is not applying it - and the citation did
// active harm here, because it read to every later reader as evidence the hazard had been
// accounted for. Both handlers catch now, and the reviewer is shown the server's own sentence.
// Which structural warnings belong to which crew. A warning is only useful beside the
// artefact it concerns: Alex's tree findings on his review, Casey's anchor findings on
// hers.
export const CREW_WARNING_SOURCE: Record<string, string> = {
  discovery_mapping: 'value_chain_tree',
  discovery_interviews: 'theme_anchor',
  // Matches _WARNING_SOURCE_CREW in api/services/run_service.py. Maps a crew to a single
  // source - assessment_design's own interview_coverage warnings are not shown here either,
  // a pre-existing gap this entry does not touch. script_ledger_registration is picked
  // because a registration failure is the more actionable of the two: it names a specific
  // script id that must be rewritten, not a coverage gap that resolves itself as Maya
  // writes more scripts.
  assessment_design: 'script_ledger_registration',
}

// What each choice does, in the reviewer's language and truthfully.
//
// The third used to say "Do this on every project - becomes a capability this agent uses
// everywhere", and it did neither: it set a column nothing read. It now files the reviewer's
// sentence on the skills queue, where a human approves it and decides at that moment whether
// it applies to this engagement or to all of them - the narrow answer being the default. The
// copy says so, because a control promising to change an agent's behaviour everywhere is
// exactly what the scope decision exists to stop happening without anybody choosing it.
const INTENT_OPTIONS: [ReviewIntent, string, string][] = [
  ['change_request', 'Fix this output', 'Applies to the next run only.'],
  ['correction', 'This is true of this client', 'Becomes a standing fact for this client.'],
  ['skill', 'Make this a standing rule for this agent',
   'Goes to the skills queue - nothing changes until a reviewer approves it, and they decide whether it applies here or everywhere.'],
]

/** Why the three decision controls are not on screen, and what to do about it.
 *
 *  A gated control owes the reader a reason. CLAUDE.md states it for `PlatformTierNote` on the
 *  Settings page - a greyed or absent control with no explanation beside it reads as a bug, and
 *  the reader's next move is to reload the page rather than to ask somebody - and the shape it
 *  prescribes is this one: `data-explains` naming the controls the note accounts for, so the
 *  association is something the DOM carries rather than something proximity implies.
 *
 *  It exists because of a state nothing in the product previously said anything about. A
 *  newly created engagement has no stakeholders, and `caller_roles` reads content authority
 *  from a stakeholder row - so on a fresh project *nobody* holds it, including the consultant
 *  who created the engagement, configured it and started the run. They hold total
 *  administration and no content authority at all, which is the design working as intended on
 *  both axes and unusable where they meet. See tests/test_new_project_approval_bootstrap.py,
 *  which pins the dead end and the route out.
 *
 *  The sentence is about the **caller**, deliberately, and not about the roster. "Nobody on
 *  this engagement can approve anything" is the more useful diagnosis and this component cannot
 *  honestly make it - it would need a roster read, and a note that overstates what it knows is
 *  worse than one that is merely narrow. What it can say, truthfully and without another
 *  request, is which axis the refusal came from and which door grants it. */
function ContentAuthorityNote({ reason }: { reason: 'refused' | 'unknown' }) {
  return (
    <p
      data-explains="approve revise reject"
      className="text-xs text-muted leading-relaxed flex items-start gap-1.5"
    >
      <Lock size={12} className="mt-0.5 shrink-0" />
      {/* Two sentences, because the two states owe the reader different things to do. Telling a
          consultant to add a stakeholder when the truth is that the permissions request failed
          sends them to reconfigure an engagement that was never misconfigured - the same class
          of harm as the knowledge-tier refusal that named the wrong verb. */}
      {reason === 'refused' ? (
        <span>
          Deciding on an agent's output is a content role, read from your stakeholder record on
          this engagement - administering the project does not confer it, and a new engagement
          starts with no stakeholders at all. Add yourself or a colleague on the Stakeholders tab
          with the Reviewer or Approver role and send the invite; redeeming it grants the
          authority this gate is waiting for.
        </span>
      ) : (
        <span>
          Your authority on this engagement could not be checked, so no decision is offered -
          the crew is still waiting and nothing has been recorded. Reopen this review to try
          again.
        </span>
      )}
    </p>
  )
}

export interface ReviewDialogProps {
  slug: string
  review: HumanReview
  outputs: AgentOutput[]
  onClose: () => void
}

export default function ReviewDialog({ slug, review, outputs, onClose }: ReviewDialogProps) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'idle' | 'revise' | 'reject'>('idle')
  const [notes, setNotes] = useState('')
  const [intent, setIntent] = useState<ReviewIntent>('change_request')
  const [submitting, setSubmitting] = useState(false)
  // The refusal the door gave, in the door's own words. Held in state rather than thrown at a
  // boundary because there is no error boundary anywhere on this dialog's route, and a reviewer
  // needs the sentence beside the control they just pressed.
  const [error, setError] = useState<string | null>(null)

  // Whether this caller may resolve this review, asked of the server rather than restated here.
  //
  // `can_review`, **not** `can_approve`. All three controls in this dialog post to
  // `PATCH /projects/{slug}/reviews/{id}`, and that door asks `caller_may_contribute` -
  // `{reviewer, approver}` - so a `reviewer` may approve a HITL gate, and gating on
  // `can_approve` would hide the button from a caller the door accepts. `DiscoveryReviewExtra`
  // reads `can_approve` correctly for its own Approve, because the item-review door asks
  // `caller_may_approve` when the decision is `approved`. Two doors, two predicates; the rule
  // is to read the one the door being called actually refuses with.
  const { data: permissions, isError: authorityUnknown } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug),
  })
  // Four states, not two, and the two middle ones are the ones worth spelling out.
  //
  // In flight: neither the controls nor a note. Collapsing that into "not permitted" would flash
  // a note claiming the reviewer lacks an authority they may well hold, and collapsing it the
  // other way gives a button that appears and then refuses.
  //
  // The request *failed*: no controls - an unanswered authority question must never open one -
  // but a note all the same, and a different one. That arm was missing from the first version of
  // this change and its own test found it: `isError` leaves `data` undefined, so the footer
  // rendered completely empty, no control and no explanation, which is the exact "greyed out
  // with no reason given" failure the note exists to prevent.
  const mayResolve = permissions?.can_review
  const explainWhyNotOffered: 'refused' | 'unknown' | null =
    mayResolve === false ? 'refused' : authorityUnknown ? 'unknown' : null

  const outputType = review.crew_name ? CREW_OUTPUT_TYPE[review.crew_name] : undefined
  const matchedOutput = outputType ? outputs.find(o => o.output_type === outputType) : undefined
  const crewLabel = review.crew_name ? (CREW_LABELS[review.crew_name] ?? review.crew_name) : 'Crew'
  const promptBody = stripHitlBoilerplate(review.prompt ?? '')

  // The rejecting agent's snake key and human name were derived here, for the rejection-path
  // note box that has gone. The server no longer needs telling which agent a rule is about -
  // it reads `agent_outputs.agent_name` off the output the review was made against, which is
  // the same answer without a second place for it to be got wrong.

  // `describeError` is imported rather than given a fixed string, and for this door that is
  // not a stylistic preference. "Only a reviewer or approver may resolve a review" is the one
  // thing in the product that tells a consultant why their own approval is being refused -
  // administering an engagement is not reviewing its content, and no fallback phrased by this
  // component can say that. The fallback is reached only when the refusal carries no `detail`.
  //
  // The dialog stays open on a refusal. Closing it would discard the notes the reviewer typed
  // and leave the sentence nowhere to be read, and the crew is still paused on this gate.
  async function handleApprove() {
    setSubmitting(true)
    setError(null)
    try {
      await projectsApi.resolveReview(slug, review.id, 'approved', '')
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
      onClose()
    } catch (err) {
      setError(describeError(err, 'Could not approve this output.'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSubmit() {
    if (!notes.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const decision = mode === 'reject' ? 'rejected' : 'changes_requested'
      await projectsApi.resolveReview(
        slug, review.id, decision, notes.trim(), mode === 'revise' ? intent : 'change_request',
      )
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
      onClose()
    } catch (err) {
      setError(describeError(
        err,
        mode === 'reject'
          ? 'Could not record the rejection.'
          : 'Could not submit the revision request.',
      ))
    } finally {
      setSubmitting(false)
    }
  }

  function cancel() {
    setMode('idle')
    setNotes('')
    setIntent('change_request')
    setError(null)
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-50" onClick={onClose} />

      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-white rounded-2xl shadow-2xl flex flex-col w-full max-w-3xl max-h-[90vh] pointer-events-auto">

          <div className="flex items-start gap-3 px-6 py-4 border-b border-gray-200 flex-shrink-0">
            <PauseCircle size={12} className="text-amber-500 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-gray-900">{crewLabel}</p>
              <p className="text-[11px] text-amber-600 font-medium uppercase tracking-wider mt-0.5">
                Crew paused · awaiting your approval
              </p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 flex-shrink-0" aria-label="Close">
              <X size={14} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
            {promptBody && (
              <div>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Agent summary</p>
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                  <MarkdownBody text={promptBody} />
                </div>
              </div>
            )}

            {matchedOutput && (
              <div>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">
                  Output to review · {matchedOutput.output_type} v{matchedOutput.version}
                </p>
                <OutputPreview slug={slug} output={matchedOutput} />
              </div>
            )}

            {review.crew_name && CREW_WARNING_SOURCE[review.crew_name] && (
              <ValidationWarnings
                slug={slug}
                source={CREW_WARNING_SOURCE[review.crew_name]}
              />
            )}

            {mode !== 'idle' && (
              <div className="space-y-4">
                {mode === 'revise' && (
                  <div>
                    <label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-2">
                      What should happen to this feedback?
                    </label>
                    <div className="space-y-2">
                      {INTENT_OPTIONS.map(([value, label, explanation]) => (
                        <label key={value} className="flex items-start gap-2 text-sm text-primary cursor-pointer">
                          <input
                            type="radio"
                            name="intent"
                            value={value}
                            checked={intent === value}
                            onChange={() => setIntent(value)}
                            className="mt-1"
                          />
                          <span>
                            <span className="block font-medium">{label}</span>
                            <span className="block text-xs text-muted">{explanation}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
                <div>
                  <label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-2">
                    {mode === 'reject' ? 'Reason for rejection' : 'Revision notes'}{' '}
                    <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    autoFocus
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder={
                      mode === 'reject'
                        ? 'Describe why this output is being rejected…'
                        : 'Describe the changes you\'d like the agent to make…'
                    }
                    rows={4}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none"
                  />
                </div>
                {/* A second box stood here on the rejection path - "what should Maya do
                    differently next time?" - and its answer went straight into that agent's
                    prompt on every engagement, distilled by a model and approved by nobody.
                    The question is a good one and it is now asked where it can be answered
                    properly: Request revision, then "Make this a standing rule for this
                    agent", which files it on the skills queue for a human to approve and
                    scope. */}
              </div>
            )}
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex-shrink-0 bg-gray-50 rounded-b-2xl space-y-2">
            {/* In the footer rather than the scrolling body: the body can be scrolled away from
                the control that was pressed, and a refusal a reviewer has to go looking for is
                the defect this was written to close. `role="alert"` because it appears in
                response to an action rather than being present on load. */}
            {error && (
              <p role="alert" className="text-xs text-red-600 leading-relaxed">
                {error}
              </p>
            )}
            {/* Only once the server has answered no, and only where the controls it accounts
                for would otherwise be. */}
            {mode === 'idle' && explainWhyNotOffered && (
              <ContentAuthorityNote reason={explainWhyNotOffered} />
            )}
            <div className="flex items-center justify-end gap-3">
            {mode !== 'idle' ? (
              <>
                <button onClick={cancel} disabled={submitting}
                  className="text-sm text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={submitting || !notes.trim()}
                  className={`text-sm font-semibold px-5 py-2 rounded-lg disabled:opacity-40 text-white transition-colors ${
                    mode === 'reject'
                      ? 'bg-red-600 hover:bg-red-700'
                      : 'bg-amber-500 hover:bg-amber-600'
                  }`}
                >
                  {submitting
                    ? 'Submitting…'
                    : mode === 'reject'
                      ? <span className="flex items-center gap-1"><XCircle size={13} />Confirm rejection</span>
                      : 'Submit revision request'
                  }
                </button>
              </>
            ) : mayResolve ? (
              // All three post to the same door, so all three are gated on the same answer -
              // a reviewer who may not approve may not reject or send back either, and
              // offering two of the three would refuse them one click later.
              //
              // Each carries the `id` the note names in `data-explains`. That is what makes
              // the explanation checkable rather than decorative: the ids rendered here and
              // the names declared there are held equal by test, so a fourth control added to
              // this footer fails rather than shipping gated-but-unexplained, or explained
              // under a name nothing answers to. Same mechanism as the Settings page's
              // `fieldProps`, which pairs a field's `id` with its gate for the same reason.
              <>
                <button id="reject" onClick={() => setMode('reject')}
                  className="text-sm font-medium px-5 py-2 rounded-lg bg-white hover:bg-red-50 text-red-600 border border-red-200 hover:border-red-400 transition-colors flex items-center gap-1.5">
                  <XCircle size={13} />Reject
                </button>
                <button id="revise" onClick={() => setMode('revise')}
                  className="text-sm font-medium px-5 py-2 rounded-lg bg-white hover:bg-amber-50 text-amber-600 border border-amber-200 hover:border-amber-400 transition-colors">
                  Request revision
                </button>
                <button id="approve" onClick={handleApprove} disabled={submitting}
                  className="text-sm font-semibold px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white transition-colors">
                  {submitting ? 'Approving…' : <span className="flex items-center gap-1"><Check size={13} />Approve</span>}
                </button>
              </>
            ) : null}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
