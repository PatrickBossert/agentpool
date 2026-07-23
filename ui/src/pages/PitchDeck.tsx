// ui/src/pages/PitchDeck.tsx
// Full-screen pitch deck - Scottish Power Group Services
// Option B (value-first): The Prize → Value Leaks → Approach → Agentic USP → Phase 1/2/3 → Maturity → Investment → Next Steps
// Keyboard: ← → arrows; Escape returns to app
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ArrowLeft, Download } from 'lucide-react'
import logoUrl from '../assets/TR_Logo_strapiline.png'
import arupLogoUrl from '../assets/arup-logo.jpg'
import { useAuth } from '../context/AuthContext'

// ── Slide definitions ─────────────────────────────────────────────────────────

const slides = [
  { id: 'cover',     component: SlideCover },
  { id: 'prize',     component: SlidePrize },
  { id: 'leaks',     component: SlideLeaks },
  { id: 'approach',  component: SlideApproach },
  { id: 'agents',    component: SlideAgents },
  { id: 'phase1',     component: SlidePhase1 },
  { id: 'phase1plan', component: SlidePhase1Plan },
  { id: 'phase2',     component: SlidePhase2 },
  { id: 'phase3',    component: SlidePhase3 },
  { id: 'maturity',  component: SlideMaturity },
  { id: 'investment',component: SlideInvestment },
  { id: 'pricing',     component: SlidePricing },
  { id: 'credentials', component: SlideCredentials },
  { id: 'team',        component: SlideTeam },
  { id: 'next',        component: SlideNext },
]

// ── Page shell ────────────────────────────────────────────────────────────────

export default function PitchDeck() {
  const [idx, setIdx]         = useState(0)
  const [dir, setDir]         = useState<'fwd' | 'back'>('fwd')
  const [anim, setAnim]       = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const outerRef              = useRef<HTMLDivElement>(null)
  const navigate              = useNavigate()
  const { user }              = useAuth()
  const total                 = slides.length

  function backToApp() {
    const lastProject = user?.sub ? localStorage.getItem(`ap_last_project:${user.sub}`) : null
    navigate(lastProject ? `/${lastProject}` : '/')
  }

  async function exportToPptx() {
    if (isExporting || !outerRef.current) return
    setIsExporting(true)
    const savedIdx = idx
    try {
      const [{ default: PptxGenJS }, { toPng }] = await Promise.all([
        import('pptxgenjs'),
        import('html-to-image'),
      ])
      const pptx = new PptxGenJS()
      pptx.defineLayout({ name: 'WIDE', width: 13.33, height: 7.5 })
      pptx.layout = 'WIDE'
      pptx.title  = 'TaskReimagination - Scottish Power Group Services'

      for (let i = 0; i < total; i++) {
        setIdx(i)
        // allow React to flush + images to paint
        await new Promise(r => setTimeout(r, 500))
        const dataUrl = await toPng(outerRef.current!, {
          pixelRatio: 1.5,
          cacheBust: true,
          skipFonts: true,
        })
        const slide = pptx.addSlide()
        slide.background = { color: '020712' }
        slide.addImage({ data: dataUrl, x: 0, y: 0, w: '100%', h: '100%' })
      }

      await pptx.writeFile({ fileName: 'TaskReimagination-SPGS-Proposal.pptx' })
    } catch (err) {
      console.error('PPTX export failed:', err)
    } finally {
      setIdx(savedIdx)
      setIsExporting(false)
    }
  }

  const go = useCallback((next: number) => {
    if (next < 0 || next >= total || anim) return
    setDir(next > idx ? 'fwd' : 'back')
    setAnim(true)
    setTimeout(() => { setIdx(next); setAnim(false) }, 200)
  }, [idx, total, anim])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') go(idx + 1)
      if (e.key === 'ArrowLeft'  || e.key === 'ArrowUp')  go(idx - 1)
      if (e.key === 'Escape') backToApp()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, idx, navigate])

  const Slide = slides[idx].component
  const translateClass = anim
    ? dir === 'fwd' ? '-translate-x-4 opacity-0' : 'translate-x-4 opacity-0'
    : 'translate-x-0 opacity-100'

  return (
    <div ref={outerRef} className="fixed inset-0 bg-slate-950 flex flex-col overflow-hidden select-none">

      {/* Top bar - hidden during export so it doesn't appear in screenshots */}
      {!isExporting && (
        <div className="flex items-center justify-between px-8 py-4 flex-shrink-0 border-b border-white/5">
          <button
            onClick={backToApp}
            className="flex items-center gap-1.5 text-slate-500 hover:text-slate-300 text-xs transition-colors"
          >
            <ArrowLeft size={13} /> Back to app
          </button>
          <img src={logoUrl} alt="TaskReimagination.ai" className="h-5 w-auto opacity-60" />
          <div className="flex items-center gap-4">
            <button
              onClick={exportToPptx}
              className="flex items-center gap-1.5 text-slate-500 hover:text-slate-300 text-xs transition-colors"
              title="Download as PowerPoint"
            >
              <Download size={13} /> Download PPTX
            </button>
            <p className="text-slate-600 text-xs">{idx + 1} / {total}</p>
          </div>
        </div>
      )}

      {/* Slide area */}
      <div className={`flex-1 min-h-0 flex items-center justify-center ${isExporting ? 'p-[10%]' : 'px-8 py-6'}`}>
        <div
          className={`w-full ${isExporting ? '' : 'max-w-5xl'} transition-all duration-200 ease-out ${isExporting ? '' : translateClass}`}
        >
          <Slide />
        </div>
      </div>

      {/* Bottom nav - hidden during export */}
      {!isExporting && (
        <div className="flex items-center justify-between px-8 py-5 flex-shrink-0 border-t border-white/5">
          {/* Slide indicators */}
          <div className="flex gap-1">
            {slides.map((_, i) => (
              <button
                key={i}
                onClick={() => go(i)}
                className={`w-6 h-6 rounded text-[10px] font-mono transition-all duration-200 ${
                  i === idx
                    ? 'bg-teal-400/15 text-teal-400 font-bold'
                    : 'text-slate-600 hover:text-slate-400'
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>

          {/* Arrows */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => go(idx - 1)}
              disabled={idx === 0}
              className="w-9 h-9 rounded-full border border-slate-700 hover:border-slate-500 flex items-center justify-center text-slate-400 hover:text-white transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => go(idx + 1)}
              disabled={idx === total - 1}
              className="w-9 h-9 rounded-full border border-slate-700 hover:border-slate-500 flex items-center justify-center text-slate-400 hover:text-white transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Page number - shown in export screenshots, invisible otherwise */}
      {isExporting && (
        <div className="absolute bottom-[4%] right-[5%] text-slate-600 text-[10px] font-mono tabular-nums">
          {idx + 1} / {total}
        </div>
      )}
    </div>
  )
}

// ── Shared helpers ─────────────────────────────────────────────────────────────

function SlideHeader({ eyebrow, title, subtitle }: { eyebrow?: string; title: string; subtitle?: string }) {
  return (
    <div className="mb-8">
      {eyebrow && <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-3">{eyebrow}</p>}
      <h2 className="text-white text-4xl font-bold leading-tight tracking-tight mb-3">{title}</h2>
      {subtitle && <p className="text-slate-400 text-lg leading-relaxed">{subtitle}</p>}
    </div>
  )
}

function Divider() {
  return <div className="h-px bg-white/8 my-7" />
}

function Tag({ label, color = 'teal' }: { label: string; color?: 'teal' | 'amber' | 'slate' }) {
  const cls = {
    teal:  'bg-teal-900/50 text-teal-300 border-teal-800/60',
    amber: 'bg-amber-900/50 text-amber-300 border-amber-800/60',
    slate: 'bg-slate-800 text-slate-300 border-slate-700',
  }[color]
  return (
    <span className={`inline-block text-[10px] font-bold uppercase tracking-widest border rounded px-2 py-0.5 ${cls}`}>
      {label}
    </span>
  )
}

function PhaseTag({ n }: { n: 1 | 2 | 3 }) {
  return <Tag label={`Phase ${n}`} color={n === 1 ? 'teal' : n === 2 ? 'amber' : 'slate'} />
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-900 border border-slate-800 rounded-2xl p-6 ${className}`}>
      {children}
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="text-slate-500 text-sm w-24 flex-shrink-0 pt-0.5">{label}</span>
      <span className="text-slate-200 text-sm leading-relaxed">{value}</span>
    </div>
  )
}

// ── Slide 1: Cover ─────────────────────────────────────────────────────────────

function SlideCover() {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-8 py-8">
      <div className="flex items-center gap-3">
        <div className="w-px h-10 bg-slate-700" />
        <p className="text-slate-500 text-sm tracking-widest uppercase">Prepared for</p>
        <div className="w-px h-10 bg-slate-700" />
      </div>
      <div>
        <h1 className="text-white text-5xl font-bold tracking-tight mb-2">Scottish Power</h1>
        <h1 className="text-teal-400 text-5xl font-bold tracking-tight">Group Services</h1>
      </div>
      <Divider />
      <div className="max-w-xl">
        <p className="text-slate-300 text-2xl font-light leading-relaxed">
          A prioritised roadmap of decision-support investment for Property and Fleet
        </p>
      </div>
      <div className="flex items-center gap-6">
        <div className="text-center">
          <p className="text-slate-600 text-xs uppercase tracking-widest mb-1">Prepared by</p>
          <p className="text-slate-300 text-sm font-medium">Patrick Bossert</p>
        </div>
        <div className="w-px h-8 bg-slate-800" />
        <div className="text-center">
          <p className="text-slate-600 text-xs uppercase tracking-widest mb-1">Classification</p>
          <p className="text-slate-300 text-sm font-medium">Confidential</p>
        </div>
      </div>

      <div className="flex items-center gap-10 mt-4">
        <div className="flex flex-col items-center gap-2">
          <p className="text-slate-600 text-[10px] uppercase tracking-widest">Powered by</p>
          <img src={logoUrl} alt="TaskReimagination.ai" className="h-12 w-auto" />
        </div>
        <div className="w-px h-14 bg-slate-800" />
        <div className="flex flex-col items-center gap-2">
          <p className="text-slate-600 text-[10px] uppercase tracking-widest">Facilitated by</p>
          <img src={arupLogoUrl} alt="ARUP" className="h-12 w-auto rounded" />
        </div>
      </div>
    </div>
  )
}

// ── Slide 2: Three Investment Challenges ──────────────────────────────────────

function SlidePrize() {
  return (
    <div>
      <div className="mb-6">
        <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-4">Three investment challenges</p>
        <div className="space-y-0.5 mb-4">
          {[
            'Fifteen years of asset decisions',
            'The tools to make them well',
            'Confidence in the underlying data',
          ].map((line, i) => (
            <h2 key={i} className="text-white text-3xl font-bold leading-tight tracking-tight flex items-baseline gap-3">
              <span className="text-slate-600 text-xl font-normal w-6 flex-shrink-0">{i + 1}.</span>
              {line}
            </h2>
          ))}
        </div>
        <p className="text-slate-400 text-base leading-relaxed">
          Property and Fleet face three compounding challenges: long-horizon asset decisions spanning up to 25 years, made without the right analytical tools, on data that is less than 50% complete. Confidence in the underlying data is very low. Every decision made in that condition carries unquantified risk - financial, operational, and with a 2035 net zero commitment, carbon.
        </p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Risk', body: 'Without a risk model, maintenance scheduling is reactive. Unplanned failures on long-life assets cost multiples of planned intervention - and with incomplete data, failure probability cannot be estimated.' },
          { label: 'Cost', body: 'Whole-life cost is invisible without the right tools. The cheapest intervention today is often the most expensive outcome over time - and with less than half the asset data in place, the true cost picture is unknown.' },
          { label: 'Carbon', body: 'Scottish Power has committed to net zero by 2035. Without reliable asset and consumption data, carbon liability cannot be quantified - and the decisions needed to meet that commitment cannot be confidently made.' },
        ].map(item => (
          <Card key={item.label}>
            <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-3">{item.label}</p>
            <p className="text-slate-300 text-sm leading-relaxed">{item.body}</p>
          </Card>
        ))}
      </div>
      <Divider />
      <div className="flex items-center gap-6 justify-center">
        <div className="flex items-center gap-2.5">
          <div className="w-2 h-2 rounded-full bg-teal-400 flex-shrink-0" />
          <p className="text-slate-300 text-sm"><span className="text-white font-medium">Asset investment decisions</span> - the long-horizon decisions Phase 1 tooling will support</p>
        </div>
        <div className="w-px h-6 bg-slate-700 flex-shrink-0" />
        <div className="flex items-center gap-2.5">
          <div className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" />
          <p className="text-slate-300 text-sm"><span className="text-white font-medium">Capability investment decisions</span> - which tools to build first (what Phase 1 identifies)</p>
        </div>
      </div>
    </div>
  )
}

// ── Slide 3: Where Value Leaks ─────────────────────────────────────────────────

function SlideLeaks() {
  return (
    <div>
      <SlideHeader
        eyebrow="Current state"
        title="Where value leaks today"
        subtitle="Without decision-support tooling, Property and Fleet are making long-horizon asset investment decisions on incomplete information. Each team faces the same problem in parallel - and solves it separately, compounding the cost."
      />
      <div className="grid grid-cols-3 gap-4">
        {[
          {
            dim: 'Risk',
            now: 'Reactive and fragmented',
            loss: 'Asset failures, unplanned spend, regulatory exposure',
            icon: '⚠',
          },
          {
            dim: 'Cost',
            now: 'Whole-life cost invisible',
            loss: 'Budget consumed without optimisation; lowest-cost interventions chosen over best-value ones',
            icon: '£',
          },
          {
            dim: 'Carbon',
            now: 'No carbon baseline or consumption data',
            loss: '2035 net zero target cannot be tracked or actioned without quantified carbon liability',
            icon: '↓',
          },
        ].map(item => (
          <Card key={item.dim} className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="text-2xl">{item.icon}</span>
              <p className="text-white font-bold text-lg">{item.dim}</p>
            </div>
            <div>
              <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-1">Current state</p>
              <p className="text-slate-300 text-sm">{item.now}</p>
            </div>
            <div>
              <p className="text-red-400 text-[10px] uppercase tracking-widest mb-1">Value at risk</p>
              <p className="text-slate-400 text-sm leading-relaxed">{item.loss}</p>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ── Slide 4: The Approach ──────────────────────────────────────────────────────

function SlideApproach() {
  const [lightbox, setLightbox] = useState(false)
  return (
    <div>
      <SlideHeader
        eyebrow="Our approach"
        title="Identifying the right capability investments - in the right order"
        subtitle="This is a joint effort. AI agents conduct discovery, research, and prioritisation at a scale no human team can match. ARUP leads the programme, provides domain expertise, and is accountable for every deliverable - from Phase 1 brief to Phase 3 handover."
      />
      <div className="grid grid-cols-2 gap-4">
        <Card className="flex flex-col">
          <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-3">Two layers. One process.</p>
          <div className="space-y-3">
            <div className="flex items-start gap-2.5">
              <div className="w-2 h-2 rounded-full bg-teal-400 flex-shrink-0 mt-1.5" />
              <div>
                <p className="text-white text-xs font-semibold mb-0.5">Asset investment layer</p>
                <p className="text-slate-400 text-xs leading-relaxed">The long-horizon decisions - maintenance scheduling, renewal prioritisation, capital allocation - that the tooling must support over 15+ years.</p>
              </div>
            </div>
            <div className="flex items-start gap-2.5">
              <div className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0 mt-1.5" />
              <div>
                <p className="text-white text-xs font-semibold mb-0.5">Capability investment layer</p>
                <p className="text-slate-400 text-xs leading-relaxed">Which decision-support tools to build, and in what order, to progressively unlock value from those asset decisions. This is what Phase 1 identifies.</p>
              </div>
            </div>
          </div>
          <hr className="border-slate-700 mt-4 mb-0" />
          <div className="flex-1 flex items-center justify-center pt-4">
            <button
              onClick={() => setLightbox(true)}
              className="w-full cursor-zoom-in rounded overflow-hidden border border-slate-700/50 hover:border-teal-600/50 transition-colors"
            >
              <img
                src="https://spgs.futureedge.consulting/__l5e/assets-v1/6eb7579d-6bac-46ac-8639-418b8bae35e2/value-chain-diagram.png"
                alt="Value chain diagram"
                className="w-full object-contain"
              />
            </button>
          </div>
        </Card>
        {lightbox && (
          <div
            className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center cursor-zoom-out"
            onClick={() => setLightbox(false)}
          >
            <img
              src="https://spgs.futureedge.consulting/__l5e/assets-v1/6eb7579d-6bac-46ac-8639-418b8bae35e2/value-chain-diagram.png"
              alt="Value chain diagram"
              className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
            />
          </div>
        )}
        <div className="space-y-3">
          <Card>
            <div className="flex items-center justify-between mb-3">
              <p className="text-teal-400 text-xs font-bold uppercase tracking-widest">What the agents do</p>
              <img src={logoUrl} alt="TaskReimagination" className="h-5 w-auto opacity-80" />
            </div>
            <div className="space-y-2">
              {[
                'Multi-stakeholder discovery interviews across Property and Fleet',
                'Data landscape mapping and asset information audit',
                'Value chain analysis against strategic and carbon objectives',
                'Scoring each capability investment by value unlocked, build risk, and maturity uplift',
                'Synthesis into a prioritised, sequenced roadmap with a business case for each item',
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="text-teal-500 text-xs mt-0.5 flex-shrink-0">→</span>
                  <p className="text-slate-300 text-xs leading-relaxed">{item}</p>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <div className="flex items-center justify-between mb-3">
              <p className="text-amber-400 text-xs font-bold uppercase tracking-widest">What ARUP does</p>
              <img src={arupLogoUrl} alt="ARUP" className="h-5 w-auto rounded opacity-80" />
            </div>
            <div className="space-y-2">
              {[
                'Project leadership - running the programme and owning the client relationship',
                'Domain expertise in asset management, data strategy, and organisational change',
                'Human-in-the-loop oversight of all agent outputs before they are presented',
                'Accountable for every deliverable at every phase gate',
                'Collaborating with Scottish Power IT to build internal capability and confidence',
                'PMO and change partner through Phase 3 - embedding tools, practices, and alignment',
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="text-amber-500 text-xs mt-0.5 flex-shrink-0">→</span>
                  <p className="text-slate-300 text-xs leading-relaxed">{item}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

// ── Slide 5: The Agentic Advantage ───────────────────────────────────────────

function SlideAgents() {
  return (
    <div>
      <SlideHeader
        eyebrow="Why agentic?"
        title="Why agentic for discovery and strategy?"
        subtitle="A traditional engagement to do this work would take around 17 consultants over 12 weeks. That model has real costs - in budget, in continuity, and in what happens when the team leaves."
      />
      <div className="grid grid-cols-2 gap-5 mb-5">

        {/* Traditional column */}
        <Card className="border-red-900/30 bg-red-950/20">
          <p className="text-red-400 text-xs font-bold uppercase tracking-widest mb-4">Traditional strategy consulting team</p>
          <div className="space-y-3">
            {[
              { label: 'Cost', detail: 'Day rates across a mixed team of 17 - senior time heavily loaded with management overhead.' },
              { label: 'Continuity', detail: 'Not everyone is full-time. People rotate off. Knowledge walks when the engagement ends.' },
              { label: 'Consistency', detail: 'Methodology applied differently across team members - outputs reflect who wrote them, not a single standard.' },
              { label: 'Memory', detail: 'No institutional memory after handover. The debrief deck is not the same as the context in the analysts\' heads.' },
            ].map(row => (
              <div key={row.label} className="flex items-start gap-3">
                <span className="text-red-500 text-xs mt-0.5 flex-shrink-0">✕</span>
                <div>
                  <span className="text-slate-300 text-xs font-semibold">{row.label}: </span>
                  <span className="text-slate-400 text-xs leading-relaxed">{row.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Agentic column */}
        <Card className="border-teal-800/40 bg-teal-950/20">
          <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-4">TaskReimagination.ai agent team</p>
          <div className="space-y-3">
            {[
              { label: 'Always on', detail: 'Agents never take holidays, sick days, or rotate off. The team is available at the same capacity from day one to delivery.' },
              { label: 'Deterministic', detail: 'The same methodology, the same rigour, every session. Output quality does not vary by who is in the room.' },
              { label: 'Continuous memory', detail: 'PAM - the Project Automation Manager - holds context across the full engagement and beyond. Nothing is lost between stages, and the institutional knowledge does not walk out the door when the strategy engagement ends.' },
              { label: 'Human-in-the-loop', detail: 'HITL oversight is built into Phase 1. Agents do the heavy lifting; humans make the decisions that matter.' },
            ].map(row => (
              <div key={row.label} className="flex items-start gap-3">
                <span className="text-teal-400 text-xs mt-0.5 flex-shrink-0">→</span>
                <div>
                  <span className="text-slate-200 text-xs font-semibold">{row.label}: </span>
                  <span className="text-slate-300 text-xs leading-relaxed">{row.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Cost callout */}
      <div className="bg-teal-900/25 border border-teal-700/40 rounded-xl px-6 py-4 flex items-center gap-6">
        <div className="flex-1">
          <p className="text-teal-200 text-sm leading-relaxed">
            <span className="font-semibold text-white">The whole team, licensed for a year,</span> costs less than the annual salary of a single human analyst - and delivers outputs within weeks, not quarters.
          </p>
        </div>
        <div className="flex-shrink-0 text-right border-l border-teal-800/50 pl-6">
          <p className="text-teal-400 text-[10px] uppercase tracking-widest mb-1">Annual licence</p>
          <p className="text-white text-2xl font-bold">&lt; 1 analyst</p>
          <p className="text-slate-500 text-xs">vs. 17-person team</p>
        </div>
      </div>
    </div>
  )
}

// ── Slide 6: Phase 1 ──────────────────────────────────────────────────────────

function SlidePhase1() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <PhaseTag n={1} />
        <h2 className="text-white text-4xl font-bold tracking-tight">Discovery &amp; Prioritisation</h2>
      </div>
      <div className="grid grid-cols-3 gap-4 mb-5">
        <Card className="col-span-2">
          <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-4">What happens</p>
          <div className="space-y-3">
            <MetaRow label="Interviews" value="Structured stakeholder sessions across Property and Fleet, conducted by Avery - our AI interviewer - with human review of all transcripts and findings." />
            <MetaRow label="Data mapping" value="Inventory of existing data assets, systems, and gaps across both teams, synthesised by the discovery agent crew." />
            <MetaRow label="Value chain" value="Analysis of where decision-support tools would unlock the most value relative to strategic objectives." />
            <MetaRow label="Project management" value="PAM - the Project Automation Manager - coordinates the full agent crew, tracks progress, and maintains context throughout the engagement." />
            <MetaRow label="Output" value="A prioritised, sequenced capability investment roadmap - each tool ranked by value it unlocks from asset investment decisions, build feasibility, and maturity uplift - reviewed and signed off by a human lead." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Timeline</p>
            <p className="text-white text-2xl font-bold">12–14 <span className="text-base font-normal text-slate-400">weeks</span></p>
          </Card>
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Maturity outputs</p>
            <div className="space-y-1.5 text-xs text-slate-300">
              <p>→ Asset management baseline</p>
              <p>→ Data management baseline</p>
              <p>→ Governance maturity score</p>
            </div>
          </Card>
        </div>
      </div>
      <div className="bg-teal-900/20 border border-teal-800/40 rounded-xl px-5 py-4 flex items-start gap-4">
        <div className="flex-1">
          <p className="text-teal-200 text-sm">
            <span className="font-semibold">Gate value:</span> Scottish Power knows which capability investments to make - and in what order - before a single pound is committed to building tools. The sequencing matters: build the wrong tool first and the budget is consumed on low-value capability while the high-value decisions remain unsupported.
          </p>
        </div>
        <div className="flex-shrink-0 border-l border-teal-800/40 pl-4">
          <p className="text-teal-400 text-[10px] uppercase tracking-widest mb-1">Human oversight</p>
          <p className="text-teal-200 text-xs">All outputs reviewed<br />before sign-off</p>
        </div>
      </div>
    </div>
  )
}

// ── Slide 7: Phase 1 Project Plan ────────────────────────────────────────────

function SlidePhase1Plan() {
  const DAYS = 98  // Aug 2 → Nov 8 inclusive

  function pct(days: number) {
    return `${((days / DAYS) * 100).toFixed(2)}%`
  }
  function wPct(start: number, end: number) {
    return `${(((end - start) / DAYS) * 100).toFixed(2)}%`
  }

  const bands = [
    { label: 'Setup & value chain',       start: 0,  end: 13, color: 'teal' },
    { label: 'Stakeholder & instruments', start: 13, end: 28, color: 'teal' },
    { label: 'Interview programme',       start: 28, end: 62, color: 'teal' },
    { label: 'Analysis & value design',   start: 62, end: 84, color: 'teal' },
    { label: 'Business case compilation', start: 84, end: 98, color: 'amber' },
  ] as const

  const gates = [
    { label: 'Value chain approved',    date: '15 Aug', days: 13 },
    { label: 'Scripts approved',        date: '30 Aug', days: 28 },
    { label: 'Interviews complete',     date: '3 Oct',  days: 62 },
    { label: 'Propositions approved',   date: '11 Oct', days: 70 },
    { label: 'Portfolio approved',      date: '19 Oct', days: 78 },
    { label: 'Roadmap approved',        date: '25 Oct', days: 84 },
    { label: 'Business case delivered', date: '6 Nov',  days: 96 },
  ]

  const allMarkers = [
    { label: 'Kick-off',            days: 0,  gate: false },
    { label: 'Docs uploaded',       days: 5,  gate: false },
    { label: 'Value chain ✓',       days: 13, gate: true  },
    { label: 'Stakeholders',        days: 21, gate: false },
    { label: 'Scripts ✓',           days: 28, gate: true  },
    { label: 'Interviews live',     days: 34, gate: false },
    { label: 'Interviews done ✓',   days: 62, gate: true  },
    { label: 'Propositions ✓',      days: 70, gate: true  },
    { label: 'Portfolio ✓',         days: 78, gate: true  },
    { label: 'Roadmap ✓',           days: 84, gate: true  },
    { label: 'Draft BC',            days: 89, gate: false },
    { label: 'BC delivered ✓',      days: 96, gate: true  },
    { label: 'Closeout',            days: 98, gate: false },
  ]

  const months = [
    { label: 'Aug', days: 0  },
    { label: 'Sep', days: 30 },
    { label: 'Oct', days: 61 },
    { label: 'Nov', days: 91 },
  ]

  const bandColor = {
    teal:  { bar: 'bg-teal-700/55',  border: 'border border-teal-600/40' },
    amber: { bar: 'bg-amber-700/55', border: 'border border-amber-600/40' },
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <PhaseTag n={1} />
        <h2 className="text-white text-3xl font-bold tracking-tight">Indicative Project Plan</h2>
        <span className="text-slate-500 text-sm ml-1">14 weeks · 2 Aug – 8 Nov 2026</span>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl px-5 pt-3 pb-4 mb-3">

        {/* Month axis */}
        <div className="flex mb-2">
          <div className="w-44 flex-shrink-0" />
          <div className="flex-1 relative h-4">
            <div className="absolute inset-x-0 bottom-0 h-px bg-slate-700/60" />
            {months.map(m => (
              <div key={m.label} className="absolute flex flex-col items-center" style={{ left: pct(m.days) }}>
                <div className="h-1.5 w-px bg-slate-700 mb-0.5" />
                <span className="text-[9px] text-slate-500 font-medium">{m.label}</span>
              </div>
            ))}
            {/* end tick */}
            <div className="absolute right-0 flex flex-col items-center">
              <div className="h-1.5 w-px bg-slate-700 mb-0.5" />
            </div>
          </div>
        </div>

        {/* Phase activity bands */}
        <div className="space-y-1.5 mb-2">
          {bands.map(b => (
            <div key={b.label} className="flex items-center">
              <div className="w-44 flex-shrink-0 text-[9px] text-slate-400 text-right pr-3 leading-tight">
                {b.label}
              </div>
              <div className="flex-1 relative h-5 rounded overflow-hidden bg-slate-800/30">
                <div
                  className={`absolute inset-y-0 rounded ${bandColor[b.color].bar} ${bandColor[b.color].border}`}
                  style={{ left: pct(b.start), width: wPct(b.start, b.end) }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* ARUP oversight — thin persistent bar */}
        <div className="flex items-center mb-2">
          <div className="w-44 flex-shrink-0 text-[9px] text-slate-500 text-right pr-3">ARUP oversight</div>
          <div className="flex-1 relative h-2">
            <div className="absolute inset-0 rounded-full bg-teal-900/50 border border-teal-700/30" />
          </div>
        </div>

        {/* Gate diamond markers */}
        <div className="flex items-center">
          <div className="w-44 flex-shrink-0 text-[9px] text-slate-500 text-right pr-3">Human review gates</div>
          <div className="flex-1 relative h-5">
            <div className="absolute inset-x-0 top-2 h-px bg-slate-700/40" />
            {gates.map(g => (
              <div
                key={g.label}
                className="absolute top-0.5 flex flex-col items-center"
                style={{ left: pct(g.days), transform: 'translateX(-50%)' }}
                title={`${g.label} — ${g.date}`}
              >
                <div className="w-2 h-2 bg-teal-400 rotate-45 rounded-sm" />
              </div>
            ))}
          </div>
        </div>

        {/* All milestone labels below the gate row */}
        <div className="flex mt-1">
          <div className="w-44 flex-shrink-0" />
          <div className="flex-1 relative h-10">
            {allMarkers.map((m, i) => {
              const leftNum = (m.days / DAYS) * 100
              return (
                <div
                  key={i}
                  className={`absolute top-0 flex flex-col items-center`}
                  style={{ left: pct(m.days), transform: leftNum > 5 && leftNum < 95 ? 'translateX(-50%)' : undefined }}
                >
                  <div className={`w-px h-1.5 ${m.gate ? 'bg-teal-500/60' : 'bg-slate-600/40'}`} />
                  <span className={`text-[7.5px] leading-tight text-center whitespace-nowrap ${m.gate ? 'text-teal-500' : 'text-slate-600'}`}>
                    {m.label}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

      </div>

      {/* Key milestone summary */}
      <div className="grid grid-cols-4 gap-2.5">
        {[
          { title: 'Value chain & instruments signed off', date: 'By 30 Aug', note: 'Before interview campaign launches' },
          { title: 'All stakeholder interviews complete',  date: 'By 3 Oct',  note: 'Both Property and Fleet teams' },
          { title: 'Roadmap & portfolio approved',         date: 'By 25 Oct', note: 'Evidence-based and investment-ready' },
          { title: 'Business case delivered',              date: 'By 6 Nov',  note: 'Word, Excel model, and slide deck' },
        ].map(m => (
          <div key={m.title} className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 flex gap-2">
            <div className="w-1.5 h-1.5 bg-teal-400 rotate-45 flex-shrink-0 mt-1" />
            <div>
              <p className="text-slate-200 text-[10px] font-semibold leading-tight mb-0.5">{m.title}</p>
              <p className="text-teal-400 text-[9px] font-medium mb-0.5">{m.date}</p>
              <p className="text-slate-500 text-[9px] leading-tight">{m.note}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Slide 8: Phase 2 ──────────────────────────────────────────────────────────

function SlidePhase2() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <PhaseTag n={2} />
        <h2 className="text-white text-4xl font-bold tracking-tight">Decision-Support Demonstrators</h2>
      </div>
      <div className="grid grid-cols-3 gap-4 mb-5">
        <Card className="col-span-2">
          <p className="text-amber-400 text-xs font-bold uppercase tracking-widest mb-4">What happens</p>
          <div className="space-y-3">
            <MetaRow label="Scope" value="Working prototypes of the three to five highest-value tools identified and prioritised in Phase 1." />
            <MetaRow label="Preferred model" value="Upskill a frontier IT team within Scottish Power Group Services. TaskReimagination.ai provides engineering support and assurance - the build happens within Scottish Power's own IT estate, demonstrating internal deliverability from day one." />
            <MetaRow label="Why this matters" value="The demonstrators are not a vendor prototype. They are built by Scottish Power's own engineers, proving the organisation can industrialise and own them. We de-risk the build; you own the outcome." />
            <MetaRow label="Examples" value="Risk exposure dashboard, whole-life cost optimisation model, carbon liability and net zero tracking tool. Final scope confirmed by Phase 1 output." />
            <MetaRow label="Output" value="Interactive demonstrators - built in-house, assured externally - that bring potential value to life for leadership and are ready to industrialise." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Timeline</p>
            <p className="text-white text-2xl font-bold">8–12 <span className="text-base font-normal text-slate-400">weeks</span></p>
          </Card>
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Delivery model</p>
            <div className="space-y-1.5 text-xs text-slate-300">
              <p>→ SP IT team builds</p>
              <p>→ TR.ai engineers support</p>
              <p>→ TR.ai provides assurance</p>
              <p>→ SP owns the output</p>
            </div>
          </Card>
        </div>
      </div>
      <div className="bg-amber-900/20 border border-amber-800/40 rounded-xl px-5 py-4">
        <p className="text-amber-200 text-sm">
          <span className="font-semibold">Gate value:</span> Proof of concept before committing to a full production build. A demonstrator that fails to convince stakeholders costs a fraction of a failed production deployment.
        </p>
      </div>
    </div>
  )
}

// ── Slide 7: Phase 3 ──────────────────────────────────────────────────────────

function SlidePhase3() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <PhaseTag n={3} />
        <h2 className="text-white text-4xl font-bold tracking-tight">Capability Uplift &amp; Operating Model</h2>
      </div>
      <div className="grid grid-cols-3 gap-4 mb-5">
        <Card className="col-span-2">
          <p className="text-slate-400 text-xs font-bold uppercase tracking-widest mb-4">What happens</p>
          <div className="space-y-3">
            <MetaRow label="Scope" value="Determined by the Phase 1 business case. The investment backlog defines which capabilities to industrialise and in what order - Phase 3 is shaped by the evidence, not by assumptions made before the discovery." />
            <MetaRow label="PMO support" value="Structured programme delivery with clear milestones, governance, and accountability across Property and Fleet." />
            <MetaRow label="Change management" value="Embedding new ways of working - ensuring tools are adopted, trusted, and sustained in daily operations across both teams." />
            <MetaRow label="Capability building" value="Role-specific training and knowledge transfer so Property and Fleet teams can operate and extend the tooling independently of external support." />
            <MetaRow label="Output" value="Production-grade tooling embedded in Scottish Power's IT estate, with a durable operating model that establishes alignment, sustains the change, and extends the capability after the engagement closes." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Timeline</p>
            <p className="text-white text-2xl font-bold">12–18 <span className="text-base font-normal text-slate-400">months</span></p>
          </Card>
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Sustainably establishes</p>
            <div className="space-y-1.5 text-xs text-slate-300">
              <p>→ Production tooling</p>
              <p>→ Organisational alignment</p>
              <p>→ Data governance model</p>
              <p>→ Asset management practice</p>
              <p>→ Internal capability to extend</p>
            </div>
          </Card>
        </div>
      </div>
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl px-5 py-4 flex items-start gap-4">
        <div className="flex-1">
          <p className="text-slate-200 text-sm">
            <span className="font-semibold">Gate value:</span> Because scope is determined by Phase 1, every pound committed to Phase 3 is backed by an evidence-based business case. The result is sustainable capability that outlasts the engagement - a permanent step-change, not a one-off project.
          </p>
        </div>
        <div className="flex-shrink-0 border-l border-slate-700 pl-4">
          <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-1">Scope set by</p>
          <p className="text-slate-200 text-xs">Phase 1<br />business case</p>
        </div>
      </div>
    </div>
  )
}

// ── Slide 8: Maturity Trajectory ──────────────────────────────────────────────

function SlideMaturity() {
  const phases = [
    {
      n: 1 as const,
      heading: 'Confidence in direction',
      question: 'Are we targeting the right things?',
      body: 'Discovery confirms which opportunity areas are real, material, and correctly sequenced. You know what to build - and critically, what not to build - before committing to build anything. This is not a consultant\'s opinion; it is evidence from your own data, your own stakeholders, and your own constraints.',
      resolves: 'Investment priorities and sequencing',
    },
    {
      n: 2 as const,
      heading: 'Confidence in approach',
      question: 'Can these tools actually be built?',
      body: 'Demonstrators built by Scottish Power\'s own team prove technical and organisational feasibility before production investment. The question of whether the right tools can be developed - and owned - is answered by doing it at small scale, with real data, under real constraints.',
      resolves: 'Technical feasibility and internal deliverability',
    },
    {
      n: 3 as const,
      heading: 'Confidence in outcomes',
      question: 'Can we deliver and sustain results?',
      body: 'Implementation proceeds against an evidence-based roadmap. Maturity improves as each capability is embedded - new tools, new practices, new accountability. The phases do not deliver maturity; the implementation does. What the phases deliver is the conviction to invest at the right scale, in the right order.',
      resolves: 'Execution confidence and sustained business outcomes',
    },
  ]

  return (
    <div>
      <SlideHeader
        eyebrow="Investment logic"
        title="Each phase resolves a different uncertainty"
        subtitle="Maturity improves as the roadmap is implemented through Phase 3 - the phases build the confidence to invest with conviction."
      />
      <div className="grid grid-cols-3 gap-4 mb-5">
        {phases.map(p => (
          <Card key={p.n} className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <PhaseTag n={p.n} />
              <p className="text-white text-sm font-semibold">{p.heading}</p>
            </div>
            <p className="text-teal-400 text-xs italic">"{p.question}"</p>
            <p className="text-slate-400 text-xs leading-relaxed flex-1">{p.body}</p>
            <div className="border-t border-slate-700 pt-2">
              <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-0.5">Uncertainty resolved</p>
              <p className="text-slate-300 text-xs">{p.resolves}</p>
            </div>
          </Card>
        ))}
      </div>
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl px-5 py-3">
        <p className="text-slate-400 text-sm">
          <span className="text-slate-200 font-semibold">Maturity is the product of implementation, not of phases.</span>{' '}
          Asset management, data quality, and governance improve as each capability is delivered through Phase 3. The phases create the conditions - and the evidence - to proceed with conviction at each gate.
        </p>
      </div>
    </div>
  )
}

// ── Slide 9: Investment & Return ───────────────────────────────────────────────

function SlideInvestment() {
  return (
    <div>
      <SlideHeader
        eyebrow="Investment model"
        title="De-risked at every gate"
        subtitle="Each phase stands on its own commercial logic. Scottish Power Group Services can pause or redirect at any point without stranded investment."
      />
      <div className="space-y-4">
        {[
          {
            phase: 1 as const,
            title: 'Discovery & Prioritisation',
            logic: 'Phase 1 resolves the capability investment question - which tools to build, and in what order, to sustainably support asset investment decisions over 15+ years. The cost of getting this sequence wrong far exceeds the cost of Phase 1. Knowing it before committing to a build is the return.',
            risk: 'Identified',
          },
          {
            phase: 2 as const,
            title: 'Decision-Support Demonstrators',
            logic: 'Built by Scottish Power\'s own IT team with external support and assurance - so the question of internal deliverability is answered during the demonstrator, not after. A demonstrator that doesn\'t convince stakeholders costs a fraction of a failed production deployment.',
            risk: 'Qualified',
          },
          {
            phase: 3 as const,
            title: 'Capability Uplift & Operating Model',
            logic: 'Scope is determined by the Phase 1 business case - every pound committed is backed by evidence. Production tools embedded in Scottish Power\'s estate create compounding returns: reduced reactive spend, optimised budgets, and performance accountability that persists year on year.',
            risk: 'Managed',
          },
        ].map(item => (
          <div key={item.phase} className="flex gap-4 items-start">
            <div className="flex-shrink-0 pt-1"><PhaseTag n={item.phase} /></div>
            <Card className="flex-1 flex gap-6 py-4">
              <div className="flex-1">
                <p className="text-white text-sm font-semibold mb-1.5">{item.title}</p>
                <p className="text-slate-400 text-sm leading-relaxed">{item.logic}</p>
              </div>
              <div className="flex-shrink-0 text-right">
                <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-1">Residual risk</p>
                <p className="text-slate-200 text-sm font-medium">{item.risk}</p>
              </div>
            </Card>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Slide 11: Indicative Pricing ─────────────────────────────────────────────

function SlidePricing() {
  const phases = [
    {
      n: 1 as const,
      duration: '12 - 14 weeks',
      team: '3 specialists, part-time',
      fee: '£90 - 110k',
      feeNote: undefined as string | undefined,
      activities: [
        'Programme leadership and client relationship management',
        'Stakeholder workshop and interview facilitation',
        'Review and validation of all agent outputs and findings',
      ],
      deliverables: [
        'Prioritised capability investment roadmap',
        'Business case for Phase 2',
        'Stakeholder-ready discovery report',
      ],
    },
    {
      n: 2 as const,
      duration: '8 - 12 weeks',
      team: '2 specialists (1 full-time)',
      fee: '£120 - 220k',
      feeNote: 'Range reflects scope and IT capabilities',
      activities: [
        'IT collaboration and demonstrator delivery oversight',
        'Assurance, sign-off, and stakeholder presentations',
        'Phase 3 scope definition',
      ],
      deliverables: [
        '2 - 3 working demonstrators (built by Scottish Power IT)',
        'Assurance and sign-off documentation',
        'Phase 3 scope and business case',
      ],
    },
    {
      n: 3 as const,
      duration: 'TBC',
      team: 'TBC',
      fee: 'TBC',
      feeNote: 'Determined by Phase 1 business case',
      activities: [
        'PMO and programme delivery management',
        'Change management and capability transfer',
        'Delivery assurance throughout rollout',
      ],
      deliverables: [
        'Production tools embedded in Scottish Power estate',
        'Operating model and governance documentation',
        'Trained internal teams and handover pack',
      ],
    },
  ]

  return (
    <div>
      <SlideHeader
        eyebrow="Indicative Investment"
        title="Phased costs and team"
        subtitle="ARUP fees are indicative based on team composition and scope assumptions. Agent team licence is annual and spans all phases."
      />

      {/* Swimlane grid: label col + 3 phase cols */}
      <div className="grid grid-cols-[96px_1fr_1fr_1fr] gap-px bg-slate-800/50 rounded-xl overflow-hidden text-xs">

        {/* ── Header row ── */}
        <div className="bg-slate-950 p-2" />
        {phases.map((p) => (
          <div key={p.n} className="bg-slate-900 px-3 py-2 flex items-center gap-2">
            <PhaseTag n={p.n} />
            <span className="text-slate-500 text-[10px]">{p.duration}</span>
          </div>
        ))}

        {/* ── ARUP Activities row ── */}
        <div className="bg-slate-900 px-3 py-3 flex flex-col gap-0.5 border-t border-slate-800/60">
          <span className="text-teal-400 text-[9px] font-bold uppercase tracking-widest">ARUP</span>
          <span className="text-slate-300 text-[10px] font-semibold">Activities</span>
        </div>
        {phases.map((p) => (
          <div key={p.n} className="bg-slate-900/40 px-3 py-3 border-t border-slate-800/60 border-l border-slate-800/40 space-y-1.5">
            <div className="flex items-baseline justify-between gap-2 mb-1.5">
              <span className="text-white font-bold text-sm">{p.fee}</span>
              <span className="text-slate-500 text-[9px]">{p.team}</span>
            </div>
            {p.activities.map((a, i) => (
              <div key={i} className="flex gap-1.5">
                <span className="text-teal-600 flex-shrink-0 leading-tight">·</span>
                <span className="text-slate-400 text-[10px] leading-tight">{a}</span>
              </div>
            ))}
            {p.feeNote && (
              <p className="text-amber-400/60 text-[9px] italic pt-0.5">{p.feeNote}</p>
            )}
          </div>
        ))}

        {/* ── ARUP Deliverables row ── */}
        <div className="bg-slate-900 px-3 py-3 flex flex-col gap-0.5 border-t border-slate-800/60">
          <span className="text-teal-400 text-[9px] font-bold uppercase tracking-widest">ARUP</span>
          <span className="text-slate-300 text-[10px] font-semibold">Deliverables</span>
        </div>
        {phases.map((p) => (
          <div key={p.n} className="bg-slate-900/40 px-3 py-3 border-t border-slate-800/60 border-l border-slate-800/40 space-y-1.5">
            {p.deliverables.map((d, i) => (
              <div key={i} className="flex gap-1.5">
                <span className="text-teal-600 flex-shrink-0 leading-tight">·</span>
                <span className="text-slate-400 text-[10px] leading-tight">{d}</span>
              </div>
            ))}
          </div>
        ))}

        {/* ── Agent Team row (spans all 3 phase columns) ── */}
        <div className="bg-slate-900 px-3 py-3 flex flex-col gap-0.5 border-t border-slate-800/60">
          <span className="text-teal-400 text-[9px] font-bold uppercase tracking-widest">Agent Team</span>
          <span className="text-slate-300 text-[10px] font-semibold">Annual licence</span>
        </div>
        <div className="bg-slate-900/40 px-4 py-3 col-span-3 border-t border-slate-800/60 border-l border-slate-800/40">
          <div className="flex items-center gap-2 mb-2.5">
            <Tag label="Preview pricing" color="amber" />
            <span className="text-slate-500 text-[10px]">Discounted in exchange for client referenceability</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800/60 border border-slate-700/40 rounded-lg px-3 py-2.5">
              <div className="flex items-baseline gap-1.5 mb-1">
                <span className="text-white font-bold text-lg">£48k</span>
                <span className="text-slate-500 text-[10px]">/ year</span>
              </div>
              <p className="text-slate-300 text-[10px] font-medium mb-0.5">Corporate self-hosted</p>
              <p className="text-slate-500 text-[9px]">Requires a corporate AI LLM / token budget</p>
            </div>
            <div className="bg-slate-800/60 border border-slate-700/40 rounded-lg px-3 py-2.5">
              <div className="flex items-baseline gap-1.5 mb-1">
                <span className="text-white font-bold text-lg">£75k</span>
                <span className="text-slate-500 text-[10px]">/ year</span>
              </div>
              <p className="text-slate-300 text-[10px] font-medium mb-0.5">Secure server-hosted</p>
              <p className="text-slate-500 text-[9px]">Mac Mini M4 + private LLM, includes £5k of token credits</p>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}

// ── Slide 12: ARUP Credentials ───────────────────────────────────────────────

function SlideCredentials() {
  const creds = [
    {
      project: 'Adaptive Planning Tool',
      client: 'Network Rail Technical Authority',
      color: 'teal' as const,
      relevance: 'Scenario Testing & Investment Confidence',
    },
    {
      project: 'Intelligent Infrastructure Programme',
      client: 'Network Rail Technical Authority',
      color: 'teal' as const,
      relevance: 'Asset Information & Decision Support',
    },
    {
      project: 'Structures Decision Support Tool',
      client: 'National Highways',
      color: 'teal' as const,
      relevance: 'Investment Prioritisation',
    },
    {
      project: 'Infrastructure Strategic Alliance (ISA)',
      client: 'Sellafield',
      color: 'amber' as const,
      relevance: 'Asset Portfolio Risk & Investment Planning',
    },
    {
      project: 'Service Measure Framework & Investment Prioritisation Tool',
      client: 'Northern Ireland Water',
      color: 'teal' as const,
      relevance: 'Investment Prioritisation & Decision Confidence',
    },
    {
      project: 'PR24 Resilience Framework & Long-term Planning',
      client: 'Yorkshire Water',
      color: 'teal' as const,
      relevance: 'Portfolio Risk & Resilience Planning',
    },
    {
      project: 'Risk & Investment Decision-Making Support',
      client: 'Wessex Water',
      color: 'teal' as const,
      relevance: 'Risk-Based Investment Prioritisation',
    },
    {
      project: 'Storm Overflow Data Portal',
      client: 'Welsh Water / DCC',
      color: 'teal' as const,
      relevance: 'Portfolio Visibility & Decision Support',
    },
    {
      project: 'NESO Target Operating Model Design',
      client: 'National Energy System Operator',
      color: 'amber' as const,
      relevance: 'TOM Design, Governance & Capability Development',
    },
    {
      project: 'New Organisational Structure',
      client: 'Nuclear Decommissioning Authority',
      color: 'amber' as const,
      relevance: 'Governance, Organisational Change & Future Ownership',
    },
    {
      project: 'GBN Target Operating Model',
      client: 'Great British Nuclear',
      color: 'amber' as const,
      relevance: 'Operating Model Design & Future Delivery Planning',
    },
    {
      project: 'Heathrow Expansion Capability Mapping',
      client: 'Heathrow Airport',
      color: 'slate' as const,
      relevance: 'Capability Assessment & Delivery Readiness',
    },
  ]

  const colorCls = {
    teal:  'text-teal-400',
    amber: 'text-amber-400',
    slate: 'text-slate-400',
  }

  return (
    <div>
      <SlideHeader
        eyebrow="ARUP Credentials"
        title="Relevant experience"
        subtitle="A selection of ARUP engagements directly relevant to the Scottish Power Group Services challenge."
      />
      <div className="grid grid-cols-4 gap-2.5">
        {creds.map((c) => (
          <div key={c.project} className="bg-slate-900 border border-slate-800 rounded-xl p-3 flex flex-col">
            <p className="text-white text-[10px] font-semibold leading-snug mb-1">{c.project}</p>
            <p className={`text-[9px] font-bold uppercase tracking-wide mb-auto pb-2 ${colorCls[c.color]}`}>{c.client}</p>
            <div className="border-t border-slate-800 pt-1.5 mt-1">
              <p className="text-slate-600 text-[9px] leading-snug">
                <span className="text-slate-700">Relevance: </span>
                <span className="text-slate-400">{c.relevance}</span>
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Slide 13: Meet the Team ───────────────────────────────────────────────────

function SlideTeam() {
  const humanTeam = [
    {
      initials: 'JM',
      name: 'John Mullen',
      role: 'Project Director',
      bio: 'Over 30 years leading major energy businesses across generation, distributed energy, hydrogen, renewables and nuclear. Established asset management and engineering frameworks for SSE Generation and SSE Distributed Energy; developed digital, operating model and growth strategies for energy transition businesses. Director in the ARUP Energy team.',
    },
    {
      initials: 'IS',
      name: 'Iain Swan',
      role: 'Project Manager',
      bio: 'Chartered Engineer with a PhD in Civil/Structural Engineering and 19+ years across rail, highways, utilities and defence. Work includes Network Rail\'s Intelligent Infrastructure programme and asset management strategies for SPT and the Environment Agency. Sits within the ARUP Edinburgh Advisory Services team.',
    },
    {
      initials: 'SR',
      name: 'Sharon Rose',
      role: 'Asset Management Lead',
      bio: 'Chartered Civil Engineer with 30+ years leading asset management, assurance, safety and governance across regulated and non-regulated organisations. Over 12 years at Network Rail in senior operational roles. Director in Transport Asset Management at ARUP and Global Service Lead for Assets & Operations.',
    },
    {
      initials: 'PB',
      name: 'Patrick Bossart',
      role: 'AI Developer / Asset Management Specialist',
      bio: 'Electronic engineer and former Director of the Institute of Asset Management with 30+ years shaping major infrastructure programmes - digital transformation for Essential Energy, Ausgrid, and Network Rail\'s Green Book signalling business case. Leads ARUP\'s Energy/Digital capability in APAC.',
    },
  ]

  const agents = [
    { name: 'Pamela Reid',     role: 'PMO / Pipeline Orchestrator' },
    { name: 'Alex Chen',       role: 'Value Chain Mapper' },
    { name: 'Maya Patel',      role: 'Assessment Designer' },
    { name: 'Jordan Williams', role: 'Stakeholder Manager' },
    { name: 'Sam Torres',      role: 'Requirements Capture' },
    { name: 'Riley Kim',       role: 'Requirements Analyst' },
    { name: 'Morgan Davis',    role: 'Value Lever Analyst' },
    { name: 'Taylor Brooks',   role: 'Interview Coordinator' },
    { name: 'Avery Singh',     role: 'Stakeholder Interviewer' },
    { name: 'Casey Liu',       role: 'Synthesis Analyst' },
    { name: 'Quinn Harper',    role: 'Value Proposition Generator' },
    { name: 'Blake Anderson',  role: 'Portfolio Manager' },
    { name: 'Drew Mitchell',   role: 'Enterprise Architect' },
    { name: 'Sage Thompson',   role: 'Initiative Identifier' },
    { name: 'River Martinez',  role: 'Roadmap Generator' },
    { name: 'Luca Romano',     role: 'Visual Illustrator' },
    { name: 'Finley Cooper',   role: 'Business Plan Generator' },
  ]

  return (
    <div>
      <SlideHeader eyebrow="Meet the Team" title="Who you work with" />

      {/* ARUP human team */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2.5">
          <span className="text-slate-500 text-[10px] font-bold uppercase tracking-widest">ARUP engagement team</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {humanTeam.map((p) => (
            <div key={p.name} className="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
              <div className="w-8 h-8 rounded-full bg-teal-900/60 border border-teal-700/40 flex items-center justify-center text-teal-300 text-[10px] font-bold mb-2.5 flex-shrink-0">
                {p.initials}
              </div>
              <p className="text-white text-xs font-semibold leading-tight">{p.name}</p>
              <p className="text-teal-400 text-[9px] font-medium uppercase tracking-wide mt-0.5 mb-2 leading-tight">{p.role}</p>
              <p className="text-slate-400 text-[10px] leading-relaxed">{p.bio}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Agent team roster */}
      <div>
        <div className="flex items-center gap-2 mb-2.5">
          <span className="text-slate-500 text-[10px] font-bold uppercase tracking-widest">TaskReimagination.ai agent team</span>
        </div>
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-3 grid grid-cols-3 gap-x-8 gap-y-1.5">
          {agents.map((a) => (
            <div key={a.name} className="flex items-baseline gap-1.5 min-w-0">
              <span className="text-slate-300 text-[10px] font-medium whitespace-nowrap">{a.name}</span>
              <span className="text-slate-600 text-[9px] truncate">{a.role}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Slide 14: Next Steps ──────────────────────────────────────────────────────

function SlideNext() {
  return (
    <div className="flex flex-col items-center text-center">
      <SlideHeader
        eyebrow="Next steps"
        title="Ready to begin"
      />
      <div className="grid grid-cols-3 gap-4 w-full mb-8">
        {[
          { n: '01', label: 'Agree scope and prepare proposal', body: 'Align on Phase 1 scope, stakeholder access across Property and Fleet, programme governance, and ARUP team composition. ARUP prepares a formal proposal for client review.' },
          { n: '02', label: 'Confirm Phase 1 - 2 budget and procurement route', body: 'Agree the budget envelope for Phase 1 and indicative envelope for Phase 2. Confirm the procurement route - direct appointment, framework, or competitive tender - and any internal approval steps required. IT to procure the agent team annual licence (TaskReimagination.ai) in parallel.' },
          { n: '03', label: 'Finalise procurement and kick off', body: 'Complete procurement formalities, confirm contract terms, and agree a start date. Mobilise the ARUP and agent teams, set up tooling access, and begin Phase 1 discovery.' },
        ].map(item => (
          <Card key={item.n} className="text-left">
            <p className="text-teal-400 text-3xl font-bold mb-3 opacity-40">{item.n}</p>
            <p className="text-white font-semibold mb-2">{item.label}</p>
            <p className="text-slate-400 text-sm leading-relaxed">{item.body}</p>
          </Card>
        ))}
      </div>
      <Divider />
      <div className="flex items-center gap-8 text-center">
        <div>
          <p className="text-slate-500 text-xs uppercase tracking-widest mb-1">Contact</p>
          <div className="flex items-center gap-2 justify-center mb-1">
            <img src={arupLogoUrl} alt="ARUP" className="h-4 w-auto opacity-70 rounded" />
            <p className="text-slate-200 text-sm">John Mullen</p>
          </div>
          <p className="text-slate-500 text-[10px]">John.Mullen@Arup.com</p>
        </div>
        <div className="w-px h-8 bg-slate-800" />
        <div>
          <p className="text-slate-500 text-xs uppercase tracking-widest mb-1">Prepared for</p>
          <p className="text-slate-200 text-sm">Scottish Power Group Services</p>
        </div>
        <div className="w-px h-8 bg-slate-800" />
        <div>
          <p className="text-slate-500 text-xs uppercase tracking-widest mb-1">Classification</p>
          <p className="text-slate-200 text-sm">Confidential</p>
        </div>
      </div>
    </div>
  )
}
