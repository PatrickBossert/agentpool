// ui/src/components/CrewCarousel.tsx
import { Play, RotateCcw, Loader2, CheckCircle2, XCircle, PauseCircle, Circle, GitBranch, ChevronLeft, ChevronRight } from 'lucide-react'
import { useRef, useState, useEffect, useCallback } from 'react'
import type { CrewRun, HumanReview } from '../types'
import {
  CREW_ORDER, CREW_LABELS, CREW_AGENTS,
  AGENT_AVATAR, AGENT_AVATAR_IMAGE, AGENT_HUMAN_NAME,
  inferAgentStatuses, getCrewStatus, getIdleStatus,
  type AgentStatus,
} from './agentStatus'
import { CREW_ICON_COMPONENT } from './crewIcons'
import AgentHoverCard from './AgentHoverCard'

// ── Helpers ────────────────────────────────────────────────────────────────────

// card inner width = 192px (w-48) − 24px padding = 168px, gap-1.5 = 6px
// lg(80px): 2×80+6  = 166 ≤ 168  ✓
// md(48px): 3×48+12 = 156 ≤ 168  ✓
// sm(36px): 4×36+18 = 162 ≤ 168  ✓  (5+ wraps)
function computeFaceSize(n: number): 'sm' | 'md' | 'lg' {
  if (n <= 2) return 'lg'
  if (n <= 4) return 'md'
  return 'sm'
}

// ── Agent face circle ──────────────────────────────────────────────────────────

function AgentFace({ name, status, size = 'md' }: { name: string; status: AgentStatus; size?: 'sm' | 'md' | 'lg' }) {
  const avatar    = AGENT_AVATAR[name] ?? { gradient: 'from-gray-400 to-gray-600' }
  const humanName = AGENT_HUMAN_NAME[name] ?? name
  const firstName = humanName.split(' ')[0]
  const imageSrc  = AGENT_AVATAR_IMAGE[name]

  const dim = size === 'lg' ? 'w-20 h-20' : size === 'md' ? 'w-12 h-12' : 'w-9 h-9'
  const textDim = size === 'lg' ? 'text-2xl' : size === 'md' ? 'text-lg' : 'text-sm'

  const ringClass =
    status === 'running'   ? 'ring-2 ring-teal-400 ring-offset-1' :
    status === 'waiting'   ? 'ring-2 ring-amber-400 ring-offset-1' :
    status === 'completed' ? 'ring-2 ring-green-400 ring-offset-1' :
                             ''

  return (
    <AgentHoverCard agentName={name}>
      <div className={`${dim} rounded-full overflow-hidden flex-shrink-0 ${ringClass} transition-all cursor-default`}>
        {imageSrc ? (
          <img src={imageSrc} alt={firstName} className="w-full h-full object-cover" />
        ) : (
          <div className={`w-full h-full bg-gradient-to-br ${avatar.gradient} flex items-center justify-center font-bold text-white ${textDim}`}>
            {humanName.split(' ').map((w: string) => w[0]).join('').slice(0, 2)}
          </div>
        )}
      </div>
    </AgentHoverCard>
  )
}

// ── PAM card ───────────────────────────────────────────────────────────────────

interface PamCardProps {
  orchestrationStatus: string | null
  isPipelineActive: boolean
  isStarting: boolean
  hitlReviewCount: number
  runCount: number
  isSelected: boolean
  isHovered: boolean
  anotherCardHovered: boolean
  carouselDragging: boolean
  onSelect: () => void
  onRunPipeline: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
}

function PamCard({ orchestrationStatus, isPipelineActive, isStarting, hitlReviewCount, runCount, isSelected, isHovered, anotherCardHovered, carouselDragging, onSelect, onRunPipeline, onMouseEnter, onMouseLeave }: PamCardProps) {
  const imageSrc = AGENT_AVATAR_IMAGE['PAM']

  const borderClass = isSelected
    ? 'border-teal-500 ring-2 ring-teal-400/40 animate-crewGlow'
    : isPipelineActive
      ? 'border-teal-400 shadow-md shadow-teal-100'
      : orchestrationStatus === 'failed'
        ? 'border-red-200'
        : 'border-teal-200'

  const statusChip = isPipelineActive
    ? <span className="text-[10px] font-medium text-teal-600 flex items-center gap-1"><Loader2 size={10} className="animate-spin" />Running</span>
    : orchestrationStatus === 'completed'
      ? <span className="text-[10px] font-medium text-green-600 flex items-center gap-1"><CheckCircle2 size={10} />Done</span>
      : orchestrationStatus === 'failed'
        ? <span className="text-[10px] font-medium text-red-500 flex items-center gap-1"><XCircle size={10} />Failed</span>
        : <span className="text-[10px] font-medium text-gray-400">{getIdleStatus('pam', runCount)}</span>

  return (
    <div
      className={`relative flex-shrink-0 w-48 rounded-xl border bg-white flex flex-col ${borderClass} transition-transform duration-300 ease-in-out cursor-pointer ${!carouselDragging && (isHovered || (isSelected && !anotherCardHovered)) ? 'scale-[1.06] z-10' : 'scale-100'}`}
      onClick={onSelect}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* Running scanline */}
      {isPipelineActive && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-teal-400 to-transparent animate-scanline pointer-events-none rounded-t-xl" />
      )}

      {/* Teal header band */}
      <div className="bg-gradient-to-r from-teal-600 to-teal-500 px-3 py-2 rounded-t-xl flex items-center gap-1.5 flex-shrink-0">
        <GitBranch size={11} className="text-white/80 flex-shrink-0" />
        <span className="text-white text-[10px] font-bold uppercase tracking-wider truncate flex-1">Pipeline Director</span>
        {hitlReviewCount > 0 && (
          <span className="bg-amber-400 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none flex-shrink-0">
            {hitlReviewCount}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="p-3 flex flex-col gap-2.5 flex-1">
        {/* PAM face + name */}
        <div className="flex-1 flex flex-col items-center justify-center gap-1 py-1">
          <AgentHoverCard agentName="PAM">
            <div className="w-20 h-20 rounded-full overflow-hidden border-2 border-teal-200 shadow-sm flex-shrink-0 cursor-default">
              {imageSrc ? (
                <img src={imageSrc} alt="Pamela" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full bg-gradient-to-br from-teal-500 to-teal-700 flex items-center justify-center text-2xl font-bold text-white">P</div>
              )}
            </div>
          </AgentHoverCard>
          <span className="text-xs text-gray-500 font-medium">Pam</span>
          {hitlReviewCount > 0 && (
            <span className="text-[9px] text-amber-600 font-medium flex items-center gap-0.5">
              <PauseCircle size={9} />{hitlReviewCount} awaiting review
            </span>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-1 pt-0.5 border-t border-gray-100">
          {statusChip}
          <button
            onClick={e => { e.stopPropagation(); onRunPipeline() }}
            disabled={isPipelineActive || isStarting}
            title={isPipelineActive || isStarting ? 'Running…' : 'Run all crews'}
            className="w-7 h-7 rounded-full flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed bg-teal-600 text-white hover:bg-teal-700 flex-shrink-0"
          >
            {isPipelineActive || isStarting
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Single crew card ───────────────────────────────────────────────────────────

interface CrewCardProps {
  crewKey: string
  crewRun: CrewRun | undefined
  isActive: boolean
  isPipelineActive: boolean
  isWaiting: boolean
  isRejected: boolean
  isSelected: boolean
  isHovered: boolean
  anotherCardHovered: boolean
  carouselDragging: boolean
  logs: string[]
  anyBusy: boolean
  onSelect: () => void
  onRun: (crewKey: string) => void
  onRerun: (crewKey: string) => void
  onMouseEnter: () => void
  onMouseLeave: () => void
}

function CrewCard({ crewKey, crewRun, isActive, isPipelineActive, isWaiting, isRejected, isSelected, isHovered, anotherCardHovered, carouselDragging, logs, anyBusy, onSelect, onRun, onRerun, onMouseEnter, onMouseLeave }: CrewCardProps) {
  const status = getCrewStatus(crewRun, isActive, isPipelineActive, isWaiting, isRejected)
  const agents = CREW_AGENTS[crewKey] ?? []

  const faceSize = computeFaceSize(agents.length)

  const agentStatuses: AgentStatus[] = isWaiting
    ? agents.map(() => 'waiting' as AgentStatus)
    : isActive
      ? inferAgentStatuses(crewKey, logs)
      : status === 'completed'
        ? agents.map(() => 'completed' as AgentStatus)
        : agents.map(() => (isPipelineActive ? 'queued' : 'idle') as AgentStatus)

  function handlePlay(e: React.MouseEvent) {
    e.stopPropagation()
    if (status === 'completed') {
      onRerun(crewKey)
      return
    }
    onRun(crewKey)
  }

  const borderClass = isSelected
    ? 'border-teal-400 ring-1 ring-teal-400/40 animate-crewGlow'
    : status === 'running'
      ? 'border-teal-300'
      : status === 'waiting'
        ? 'border-amber-300'
        : status === 'completed'
          ? 'border-green-200'
          : status === 'failed'
            ? 'border-red-200'
            : 'border-gray-200 hover:border-gray-300'

  const bgClass = isSelected
    ? 'bg-teal-50/60'
    : status === 'running'
      ? 'bg-teal-50/30'
      : 'bg-white'

  const statusLabel =
    status === 'running'   ? <span className="text-[10px] font-medium text-teal-600 flex items-center gap-1"><Loader2 size={10} className="animate-spin text-teal-500" />Running</span> :
    status === 'waiting'   ? <span className="text-[10px] font-medium text-amber-600 flex items-center gap-1"><PauseCircle size={10} />Waiting</span> :
    status === 'completed' ? <span className="text-[10px] font-medium text-green-600 flex items-center gap-1"><CheckCircle2 size={10} />Done</span> :
    status === 'failed'    ? <span className="text-[10px] font-medium text-red-500 flex items-center gap-1"><XCircle size={10} />Failed</span> :
    status === 'queued'    ? <span className="text-[10px] font-medium text-gray-400 flex items-center gap-1"><Circle size={10} />Queued</span> :
                             <span className="text-[10px] font-medium text-gray-300">{getIdleStatus(crewKey, crewRun?.id ?? 0)}</span>

  const canPlay = !anyBusy && status !== 'running'
  const isSingleAgent = agents.length === 1

  return (
    <div
      onClick={onSelect}
      className={`relative flex-shrink-0 w-48 rounded-xl border cursor-pointer transition-transform duration-300 ease-in-out select-none flex flex-col ${borderClass} ${bgClass} ${!carouselDragging && (isHovered || (isSelected && !anotherCardHovered)) ? 'scale-[1.06] z-10' : 'scale-100'}`}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* Running scanline */}
      {status === 'running' && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-teal-400 to-transparent animate-scanline pointer-events-none rounded-t-xl" />
      )}

      {/* Selected indicator */}
      {isSelected && (
        <div className="absolute bottom-0 left-4 right-4 h-0.5 bg-teal-500 rounded-full" />
      )}

      <div className="p-3 flex flex-col gap-2.5 flex-1">
        {/* Header — min-h normalises 1-line vs 2-line labels so avatar centres align across all cards */}
        <div className="flex items-start gap-1.5 flex-shrink-0 min-h-[34px]">
          {(() => { const CrewIcon = CREW_ICON_COMPONENT[crewKey]; return CrewIcon ? <CrewIcon size={13} className="text-gray-400 flex-shrink-0 mt-0.5" /> : null })()}
          <span className="text-[11px] font-bold text-gray-600 uppercase tracking-wide leading-tight">
            {CREW_LABELS[crewKey]}
          </span>
        </div>

        {/* Agent faces - flex-1 keeps footer pinned to bottom */}
        <div className="flex-1 flex items-center">
          {isSingleAgent ? (
            <div className="flex flex-col items-center gap-1.5 w-full justify-center">
              <AgentFace name={agents[0]} status={agentStatuses[0]} size="lg" />
              <span className="text-xs text-gray-500 font-medium">
                {(AGENT_HUMAN_NAME[agents[0]] ?? agents[0]).split(' ')[0]}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 flex-wrap justify-center w-full">
              {agents.map((agent, idx) => (
                <div key={agent} className="flex flex-col items-center gap-1">
                  <AgentFace name={agent} status={agentStatuses[idx]} size={faceSize} />
                  <span className="text-[10px] text-gray-400 font-medium leading-none">
                    {(AGENT_HUMAN_NAME[agent] ?? agent).split(' ')[0]}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer: status + play button - always at bottom */}
        <div className="flex items-center justify-between gap-1 pt-0.5 border-t border-gray-100 flex-shrink-0">
          {statusLabel}
          <button
            onClick={handlePlay}
            disabled={!canPlay}
            title={
              status === 'running'   ? 'Running…' :
              status === 'completed' ? 'Re-run' :
                                       'Run'
            }
            className={`w-6 h-6 rounded-full flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0 ${
              status === 'running'
                ? 'bg-teal-50 text-teal-500 border border-teal-200'
                : status === 'completed'
                  ? 'bg-white text-gray-400 border border-gray-200 hover:border-teal-300 hover:text-teal-600'
                  : 'bg-teal-600 text-white hover:bg-teal-700'
            }`}
          >
            {status === 'running'
              ? <Loader2 size={10} className="animate-spin" />
              : status === 'completed'
                ? <RotateCcw size={10} />
                : <Play size={10} />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── CrewCarousel ───────────────────────────────────────────────────────────────

export interface CrewCarouselProps {
  crewRuns: CrewRun[]
  isPipelineActive: boolean
  logs: string[]
  hitlReviews?: HumanReview[]
  rejectedCrews?: Set<string>
  selectedCrew: string
  onSelectCrew: (crewKey: string) => void
  onRunCrew: (crewKey: string) => void
  onRerunCrew: (crewKey: string) => void
  runningCrew?: string | null
  // PAM card props
  onRunPipeline: () => void
  isPipelineStarting?: boolean
  orchestrationStatus?: string | null
}

export default function CrewCarousel({
  crewRuns, isPipelineActive, logs, hitlReviews = [], rejectedCrews = new Set(),
  selectedCrew, onSelectCrew, onRunCrew, onRerunCrew, runningCrew,
  onRunPipeline, isPipelineStarting = false, orchestrationStatus = null,
}: CrewCarouselProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  // ── Click-drag state ──────────────────────────────────────────────────────
  const dragState = useRef<{ startX: number; scrollLeft: number; dragging: boolean } | null>(null)
  const didDrag = useRef(false)
  const [isDragging, setIsDragging]     = useState(false)
  const [isMouseDown, setIsMouseDown]   = useState(false)
  const [isHovering, setIsHovering]     = useState(false)
  const [hoveredCrew, setHoveredCrew]   = useState<string | null>(null)

  function onMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    const el = scrollRef.current
    if (!el) return
    didDrag.current = false
    dragState.current = { startX: e.pageX, scrollLeft: el.scrollLeft, dragging: true }
    setIsMouseDown(true)
  }

  function onMouseLeaveCarousel() {
    setIsHovering(false)
    setHoveredCrew(null)
    if (dragState.current) dragState.current.dragging = false
    setIsDragging(false)
    setIsMouseDown(false)
  }

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      const ds = dragState.current
      if (!ds?.dragging || !scrollRef.current) return
      const dx = e.pageX - ds.startX
      if (!isDragging && Math.abs(dx) > 5) setIsDragging(true)
      if (Math.abs(dx) > 5) didDrag.current = true
      scrollRef.current.scrollLeft = ds.scrollLeft - dx
    }
    function onMouseUp() {
      if (dragState.current) dragState.current.dragging = false
      setIsDragging(false)
      setIsMouseDown(false)
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [isDragging])

  const checkScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 4)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4)
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    checkScroll()
    el.addEventListener('scroll', checkScroll, { passive: true })
    const ro = new ResizeObserver(checkScroll)
    ro.observe(el)
    return () => { el.removeEventListener('scroll', checkScroll); ro.disconnect() }
  }, [checkScroll])

  function scrollBy(delta: number) {
    scrollRef.current?.scrollBy({ left: delta, behavior: 'smooth' })
  }

  // Treat newest run as canonical per crew (crewRuns is DESC newest-first)
  const deduped = new Map<string, CrewRun>()
  for (const r of crewRuns) if (!deduped.has(r.crew_name)) deduped.set(r.crew_name, r)

  const activeCrewName = crewRuns.find(r => r.status === 'running')?.crew_name
  const waitingCrews = new Set(hitlReviews.map(r => r.crew_name).filter(Boolean) as string[])
  const anyBusy = isPipelineActive || !!activeCrewName || !!runningCrew

  return (
    <div className="relative">
      {/* Left scroll button */}
      {canScrollLeft && (
        <button
          onClick={() => scrollBy(-220)}
          className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-gray-200 shadow-sm flex items-center justify-center text-gray-500 hover:text-gray-800 hover:shadow-md transition-all -ml-3"
          aria-label="Scroll left"
        >
          <ChevronLeft size={14} />
        </button>
      )}

      {/* Right scroll button */}
      {canScrollRight && (
        <button
          onClick={() => scrollBy(220)}
          className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-7 h-7 rounded-full bg-white border border-gray-200 shadow-sm flex items-center justify-center text-gray-500 hover:text-gray-800 hover:shadow-md transition-all -mr-3"
          aria-label="Scroll right"
        >
          <ChevronRight size={14} />
        </button>
      )}

      <div
        ref={scrollRef}
        onMouseDown={onMouseDown}
        onMouseEnter={() => setIsHovering(true)}
        onMouseLeave={onMouseLeaveCarousel}
        className={`flex gap-3 overflow-x-auto py-10 px-6 items-stretch select-none ${
          (isMouseDown || isDragging) ? 'cursor-grabbing [&_*]:cursor-grabbing' : isHovering ? 'cursor-pointer' : ''
        }`}
        style={{ scrollbarWidth: 'none' }}
      >
        {/* PAM - pipeline orchestrator */}
        <PamCard
          orchestrationStatus={orchestrationStatus}
          isPipelineActive={isPipelineActive}
          isStarting={isPipelineStarting}
          hitlReviewCount={hitlReviews.length}
          runCount={crewRuns.length}
          isSelected={selectedCrew === 'PAM'}
          isHovered={hoveredCrew === 'PAM'}
          anotherCardHovered={hoveredCrew !== null && hoveredCrew !== 'PAM'}
          carouselDragging={isDragging}
          onSelect={() => { if (!didDrag.current) onSelectCrew('PAM') }}
          onRunPipeline={onRunPipeline}
          onMouseEnter={() => setHoveredCrew('PAM')}
          onMouseLeave={() => setHoveredCrew(null)}
        />

        {/* Visual separator */}
        <div className="flex-shrink-0 w-px bg-gray-300 self-stretch my-1" />

        {/* Crew cards */}
        {CREW_ORDER.map(crewKey => (
          <CrewCard
            key={crewKey}
            crewKey={crewKey}
            crewRun={deduped.get(crewKey)}
            isActive={activeCrewName === crewKey || runningCrew === crewKey}
            isPipelineActive={isPipelineActive}
            isWaiting={waitingCrews.has(crewKey)}
            isRejected={rejectedCrews.has(crewKey)}
            isSelected={selectedCrew === crewKey}
            isHovered={hoveredCrew === crewKey}
            anotherCardHovered={hoveredCrew !== null && hoveredCrew !== crewKey}
            carouselDragging={isDragging}
            logs={logs}
            anyBusy={anyBusy}
            onSelect={() => { if (!didDrag.current) onSelectCrew(crewKey) }}
            onRun={onRunCrew}
            onRerun={onRerunCrew}
            onMouseEnter={() => setHoveredCrew(crewKey)}
            onMouseLeave={() => setHoveredCrew(null)}
          />
        ))}
      </div>
    </div>
  )
}
