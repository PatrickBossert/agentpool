// ui/src/components/CrewApprovalRow.tsx
import CommitControl from './CommitControl'
import { CREW_LABELS } from './agentStatus'

export type CrewState = 'working' | 'ready' | 'committed'

/**
 * One crew's place in the approval loop, and the single act available from here.
 *
 * The contributor shapes the output and marks it ready; the approver approves. Showing
 * both controls at once would invite the approver to act before the contributor has
 * finished, which is the confusion this whole project exists to remove.
 */
export function CrewApprovalRow({
  crewName,
  state,
  changeCount,
  onSubmit,
  onApprove,
}: {
  crewName: string
  state: CrewState
  changeCount: number
  onSubmit: (crewName: string) => void | Promise<void>
  onApprove: (crewName: string) => void | Promise<void>
}) {
  const label = CREW_LABELS[crewName] ?? crewName

  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-gray-100">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{label}</p>
        <p className="text-[11px] text-gray-500">
          {state === 'working'
            ? 'In progress'
            : state === 'ready'
              ? 'Ready for approval'
              : 'Approved'}
        </p>
      </div>

      {state === 'working' && (
        <CommitControl
          crewName={crewName}
          changeCount={0}
          onCommit={onSubmit}
          label="Ready for approval"
        />
      )}
      {state === 'ready' && (
        <CommitControl
          crewName={crewName}
          changeCount={changeCount}
          onCommit={onApprove}
          label="Approve"
        />
      )}
    </div>
  )
}

export default CrewApprovalRow
