// ui/src/pages/Templates.tsx
import { useState, useEffect, useCallback } from 'react'
import { listTemplates, getTemplate, createTemplate, updateTemplate, deleteTemplate } from '../api/templates'
import type {
  TemplateListItem,
  TemplateDetail,
  InterviewTemplateSchema,
  QuestionnaireTemplateSchema,
} from '../types'

// ─── helpers ────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch {
    return iso
  }
}

const INPUT_CLS =
  'w-full bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand placeholder:text-gray-400'

const BTN_SM = 'text-xs px-3 py-1.5 rounded transition-colors'

// ─── default schema factories ────────────────────────────────────────────────

function defaultInterviewSchema(): InterviewTemplateSchema {
  return { welcome_message: '', closing_message: '', sections: [] }
}

function defaultQuestionnaireSchema(): QuestionnaireTemplateSchema {
  return {
    scale: {
      min: 0,
      max: 4,
      labels: {
        '0': 'Not Accounted For',
        '1': 'Initial',
        '2': 'Developing',
        '3': 'Managed',
        '4': 'Optimised',
      },
    },
    sections: [],
  }
}

// ─── Interview schema builder ─────────────────────────────────────────────────

function InterviewSchemaBuilder({
  schema,
  onChange,
}: {
  schema: InterviewTemplateSchema
  onChange: (s: InterviewTemplateSchema) => void
}) {
  function setField(field: keyof Pick<InterviewTemplateSchema, 'welcome_message' | 'closing_message'>, val: string) {
    onChange({ ...schema, [field]: val })
  }

  function addSection() {
    onChange({ ...schema, sections: [...schema.sections, { title: '', questions: [] }] })
  }

  function removeSection(si: number) {
    const sections = schema.sections.filter((_, i) => i !== si)
    onChange({ ...schema, sections })
  }

  function updateSection(si: number, title: string) {
    const sections = schema.sections.map((s, i) => (i === si ? { ...s, title } : s))
    onChange({ ...schema, sections })
  }

  function addQuestion(si: number) {
    const newQ = {
      id: `q_${Date.now()}`,
      text: '',
      probing_instructions: '',
      follow_up_branches: [],
      evasion_signals: [],
      follow_up_count: 2,
    }
    const sections = schema.sections.map((s, i) =>
      i === si ? { ...s, questions: [...s.questions, newQ] } : s
    )
    onChange({ ...schema, sections })
  }

  function removeQuestion(si: number, qi: number) {
    const sections = schema.sections.map((s, i) =>
      i === si ? { ...s, questions: s.questions.filter((_, j) => j !== qi) } : s
    )
    onChange({ ...schema, sections })
  }

  function updateQuestion(
    si: number,
    qi: number,
    field: string,
    val: string | number | string[]
  ) {
    const sections = schema.sections.map((s, i) =>
      i === si
        ? {
            ...s,
            questions: s.questions.map((q, j) => (j === qi ? { ...q, [field]: val } : q)),
          }
        : s
    )
    onChange({ ...schema, sections })
  }

  return (
    <div className="space-y-4">
      {/* welcome / closing */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-600 block mb-1">Welcome Message</label>
          <textarea
            value={schema.welcome_message}
            onChange={(e) => setField('welcome_message', e.target.value)}
            rows={2}
            className={INPUT_CLS}
          />
        </div>
        <div>
          <label className="text-xs text-gray-600 block mb-1">Closing Message</label>
          <textarea
            value={schema.closing_message}
            onChange={(e) => setField('closing_message', e.target.value)}
            rows={2}
            className={INPUT_CLS}
          />
        </div>
      </div>

      {/* sections */}
      <div className="space-y-4">
        {schema.sections.map((sec, si) => (
          <div key={si} className="border border-gray-200 rounded p-3 space-y-3">
            <div className="flex items-center gap-2">
              <input
                value={sec.title}
                onChange={(e) => updateSection(si, e.target.value)}
                placeholder={`Section ${si + 1} title`}
                className={INPUT_CLS}
              />
              <button
                type="button"
                onClick={() => removeSection(si)}
                className="text-red-400 hover:text-red-300 text-xs shrink-0"
              >
                Remove
              </button>
            </div>

            {/* questions */}
            <div className="space-y-3 pl-3 border-l border-gray-200">
              {sec.questions.map((q, qi) => (
                <div key={qi} className="space-y-2 bg-gray-50 rounded p-2">
                  <div className="flex items-start gap-2">
                    <div className="flex-1 space-y-2">
                      <input
                        value={q.text}
                        onChange={(e) => updateQuestion(si, qi, 'text', e.target.value)}
                        placeholder="Question text"
                        className={INPUT_CLS}
                      />
                      <input
                        value={q.probing_instructions}
                        onChange={(e) => updateQuestion(si, qi, 'probing_instructions', e.target.value)}
                        placeholder="Probing instructions"
                        className={INPUT_CLS}
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          value={q.follow_up_branches.join(', ')}
                          onChange={(e) =>
                            updateQuestion(
                              si,
                              qi,
                              'follow_up_branches',
                              e.target.value.split(',').map((x) => x.trim()).filter(Boolean)
                            )
                          }
                          placeholder="Follow-up branches (comma-separated)"
                          className={INPUT_CLS}
                        />
                        <input
                          value={q.evasion_signals.join(', ')}
                          onChange={(e) =>
                            updateQuestion(
                              si,
                              qi,
                              'evasion_signals',
                              e.target.value.split(',').map((x) => x.trim()).filter(Boolean)
                            )
                          }
                          placeholder="Evasion signals (comma-separated)"
                          className={INPUT_CLS}
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-gray-600 shrink-0">Follow-up count</label>
                        <input
                          type="number"
                          min={0}
                          max={10}
                          value={q.follow_up_count}
                          onChange={(e) => updateQuestion(si, qi, 'follow_up_count', Number(e.target.value))}
                          className="w-20 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900 outline-none focus:border-brand"
                        />
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeQuestion(si, qi)}
                      className="text-red-400 hover:text-red-300 text-xs shrink-0 mt-1"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
              <button
                type="button"
                onClick={() => addQuestion(si)}
                className={`${BTN_SM} border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-400`}
              >
                + Add Question
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={addSection}
          className={`${BTN_SM} border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-400`}
        >
          + Add Section
        </button>
      </div>
    </div>
  )
}

// ─── Questionnaire schema builder ─────────────────────────────────────────────

function QuestionnaireSchemaBuilder({
  schema,
  onChange,
}: {
  schema: QuestionnaireTemplateSchema
  onChange: (s: QuestionnaireTemplateSchema) => void
}) {
  function addSection() {
    const id = `sec_${Date.now()}`
    onChange({ ...schema, sections: [...schema.sections, { id, title: '', description: '', questions: [] }] })
  }

  function removeSection(si: number) {
    onChange({ ...schema, sections: schema.sections.filter((_, i) => i !== si) })
  }

  function updateSectionField(si: number, field: 'id' | 'title' | 'description', val: string) {
    const sections = schema.sections.map((s, i) => (i === si ? { ...s, [field]: val } : s))
    onChange({ ...schema, sections })
  }

  function addQuestion(si: number) {
    const id = `q_${Date.now()}`
    const sections = schema.sections.map((s, i) =>
      i === si ? { ...s, questions: [...s.questions, { id, text: '' }] } : s
    )
    onChange({ ...schema, sections })
  }

  function removeQuestion(si: number, qi: number) {
    const sections = schema.sections.map((s, i) =>
      i === si ? { ...s, questions: s.questions.filter((_, j) => j !== qi) } : s
    )
    onChange({ ...schema, sections })
  }

  function updateQuestion(si: number, qi: number, field: 'id' | 'text', val: string) {
    const sections = schema.sections.map((s, i) =>
      i === si
        ? { ...s, questions: s.questions.map((q, j) => (j === qi ? { ...q, [field]: val } : q)) }
        : s
    )
    onChange({ ...schema, sections })
  }

  const scaleEntries = Object.entries(schema.scale.labels).sort(
    ([a], [b]) => Number(a) - Number(b)
  )

  return (
    <div className="space-y-4">
      {/* Scale (read-only) */}
      <div>
        <label className="text-xs text-gray-600 block mb-1">Scale (read-only)</label>
        <div className="flex flex-wrap gap-2">
          {scaleEntries.map(([k, v]) => (
            <span key={k} className="text-xs bg-gray-100 text-gray-700 rounded px-2 py-0.5">
              {k} = {v}
            </span>
          ))}
        </div>
      </div>

      {/* sections */}
      <div className="space-y-4">
        {schema.sections.map((sec, si) => (
          <div key={si} className="border border-gray-200 rounded p-3 space-y-3">
            <div className="flex items-center gap-2">
              <input
                value={sec.id}
                onChange={(e) => updateSectionField(si, 'id', e.target.value)}
                placeholder="Section ID"
                className="w-32 bg-white border border-gray-200 rounded px-2 py-1.5 text-sm text-gray-900 outline-none focus:border-brand font-mono"
              />
              <input
                value={sec.title}
                onChange={(e) => updateSectionField(si, 'title', e.target.value)}
                placeholder="Section title"
                className={`${INPUT_CLS} flex-1`}
              />
              <button
                type="button"
                onClick={() => removeSection(si)}
                className="text-red-400 hover:text-red-300 text-xs shrink-0"
              >
                Remove
              </button>
            </div>
            <input
              value={sec.description}
              onChange={(e) => updateSectionField(si, 'description', e.target.value)}
              placeholder="Section description"
              className={INPUT_CLS}
            />

            {/* questions */}
            <div className="space-y-2 pl-3 border-l border-gray-200">
              {sec.questions.map((q, qi) => (
                <div key={qi} className="flex items-center gap-2">
                  <input
                    value={q.id}
                    onChange={(e) => updateQuestion(si, qi, 'id', e.target.value)}
                    placeholder="Q ID"
                    className="w-24 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900 outline-none focus:border-brand font-mono"
                  />
                  <input
                    value={q.text}
                    onChange={(e) => updateQuestion(si, qi, 'text', e.target.value)}
                    placeholder="Question text"
                    className={`${INPUT_CLS} flex-1`}
                  />
                  <button
                    type="button"
                    onClick={() => removeQuestion(si, qi)}
                    className="text-red-400 hover:text-red-300 text-xs shrink-0"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => addQuestion(si)}
                className={`${BTN_SM} border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-400`}
              >
                + Add Question
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={addSection}
          className={`${BTN_SM} border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-400`}
        >
          + Add Section
        </button>
      </div>
    </div>
  )
}

// ─── Modal ───────────────────────────────────────────────────────────────────

interface ModalProps {
  type: 'interview' | 'questionnaire'
  initial: TemplateDetail | null
  onClose: () => void
  onSaved: () => void
}

function TemplateModal({ type, initial, onClose, onSaved }: ModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [interviewSchema, setInterviewSchema] = useState<InterviewTemplateSchema>(
    initial && type === 'interview'
      ? (initial.schema_json as InterviewTemplateSchema)
      : defaultInterviewSchema()
  )
  const [questionnaireSchema, setQuestionnaireSchema] = useState<QuestionnaireTemplateSchema>(
    initial && type === 'questionnaire'
      ? (initial.schema_json as QuestionnaireTemplateSchema)
      : defaultQuestionnaireSchema()
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    if (!name.trim()) {
      setError('Name is required.')
      return
    }
    setSaving(true)
    setError(null)
    const schema_json = type === 'interview' ? interviewSchema : questionnaireSchema
    try {
      if (initial) {
        await updateTemplate(initial.id, { name, description, schema_json })
      } else {
        await createTemplate({ name, description, type, schema_json })
      }
      onSaved()
    } catch {
      setError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-white border border-gray-200 rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 shrink-0">
          <h3 className="text-sm font-semibold text-gray-900">
            {initial ? 'Edit' : 'New'}{' '}
            {type === 'interview' ? 'Interview' : 'Questionnaire'} Template
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg leading-none">
            ×
          </button>
        </div>

        {/* body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">Name *</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Template name"
                className={INPUT_CLS}
              />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Description</label>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Short description"
                className={INPUT_CLS}
              />
            </div>
          </div>

          <div className="border-t border-gray-200 pt-4">
            {type === 'interview' ? (
              <InterviewSchemaBuilder schema={interviewSchema} onChange={setInterviewSchema} />
            ) : (
              <QuestionnaireSchemaBuilder
                schema={questionnaireSchema}
                onChange={setQuestionnaireSchema}
              />
            )}
          </div>
        </div>

        {/* footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 shrink-0">
          {error ? <p className="text-xs text-red-400">{error}</p> : <span />}
          <div className="flex gap-2">
            <button onClick={onClose} className={`${BTN_SM} text-gray-400 hover:text-gray-700`}>
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className={`${BTN_SM} bg-brand hover:bg-brand-dark disabled:opacity-50 text-white`}
            >
              {saving ? 'Saving…' : 'Save Template'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Template list row ────────────────────────────────────────────────────────

function TemplateRow({
  item,
  onEdit,
  onDelete,
}: {
  item: TemplateListItem
  onEdit: () => void
  onDelete: () => void
}) {
  // question count based on list item - we don't have schema_json here so show -
  return (
    <tr className="border-t border-gray-200 hover:bg-gray-50">
      <td className="px-4 py-2.5">
        <p className="text-gray-900 text-sm font-medium">{item.name}</p>
        {item.description && <p className="text-gray-400 text-xs mt-0.5">{item.description}</p>}
      </td>
      <td className="px-3 py-2.5 text-xs text-gray-500">{fmtDate(item.created_at)}</td>
      <td className="px-3 py-2.5 text-xs text-gray-500 text-center">-</td>
      <td className="px-3 py-2.5 text-right">
        <div className="flex items-center justify-end gap-3">
          <button onClick={onEdit} className="text-xs text-brand hover:text-brand-dark transition-colors">
            Edit
          </button>
          <button
            onClick={onDelete}
            className="text-xs text-red-400 hover:text-red-300 transition-colors"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

// ─── Tab panel ────────────────────────────────────────────────────────────────

function TemplateTab({
  type,
  items,
  loading,
  error,
  onNew,
  onEdit,
  onDelete,
}: {
  type: 'interview' | 'questionnaire'
  items: TemplateListItem[]
  loading: boolean
  error: string | null
  onNew: () => void
  onEdit: (item: TemplateListItem) => void
  onDelete: (item: TemplateListItem) => void
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          {items.length} template{items.length !== 1 ? 's' : ''}
        </p>
        <button
          onClick={onNew}
          className="text-xs bg-brand hover:bg-brand-dark text-white rounded px-3 py-1.5 transition-colors"
        >
          + New Template
        </button>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-400">{error}</p>}

      {!loading && items.length === 0 && (
        <p className="text-sm text-gray-400">
          No {type === 'interview' ? 'interview' : 'questionnaire'} templates yet.
        </p>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-4 py-2 text-left text-xs text-gray-500 font-medium">Name</th>
                <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Created</th>
                <th className="px-3 py-2 text-center text-xs text-gray-500 font-medium">Questions</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <TemplateRow
                  key={item.id}
                  item={item}
                  onEdit={() => onEdit(item)}
                  onDelete={() => onDelete(item)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

type TabType = 'interview' | 'questionnaire'

export default function Templates() {
  const [activeTab, setActiveTab] = useState<TabType>('interview')
  const [interviewItems, setInterviewItems] = useState<TemplateListItem[]>([])
  const [questionnaireItems, setQuestionnaireItems] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // modal state
  const [modal, setModal] = useState<{
    open: boolean
    type: TabType
    initial: TemplateDetail | null
  }>({ open: false, type: 'interview', initial: null })

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    try {
      const [interviews, questionnaires] = await Promise.all([
        listTemplates('interview'),
        listTemplates('questionnaire'),
      ])
      setInterviewItems(interviews)
      setQuestionnaireItems(questionnaires)
    } catch {
      setFetchError('Failed to load templates.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  function openNew(type: TabType) {
    setModal({ open: true, type, initial: null })
  }

  async function openEdit(item: TemplateListItem) {
    try {
      const detail = await getTemplate(item.id)
      setModal({ open: true, type: item.type, initial: detail })
    } catch {
      setFetchError('Failed to load template.')
    }
  }

  async function handleDelete(item: TemplateListItem) {
    if (!window.confirm(`Delete template "${item.name}"?`)) return
    try {
      await deleteTemplate(item.id)
      await fetchAll()
    } catch {
      setFetchError('Delete failed.')
    }
  }

  function handleSaved() {
    setModal({ open: false, type: 'interview', initial: null })
    fetchAll()
  }

  const TABS: { key: TabType; label: string }[] = [
    { key: 'interview', label: 'Interview Templates' },
    { key: 'questionnaire', label: 'Questionnaire Templates' },
  ]

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">Templates</h2>

      {/* Tabs */}
      <div className="flex gap-0 border-b border-gray-200">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`text-sm px-4 py-2 border-b-2 transition-colors -mb-px ${
              activeTab === tab.key
                ? 'border-brand text-brand'
                : 'border-transparent text-gray-400 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'interview' && (
        <TemplateTab
          type="interview"
          items={interviewItems}
          loading={loading}
          error={fetchError}
          onNew={() => openNew('interview')}
          onEdit={openEdit}
          onDelete={handleDelete}
        />
      )}
      {activeTab === 'questionnaire' && (
        <TemplateTab
          type="questionnaire"
          items={questionnaireItems}
          loading={loading}
          error={fetchError}
          onNew={() => openNew('questionnaire')}
          onEdit={openEdit}
          onDelete={handleDelete}
        />
      )}

      {/* Modal */}
      {modal.open && (
        <TemplateModal
          type={modal.type}
          initial={modal.initial}
          onClose={() => setModal({ open: false, type: 'interview', initial: null })}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
