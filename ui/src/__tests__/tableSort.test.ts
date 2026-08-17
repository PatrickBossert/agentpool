// ui/src/__tests__/tableSort.test.ts
//
// The comparator on its own. It is a pure function, so asserting it here is not a stand-in
// for asserting the table - UserListPerson.test.tsx does that through the rendered rows. What
// is here is the behaviour a rendered test reads back awkwardly: the null rule, which has to
// hold in *both* directions and is the one thing about this that is not obvious.
import { sortRows, toggleSort, type SortState } from '../utils/tableSort'

const rows = [
  { id: 1, name: 'Charlie' },
  { id: 2, name: null },
  { id: 3, name: 'alice' },
  { id: 4, name: 'Bob' },
]

const byName = (row: { name: string | null }) => row.name

function ids(state: SortState) {
  return sortRows(rows, state, byName).map((r) => r.id)
}

test('ascending sorts case-insensitively with the absent row last', () => {
  expect(ids({ key: 'name', direction: 'asc' })).toEqual([3, 4, 1, 2])
})

test('descending reverses the named rows and still leaves the absent row last', () => {
  // Not [2, 1, 4, 3]. Reversing an ordinary sort would open "sort by name, descending" with a
  // screen of dashes - and an absent name is the ordinary state of the built-in administrator
  // and every account created directly, so that is not a rare row.
  expect(ids({ key: 'name', direction: 'desc' })).toEqual([1, 4, 3, 2])
})

test('sorting returns a new array and leaves the original order alone', () => {
  const before = rows.map((r) => r.id)
  sortRows(rows, { key: 'name', direction: 'desc' }, byName)
  expect(rows.map((r) => r.id)).toEqual(before)
})

test('numbers inside a label compare numerically, not lexically', () => {
  const regions = [{ v: 'Region 10' }, { v: 'Region 9' }]
  const sorted = sortRows(regions, { key: 'v', direction: 'asc' }, (r) => r.v)
  expect(sorted.map((r) => r.v)).toEqual(['Region 9', 'Region 10'])
})

test('a column nothing knows how to compare leaves every row in place', () => {
  const sorted = sortRows(rows, { key: 'unknown', direction: 'asc' }, () => null)
  expect(sorted.map((r) => r.id)).toEqual([1, 2, 3, 4])
})

test('clicking a new column starts it ascending; clicking the same one flips it', () => {
  const start: SortState = { key: 'name', direction: 'desc' }
  expect(toggleSort(start, 'email')).toEqual({ key: 'email', direction: 'asc' })
  expect(toggleSort(start, 'name')).toEqual({ key: 'name', direction: 'asc' })
  expect(toggleSort({ key: 'name', direction: 'asc' }, 'name')).toEqual({
    key: 'name',
    direction: 'desc',
  })
})
