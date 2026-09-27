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

// What a file has to name, in code or in a comment, to be about this at all.
const USERS_OF_VARIANCE = ['milestoneVariance', 'PamReportView', 'ProjectScheduleSetup']

// Files whose subjects reach milestoneVariance, directly or through a component.
const REACHES_MILESTONE_VARIANCE = [
  'milestoneVariance.test.ts',
  'PamReportExport.test.ts',
  'PamSetupMilestones.test.tsx',
  // Drives the whole panel, and the PMO crew's Setup tab mounts the schedule.
  'TabClassification.test.tsx',
]

/**
 * The source with its comments taken out, so a file that *cites* this lesson is not listed as
 * one that has to obey it.
 *
 * `VoiceInterviewElapsed.test.tsx` is why: it quotes `milestoneVariance.test.ts` as the reason
 * its own clock is passed rather than read - which is exactly the discipline this file
 * enforces - and the sweep listed it as a milestone test for saying so. That is `CLAUDE.md`'s
 * *enumerate by behaviour, not by name* arriving in the shape it warns is hardest to see: not
 * a file hidden from the sweep, but a file the sweep saw and misread.
 *
 * **Deliberately an approximation, and it errs towards listing.** A line comment is only
 * stripped where `//` opens the line, so a `'wss://…'` inside a string survives; a block
 * comment is stripped wherever it is. Neither a real import nor a real call is written inside a
 * comment, and a miss here would be a file that should be on the list and is not - so the
 * cheaper mistake is the one that keeps a file on it.
 */
function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '')
}

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
    // The list above is hand-maintained, which is the weakness, and this is the half that stops
    // it falling behind the suite: a file whose **code** names milestoneVariance or a component
    // known to use it must be on the list.
    //
    // A subset rather than an equality, and the reason is `TabClassification.test.tsx`. It is a
    // genuine member - the PMO crew's Setup tab mounts `ProjectScheduleSetup` - and it never
    // names any of them outside a comment, because it reaches them by rendering a panel. So
    // equality here would force either a wrong list or a comment written to satisfy a sweep.
    const named = readdirSync(DIR)
      .filter(f => f.endsWith('.test.ts') || f.endsWith('.test.tsx'))
      .filter(f => {
        const src = withoutComments(readFileSync(join(DIR, f), 'utf8'))
        return USERS_OF_VARIANCE.some(u => src.includes(u))
      })
      .filter(f => f !== 'milestoneClockDiscipline.test.ts')
    const undeclared = named.filter(f => !REACHES_MILESTONE_VARIANCE.includes(f))
    expect(undeclared).toEqual([])
  })

  it('names nothing that has stopped having anything to do with milestones', () => {
    // The other direction, and it is what a subset alone gives up. A declared file must still
    // exist and must still mention one of these somewhere - **comments included**, because an
    // indirect reacher's only evidence is the comment saying why it is here. Weaker than the
    // test above by design: it catches an entry that has gone stale, not one that is wrong.
    for (const name of REACHES_MILESTONE_VARIANCE) {
      const src = readFileSync(join(DIR, name), 'utf8')
      expect(USERS_OF_VARIANCE.some(u => src.includes(u)), name).toBe(true)
    }
  })
})
