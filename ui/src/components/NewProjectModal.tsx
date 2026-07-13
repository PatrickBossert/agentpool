// ui/src/components/NewProjectModal.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'

interface Props {
  onClose: () => void
}

export default function NewProjectModal({ onClose }: Props) {
  const [slug, setSlug] = useState('')
  const [sector, setSector] = useState('')
  const [llmMode, setLlmMode] = useState<'standard' | 'sensitive' | 'fallback'>('standard')
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
      await projectsApi.create({ client_slug: slug, sector: sector.trim(), llm_mode: llmMode })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      onClose()
      navigate(`/${slug}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create project'
      setServerError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-white border border-gray-200 rounded-xl p-6 w-80 space-y-4">
        <h2 className="text-gray-900 font-semibold">New Project</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
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
