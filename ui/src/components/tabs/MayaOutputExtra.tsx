// ui/src/components/tabs/MayaOutputExtra.tsx
// Maya's Output tab extra: generated interview scripts organised by level
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import type { InterviewScript } from '../../types'

const LEVEL_BADGE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-indigo-100 text-indigo-700',
  L2: 'bg-blue-100 text-blue-700',
  L3: 'bg-teal-100 text-teal-700',
  C:  'bg-amber-100 text-amber-700',
  A:  'bg-red-100 text-red-700',
  F:  'bg-orange-100 text-orange-700',
  S:  'bg-emerald-100 text-emerald-700',
}

const LEVEL_TITLE: Record<string, string> = {
  L0: 'Portfolio / Board',
  L1: 'GM / Value Stream',
  L2: 'Process Manager',
  L3: 'Practitioner',
  C:  'Customer',
  A:  'Auditor / Regulator',
  F:  'Frontline Worker',
  S:  'Corporate Services',
}

const VC_LEVELS  = new Set(['L0', 'L1', 'L2', 'L3'])
const EXT_LEVELS = new Set(['C', 'A', 'F', 'S'])

function ScriptCard({ script }: { script: InterviewScript }) {
  const [expanded, setExpanded] = useState(false)
  const badgeCls = LEVEL_BADGE[script.level] ?? 'bg-gray-100 text-gray-600'

  return (
    <div className="rounded-lg border border-gray-100 overflow-hidden">
      <button
        className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="mt-0.5 flex-shrink-0 text-gray-300">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${badgeCls}`}>
              {script.level}
            </span>
            <span className="text-[10px] text-gray-500">{LEVEL_TITLE[script.level] ?? script.level}</span>
            <span className="text-xs font-medium text-gray-800 truncate">{script.node_label}</span>
          </div>
          <p className="text-[10px] text-gray-400 line-clamp-1">{script.research_brief}</p>
        </div>
        <span className="text-[10px] text-gray-300 flex-shrink-0 mt-0.5 whitespace-nowrap">
          {script.sections.length} sections
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-3 py-2.5 space-y-3 bg-gray-50/60">
          <div>
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1">Research Brief</p>
            <p className="text-[11px] text-gray-700 leading-relaxed">{script.research_brief}</p>
          </div>
          {script.study_objectives?.length > 0 && (
            <div>
              <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1">Study Objectives</p>
              <ul className="space-y-0.5">
                {script.study_objectives.map((obj, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <span className="text-gray-300 mt-0.5 flex-shrink-0">·</span>
                    <p className="text-[11px] text-gray-600 leading-relaxed">{obj}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Sections</p>
            <div className="space-y-1">
              {script.sections.map((s, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="text-[10px] text-gray-400 w-5 flex-shrink-0 font-mono">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] text-gray-700">{s.title}</p>
                    <p className="text-[10px] text-gray-400">
                      {s.questions.length} question{s.questions.length !== 1 ? 's' : ''}
                      {s.target_minutes ? ` · ${s.target_minutes} min` : ''}
                      {s.maturity_rating ? ' · maturity rating' : ''}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function MayaOutputExtra({ slug }: { slug: string }) {
  const { data: scriptsMap, isLoading } = useQuery({
    queryKey: ['interview-scripts', slug],
    queryFn: () => projectsApi.getInterviewScripts(slug),
  })

  if (isLoading) {
    return <p className="text-xs text-gray-400 animate-pulse py-3">Loading interview scripts…</p>
  }

  const scripts: InterviewScript[] = Object.values(scriptsMap ?? {})

  if (scripts.length === 0) return null

  const vcScripts  = scripts.filter(s => VC_LEVELS.has(s.level))
  const extScripts = scripts.filter(s => EXT_LEVELS.has(s.level))

  return (
    <div className="space-y-4">
      {vcScripts.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            Value Chain Interviews
          </p>
          <div className="space-y-1.5">
            {vcScripts.map((s, i) => <ScriptCard key={i} script={s} />)}
          </div>
        </div>
      )}
      {extScripts.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
            External Perspectives
          </p>
          <div className="space-y-1.5">
            {extScripts.map((s, i) => <ScriptCard key={i} script={s} />)}
          </div>
        </div>
      )}
    </div>
  )
}
