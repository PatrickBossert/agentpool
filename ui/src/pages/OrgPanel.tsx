// ui/src/pages/OrgPanel.tsx
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import { useAuth } from '../context/AuthContext'
import type { OrgMember, ProjectRegistryEntry } from '../types'

function RoleBadge({ role }: { role: string }) {
  const colours: Record<string, string> = {
    sysadmin: 'bg-red-900/40 text-red-300',
    org_admin: 'bg-amber-900/40 text-amber-300',
    reviewer: 'bg-slate-700 text-slate-300',
    member: 'bg-slate-700 text-slate-300',
  }
  return (
    <span
      className={`inline-block text-xs font-mono px-1.5 py-0.5 rounded ${colours[role] ?? 'bg-slate-700 text-slate-300'}`}
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
        <p className="text-sm text-muted">You are not assigned to an organisation.</p>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-primary">Team</h1>
        {org && (
          <span className="text-xs text-muted font-mono">{org.name}</span>
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
            className="text-xs border border-slate-700 text-secondary px-3 py-1.5 rounded hover:border-slate-500"
          >
            Manage Users
          </button>
        </div>
      </div>

      {/* Members */}
      <div className="bg-surface-card rounded-lg border border-slate-800 mb-6">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Members</h2>
        </div>
        {membersLoading ? (
          <p className="px-4 py-3 text-sm text-muted">Loading…</p>
        ) : members.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No members yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-slate-800 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-primary">{m.username}</td>
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
      <div className="bg-surface-card rounded-lg border border-slate-800">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Projects</h2>
        </div>
        {projectsLoading ? (
          <p className="px-4 py-3 text-sm text-muted">Loading…</p>
        ) : projects.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No projects linked to this organisation.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Display Name</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-b border-slate-800 hover:bg-surface-raised">
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
