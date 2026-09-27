// ui/src/__tests__/TestInterviewCardOverflow.test.ts
//
// The rehearsal dialog's transcript ran outside its card, and this is the guard on the fix.
//
// **What this test is not.** jsdom performs no layout - every box is zero-sized and
// `getBoundingClientRect` answers zeroes - so nothing in the vitest suite can see an overflow.
// This is a source walk, and it checks that the question was asked rather than that the layout is
// right. The real evidence is a measurement in a real browser against this exact class chain,
// recorded here so the next reader does not have to take the fix on trust:
//
//   viewport 1490, card held at its 768px max-w-3xl
//     before:  the flexible column's right edge ran 40px past the card's
//     after:   0px
//   viewport 420, card 388px
//     before:  the column ran 420px past the card - a full viewport, with the question and
//              every control pushed out of the visible area
//     after:   0px, and the page body still did not scroll horizontally in either case
//
// **The mechanism, because the fix looks like a no-op if you do not know it.** A flex item's
// automatic minimum size is its *content-based* minimum, and `min-width` beats `max-width`. So
// `flex-1` alone will not let a column shrink below the widest unbreakable thing inside it, and
// nothing on an ancestor can rein that in. The transcript's `Q:` line is `truncate`, which is
// `white-space: nowrap`, which makes its min-content width the whole of the line. `min-w-0` is
// what releases that, and it is invisible to every other kind of test.
//
// **Deliberately not a blanket rule.** "Every `flex-1` also carries `min-w-0`" was measured and
// rejected: five of the ten `flex-1` elements in this file are children of the card's *column*
// flex container, where the constrained axis is height and `min-w-0` means nothing. A guard that
// demanded it there would be satisfied by noise and would read as protecting an axis it does not.
//
// **What it cannot see:** a new flexible child of the interviewing row; the complete phase, whose
// bubbles were fixed in the same change and whose symptom is a sideways scrollbar rather than a
// spill; and any of this being right in the source while some ancestor introduced later puts it
// back. It is one door, held shut.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// process.cwd() is `ui/` under vitest; import.meta.url resolves against the Vite base
// (`/dashboard`) and gives a path that does not exist on disk.
const SOURCE = join(process.cwd(), 'src', 'components', 'tabs', 'TestInterviewDialog.tsx')

/**
 * The source with its comments removed.
 *
 * **Not load-bearing, and that was measured rather than assumed.** The first version of this
 * comment claimed it was - that the comments explaining the fix quote `min-w-0` and
 * `break-words` often enough to satisfy a walk over the raw file, so stripping them is what makes
 * the guard real. Driven both ways, that is false: every assertion below reads a class string out
 * of an actual `className="..."` attribute, and prose mentioning a class in backticks cannot form
 * one. With the stripping deleted *and* the fix deleted, all four assertions still failed.
 *
 * Recorded at length because the false version is the more instructive artefact: it is this
 * project's own "quoting a rule is not applying it", committed inside the docstring of a guard, by
 * an author who had just read the rule. A comment asserting that a mechanism protects something
 * reads as evidence about behaviour and is only ever evidence about intent.
 *
 * It stays because it is cheap and it closes one thing the regexes genuinely cannot tell apart: a
 * comment containing a literal `className="flex-1 min-w-0"` as an example would satisfy the walk.
 * That is insurance against a future comment, not a description of what is happening today.
 */
function sourceWithoutComments(): string {
  return readFileSync(SOURCE, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '')
}

/**
 * The `className` of the flexible column in the interviewing row.
 *
 * Found by structure rather than by matching a literal class string, so reordering the classes or
 * restyling the panel does not quietly stop the guard finding its subject. The row holds exactly
 * two children: the interviewer's face at a fixed `w-52`, and the column that absorbs the rest.
 * The face is the landmark; the column is the next `className` after it that flexes.
 */
function flexibleColumnClasses(src: string): string {
  const face = src.indexOf('w-52')
  expect(face, 'the interviewer face column (w-52) is the landmark this guard navigates by').toBeGreaterThan(-1)

  const after = src.slice(face)
  const match = after.match(/className="([^"]*\bflex-1\b[^"]*)"/)
  expect(match, 'the interviewing row should still have a flexible column after the face').not.toBeNull()
  return match![1]
}

describe('the rehearsal card does not let its transcript out', () => {
  it('the flexible column in the interviewing row may shrink below its content', () => {
    const classes = flexibleColumnClasses(sourceWithoutComments())
    // `min-w-0` and nothing else releases the content-based minimum. Asserted on the column that
    // actually holds the transcript, so the assertion is about the box that overflowed.
    expect(classes).toMatch(/\bmin-w-0\b/)
  })

  it('a transcript answer with no spaces in it wraps rather than widening the card', () => {
    const src = sourceWithoutComments()
    // The `A:` line of the in-interview transcript. A URL or a run-on has no break opportunity,
    // so releasing the column's minimum is not enough on its own - the text has to be allowed to
    // break mid-word or it becomes the new minimum.
    const answerLine = src.match(/className="([^"]*\bline-clamp-2\b[^"]*)"/)
    expect(answerLine, 'the in-interview transcript should still clamp its answer lines').not.toBeNull()
    expect(answerLine![1]).toMatch(/\bbreak-words\b/)
  })

  it('the question on screen wraps too, being the other thing in that column with no width', () => {
    const src = sourceWithoutComments()
    // Anchored on `{currentQuestion}` rather than on a class prefix. `text-white text-lg` also
    // matches the ready screen's node-label heading, which appears earlier in the file - so the
    // first draft of this test asserted against a different element in a different phase and
    // failed while the code was right. Exactly the "one layer away from the property" shape this
    // project keeps recording, caught here only because it failed rather than passed.
    const questionLine = src.match(/className="([^"]*)"[^<>]*>\{currentQuestion\}/)
    expect(questionLine, 'the current question should still be rendered in that column').not.toBeNull()
    expect(questionLine![1]).toMatch(/\bbreak-words\b/)
  })

  it('the live caption wraps, being unbroken machine output by nature', () => {
    const src = sourceWithoutComments()
    // The caption is the recogniser's own text, so it arrives with whatever spacing the
    // recogniser gave it and none is guaranteed. It sits in the same column as everything above.
    const caption = src.match(/data-testid="live-caption"[\s\S]{0,300}?className="([^"]*)"/)
      ?? src.match(/className="([^"]*)"[\s\S]{0,300}?data-testid="live-caption"/)
    expect(caption, 'the live caption should still be rendered').not.toBeNull()
    expect(caption![1]).toMatch(/\bbreak-words\b/)
  })
})
