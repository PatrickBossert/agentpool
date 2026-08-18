// ui/src/pages/Stakeholders.tsx
//
// The roster, and now the two things about it nobody could see: whether each person can
// actually get into the engagement, and how to hand them a link if they cannot yet.
//
// Access is a server-computed `access_state` rather than something inferred here. Two of
// its states turn on system.db - a login linked to this project, an unredeemed invite -
// which the browser has no sight of at all, and the third (a role with no deliverable
// address) is a condition the write doors already enforce, so a second copy in this file
// would be free to disagree with the 422 they raise.
//
// The invite link is presented the way sp42 presented the administrator's reset link, and
// for the same reasons: no outbound-email path is wired for invites, so it is delivered by
// hand; asking again mints a new token and kills the old link, so it is rendered into the
// page until dismissed rather than into a toast that vanishes; and the panel says in as
// many words that nothing was emailed, because the failure mode is an administrator
// assuming the system did the sending.
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  MessageSquare, UserCheck, CheckSquare, Mail, MessageCircle, Smartphone, Link2, X,
} from 'lucide-react'
import { projectsApi, stakeholdersApi } from '../api/endpoints'
import { describeError } from '../utils/describeError'
import type { AccessState, Stakeholder, StakeholderImportResult } from '../types'

const LEVEL_STYLE: Record<string, string> = {
  L0: 'bg-purple-100 text-purple-700',
  L1: 'bg-brand/10 text-teal-700',
  L2: 'bg-gray-100 text-gray-600',
  L3: 'bg-gray-50 text-gray-500',
}

const COMMS_ICON: Record<string, React.ReactNode> = {
  email: <Mail size={11} />,
  slack: <MessageCircle size={11} />,
  sms:   <Smartphone size={11} />,
}

// Label and styling per access state. `unreachable` is the one that reads as a fault
// rather than a status: it is a role nobody can exercise, which is exactly the row that sat
// on a live project for weeks looking like every other.
const ACCESS_BADGE: Record<AccessState, { label: string; title: string; style: string }> = {
  has_login: {
    label: 'Has login',
    title: 'Has a login linked to this project',
    style: 'bg-emerald-100 text-emerald-700',
  },
  invited: {
    label: 'Invited',
    title: 'Invited, not yet accepted - an invite link can be issued',
    style: 'bg-brand/10 text-teal-700',
  },
  unreachable: {
    label: 'Unreachable',
    title: 'Holds a role beyond participant with no deliverable address, so cannot be invited',
    style: 'bg-red-100 text-red-700',
  },
  not_invited: {
    // Advice a single reader can actually act on. Re-granting a reviewer or approver role
    // is something an org admin can do alone, and the invite is issued by the write; a
    // project administrator or governor role can only be re-granted by a project
    // administrator, while retrieving the resulting link needs an org admin - so that one
    // takes two people and the tooltip says so rather than implying one.
    label: 'Not invited',
    title: 'Holds a role but has neither a login nor an invite. Clearing the role and '
      + 'setting it again issues one - for a project administrator or governor role, that '
      + 're-grant needs a project administrator as well as an org admin.',
    style: 'bg-amber-100 text-amber-700',
  },
  no_login_needed: {
    label: 'No login needed',
    title: 'Participant only - interviews reach them by campaign link',
    style: 'bg-gray-100 text-gray-500',
  },
}

// The route an invite token is redeemed at, with the router's basename. Built from the
// current origin - like resetLinkUrl in UserList.tsx - so a link issued against a local
// server does not tell somebody to visit production, and vice versa.
export function inviteLinkUrl(token: string): string {
  return `${window.location.origin}/dashboard/accept-invite/${token}`
}

// Nothing at all when the server sent no state, rather than a dash or an "unknown" badge.
// The field is absent for a caller who may not be told the account-derived states (see
// api/services/stakeholder_access.py), and a placeholder would still confirm that the row
// has one of them - the same disclosure in a thinner costume. An unrecognised value is
// treated the same way: a state this build does not know is not a state it should label.
function AccessBadge({ state }: { state?: AccessState }) {
  if (!state) return null
  const badge = ACCESS_BADGE[state]
  if (!badge) return null
  return (
    <span
      title={badge.title}
      className={`rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap ${badge.style}`}
    >
      {badge.label}
    </span>
  )
}

function LevelBadge({ level }: { level: string }) {
  if (!level) return null
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${LEVEL_STYLE[level] ?? 'bg-gray-100 text-gray-500'}`}>
      {level}
    </span>
  )
}

function RoleDots({ s }: { s: Stakeholder }) {
  return (
    <span className="flex items-center gap-1">
      {s.is_participant && (
        <span title="Participant" className="text-brand">
          <MessageSquare size={11} />
        </span>
      )}
      {s.is_reviewer && (
        <span title="Reviewer" className="text-amber-500">
          <UserCheck size={11} />
        </span>
      )}
      {s.is_approver && (
        <span title="Approver" className="text-emerald-600">
          <CheckSquare size={11} />
        </span>
      )}
    </span>
  )
}

export default function Stakeholders() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [issued, setIssued] = useState<{ name: string; token: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)

  const { data: stakeholders = [], isLoading } = useQuery<Stakeholder[]>({
    queryKey: ['stakeholders', slug],
    queryFn: () => stakeholdersApi.list(slug!),
    enabled: !!slug,
  })

  // Whether to offer the invite-link action at all. The door is the platform tier - it was
  // returned there after sp44 showed a project_admin could mint a login for an address they
  // chose and collect a membership on somebody else's engagement with it - so rendering the
  // action unconditionally would put a button on this page that 403s for the client's own
  // administrator. Asked rather than inferred from the login role, because access to the
  // project is per slug and the answer is not in the JWT.
  const { data: permissions } = useQuery({
    queryKey: ['my-permissions', slug],
    queryFn: () => projectsApi.getMyPermissions(slug!),
    enabled: !!slug,
    retry: false,
  })
  const canIssueInviteLinks = permissions?.can_issue_invite_links ?? false

  const inviteLinkMut = useMutation({
    mutationFn: (s: Stakeholder) =>
      stakeholdersApi.resendInvite(slug!, s.id).then((r) => ({ name: s.name, token: r.invite_token })),
    onMutate: () => {
      setInviteError(null)
      setCopied(false)
    },
    onSuccess: (data) => {
      setIssued(data)
      // The token that was live a moment ago is dead now, so anything reading invite state
      // off the list is stale. The states themselves do not change - still invited - but
      // the list is what the action is offered from, so it is refetched rather than trusted.
      qc.invalidateQueries({ queryKey: ['stakeholders', slug] })
    },
    onError: (err) =>
      setInviteError(describeError(err, 'That invite link could not be issued.')),
  })

  const filtered = stakeholders.filter((s) => {
    const q = search.toLowerCase()
    return (
      s.name.toLowerCase().includes(q) ||
      s.organisation.toLowerCase().includes(q) ||
      s.email.toLowerCase().includes(q) ||
      s.entity.toLowerCase().includes(q)
    )
  })

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !slug) return
    try {
      const result: StakeholderImportResult = await stakeholdersApi.importCsv(slug, file)
      const errMsg = result.errors.length > 0 ? ` (${result.errors.length} rows skipped)` : ''
      setImportMsg(`Imported: ${result.created} created, ${result.updated} updated${errMsg}`)
      qc.invalidateQueries({ queryKey: ['stakeholders', slug] })
    } catch {
      setImportMsg('Import failed. Check the file format.')
    }
    if (fileRef.current) fileRef.current.value = ''
    setTimeout(() => setImportMsg(null), 5000)
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Stakeholders</h2>
        <div className="flex items-center gap-3">
          {importMsg && (
            <span className="text-xs text-emerald-600">{importMsg}</span>
          )}
          <label
            htmlFor="csv-import"
            className="cursor-pointer text-xs text-gray-600 hover:text-gray-900 border border-gray-200 hover:border-gray-400 rounded px-3 py-1.5 transition-colors"
          >
            Import CSV
          </label>
          <input
            id="csv-import"
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            className="sr-only"
          />
          <button
            onClick={() => navigate(`/${slug}/stakeholders/new`)}
            className="text-xs bg-brand hover:bg-brand-dark text-white rounded px-3 py-1.5 transition-colors"
          >
            + Add Stakeholder
          </button>
        </div>
      </div>

      {issued && (
        <div className="bg-surface-card border border-brand rounded-lg p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-primary flex items-center gap-2">
                <Link2 size={16} className="text-brand" />
                Invite link for {issued.name}
              </h3>
              <p className="text-xs text-secondary mt-1">
                Nothing has been emailed - send this link to them yourself. It can be used
                once, expires in seven days, and asking again replaces it. They choose their
                own password; you never see it.
              </p>
              <p className="mt-3 font-mono text-xs text-gray-900 break-all bg-surface-raised rounded px-2 py-2">
                {inviteLinkUrl(issued.token)}
              </p>
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(inviteLinkUrl(issued.token)).catch(() => {})
                  setCopied(true)
                }}
                className="mt-2 text-xs bg-brand hover:bg-brand-dark text-white px-3 py-1.5 rounded transition-colors"
              >
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
            <button
              onClick={() => setIssued(null)}
              aria-label="Dismiss invite link"
              className="text-gray-600 hover:text-gray-900"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {inviteError && (
        <p role="alert" className="text-sm text-red-400">
          {inviteError}
        </p>
      )}

      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, entity, organisation, or email…"
        className="w-full max-w-sm bg-white border border-gray-200 rounded px-3 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 outline-none focus:border-brand"
      />

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

      {!isLoading && stakeholders.length === 0 && (
        <p className="text-sm text-gray-400">
          No stakeholders yet. Add one or import a CSV.
        </p>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-4 py-2 text-left text-gray-500 font-medium">Name / Title</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Level</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Entity</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Roles</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Access</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Comms</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Disposition</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium">Email</th>
                <th className="px-3 py-2 text-left text-gray-500 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className="border-t border-gray-200 hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <p className="text-gray-900 font-medium flex items-center gap-1.5">
                      {s.name}
                      {/* This is the screen somebody audits before the real engagement, and
                          on the test project sixty of the sixty-two rows are seeded. The
                          marker is a column no ordinary edit can set or clear, so the badge
                          says what the removal script will actually take. */}
                      {s.is_synthetic && (
                        <span
                          className="text-[9px] uppercase tracking-wider text-amber-600 border border-amber-200 bg-amber-50 rounded px-1"
                          title="Seeded test data - removed by the synthetic stakeholder script"
                        >
                          seeded
                        </span>
                      )}
                    </p>
                    {s.job_title && <p className="text-gray-400 mt-0.5">{s.job_title}</p>}
                  </td>
                  <td className="px-3 py-2.5">
                    <LevelBadge level={s.level} />
                  </td>
                  <td className="px-3 py-2.5 text-gray-600 max-w-[140px] truncate">{s.entity || '-'}</td>
                  <td className="px-3 py-2.5">
                    <RoleDots s={s} />
                  </td>
                  <td className="px-3 py-2.5">
                    <AccessBadge state={s.access_state} />
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="flex items-center gap-1 text-gray-500">
                      {COMMS_ICON[s.comms_channel]}
                      <span className="capitalize">{s.comms_channel}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      s.disposition === 'champion' ? 'bg-emerald-100 text-emerald-700' :
                      s.disposition === 'supporter' ? 'bg-teal-100 text-teal-700' :
                      s.disposition === 'neutral' ? 'bg-gray-100 text-gray-600' :
                      s.disposition === 'skeptic' ? 'bg-orange-100 text-orange-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {s.disposition}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-gray-600">{s.email || '-'}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap space-x-3">
                    <button
                      onClick={() => navigate(`/${slug}/stakeholders/${s.id}/edit`)}
                      className="text-brand hover:text-brand-dark transition-colors"
                    >
                      Edit
                    </button>
                    {/* Offered for the one state the door serves. Every other state answers
                        403, 404 or 409, and an action that refuses is worse than none. */}
                    {canIssueInviteLinks && s.access_state === 'invited' && (
                      <button
                        onClick={() => inviteLinkMut.mutate(s)}
                        disabled={inviteLinkMut.isPending}
                        className="text-brand hover:text-brand-dark disabled:opacity-50 transition-colors"
                      >
                        Invite link
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-gray-400 border-t border-gray-100 pt-3">
        <span className="flex items-center gap-1"><MessageSquare size={10} className="text-brand" /> Participant</span>
        <span className="flex items-center gap-1"><UserCheck size={10} className="text-amber-500" /> Reviewer</span>
        <span className="flex items-center gap-1"><CheckSquare size={10} className="text-emerald-600" /> Approver</span>
      </div>
    </div>
  )
}
