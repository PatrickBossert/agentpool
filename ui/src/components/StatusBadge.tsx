// ui/src/components/StatusBadge.tsx
const COLORS: Record<string, string> = {
  pending:   'bg-gray-100 text-gray-600',
  queued:    'bg-amber-100 text-amber-700',
  running:   'bg-brand/10 text-teal-700',
  completed: 'bg-emerald-100 text-emerald-700',
  failed:    'bg-red-100 text-red-700',
  created:   'bg-gray-100 text-gray-600',
  awaiting_assignment: 'bg-amber-100 text-amber-700',
}

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {status}
    </span>
  )
}
