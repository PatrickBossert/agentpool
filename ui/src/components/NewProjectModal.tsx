// ui/src/components/NewProjectModal.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { describeError } from '../utils/describeError'

interface Props {
  onClose: () => void
}

export default function NewProjectModal({ onClose }: Props) {
  const [slug, setSlug] = useState('')
  const [sector, setSector] = useState('')
  const [llmMode, setLlmMode] = useState<'standard' | 'sensitive' | 'fallback'>('standard')
  const [approverName, setApproverName] = useState('')
  const [approverEmail, setApproverEmail] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  function validate() {
    const e: Record<string, string> = {}
    if (!slug) e.slug = 'Required'
    else if (!/^[a-z0-9-]{2,}$/.test(slug)) e.slug = 'Lowercase letters, numbers, hyphens only (min 2 chars)'
    if (!sector || sector.trim().length < 2) e.sector = 'Required (min 2 characters)'
    // The approver, checked here as well as at the door. Not a second declaration of the
    // rule - the server's `looks_like_email` is the authority and refuses this body with a
    // 422 whatever the browser thinks - but pydantic's 422 carries a list `detail` rather
    // than a sentence, so `describeError` cannot render it and the consultant would see the
    // fallback. Catching the ordinary mistakes here is what puts a useful message in front
    // of them; the server is what makes the rule true.
    if (!approverName.trim()) e.approverName = 'Required'
    if (!approverEmail.trim()) e.approverEmail = 'Required'
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(approverEmail.trim()))
      e.approverEmail = 'Enter a valid email address'
    return e
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length) {
      setErrors(errs)
      return
    }
    setSubmitting(true)
    setServerError('')
    try {
      await projectsApi.create({
        client_slug: slug,
        sector: sector.trim(),
        llm_mode: llmMode,
        approver_name: approverName.trim(),
        approver_email: approverEmail.trim(),
      })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      onClose()
      navigate(`/${slug}`)
    } catch (err: unknown) {
      // describeError, imported rather than copied: this door's refusals say things a fixed
      // string cannot - which field was missing, or that the address cannot be one - and
      // "Failed to create project" reads as a transient fault that retrying will fix.
      setServerError(describeError(err, 'Failed to create project'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-white border border-gray-200 rounded-xl p-6 w-96 space-y-4">
        <h2 className="text-gray-900 font-semibold">New Project</h2>
        {/* noValidate: this form's refusals are the inline messages below and the server's own
            sentence, and native constraint validation would pre-empt both - silently, and
            differently per browser. Explicit rather than implied by "no input currently
            declares a constraint", so adding type="email" or required later cannot
            reintroduce the two-stories problem this form has already had once. */}
        <form onSubmit={handleSubmit} className="space-y-3" noValidate>
          <div>
            <label className="block text-xs text-gray-600 mb-1">Slug</label>
            <input
              className="w-full bg-surface border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:border-brand"
              placeholder="acme-rail"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
            {errors.slug && <p className="text-xs text-red-400 mt-1">{errors.slug}</p>}
          </div>
          <div>
            <label className="block text-xs text-gray-600 mb-1">Sector</label>
            <input
              className="w-full bg-surface border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:border-brand"
              placeholder="logistics"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
            />
            {errors.sector && <p className="text-xs text-red-400 mt-1">{errors.sector}</p>}
          </div>
          <div>
            <label className="block text-xs text-gray-600 mb-1">LLM Mode</label>
            <select
              className="w-full bg-surface border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:border-brand"
              value={llmMode}
              onChange={(e) =>
                setLlmMode(e.target.value as 'standard' | 'sensitive' | 'fallback')
              }
            >
              <option value="standard">Standard (Claude API)</option>
              <option value="sensitive">Sensitive (Local only)</option>
              <option value="fallback">Fallback (Claude → Local)</option>
            </select>
          </div>
          <div className="pt-1 border-t border-gray-200 space-y-3">
            <div>
              <p className="text-xs font-medium text-gray-700">First approver</p>
              <p className="text-xs text-gray-600 mt-0.5">
                Somebody has to be able to approve this engagement&apos;s outputs. They are
                invited as an approver and can be changed later on the Stakeholders tab.
              </p>
            </div>
            <div>
              <label htmlFor="approver_name" className="block text-xs text-gray-600 mb-1">
                Name
              </label>
              <input
                id="approver_name"
                className="w-full bg-surface border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:border-brand"
                placeholder="Rosalind Achebe"
                value={approverName}
                onChange={(e) => setApproverName(e.target.value)}
              />
              {errors.approverName && (
                <p className="text-xs text-red-400 mt-1">{errors.approverName}</p>
              )}
            </div>
            <div>
              <label htmlFor="approver_email" className="block text-xs text-gray-600 mb-1">
                Email
              </label>
              {/* inputMode rather than type="email", deliberately. `type="email"` brings the
                  browser's own constraint validation, which blocks submit and shows a native
                  bubble *before* `validate()` runs - so the inline message below became
                  unreachable for exactly the inputs it exists for, while `rosalind@client`
                  (valid HTML5, no dot required) fell through to it. One field, two validation
                  stories, and which one a consultant met depended on how their address was
                  wrong. `inputMode` keeps the mobile keyboard without the constraint. */}
              <input
                id="approver_email"
                inputMode="email"
                autoComplete="email"
                className="w-full bg-surface border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:border-brand"
                placeholder="rosalind.achebe@client.com"
                value={approverEmail}
                onChange={(e) => setApproverEmail(e.target.value)}
              />
              {errors.approverEmail && (
                <p className="text-xs text-red-400 mt-1">{errors.approverEmail}</p>
              )}
            </div>
          </div>
          {serverError && <p className="text-xs text-red-400">{serverError}</p>}
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 text-sm text-gray-400 hover:text-gray-700 py-1.5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm rounded py-1.5"
            >
              {submitting ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
