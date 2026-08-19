// ui/src/__tests__/fixtures/platformTierSettings.ts
//
// What `GET /projects/{slug}/my-permissions` answers for `platform_tier_settings`, standing
// in for the server in frontend tests.
//
// **One copy, and it is held equal to the server's tuple.** These nine names used to be typed
// out in two separate test files, and review proved what that cost: adding a tenth member to
// `_PLATFORM_TIER_SETTINGS` on the server left the entire frontend suite green at 654,
// because nothing on this side had any idea the list had moved. That is the same
// rule-in-two-places this branch spent two tasks deleting, reintroduced in the fixtures.
//
// `tests/test_settings_platform_tier_wiring.py` reads this file, extracts the array, and
// fails if it is not exactly `api.routers.projects._PLATFORM_TIER_SETTINGS` in order. So the
// list is still written down twice - a Python tuple cannot be imported by vitest - but the
// two can no longer disagree without a test saying so, which is the property that matters.
//
// The **page** does not read this. It reads whatever the server serves it at runtime; that
// the two agree is what this fixture asserts, not something the page assumes.
export const PLATFORM_TIER_SETTINGS = [
  'llm_mode',
  'force_local_inference',
  'dev_mode',
  'anthropic_fast_model',
  'anthropic_deep_model',
  'local_fast_model',
  'local_fast_url',
  'local_deep_model',
  'local_deep_url',
]

// The members of the list above for which the Settings page renders no control at all.
// Asserted rather than assumed - `renders a control for every platform-tier field but these`
// pins it, so a control that silently disappeared cannot pass for a correctly absent one.
export const PLATFORM_TIER_FIELDS_WITH_NO_CONTROL = ['dev_mode']

export const PLATFORM_TIER_FIELDS_WITH_A_CONTROL = PLATFORM_TIER_SETTINGS.filter(
  (f) => !PLATFORM_TIER_FIELDS_WITH_NO_CONTROL.includes(f),
)
