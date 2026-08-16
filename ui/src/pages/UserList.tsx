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
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound, X } from 'lucide-react'
import { adminApi } from '../api/admin'
import type { AdminUser, ResetLinkResponse } from '../types'

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

  const { data: users = [], isLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: adminApi.listUsers,
  })

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
    onError: () =>
      setResetError(
        'That reset link could not be issued - the account may sit outside your organisation.',
      ),
  })

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
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900">Users</h1>
        <button
          onClick={() => navigate('/admin/users/new')}
          className="text-xs bg-brand text-white px-3 py-1.5 rounded"
        >
          + New User
        </button>
      </div>

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
          <p className="px-4 py-6 text-sm text-gray-600">No users yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-600 border-b border-gray-200">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-gray-200 hover:bg-surface-raised">
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
