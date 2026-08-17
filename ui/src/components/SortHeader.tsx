// ui/src/components/SortHeader.tsx
//
// A sortable column heading, shared by the three places a list of logins is shown.
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'
import type { SortState } from '../utils/tableSort'

interface Props {
  label: string
  sortKey: string
  state: SortState
  onSort: (key: string) => void
  className?: string
}

export default function SortHeader({ label, sortKey, state, onSort, className = '' }: Props) {
  const active = state.key === sortKey
  const ascending = active && state.direction === 'asc'
  return (
    <th className={`text-left px-4 py-2 font-normal ${className}`} aria-sort={
      active ? (ascending ? 'ascending' : 'descending') : 'none'
    }>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`flex items-center gap-1 hover:text-gray-900 ${active ? 'text-gray-900 font-semibold' : ''}`}
      >
        {label}
        {!active && <ChevronsUpDown size={12} className="text-gray-400" />}
        {active && ascending && <ChevronUp size={12} />}
        {active && !ascending && <ChevronDown size={12} />}
      </button>
    </th>
  )
}
