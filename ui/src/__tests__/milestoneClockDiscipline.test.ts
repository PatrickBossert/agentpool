// ui/src/__tests__/milestoneClockDiscipline.test.ts
//
// Twice now a test has read the wall clock through `milestoneVariance` and expired.
//
// 19 Aug 2026: three tests in milestoneVariance.test.ts were written against the day they
// were written on. Fixed by pinning `today` at every call *in that file*.
// 3 Sep 2026: three more failed, in PamReportExport.test.ts and PamSetupMilestones.test.tsx -
// files that never call `milestoneVariance` directly. They exercise components that do, and
// those components legitimately read the clock. The first fix was applied to the file that
// failed and not to the class of defect.
//
// This is the guard the second fix should have carried. It walks the test sources rather than
// asserting behaviour, because the failure it prevents is one nobody sees until a date passes.
//
// What it CANNOT see: a test that pins the clock to a date which is itself wrong for its
// fixtures, and a component reached through a helper this walk does not know reaches
// `milestoneVariance`. It checks that the question was asked, not that it was answered well.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

// process.cwd() is `ui/` under vitest; import.meta.url resolves against the Vite base
// (`/dashboard`) and gives a path that does not exist on disk.
const DIR = join(process.cwd(), 'src', '__tests__')

// Files whose subjects reach milestoneVariance, directly or through a component.
const REACHES_MILESTONE_VARIANCE = [
  'milestoneVariance.test.ts',
  'PamReportExport.test.ts',
  'PamSetupMilestones.test.tsx',
]

describe('milestone tests do not read the wall clock', () => {
  it('every file whose subject reaches milestoneVariance pins the clock', () => {
    const unpinned: string[] = []
    for (const name of REACHES_MILESTONE_VARIANCE) {
      const src = readFileSync(join(DIR, name), 'utf8')
      const pinsPerCall = /milestoneVariance\([^)]*'\d{4}-\d{2}-\d{2}'/.test(src)
      const pinsTheClock = src.includes('setSystemTime')
      if (!pinsPerCall && !pinsTheClock) unpinned.push(name)
    }
    expect(unpinned).toEqual([])
  })

  it('names every test file that reaches milestoneVariance, so a new one is not missed', () => {
    // The list above is hand-maintained, which is the weakness. This fails when a test file
    // mentions milestoneVariance or a component known to use it and is absent from the list -
    // so the list cannot silently fall behind the suite.
    const USERS_OF_VARIANCE = ['milestoneVariance', 'PamReportView', 'PamSetupTab']
    const candidates = readdirSync(DIR)
      .filter(f => f.endsWith('.test.ts') || f.endsWith('.test.tsx'))
      .filter(f => {
        const src = readFileSync(join(DIR, f), 'utf8')
        return USERS_OF_VARIANCE.some(u => src.includes(u))
      })
      .filter(f => f !== 'milestoneClockDiscipline.test.ts')
    expect(candidates.sort()).toEqual([...REACHES_MILESTONE_VARIANCE].sort())
  })
})
