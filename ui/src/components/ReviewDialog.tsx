// ui/src/components/ReviewDialog.tsx
import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Check, PauseCircle, Download, XCircle } from 'lucide-react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { projectsApi, skillNotesApi } from '../api/endpoints'
import { AGENT_RUN_KEYS, AGENT_HUMAN_NAME } from './agentStatus'
import type { HumanReview, AgentOutput } from '../types'

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

// Maps crew_name → the output_type that crew produces (for inline preview)
const CREW_OUTPUT_TYPE: Record<string, string> = {
  discovery_mapping:    'value_chain',
  value_design:         'value_propositions',
  architecture:         'architecture',
  delivery:             'roadmap',
  business_plan:        'business_plan',
  discovery:            'discovery',
  discovery_interviews: 'interview_synthesis',
}

const CREW_LABEL: Record<string, string> = {
  discovery_mapping:    'Value Chain Mapper',
  value_design:         'Value Design',
  architecture:         'Architecture',
  delivery:             'Delivery Planning',
  business_plan:        'Business Plan',
  discovery:            'Discovery',
  discovery_interviews: 'Interview Synthesis',
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
  const [skillInput, setSkillInput] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const outputType = review.crew_name ? CREW_OUTPUT_TYPE[review.crew_name] : undefined
  const matchedOutput = outputType ? outputs.find(o => o.output_type === outputType) : undefined
  const crewLabel = review.crew_name ? (CREW_LABEL[review.crew_name] ?? review.crew_name) : 'Crew'
  const promptBody = stripHitlBoilerplate(review.prompt ?? '')

  // Derive the rejecting agent's snake_case key and human name from matchedOutput
  const rejectingAgentKey = matchedOutput?.agent_name ?? null
  const rejectingAgentDisplayName = rejectingAgentKey
    ? (Object.keys(AGENT_RUN_KEYS).find(k => AGENT_RUN_KEYS[k] === rejectingAgentKey) ?? null)
    : null
  const rejectingAgentHumanName = rejectingAgentDisplayName
    ? (AGENT_HUMAN_NAME[rejectingAgentDisplayName] ?? rejectingAgentDisplayName)
    : null

  async function handleApprove() {
    setSubmitting(true)
    try {
      await projectsApi.resolveReview(slug, review.id, 'approved', '')
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSubmit() {
    if (!notes.trim()) return
    setSubmitting(true)
    try {
      const decision = mode === 'reject' ? 'rejected' : 'changes_requested'
      await projectsApi.resolveReview(slug, review.id, decision, notes.trim())
      // Save skill note alongside rejection (fire-and-forget, non-blocking)
      if (mode === 'reject' && rejectingAgentKey && skillInput.trim()) {
        skillNotesApi.create(rejectingAgentKey, skillInput.trim()).catch(() => {})
      }
      qc.invalidateQueries({ queryKey: ['reviews', slug] })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  function cancel() { setMode('idle'); setNotes(''); setSkillInput('') }

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

            {mode !== 'idle' && (
              <div className="space-y-4">
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
                {mode === 'reject' && rejectingAgentHumanName && (
                  <div>
                    <label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-2">
                      What should {rejectingAgentHumanName} do differently next time?{' '}
                      <span className="text-gray-400 font-normal">(optional)</span>
                    </label>
                    <textarea
                      value={skillInput}
                      onChange={e => setSkillInput(e.target.value)}
                      placeholder="Describe specific improvements for future runs…"
                      rows={3}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-brand resize-none"
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 flex-shrink-0 bg-gray-50 rounded-b-2xl">
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
            ) : (
              <>
                <button onClick={() => setMode('reject')}
                  className="text-sm font-medium px-5 py-2 rounded-lg bg-white hover:bg-red-50 text-red-600 border border-red-200 hover:border-red-400 transition-colors flex items-center gap-1.5">
                  <XCircle size={13} />Reject
                </button>
                <button onClick={() => setMode('revise')}
                  className="text-sm font-medium px-5 py-2 rounded-lg bg-white hover:bg-amber-50 text-amber-600 border border-amber-200 hover:border-amber-400 transition-colors">
                  Request revision
                </button>
                <button onClick={handleApprove} disabled={submitting}
                  className="text-sm font-semibold px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white transition-colors">
                  {submitting ? 'Approving…' : <span className="flex items-center gap-1"><Check size={13} />Approve</span>}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
