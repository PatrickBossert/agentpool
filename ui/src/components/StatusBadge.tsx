// ui/src/components/StatusBadge.tsx
const COLORS: Record<string, string> = {
  pending:   'bg-slate-700 text-slate-300',
  queued:    'bg-amber-900/50 text-amber-300',
  running:   'bg-sky-900/50 text-sky-300',
  completed: 'bg-emerald-900/50 text-emerald-300',
  failed:    'bg-red-900/50 text-red-300',
  created:   'bg-slate-700 text-slate-300',
  awaiting_assignment: 'bg-amber-900/50 text-amber-300',
}

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? 'bg-slate-700 text-slate-300'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {status}
    </span>
  )
}
