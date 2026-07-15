// ui/src/components/tabs/MayaSetupTab.tsx
// Maya's Setup tab: template assignments per value chain node + link to template library
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { projectsApi } from '../../api/endpoints'
import { listNodeTemplates, putNodeTemplate } from '../../api/nodeTemplates'
import { listTemplates } from '../../api/templates'
import type { NodeTemplateAssignment, TemplateListItem } from '../../types'

function sortByActivityId(assignments: NodeTemplateAssignment[]): NodeTemplateAssignment[] {
  return [...assignments].sort((a, b) => {
    if (!a.activity_id && !b.activity_id) return a.node_label.localeCompare(b.node_label)
    if (!a.activity_id) return 1
    if (!b.activity_id) return -1
    const aParts = a.activity_id.split('.').map(Number)
    const bParts = b.activity_id.split('.').map(Number)
    const len = Math.max(aParts.length, bParts.length)
    for (let i = 0; i < len; i++) {
      const diff = (aParts[i] ?? 0) - (bParts[i] ?? 0)
      if (diff !== 0) return diff
    }
    return 0
  })
}

export default function MayaSetupTab({ slug }: { slug: string }) {
  const navigate = useNavigate()
  const [nodeAssignments, setNodeAssignments] = useState<NodeTemplateAssignment[]>([])
  const [interviewTemplates, setInterviewTemplates] = useState<TemplateListItem[]>([])
  const [questionnaireTemplates, setQuestionnaireTemplates] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(true)

  const { data: settings } = useQuery({
    queryKey: ['settings', slug],
    queryFn: () => projectsApi.getSettings(slug),
  })

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    Promise.all([
      listNodeTemplates(slug),
      listTemplates('interview'),
      listTemplates('questionnaire'),
    ]).then(([assignments, interviewTpls, questionnaireTpls]) => {
      setNodeAssignments(sortByActivityId(assignments))
      setInterviewTemplates(interviewTpls)
      setQuestionnaireTemplates(questionnaireTpls)
    }).catch(console.error).finally(() => setLoading(false))
  }, [slug])

  async function handleTemplateChange(
    nodeLabel: string,
    field: 'interview_template_id' | 'questionnaire_template_id',
    value: number | null,
  ) {
    const current = nodeAssignments.find(a => a.node_label === nodeLabel)
    const updated: NodeTemplateAssignment = current
      ? { ...current, [field]: value }
      : { node_label: nodeLabel, activity_id: null, interview_template_id: null, questionnaire_template_id: null, [field]: value }

    setNodeAssignments(prev =>
      prev.some(a => a.node_label === nodeLabel)
        ? prev.map(a => (a.node_label === nodeLabel ? updated : a))
        : [...prev, updated]
    )

    try {
      await putNodeTemplate(slug, nodeLabel, {
        interview_template_id: updated.interview_template_id,
        questionnaire_template_id: updated.questionnaire_template_id,
      })
    } catch (e) {
      console.error('Auto-save failed', e)
    }
  }

  const standardsRefs = settings?.standards_references

  return (
    <div className="space-y-5">

      {/* Standards context */}
      {standardsRefs && (
        <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2.5">
          <p className="text-[10px] font-bold text-blue-500 uppercase tracking-widest mb-1">Standards &amp; Frameworks</p>
          <p className="text-[11px] text-blue-700 leading-relaxed">{standardsRefs}</p>
          <p className="text-[10px] text-blue-500 mt-1">Edit in Alex's Setup tab.</p>
        </div>
      )}

      {/* Template Library link */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">Template Library</p>
          <p className="text-[11px] text-gray-400">
            {interviewTemplates.length} interview · {questionnaireTemplates.length} questionnaire template{questionnaireTemplates.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={() => navigate(`/${slug}/templates`)}
          className="flex items-center gap-1.5 text-xs font-medium text-brand hover:text-brand-dark border border-brand/30 rounded-lg px-3 py-1.5 hover:bg-brand/5 transition-colors"
        >
          <ExternalLink size={12} /> Manage Templates
        </button>
      </div>

      {/* Node assignments table */}
      <div>
        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Template Assignments</p>
        <p className="text-[11px] text-gray-400 mb-3">
          Assign interview and questionnaire templates to each value chain node. Changes save automatically.
        </p>

        {loading ? (
          <p className="text-xs text-gray-400 animate-pulse py-4">Loading assignments…</p>
        ) : nodeAssignments.length === 0 ? (
          <p className="text-xs text-gray-400 italic py-4">
            No nodes yet — run the Value Chain crew (Alex) first to generate nodes.
          </p>
        ) : (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-400">
                  <th className="pb-1.5 pr-2 font-medium w-10">#</th>
                  <th className="pb-1.5 pr-3 font-medium">Node</th>
                  <th className="pb-1.5 pr-3 font-medium">Interview</th>
                  <th className="pb-1.5 font-medium">Questionnaire</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {nodeAssignments.map(a => {
                  const isL1 = a.level === 'L1'
                  return (
                    <tr key={a.node_label} className={isL1 ? 'bg-gray-50' : ''}>
                      <td className="py-2 pr-2 font-mono text-[10px] text-gray-400 whitespace-nowrap">
                        {a.activity_id ?? '-'}
                      </td>
                      <td className="py-2 pr-3">
                        <span className={`text-xs ${isL1 ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>
                          {a.node_label}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <select
                          value={a.interview_template_id ?? ''}
                          onChange={e => handleTemplateChange(a.node_label, 'interview_template_id', e.target.value ? Number(e.target.value) : null)}
                          className="bg-white border border-gray-200 rounded px-1.5 py-0.5 text-xs text-gray-800 outline-none focus:border-brand w-full max-w-[140px]"
                        >
                          <option value="">— None —</option>
                          {interviewTemplates.map(t => (
                            <option key={t.id} value={t.id}>{t.name}</option>
                          ))}
                        </select>
                      </td>
                      <td className="py-2">
                        <select
                          value={a.questionnaire_template_id ?? ''}
                          onChange={e => handleTemplateChange(a.node_label, 'questionnaire_template_id', e.target.value ? Number(e.target.value) : null)}
                          className="bg-white border border-gray-200 rounded px-1.5 py-0.5 text-xs text-gray-800 outline-none focus:border-brand w-full max-w-[140px]"
                        >
                          <option value="">— None —</option>
                          {questionnaireTemplates.map(t => (
                            <option key={t.id} value={t.id}>{t.name}</option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
