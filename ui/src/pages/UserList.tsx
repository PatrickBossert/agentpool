// ui/src/pages/UserList.tsx
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import type { AdminUser } from '../types'

export default function UserList() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: users = [], isLoading } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: adminApi.listUsers,
  })

  const deleteUserMut = useMutation({
    mutationFn: (userId: number) => adminApi.deleteUser(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
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
