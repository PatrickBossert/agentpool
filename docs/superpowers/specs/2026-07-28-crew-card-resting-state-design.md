# Crew Card Resting State - Design

**Date:** 2026-07-28
**Status:** Approved for implementation

## Problem

A crew that has finished announces it in four places at once: a green "Done" chip, a
green card border, every agent's face in its completed treatment, and a repeat button.
The card stays visibly "finished" indefinitely, so a board where several crews have run
is a wall of green that never returns to rest - and the breathing idle activity, which
signals that the platform's clock is alive, is suppressed on exactly the cards that have
been used most.

## Approach

A finished crew returns to its resting state. Completion is carried by one thing: the
button, which changes from a green start arrow to a green repeat arrow. That says both
"this has run" and "you can run it again" in the one control you would use to act on it.

The `status` value is not touched - only its rendering. `handlePlay`
(`ui/src/components/CrewCarousel.tsx:202`) branches on `status === 'completed'` to call
`onRerun` rather than `onRun`, and re-colouring a button must not quietly turn a re-run
into a fresh run.

Running is unchanged: the spinner stays. Waiting, queued, and failed are unchanged - a
failed crew keeps its red chip and border, because "it broke" is not a resting state and
must not be hidden behind a wellbeing activity.

---

## Crew cards

`ui/src/components/CrewCarousel.tsx`, the `CrewCard` component.

| Element | Now | After |
|---|---|---|
| Status chip (`statusLabel`) | Green "Done" with `CheckCircle2` | The `completed` branch is removed, so it falls through to the breathing `FadingText` |
| Card border (`borderClass`) | `border-green-200` | The `completed` branch is removed, so it falls through to `border-gray-200 hover:border-gray-300` |
| Agent faces (`agentStatuses`) | `agents.map(() => 'completed')` | `agents.map(() => 'idle')` |
| Button | `bg-white text-gray-400 border border-gray-200 hover:border-teal-300 hover:text-teal-600`, `RotateCcw` | `bg-teal-600 text-white hover:bg-teal-700` - identical to the start button - keeping `RotateCcw` |

**The agent faces are re-mapped, not deleted.** Removing the `completed` branch from
`agentStatuses` would drop through to `isPipelineActive ? 'queued' : 'idle'`, which would
paint a finished crew's agents as *queued* whenever a pipeline happened to be running.
Mapping explicitly to `'idle'` avoids that.

The button's `title` stays `'Re-run'`. After this change the only visual difference
between a crew that has never run and one that has finished is the icon inside an
otherwise identical green button - which is the intent: one calm resting state, and a
glance across the icons tells you what has been run.

## Pamela's card

`ui/src/components/CrewCarousel.tsx`, the `PamCard` component - the same rule, for
consistency.

- `statusChip`: the `orchestrationStatus === 'completed'` branch is removed, so a
  finished pipeline falls through to the breathing `FadingText`.
- The button renders `RotateCcw` instead of `Play` when
  `orchestrationStatus === 'completed'`, and its `title` becomes `'Re-run all crews'`.

Her border needs no change - it is `border-teal-200` at rest and never went green.

Her button is **already** green and always enabled, so this changes only the icon. It
does not make a full-pipeline re-run more inviting than it is today.

---

## The existing test this breaks

`ui/src/__tests__/Dashboard.test.tsx` asserts `findByText('Done')` against a mocked
completed crew run. This design deletes that string.

The assertion moves to the indicator that replaces it - the re-run button, found by its
`title`. That is the better assertion regardless: it pins the meaning rather than the
wording.

## Testing

`CrewCarousel` has no test file of its own. Rather than build one out for this change,
extend `Dashboard.test.tsx`, which already renders the full board with a completed crew,
to assert what actually changed:

- no "Done" text anywhere on the board
- a control titled `Re-run` is present
- the completed crew's card shows its breathing idle activity

For the third, `IDLE_STATUSES` is module-private and cannot be enumerated by a test, but
`getRotatedIdleStatus(key, runIndex, rotation)` is exported and deterministic. The test
renders `Dashboard` directly rather than inside `AppLayout`, so there is no
`SchedulerHeartbeatProvider` and `rotation` is the context default of `0`; with the
mocked crew run's `id`, the expected string is
`getRotatedIdleStatus('discovery', <mocked run id>, 0)`. Assert that exact string is on
screen.

This exercises the change through the real component tree rather than a mocked shell.

## Out of scope

The failed, waiting, and queued states. Any change to when a crew is *considered*
completed - this is presentation only.
