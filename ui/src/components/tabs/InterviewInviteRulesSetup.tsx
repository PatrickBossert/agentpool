// ui/src/components/tabs/InterviewInviteRulesSetup.tsx
//
// How this engagement chases an interview invitation: how often, how many times, how firmly,
// and in what tone.
//
// It was the lower half of `TaylorSetupTab`. Taylor sends the chasers, which is what made the
// filename read as configuration *of* the coordinator - but replace her tomorrow and the rules
// stay exactly as they are, because they are the client's tolerance for being chased rather
// than her manner. That is the rename test, and it puts this on Setup.
//
// **These preferences are still `localStorage`, per browser rather than per project, and they
// still reach no server and therefore no chaser.** Pre-existing and out of scope here - moving
// a panel between tabs does not make it work - but a reader should not assume the tab it is on
// means the value is stored with the engagement.
import { useState } from 'react'

const INVITE_CONFIG_KEY = 'agentpool-taylor-invite-config'

interface InviteConfig {
  chaseFrequencyDays: number
  maxChases: number
  escalationStyle: 'gentle' | 'moderate' | 'persistent'
  tone: string
}

function loadInviteConfig(slug: string): InviteConfig {
  try {
    const raw = localStorage.getItem(`${INVITE_CONFIG_KEY}-${slug}`)
    if (raw) return JSON.parse(raw) as InviteConfig
  } catch { /* ignore */ }
  return { chaseFrequencyDays: 3, maxChases: 3, escalationStyle: 'moderate', tone: 'Professional and respectful; reference the value chain mapping work and its importance to the programme.' }
}

export default function InterviewInviteRulesSetup({ slug }: { slug: string }) {
  const [inviteConfig, setInviteConfig] = useState<InviteConfig>(() => loadInviteConfig(slug))
  const [configSaved, setConfigSaved] = useState(false)

  function saveInviteConfig() {
    try {
      localStorage.setItem(`${INVITE_CONFIG_KEY}-${slug}`, JSON.stringify(inviteConfig))
      setConfigSaved(true)
      setTimeout(() => setConfigSaved(false), 2500)
    } catch { /* quota */ }
  }

  const selectCls = 'bg-white border border-gray-200 rounded px-2 py-1 text-xs text-gray-800 outline-none focus:border-brand'

  return (
    <div>
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Interview Invite Rules</p>

      <div className="space-y-3">
        <div className="flex gap-4">
          <div className="flex-1">
            <label className="block text-[10px] text-gray-500 mb-1">Chase every (days)</label>
            <input
              type="number"
              min={1}
              max={14}
              value={inviteConfig.chaseFrequencyDays}
              onChange={e => setInviteConfig(c => ({ ...c, chaseFrequencyDays: Math.max(1, Number(e.target.value)) }))}
              className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[10px] text-gray-500 mb-1">Max chasers</label>
            <input
              type="number"
              min={1}
              max={10}
              value={inviteConfig.maxChases}
              onChange={e => setInviteConfig(c => ({ ...c, maxChases: Math.max(1, Number(e.target.value)) }))}
              className="w-20 bg-white border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-brand"
            />
          </div>
          <div className="flex-1">
            <label className="block text-[10px] text-gray-500 mb-1">Escalation style</label>
            <select
              value={inviteConfig.escalationStyle}
              onChange={e => setInviteConfig(c => ({ ...c, escalationStyle: e.target.value as InviteConfig['escalationStyle'] }))}
              className={selectCls}
            >
              <option value="gentle">Gentle</option>
              <option value="moderate">Moderate</option>
              <option value="persistent">Persistent</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Tone &amp; context for chasers</label>
          <textarea
            value={inviteConfig.tone}
            onChange={e => setInviteConfig(c => ({ ...c, tone: e.target.value }))}
            rows={3}
            placeholder="Describe the tone a chaser should take…"
            className="w-full bg-white border border-gray-200 rounded px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 outline-none focus:border-brand resize-y"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={saveInviteConfig}
            className="px-3 py-1.5 bg-brand hover:bg-brand-dark text-white text-xs font-medium rounded"
          >
            Save Rules
          </button>
          {configSaved && <span className="text-emerald-500 text-xs">Saved.</span>}
        </div>
      </div>
    </div>
  )
}
