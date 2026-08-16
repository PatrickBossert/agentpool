// ui/src/utils/describeError.ts
//
// The server's own sentence, or a fallback. Three identical copies of this had grown - in
// StakeholderForm, ScriptReviewPanel and MayaOutputExtra - and UserForm was about to be the
// fourth, so it moved here instead. CLAUDE.md records what copied conditions do on this
// project: the register_scripts_sync / scripts_awaiting_regeneration pair diverged.
//
// It matters more than an ordinary error message because several of this API's refusals say
// something a fixed string cannot. "email is required to invite a stakeholder holding a role
// beyond participant" is the only thing in the product that tells an administrator they have
// just created a role nobody can be invited to; "Access denied to this project" tells an
// org_admin the slug they typed is not theirs. Swallowed into "Save failed. Please try
// again.", both read as transient faults, and retrying reproduces them exactly.
import axios from 'axios'

export function describeError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
  }
  return fallback
}
