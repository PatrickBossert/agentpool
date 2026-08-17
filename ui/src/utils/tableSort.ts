// ui/src/utils/tableSort.ts
//
// Client-side sorting for the administration listings. Pure, so it can be asserted directly
// rather than through a rendered table.
//
// Client-side is the right call at this scale and is a decision rather than a shortcut: the
// user list is one unpaginated request already, tens of rows on the largest deployment this
// serves, and every column being sorted on is in the payload. Moving it to the server would
// buy nothing and would put the ORDER BY on a query whose scoping (`fetch_users_by_org`, and
// the project scoping behind the person block) is the delicate part. It stops being right the
// day the list is paginated - a page-at-a-time sort is a sort of the page, not of the list -
// and that is the signal to move it.
export type SortDirection = 'asc' | 'desc'

export interface SortState {
  key: string
  direction: SortDirection
}

/** What clicking a column header does: a new column starts ascending, the current one flips. */
export function toggleSort(current: SortState, key: string): SortState {
  if (current.key !== key) return { key, direction: 'asc' }
  return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
}

/**
 * `rows` ordered by `state`, as a new array - `keyFor` returns the comparable string for a
 * row and column, or null when the row has no value for it.
 *
 * Null sorts last in *both* directions, deliberately. Half the point of these listings is a
 * name that is absent because the account holds no stakeholder row - the built-in
 * administrator, anything created directly through /admin - and flipping to descending must
 * not answer "sort by name" with a screen of dashes. Absent is not a low value; it is the
 * absence of one, and it stays out of the way at either end.
 *
 * Comparison is case- and accent-insensitive and numeric-aware, so "de Vries" sorts beside
 * "De Vries" and "Region 10" after "Region 9".
 */
export function sortRows<T>(
  rows: T[],
  state: SortState,
  keyFor: (row: T, key: string) => string | null,
): T[] {
  const sign = state.direction === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const left = keyFor(a, state.key)
    const right = keyFor(b, state.key)
    if (left === null && right === null) return 0
    if (left === null) return 1
    if (right === null) return -1
    return sign * left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
  })
}
