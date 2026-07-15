// ui/src/components/tabs/AverySetupTab.tsx
// Avery's Setup tab: voice interviewer configuration (localStorage-backed preferences)
import { useState } from 'react'

const AVERY_CONFIG_KEY = 'agentpool-avery-voice-config'

interface AveryConfig {
  interviewStyle: 'conversational' | 'structured' | 'probing'
  questionDepth: 'surface' | 'detailed' | 'deep'
  followUpAggressiveness: 'gentle' | 'moderate' | 'persistent'
  maxSecondsSilence: number
  maxSecondsPerQuestion: number
  interviewingGuidance: string
}

function loadConfig(slug: string): AveryConfig {
  try {
    const raw = localStorage.getItem(`${AVERY_CONFIG_KEY}-${slug}`)
    if (raw) return JSON.parse(raw) as AveryConfig
  } catch { /* ignore */ }
  return {
    interviewStyle: 'conversational',
    questionDepth: 'detailed',
    followUpAggressiveness: 'moderate',
    maxSecondsSilence: 8,
    maxSecondsPerQuestion: 120,
    interviewingGuidance: 'Focus on specific examples and evidence. Avoid leading questions. Follow the interview script closely but adapt naturally to the conversation. If the stakeholder goes off-topic, gently redirect after they have finished speaking.',
  }
}

export default function AverySetupTab({ slug }: { slug: string }) {
  const [config, setConfig] = useState<AveryConfig>(() => loadConfig(slug))
  const [saved, setSaved] = useState(false)

  function save() {
    try {
      localStorage.setItem(`${AVERY_CONFIG_KEY}-${slug}`, JSON.stringify(config))
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch { /* quota */ }
  }

  function set<K extends keyof AveryConfig>(key: K, value: AveryConfig[K]) {
    setConfig(c => ({ ...c, [key]: value }))
  }

  const selectCls = 'bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-800 outline-none focus:border-brand'

  return (
    <div className="space-y-5">

      <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2.5">
        <p className="text-[11px] text-blue-700 leading-relaxed">
          Avery uses a male AI voice with accent matched to the interviewee's country (set on each stakeholder profile). These settings configure his interviewing behaviour across all sessions.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Interview Style</label>
          <select value={config.interviewStyle} onChange={e => set('interviewStyle', e.target.value as AveryConfig['interviewStyle'])} className={`${selectCls} w-full`}>
            <option value="conversational">Conversational — natural flow, adaptive</option>
            <option value="structured">Structured — follow script closely</option>
            <option value="probing">Probing — push for depth and evidence</option>
          </select>
        </div>

        <div>
          <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Question Depth</label>
          <select value={config.questionDepth} onChange={e => set('questionDepth', e.target.value as AveryConfig['questionDepth'])} className={`${selectCls} w-full`}>
            <option value="surface">Surface — broad landscape only</option>
            <option value="detailed">Detailed — ask for specifics and examples</option>
            <option value="deep">Deep — challenge assumptions, ask for evidence</option>
          </select>
        </div>

        <div>
          <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Follow-up Persistence</label>
          <select value={config.followUpAggressiveness} onChange={e => set('followUpAggressiveness', e.target.value as AveryConfig['followUpAggressiveness'])} className={`${selectCls} w-full`}>
            <option value="gentle">Gentle — accept first answer</option>
            <option value="moderate">Moderate — one follow-up if vague</option>
            <option value="persistent">Persistent — press until concrete answer</option>
          </select>
        </div>

        <div>
          <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Silence Tolerance</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={3}
              max={30}
              value={config.maxSecondsSilence}
              onChange={e => set('maxSecondsSilence', Math.max(3, Number(e.target.value)))}
              className="w-16 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
            <span className="text-xs text-gray-400">seconds before reprompting</span>
          </div>
        </div>

        <div>
          <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Max Time per Question</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={30}
              max={600}
              step={30}
              value={config.maxSecondsPerQuestion}
              onChange={e => set('maxSecondsPerQuestion', Math.max(30, Number(e.target.value)))}
              className="w-16 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
            <span className="text-xs text-gray-400">seconds</span>
          </div>
        </div>
      </div>

      <div>
        <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Interviewing Guidance</label>
        <p className="text-[11px] text-gray-400 mb-2">
          Additional guidance for Avery's interview behaviour — passed to the LLM elaboration step.
        </p>
        <textarea
          value={config.interviewingGuidance}
          onChange={e => set('interviewingGuidance', e.target.value)}
          rows={4}
          className="w-full bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 outline-none focus:border-brand resize-y"
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          className="px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded"
        >
          Save Config
        </button>
        {saved && <span className="text-emerald-500 text-xs">Saved.</span>}
      </div>
    </div>
  )
}
