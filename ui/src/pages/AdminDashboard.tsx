// ui/src/pages/AdminDashboard.tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import type { Organisation, AdminUser } from '../types'

export default function AdminDashboard() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newOrgName, setNewOrgName] = useState('')
  const [showOrgForm, setShowOrgForm] = useState(false)

  const { data: orgs = [] } = useQuery<Organisation[]>({
    queryKey: ['admin', 'orgs'],
    queryFn: adminApi.listOrgs,
  })

  const { data: users = [] } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: adminApi.listUsers,
  })

  const createOrgMut = useMutation({
    mutationFn: () => adminApi.createOrg(newOrgSlug, newOrgName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      setNewOrgSlug('')
      setNewOrgName('')
      setShowOrgForm(false)
    },
  })

  const deleteOrgMut = useMutation({
    mutationFn: (orgId: number) => adminApi.deleteOrg(orgId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'orgs'] }),
  })

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-xl font-bold text-primary mb-6">Admin Dashboard</h1>

      {/* Organisations panel */}
      <div className="bg-surface-card rounded-lg border border-gray-200 mb-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-primary">Organisations</h2>
          <button
            onClick={() => setShowOrgForm((v) => !v)}
            className="text-xs text-brand hover:text-brand-light"
          >
            + New Org
          </button>
        </div>

        {showOrgForm && (
          <div className="flex gap-2 px-4 py-3 border-b border-gray-200">
            <input
              className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-primary"
              placeholder="slug (e.g. acme)"
              value={newOrgSlug}
              onChange={(e) => setNewOrgSlug(e.target.value)}
            />
            <input
              className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-primary"
              placeholder="Name"
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
            />
            <button
              onClick={() => createOrgMut.mutate()}
              disabled={!newOrgSlug || !newOrgName}
              className="text-xs bg-brand text-white px-3 py-1 rounded disabled:opacity-40"
            >
              Create
            </button>
          </div>
        )}

        {orgs.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No organisations yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-gray-200">
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id} className="border-b border-gray-200 hover:bg-surface-raised">
                  <td className="px-4 py-2 text-brand font-mono text-xs">{org.slug}</td>
                  <td className="px-4 py-2 text-primary">{org.name}</td>
                  <td className="px-4 py-2 text-muted text-xs">
                    {org.created_at.slice(0, 10)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => navigate(`/admin/orgs/${org.id}`)}
                      className="text-xs text-brand hover:text-brand-light mr-3"
                    >
                      Manage
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete org "${org.name}"?`)) deleteOrgMut.mutate(org.id)
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

      {/* Users panel */}
      <div className="bg-surface-card rounded-lg border border-gray-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-primary">Users</h2>
          <button
            onClick={() => navigate('/admin/users/new')}
            className="text-xs text-brand hover:text-brand-light"
          >
            + New User
          </button>
        </div>

        {users.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No users yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-gray-200">
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
                  <td className="px-4 py-2 font-mono text-xs text-primary">{u.username}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{u.email}</td>
                  <td className="px-4 py-2">
                    <RoleBadge role={u.role} />
                  </td>
                  <td className="px-4 py-2 text-muted text-xs">{u.created_at.slice(0, 10)}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => navigate(`/admin/users/${u.id}/edit`)}
                      className="text-xs text-brand hover:text-brand-light"
                    >
                      Edit
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

function RoleBadge({ role }: { role: string }) {
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
