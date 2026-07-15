// ui/src/components/InterviewTemplateEditor.tsx
import { useState, useEffect, useCallback } from 'react'
import { X } from 'lucide-react'
import { apiClient } from '../api/client'

const INPUT = 'w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand placeholder:text-gray-400'
const BTN_SM = 'text-xs px-3 py-1.5 rounded transition-colors'

interface Question {
  id: string
  text: string
  follow_up_count: number
  probing_instructions: string
  follow_up_branches: string[]
  evasion_signals: string[]
}

interface Section {
  title: string
  questions: Question[]
}

interface Script {
  node_label?: string
  level?: string
  research_brief?: string
  study_objectives?: string[]
  welcome_message: string
  closing_message: string
  sections: Section[]
}

interface Props {
  slug: string
  nodeLabel: string
  activityId: string | null
  onClose: () => void
}

export default function InterviewTemplateEditor({ slug, nodeLabel, activityId, onClose }: Props) {
  const [script, setScript] = useState<Script | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await apiClient.get<Script>(`/projects/${slug}/interview-scripts/${encodeURIComponent(nodeLabel)}`)
      setScript(r.data)
    } catch {
      setError('No interview script found for this node. Run the Interview Script Designer first.')
    } finally {
      setLoading(false)
    }
  }, [slug, nodeLabel])

  useEffect(() => { load() }, [load])

  async function handleSave() {
    if (!script) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.patch(`/projects/${slug}/interview-scripts/${encodeURIComponent(nodeLabel)}`, { script })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError('Save failed.')
    } finally {
      setSaving(false)
    }
  }

  function setField<K extends keyof Script>(k: K, v: Script[K]) {
    setScript(s => s ? { ...s, [k]: v } : s)
  }

  function addSection() {
    setScript(s => s ? { ...s, sections: [...s.sections, { title: '', questions: [] }] } : s)
  }

  function removeSection(si: number) {
    setScript(s => s ? { ...s, sections: s.sections.filter((_, i) => i !== si) } : s)
  }

  function updateSectionTitle(si: number, title: string) {
    setScript(s => {
      if (!s) return s
      const sections = s.sections.map((sec, i) => i === si ? { ...sec, title } : sec)
      return { ...s, sections }
    })
  }

  function addQuestion(si: number) {
    const newQ: Question = {
      id: `Q${Date.now()}`,
      text: '',
      follow_up_count: 2,
      probing_instructions: '',
      follow_up_branches: [],
      evasion_signals: [],
    }
    setScript(s => {
      if (!s) return s
      const sections = s.sections.map((sec, i) =>
        i === si ? { ...sec, questions: [...sec.questions, newQ] } : sec
      )
      return { ...s, sections }
    })
  }

  function removeQuestion(si: number, qi: number) {
    setScript(s => {
      if (!s) return s
      const sections = s.sections.map((sec, i) =>
        i === si ? { ...sec, questions: sec.questions.filter((_, j) => j !== qi) } : sec
      )
      return { ...s, sections }
    })
  }

  function updateQuestion(si: number, qi: number, field: keyof Question, val: unknown) {
    setScript(s => {
      if (!s) return s
      const sections = s.sections.map((sec, i) =>
        i === si
          ? { ...sec, questions: sec.questions.map((q, j) => j === qi ? { ...q, [field]: val } : q) }
          : sec
      )
      return { ...s, sections }
    })
  }

  const title = activityId ? `${activityId} - ${nodeLabel}` : nodeLabel

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white border border-gray-200 rounded-lg shadow-xl w-full max-w-4xl max-h-[92vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 shrink-0">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Interview Script</h3>
            <p className="text-xs text-gray-400 mt-0.5">{title}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading && <p className="text-sm text-gray-400">Loading…</p>}
          {error && <p className="text-sm text-red-400">{error}</p>}

          {script && !loading && (
            <div className="space-y-6">
              {/* Meta */}
              {(script.research_brief || script.study_objectives?.length) && (
                <div className="bg-gray-50 rounded-lg p-4 space-y-2 border border-gray-200">
                  {script.research_brief && (
                    <div>
                      <label className="text-xs font-medium text-gray-600 block mb-1">Research Brief</label>
                      <textarea
                        value={script.research_brief}
                        onChange={e => setField('research_brief', e.target.value)}
                        rows={2}
                        className={INPUT}
                      />
                    </div>
                  )}
                  {script.study_objectives && (
                    <div>
                      <label className="text-xs font-medium text-gray-600 block mb-1">Study Objectives</label>
                      <textarea
                        value={script.study_objectives.join('\n')}
                        onChange={e => setField('study_objectives', e.target.value.split('\n').filter(Boolean))}
                        rows={3}
                        placeholder="One objective per line"
                        className={INPUT}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Welcome / Closing */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-600 block mb-1">Welcome Message</label>
                  <textarea
                    value={script.welcome_message}
                    onChange={e => setField('welcome_message', e.target.value)}
                    rows={2}
                    className={INPUT}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-600 block mb-1">Closing Message</label>
                  <textarea
                    value={script.closing_message}
                    onChange={e => setField('closing_message', e.target.value)}
                    rows={2}
                    className={INPUT}
                  />
                </div>
              </div>

              {/* Sections */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Sections & Questions</h4>
                  <button type="button" onClick={addSection} className={`${BTN_SM} border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-400`}>
                    + Add Section
                  </button>
                </div>

                {script.sections.map((sec, si) => (
                  <div key={si} className="border border-gray-200 rounded-lg overflow-hidden">
                    {/* Section header */}
                    <div className="flex items-center gap-2 bg-gray-50 px-3 py-2 border-b border-gray-200">
                      <span className="text-xs font-mono text-gray-400 shrink-0">§{si + 1}</span>
                      <input
                        value={sec.title}
                        onChange={e => updateSectionTitle(si, e.target.value)}
                        placeholder="Section title"
                        className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900 outline-none focus:border-brand"
                      />
                      <button type="button" onClick={() => removeSection(si)} className="text-red-400 hover:text-red-300 text-xs">Remove</button>
                    </div>

                    {/* Questions */}
                    <div className="p-3 space-y-3">
                      {sec.questions.map((q, qi) => (
                        <div key={qi} className="bg-gray-50 rounded p-3 space-y-2 border border-gray-100">
                          <div className="flex items-start gap-2">
                            <span className="text-xs font-mono text-gray-400 shrink-0 mt-1">{q.id}</span>
                            <div className="flex-1 space-y-2">
                              <input
                                value={q.text}
                                onChange={e => updateQuestion(si, qi, 'text', e.target.value)}
                                placeholder="Question text"
                                className={INPUT}
                              />
                              <input
                                value={q.probing_instructions}
                                onChange={e => updateQuestion(si, qi, 'probing_instructions', e.target.value)}
                                placeholder="Probing instructions"
                                className={INPUT}
                              />
                              <div className="grid grid-cols-2 gap-2">
                                <input
                                  value={q.follow_up_branches.join(', ')}
                                  onChange={e => updateQuestion(si, qi, 'follow_up_branches',
                                    e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
                                  placeholder="Follow-up branches (comma-separated)"
                                  className={INPUT}
                                />
                                <input
                                  value={q.evasion_signals.join(', ')}
                                  onChange={e => updateQuestion(si, qi, 'evasion_signals',
                                    e.target.value.split(',').map(x => x.trim()).filter(Boolean))}
                                  placeholder="Evasion signals (comma-separated)"
                                  className={INPUT}
                                />
                              </div>
                            </div>
                            <button type="button" onClick={() => removeQuestion(si, qi)} className="text-red-400 hover:text-red-300 text-xs shrink-0 mt-1"><X size={12} /></button>
                          </div>
                        </div>
                      ))}
                      <button type="button" onClick={() => addQuestion(si)} className={`${BTN_SM} border border-dashed border-gray-300 text-gray-400 hover:text-gray-600 hover:border-gray-400 w-full`}>
                        + Add Question
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 shrink-0">
          {error && !loading ? <p className="text-xs text-red-400">{error}</p> : (
            saved ? <p className="text-xs text-green-600">Saved and template updated.</p> : <span />
          )}
          <div className="flex gap-2">
            <button onClick={onClose} className={`${BTN_SM} text-gray-400 hover:text-gray-700`}>Close</button>
            {script && (
              <button
                onClick={handleSave}
                disabled={saving}
                className={`${BTN_SM} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
              >
                {saving ? 'Saving…' : 'Save & Sync Template'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
