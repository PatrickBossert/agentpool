// ui/src/pages/OrgPanel.tsx
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import { useAuth } from '../context/AuthContext'
import type { OrgMember, ProjectRegistryEntry } from '../types'

function RoleBadge({ role }: { role: string }) {
  const colours: Record<string, string> = {
    sysadmin: 'bg-red-100 text-red-700',
    org_admin: 'bg-amber-100 text-amber-700',
    reviewer: 'bg-gray-100 text-gray-600',
    member: 'bg-gray-100 text-gray-600',
  }
  return (
    <span
      className={`inline-block text-xs font-mono px-1.5 py-0.5 rounded ${colours[role] ?? 'bg-gray-100 text-gray-600'}`}
    >
      {role}
    </span>
  )
}

export default function OrgPanel() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const orgId = user?.org_id

  const { data: orgs = [] } = useQuery({
    queryKey: ['admin', 'orgs'],
    queryFn: adminApi.listOrgs,
    enabled: !!orgId,
  })
  const org = orgs.find((o) => o.id === orgId)

  const { data: members = [], isLoading: membersLoading } = useQuery<OrgMember[]>({
    queryKey: ['admin', 'orgs', orgId, 'members'],
    queryFn: () => adminApi.listOrgMembers(orgId!),
    enabled: !!orgId,
  })

  const { data: projects = [], isLoading: projectsLoading } = useQuery<ProjectRegistryEntry[]>({
    queryKey: ['admin', 'projects'],
    queryFn: adminApi.listRegistry,
    select: (all) => all.filter((p) => p.org_id === orgId),
    enabled: !!orgId,
  })

  if (!orgId) {
    return (
      <div className="p-6">
        <p className="text-sm text-gray-600">You are not assigned to an organisation.</p>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-gray-900">Team</h1>
        {org && (
          <span className="text-xs text-gray-600 font-mono">{org.name}</span>
        )}
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => navigate('/admin/users/new')}
            className="text-xs bg-brand text-white px-3 py-1.5 rounded hover:opacity-90"
          >
            Invite User
          </button>
          <button
            onClick={() => navigate('/admin/users')}
            className="text-xs border border-gray-200 text-secondary px-3 py-1.5 rounded hover:border-gray-400"
          >
            Manage Users
          </button>
        </div>
      </div>

      {/* Members */}
      <div className="bg-surface-card rounded-lg border border-gray-200 mb-6">
        <div className="px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Members</h2>
        </div>
        {membersLoading ? (
          <p className="px-4 py-3 text-sm text-gray-600">Loading…</p>
        ) : members.length === 0 ? (
          <p className="px-4 py-3 text-sm text-gray-600">No members yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-600 border-b border-gray-200">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-gray-200 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-gray-900">{m.username}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{m.email}</td>
                  <td className="px-4 py-2">
                    <RoleBadge role={m.org_role} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => navigate(`/admin/users`)}
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

      {/* Projects */}
      <div className="bg-surface-card rounded-lg border border-gray-200">
        <div className="px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Projects</h2>
        </div>
        {projectsLoading ? (
          <p className="px-4 py-3 text-sm text-gray-600">Loading…</p>
        ) : projects.length === 0 ? (
          <p className="px-4 py-3 text-sm text-gray-600">No projects linked to this organisation.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-600 border-b border-gray-200">
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Display Name</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-b border-gray-200 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-brand">{p.slug}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{p.display_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
