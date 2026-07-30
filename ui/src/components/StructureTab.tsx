// ui/src/components/StructureTab.tsx
// The Structure tab: the value chain model, the edits held against it, and the controls
// that commit them. Lifted out of ValueChain.tsx, which holds three unrelated tabs and had
// grown past the point where one more feature could be added to it safely.
import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { valueChainApi } from '../api/endpoints'
import { ValueChainTable, type ValueChainModel, type ValueChainSelection } from './ValueChainTable'
import { ContributionPanel } from './ContributionPanel'

// A refused migration carries the reason it was refused - which registry levels were found
// where L1 was expected, or that no party attribution could be recovered at all - and that
// message is the only route to correcting the registry or diagram, so it is shown rather
// than flattened into "Migration failed". The server reports this the same structured way
// PUT /value-chain-model already does for a save refusal: {"problems": [...]}, not a bare
// string - see saveProblems below, which reads the same shape.
function migrationErrorMessage(error: unknown): string {
  if (!axios.isAxiosError(error)) return 'Migration failed. Try again.'
  if (error.response?.status === 404) {
    return 'No existing diagram was found to migrate from - run the Value Chain Mapper first.'
  }
  if (error.response?.status === 422) {
    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
    const problems = (detail as { problems?: unknown } | undefined)?.problems
    if (Array.isArray(problems) && problems.length > 0) return problems.join(' ')
  }
  return 'Migration failed. Try again.'
}

export function StructureTab({ slug }: { slug: string }) {
  const qc = useQueryClient()

  const {
    data: modelData,
    isLoading: modelLoading,
    isError: modelIsError,
    error: modelError,
  } = useQuery({
    queryKey: ['value-chain-model', slug],
    queryFn: () => valueChainApi.get(slug),
    enabled: !!slug,
    retry: false,
  })

  const modelMissing = modelIsError && axios.isAxiosError(modelError) && modelError.response?.status === 404
  const model = (modelData?.model ?? null) as ValueChainModel | null

  const migrateMutation = useMutation({
    mutationFn: () => valueChainApi.migrate(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['value-chain-model', slug] }),
  })

  // Edits are held here, in the page, and only committed to the server by the Save
  // control - never per-keystroke, so the version history and change log stay meaningful.
  const [editedModel, setEditedModel] = useState<ValueChainModel | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [changeSummary, setChangeSummary] = useState('')
  const [saveProblems, setSaveProblems] = useState<string[] | null>(null)

  // Reseed the working copy from the server whenever a fresh model arrives and there is
  // nothing unsaved to lose - covers first load and the refetch after a successful save.
  useEffect(() => {
    if (model && !hasUnsavedChanges) setEditedModel(model)
  }, [model, hasUnsavedChanges])

  function handleModelChange(updated: ValueChainModel) {
    setEditedModel(updated)
    setHasUnsavedChanges(true)
    setSaveProblems(null)
  }

  // The table owns editing; the page owns which contribution is selected, since the panel
  // that shows it lives outside the table.
  const [selectedContribution, setSelectedContribution] = useState<ValueChainSelection | null>(null)

  function handleSelectContribution(activityId: string, partyId: string) {
    setSelectedContribution({ activityId, partyId })
  }

  const saveModelMutation = useMutation({
    mutationFn: () => valueChainApi.save(slug, editedModel, changeSummary),
    onSuccess: () => {
      setHasUnsavedChanges(false)
      setSaveProblems(null)
      setChangeSummary('')
      qc.invalidateQueries({ queryKey: ['value-chain-model', slug] })
    },
    onError: (e: unknown) => {
      if (axios.isAxiosError(e) && e.response?.status === 422) {
        const problems = (e.response.data as { detail?: { problems?: string[] } } | undefined)?.detail?.problems
        setSaveProblems(problems && problems.length > 0 ? problems : ['The value chain model could not be saved.'])
      } else {
        setSaveProblems(['Failed to save changes. Try again.'])
      }
    },
  })

  // Unsaved edits are discarded on navigation - the usual browser warning is the only
  // safeguard, since there is nowhere else in this app that persists a draft.
  useEffect(() => {
    function warnBeforeUnload(e: BeforeUnloadEvent) {
      if (!hasUnsavedChanges) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [hasUnsavedChanges])

  return (
    <>
      {/* What the migration actually recovered. A bare "success" hid a registry that
          yielded almost nothing, so the counts are shown rather than assumed. */}
      {migrateMutation.data && (
        <div
          data-testid="migration-counts"
          className="mb-4 bg-surface-card border border-surface rounded p-3"
        >
          <p className="text-primary text-xs font-medium mb-1">
            Migrated from the existing diagram
          </p>
          <p className="text-secondary text-xs">
            {migrateMutation.data.counts.segments} segments,{' '}
            {migrateMutation.data.counts.activities} activities,{' '}
            {migrateMutation.data.counts.contributions} contributions,{' '}
            {migrateMutation.data.counts.tasks} tasks across{' '}
            {migrateMutation.data.counts.parties} parties -{' '}
            {migrateMutation.data.counts.derived} attributed by inference.
          </p>
        </div>
      )}

      {modelLoading && <p className="text-sm text-muted">Loading…</p>}

      {!modelLoading && editedModel && (
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          <div className="flex-1 min-w-0">
            <ValueChainTable
              model={editedModel}
              onChange={handleModelChange}
              selected={selectedContribution}
              onSelect={handleSelectContribution}
            />

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={changeSummary}
                onChange={(e) => setChangeSummary(e.target.value)}
                placeholder="Summary of this change (optional)"
                className="flex-1 min-w-[16rem] max-w-md bg-surface-raised border border-surface rounded px-3 py-2 text-sm text-primary placeholder-muted outline-none focus:border-brand"
              />
              <button
                type="button"
                onClick={() => saveModelMutation.mutate()}
                disabled={!hasUnsavedChanges || saveModelMutation.isPending}
                className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
              >
                {saveModelMutation.isPending ? 'Saving…' : 'Save'}
              </button>
              {hasUnsavedChanges && !saveModelMutation.isPending && (
                <span data-testid="unsaved-changes" className="text-secondary text-xs">
                  Unsaved changes
                </span>
              )}
            </div>

            {saveProblems && (
              <div className="mt-3 bg-surface-card border border-surface rounded p-3">
                <p className="text-primary text-xs font-medium mb-1">Could not save:</p>
                <ul className="list-disc list-inside text-xs text-red-400 space-y-0.5">
                  {saveProblems.map((problem, i) => (
                    <li key={i}>{problem}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Side panel: a contribution's tasks and its activity's propositions, in place
              of a pop-up - selected from the table on the left. */}
          <div className="w-full lg:w-80 flex-shrink-0">
            {selectedContribution ? (
              <ContributionPanel
                model={editedModel}
                activityId={selectedContribution.activityId}
                partyId={selectedContribution.partyId}
              />
            ) : (
              <div
                data-testid="contribution-panel-placeholder"
                className="bg-surface-card rounded-xl p-4 text-center"
              >
                <p className="text-muted text-sm">
                  Select a contribution to see its tasks and propositions.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {!modelLoading && modelMissing && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-muted text-sm mb-4">
            No value chain model has been saved for this project yet.
          </p>
          <button
            type="button"
            onClick={() => migrateMutation.mutate()}
            disabled={migrateMutation.isPending}
            className="px-4 py-2 bg-brand hover:bg-brand-dark disabled:opacity-50 text-white text-sm font-medium rounded"
          >
            {migrateMutation.isPending ? 'Migrating…' : 'Migrate from the existing diagram'}
          </button>
          {migrateMutation.isError && (
            <p className="text-red-400 text-xs mt-3">{migrationErrorMessage(migrateMutation.error)}</p>
          )}
        </div>
      )}

      {!modelLoading && modelIsError && !modelMissing && (
        <p className="text-sm text-red-400">Failed to load the value chain model.</p>
      )}
    </>
  )
}
