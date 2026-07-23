// ui/src/pages/PitchDeck.tsx
// Full-screen pitch deck — Scottish Power Group Services
// Option B (value-first): The Prize → Value Leaks → Approach → Agentic USP → Phase 1/2/3 → Maturity → Investment → Next Steps
// Keyboard: ← → arrows; Escape returns to app
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ArrowLeft } from 'lucide-react'
import logoUrl from '../assets/TR_Logo_strapiline.png'
import arupLogoUrl from '../assets/arup-logo.jpg'

// ── Slide definitions ─────────────────────────────────────────────────────────

const slides = [
  { id: 'cover',     component: SlideCover },
  { id: 'prize',     component: SlidePrize },
  { id: 'leaks',     component: SlideLeaks },
  { id: 'approach',  component: SlideApproach },
  { id: 'agents',    component: SlideAgents },
  { id: 'phase1',    component: SlidePhase1 },
  { id: 'phase2',    component: SlidePhase2 },
  { id: 'phase3',    component: SlidePhase3 },
  { id: 'maturity',  component: SlideMaturity },
  { id: 'investment',component: SlideInvestment },
  { id: 'next',      component: SlideNext },
]

// ── Page shell ────────────────────────────────────────────────────────────────

export default function PitchDeck() {
  const [idx, setIdx]   = useState(0)
  const [dir, setDir]   = useState<'fwd' | 'back'>('fwd')
  const [anim, setAnim] = useState(false)
  const navigate        = useNavigate()
  const total           = slides.length

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
      if (e.key === 'Escape') navigate('/')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, idx, navigate])

  const Slide = slides[idx].component
  const translateClass = anim
    ? dir === 'fwd' ? '-translate-x-4 opacity-0' : 'translate-x-4 opacity-0'
    : 'translate-x-0 opacity-100'

  return (
    <div className="fixed inset-0 bg-slate-950 flex flex-col overflow-hidden select-none">

      {/* Top bar */}
      <div className="flex items-center justify-between px-8 py-4 flex-shrink-0 border-b border-white/5">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1.5 text-slate-500 hover:text-slate-300 text-xs transition-colors"
        >
          <ArrowLeft size={13} /> Back to app
        </button>
        <img src={logoUrl} alt="TaskReimagination.ai" className="h-5 w-auto opacity-60" />
        <p className="text-slate-600 text-xs">{idx + 1} / {total}</p>
      </div>

      {/* Slide area */}
      <div className="flex-1 min-h-0 flex items-center justify-center px-8 py-6">
        <div
          className={`w-full max-w-5xl transition-all duration-200 ease-out ${translateClass}`}
        >
          <Slide />
        </div>
      </div>

      {/* Bottom nav */}
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

      <div className="flex flex-col items-center gap-2 mt-4">
        {/* Labels row — widths matched so they sit directly above their logo */}
        <div className="flex items-center gap-10">
          <p className="text-slate-600 text-[10px] uppercase tracking-widest w-36 text-center">Powered by</p>
          <div className="w-px opacity-0" />
          <p className="text-slate-600 text-[10px] uppercase tracking-widest w-36 text-center">Facilitated by</p>
        </div>
        {/* Logos row — items-center guarantees shared centreline */}
        <div className="flex items-center gap-10">
          <img src={logoUrl} alt="TaskReimagination.ai" className="h-12 w-auto" />
          <div className="w-px h-14 bg-slate-800" />
          <img src={arupLogoUrl} alt="Arup" className="h-12 w-auto rounded" />
        </div>
      </div>
    </div>
  )
}

// ── Slide 2: The Prize ─────────────────────────────────────────────────────────

function SlidePrize() {
  return (
    <div>
      <SlideHeader
        eyebrow="Two investment problems"
        title="Fifteen years of asset decisions. The tools to make them well."
        subtitle="Property and Fleet are making long-horizon decisions about asset maintenance and renewal. A wrong call today — on a 25-year asset — compounds for decades. Getting these decisions right requires the right decision-support tooling. Building that tooling is its own investment decision."
      />
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Risk', body: 'Without a risk model, maintenance scheduling is reactive. Unplanned failures on long-life assets cost multiples of planned intervention — and the gap widens over a 15-year horizon.' },
          { label: 'Cost', body: 'Whole-life cost is invisible without the right tools. The cheapest intervention today is often the most expensive outcome over time. Capital is consumed rather than optimised.' },
          { label: 'Performance', body: 'Without baselines and benchmarks, leadership cannot demonstrate value from the budget — nor identify which assets are underperforming before the consequences are irreversible.' },
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
          <p className="text-slate-300 text-sm"><span className="text-white font-medium">Asset investment decisions</span> — the long-horizon decisions Phase 1 tooling will support</p>
        </div>
        <div className="w-px h-6 bg-slate-700 flex-shrink-0" />
        <div className="flex items-center gap-2.5">
          <div className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0" />
          <p className="text-slate-300 text-sm"><span className="text-white font-medium">Capability investment decisions</span> — which tools to build first (what Phase 1 identifies)</p>
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
        subtitle="Without decision-support tooling, Property and Fleet are making long-horizon asset investment decisions on incomplete information. Each team faces the same problem in parallel — and solves it separately, compounding the cost."
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
            dim: 'Performance',
            now: 'No baselines or benchmarks',
            loss: 'Leadership cannot demonstrate value or identify underperformance',
            icon: '↗',
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
  return (
    <div>
      <SlideHeader
        eyebrow="Our approach"
        title="Identifying the right capability investments — in the right order"
        subtitle="The agent team's job in Phase 1 is not to build tools. It is to determine which decision-support tools will unlock the most value from Scottish Power's asset investment programme — and establish the sequence in which to build them."
      />
      <div className="grid grid-cols-2 gap-5">
        <Card>
          <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-3">Two layers. One process.</p>
          <div className="space-y-3 mb-4">
            <div className="flex items-start gap-2.5">
              <div className="w-2 h-2 rounded-full bg-teal-400 flex-shrink-0 mt-1.5" />
              <div>
                <p className="text-white text-xs font-semibold mb-0.5">Asset investment layer</p>
                <p className="text-slate-400 text-xs leading-relaxed">The long-horizon decisions — maintenance scheduling, renewal prioritisation, capital allocation — that the tooling must support over 15+ years.</p>
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
          <p className="text-slate-300 text-xs border-t border-slate-800 pt-3">
            Scottish Power leaves Phase 1 with a defensible, evidence-based sequence — not a wish list.
          </p>
        </Card>
        <Card>
          <p className="text-teal-400 text-xs font-bold uppercase tracking-widest mb-4">What the agent team does</p>
          <div className="space-y-2.5">
            {[
              'Multi-stakeholder interviews across Property and Fleet',
              'Data landscape and asset information mapping',
              'Value chain analysis against strategic objectives',
              'Scoring each capability investment by value unlocked, build risk, and maturity uplift',
              'Synthesis into a prioritised, sequenced capability roadmap — with a business case for each item',
            ].map((item, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <span className="text-teal-500 text-xs mt-0.5 flex-shrink-0">→</span>
                <p className="text-slate-300 text-sm">{item}</p>
              </div>
            ))}
          </div>
        </Card>
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
        title="Not consultants. Something better."
        subtitle="A traditional engagement to do this work would take around 17 consultants over 12 weeks. That model has real costs — in budget, in continuity, and in what happens when the team leaves."
      />
      <div className="grid grid-cols-2 gap-5 mb-5">

        {/* Traditional column */}
        <Card className="border-red-900/30 bg-red-950/20">
          <p className="text-red-400 text-xs font-bold uppercase tracking-widest mb-4">Traditional consulting team</p>
          <div className="space-y-3">
            {[
              { label: 'Cost', detail: 'Day rates across a mixed team of 17 — senior time heavily loaded with management overhead.' },
              { label: 'Continuity', detail: 'Not everyone is full-time. People rotate off. Knowledge walks when the engagement ends.' },
              { label: 'Consistency', detail: 'Methodology applied differently across team members — outputs reflect who wrote them, not a single standard.' },
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
              { label: 'Continuous memory', detail: 'PAM — the Project Automation Manager — holds context across the full engagement. Nothing is lost between stages.' },
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
            <span className="font-semibold text-white">The whole team, licensed for a year,</span> costs less than the annual salary of a single human analyst — and delivers outputs within weeks, not quarters.
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
            <MetaRow label="Interviews" value="Structured stakeholder sessions across Property and Fleet, conducted by Avery — our AI interviewer — with human review of all transcripts and findings." />
            <MetaRow label="Data mapping" value="Inventory of existing data assets, systems, and gaps across both teams, synthesised by the discovery agent crew." />
            <MetaRow label="Value chain" value="Analysis of where decision-support tools would unlock the most value relative to strategic objectives." />
            <MetaRow label="Project management" value="PAM — the Project Automation Manager — coordinates the full agent crew, tracks progress, and maintains context throughout the engagement." />
            <MetaRow label="Output" value="A prioritised, sequenced capability investment roadmap — each tool ranked by value it unlocks from asset investment decisions, build feasibility, and maturity uplift — reviewed and signed off by a human lead." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Timeline</p>
            <p className="text-white text-2xl font-bold">4–6 <span className="text-base font-normal text-slate-400">weeks</span></p>
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
            <span className="font-semibold">Gate value:</span> Scottish Power knows which capability investments to make — and in what order — before a single pound is committed to building tools. The sequencing matters: build the wrong tool first and the budget is consumed on low-value capability while the high-value decisions remain unsupported.
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

// ── Slide 6: Phase 2 ──────────────────────────────────────────────────────────

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
            <MetaRow label="Preferred model" value="Upskill a frontier IT team within Scottish Power Group Services. TaskReimagination.ai provides engineering support and assurance — the build happens within Scottish Power's own IT estate, demonstrating internal deliverability from day one." />
            <MetaRow label="Why this matters" value="The demonstrators are not a vendor prototype. They are built by Scottish Power's own engineers, proving the organisation can industrialise and own them. We de-risk the build; you own the outcome." />
            <MetaRow label="Examples" value="Risk exposure dashboard, whole-life cost optimisation model, performance benchmarking and reporting. Final scope confirmed by Phase 1 output." />
            <MetaRow label="Output" value="Interactive demonstrators — built in-house, assured externally — that bring potential value to life for leadership and are ready to industrialise." />
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
            <MetaRow label="Scope" value="Determined by the Phase 1 business case. The investment backlog defines which capabilities to industrialise and in what order — Phase 3 is shaped by the evidence, not by assumptions made before the discovery." />
            <MetaRow label="PMO support" value="Structured programme delivery with clear milestones, governance, and accountability across Property and Fleet." />
            <MetaRow label="Change management" value="Embedding new ways of working — ensuring tools are adopted, trusted, and sustained in daily operations across both teams." />
            <MetaRow label="Capability building" value="Role-specific training and knowledge transfer so Property and Fleet teams can operate and extend the tooling independently of external support." />
            <MetaRow label="Output" value="Production-grade tooling embedded in Scottish Power's IT estate, with a durable operating model that sustains and extends the capability after the engagement closes." />
          </div>
        </Card>
        <div className="space-y-4">
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Timeline</p>
            <p className="text-white text-2xl font-bold">6–12 <span className="text-base font-normal text-slate-400">months</span></p>
          </Card>
          <Card>
            <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2">Sustainably establishes</p>
            <div className="space-y-1.5 text-xs text-slate-300">
              <p>→ Production tooling</p>
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
            <span className="font-semibold">Gate value:</span> Because scope is determined by Phase 1, every pound committed to Phase 3 is backed by an evidence-based business case. The result is sustainable capability that outlasts the engagement — a permanent step-change, not a one-off project.
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
  const dims = [
    {
      label: 'Asset Management',
      states: ['Reactive, fragmented', 'Baselined & prioritised', 'Proactive & data-led', 'Optimised, predictive'],
    },
    {
      label: 'Data Management',
      states: ['Siloed, inconsistent', 'Inventoried & mapped', 'Governed & integrated', 'Decision-ready, trusted'],
    },
    {
      label: 'Governance',
      states: ['Variable', 'Framework established', 'Embedded in practice', 'Transparent, auditable'],
    },
  ]
  const phases = ['Current', 'Phase 1', 'Phase 2', 'Phase 3']

  return (
    <div>
      <SlideHeader
        eyebrow="Maturity trajectory"
        title="Three dimensions. Three steps up."
        subtitle="Each phase moves the dial measurably across the dimensions that matter most to sustainable asset and fleet management."
      />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-slate-500 text-xs uppercase tracking-widest font-medium pb-4 pr-6 w-40"></th>
              {phases.map((p, i) => (
                <th key={p} className="text-center pb-4 px-2">
                  {i === 0
                    ? <span className="text-slate-500 text-xs uppercase tracking-widest font-medium">{p}</span>
                    : <PhaseTag n={i as 1|2|3} />
                  }
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dims.map((dim, di) => (
              <tr key={dim.label} className={di < dims.length - 1 ? 'border-b border-slate-800' : ''}>
                <td className="text-slate-300 text-sm font-medium py-4 pr-6 align-top">{dim.label}</td>
                {dim.states.map((state, si) => (
                  <td key={si} className="text-center py-4 px-2 align-top">
                    <div className={`rounded-lg px-3 py-2 text-xs leading-snug mx-1 ${
                      si === 0 ? 'bg-slate-800 text-slate-400' :
                      si === 1 ? 'bg-teal-900/40 text-teal-300 border border-teal-800/40' :
                      si === 2 ? 'bg-amber-900/30 text-amber-300 border border-amber-800/30' :
                                 'bg-slate-700 text-slate-200 border border-slate-600'
                    }`}>
                      {state}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
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
            logic: 'Phase 1 resolves the capability investment question — which tools to build, and in what order, to sustainably support asset investment decisions over 15+ years. The cost of getting this sequence wrong far exceeds the cost of Phase 1. Knowing it before committing to a build is the return.',
            risk: 'Low',
          },
          {
            phase: 2 as const,
            title: 'Decision-Support Demonstrators',
            logic: 'Built by Scottish Power\'s own IT team with external support and assurance — so the question of internal deliverability is answered during the demonstrator, not after. A demonstrator that doesn\'t convince stakeholders costs a fraction of a failed production deployment.',
            risk: 'Contained',
          },
          {
            phase: 3 as const,
            title: 'Capability Uplift & Operating Model',
            logic: 'Scope is determined by the Phase 1 business case — every pound committed is backed by evidence. Production tools embedded in Scottish Power\'s estate create compounding returns: reduced reactive spend, optimised budgets, and performance accountability that persists year on year.',
            risk: 'Evidence-based',
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

// ── Slide 10: Next Steps ──────────────────────────────────────────────────────

function SlideNext() {
  return (
    <div className="flex flex-col items-center text-center">
      <SlideHeader
        eyebrow="Next steps"
        title="Ready to begin"
      />
      <div className="grid grid-cols-3 gap-4 w-full mb-8">
        {[
          { n: '01', label: 'Agree scope', body: 'Confirm Phase 1 scope, stakeholder access across Property and Fleet, and programme governance.' },
          { n: '02', label: 'Confirm budget', body: 'Agree the budget envelope for Phase 1 and indicative envelope for Phases 2 and 3.' },
          { n: '03', label: 'Kick off', body: 'Agree start date and mobilise the discovery team. Phase 1 outputs within four to six weeks of kick-off.' },
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
          <p className="text-slate-200 text-sm">Patrick Bossert</p>
          <div className="flex items-center gap-1.5 mt-1.5">
            <p className="text-slate-600 text-[10px] uppercase tracking-widest">Powered by</p>
            <img src={logoUrl} alt="TaskReimagination.ai" className="h-3 w-auto opacity-35" />
          </div>
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
