// ui/src/pages/UserList.tsx
//
// The account-administration surface, and now the place a password reset is issued from.
//
// Why an administrator issues resets at all: FROM_EMAIL names a domain Resend has not
// verified, so /auth/reset-request mints a link that reaches nobody. This mirrors what the
// invite loop already does - an administrator issues the link and delivers it by hand.
//
// The link is therefore rendered into the page and left there until it is dismissed, rather
// than dropped into a toast that vanishes: it cannot be recovered once lost (the server
// stores only its digest, and asking again mints a different one, killing the first), and an
// administrator who blinked would have quietly invalidated the link they were about to send.
// The panel says in as many words that nothing was emailed, because the whole failure mode
// here is an administrator assuming the system did the sending.
//
// The list can now be read through a project, which is what lets it show who each account
// belongs to rather than only what it is called. `users` holds no name; a name lives on a
// `stakeholders` row, and a stakeholder is a person *on an engagement*, so the question only
// has an answer once a project is named.
//
// **No project selected is the default, and it shows no names at all** - not a name taken from
// whichever engagement happened to sort first. The Name and Entity columns are absent rather
// than full of dashes, because there is no question for them to be the answer to. It stays the
// default because it is the only view that lists every account, including logins holding no
// membership anywhere (the built-in administrator, anything created directly here) - accounts
// this screen can still edit, reset and delete, and which a project-scoped default would hide
// from the administrator looking for them.
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound, X } from 'lucide-react'
import { adminApi } from '../api/admin'
import PersonCell from '../components/PersonCell'
import SortHeader from '../components/SortHeader'
import { sortRows, toggleSort, type SortState } from '../utils/tableSort'
import { userSortKey } from '../utils/userSort'
import type { AdminUser, ProjectRegistryEntry, ResetLinkResponse } from '../types'

// The route this token is redeemed at, with the router's basename. Built from the current
// origin so a link issued on a laptop against a local server does not tell somebody to visit
// production, and vice versa.
export function resetLinkUrl(token: string): string {
  return `${window.location.origin}/dashboard/reset-password/${token}`
}

export default function UserList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [issued, setIssued] = useState<ResetLinkResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  // '' is "no project", and the sort key follows it: sorting by a column that is not on
  // screen would leave the list in an order with no visible explanation.
  const [project, setProject] = useState('')
  const [sort, setSort] = useState<SortState>({ key: 'username', direction: 'asc' })

  // The selector's options. Deliberately the same `GET /auth/projects` the admin panel uses -
  // a sysadmin gets every registered project, an org_admin only their organisation's - so the
  // options and the refusal on `GET /auth/users?project=` read the same project_registry
  // rather than being two answers that can drift apart.
  const { data: projects = [] } = useQuery<ProjectRegistryEntry[]>({
    queryKey: ['admin', 'projects'],
    queryFn: adminApi.listRegistry,
  })

  const { data: users = [], isLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users', project],
    queryFn: () => adminApi.listUsers(project || undefined),
  })

  const sorted = useMemo(() => sortRows(users, sort, userSortKey), [users, sort])

  const deleteUserMut = useMutation({
    mutationFn: (userId: number) => adminApi.deleteUser(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  })

  const resetLinkMut = useMutation({
    mutationFn: (userId: number) => adminApi.issueResetLink(userId),
    onMutate: () => {
      setResetError(null)
      setCopied(false)
    },
    onSuccess: (data) => setIssued(data),
    // Neutral on purpose, and matching the server's single sentence: the two refusals it can
    // raise - a sysadmin target, an account in another organisation - must not be told apart,
    // or an org_admin can read off which accounts hold the platform role and which belong to
    // somebody else's engagement.
    onError: () =>
      setResetError('That reset link could not be issued - that account is not yours to administer.'),
  })

  const onSort = (key: string) => setSort((current) => toggleSort(current, key))

  // Selecting a project brings the Name column into existence, so it is the natural thing to
  // sort by; clearing the selection takes it away again, and a sort key pointing at a column
  // that is no longer rendered orders the list by nothing the reader can see.
  const onProjectChange = (slug: string) => {
    setProject(slug)
    setSort({ key: slug ? 'name' : 'username', direction: 'asc' })
  }

  const roleBadge = (role: string) => {
    const colours: Record<string, string> = {
      sysadmin: 'bg-violet-100 text-violet-700',
      org_admin: 'bg-brand/10 text-teal-700',
      reviewer: 'bg-gray-100 text-gray-600',
    }
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full ${colours[role] ?? colours.reviewer}`}>
        {role}
      </span>
    )
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <h1 className="text-xl font-bold text-gray-900">Users</h1>
        <label className="text-xs text-secondary ml-auto" htmlFor="user-list-project">
          Show as on project
        </label>
        <select
          id="user-list-project"
          className="bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900"
          value={project}
          onChange={(e) => onProjectChange(e.target.value)}
        >
          <option value="">All accounts (no names)</option>
          {projects.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.display_name || p.slug}
            </option>
          ))}
        </select>
        <button
          onClick={() => navigate('/admin/users/new')}
          className="text-xs bg-brand text-white px-3 py-1.5 rounded"
        >
          + New User
        </button>
      </div>

      <p className="text-xs text-secondary mb-6">
        {project
          ? 'Names and entities are as recorded on this project. The list is the accounts holding'
            + ' access to it - a person can be recorded differently on another engagement.'
          : 'Every account you administer. Names live on a project, so none are shown here -'
            + ' choose a project to see who each account belongs to on it.'}
      </p>

      {issued && (
        <div className="bg-surface-card border border-brand rounded-lg p-4 mb-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-primary flex items-center gap-2">
                <KeyRound size={16} className="text-brand" />
                Reset link for {issued.email || issued.username}
              </h2>
              <p className="text-xs text-secondary mt-1">
                Nothing has been emailed - send this link to them yourself. It can be used
                once, expires in seven days, and asking again replaces it. They choose the new
                password; you never see it.
              </p>
              <p className="mt-3 font-mono text-xs text-gray-900 break-all bg-surface-raised rounded px-2 py-2">
                {resetLinkUrl(issued.reset_token)}
              </p>
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(resetLinkUrl(issued.reset_token)).catch(() => {})
                  setCopied(true)
                }}
                className="mt-2 text-xs bg-brand text-white px-3 py-1.5 rounded"
              >
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
            <button
              onClick={() => setIssued(null)}
              aria-label="Dismiss reset link"
              className="text-gray-600 hover:text-gray-900"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {resetError && (
        <p role="alert" className="text-red-400 text-sm mb-4">
          {resetError}
        </p>
      )}

      <div className="bg-surface-card rounded-lg border border-gray-200">
        {isLoading ? (
          <p className="px-4 py-6 text-sm text-gray-600">Loading…</p>
        ) : users.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-600">
            {project ? 'No accounts hold access to this project.' : 'No users yet.'}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-600 border-b border-gray-200">
                {project && (
                  <>
                    <SortHeader label="Name" sortKey="name" state={sort} onSort={onSort} />
                    <SortHeader label="Entity" sortKey="entity" state={sort} onSort={onSort} />
                  </>
                )}
                <SortHeader label="Username" sortKey="username" state={sort} onSort={onSort} />
                <SortHeader label="Email" sortKey="email" state={sort} onSort={onSort} />
                <SortHeader label="Role" sortKey="role" state={sort} onSort={onSort} />
                <SortHeader label="Created" sortKey="created" state={sort} onSort={onSort} />
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((u) => (
                <tr key={u.id} className="border-b border-gray-200 hover:bg-surface-raised">
                  {project && (
                    <>
                      <td className="px-4 py-2 text-xs"><PersonCell person={u.person} field="name" /></td>
                      <td className="px-4 py-2 text-xs"><PersonCell person={u.person} field="entity" /></td>
                    </>
                  )}
                  <td className="px-4 py-2 font-mono text-xs text-gray-900">{u.username}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{u.email || '-'}</td>
                  <td className="px-4 py-2">{roleBadge(u.role)}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{u.created_at.slice(0, 10)}</td>
                  <td className="px-4 py-2 text-right space-x-3">
                    <button
                      onClick={() => navigate(`/admin/users/${u.id}/edit`)}
                      className="text-xs text-brand hover:text-brand-light"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => resetLinkMut.mutate(u.id)}
                      disabled={resetLinkMut.isPending}
                      className="text-xs text-brand hover:text-brand-light disabled:opacity-50"
                    >
                      Reset link
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete user "${u.username}"?`)) deleteUserMut.mutate(u.id)
                      }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
