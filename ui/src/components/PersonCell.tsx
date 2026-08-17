// ui/src/components/PersonCell.tsx
//
// One field of the person a login is on the selected project - their name, or the entity they
// work for.
//
// A login has no name of its own. The name lives on a `stakeholders` row, per engagement, and
// the user list reads it through whichever project is selected - so there is exactly one
// value here, never a choice between engagements. Absent is rendered as absent: an
// administrator-granted membership carries no stakeholder row, and a dash is the truthful
// answer where a guess would be worse than saying nothing.
import type { PersonDetails } from '../types'

export type PersonField = 'name' | 'entity'

export function personValue(
  person: PersonDetails | null | undefined,
  field: PersonField,
): string | null {
  return person?.[field] ?? null
}

export default function PersonCell({
  person,
  field,
}: {
  person: PersonDetails | null | undefined
  field: PersonField
}) {
  const value = personValue(person, field)
  if (value) return <span className="text-primary">{value}</span>
  return (
    <span className="text-muted" title="No person record on this project for this account.">
      -
    </span>
  )
}
