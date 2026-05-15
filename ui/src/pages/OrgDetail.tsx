// ui/src/pages/OrgDetail.tsx
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import type { OrgMember, AdminUser, ProjectRegistryEntry } from '../types'

export default function OrgDetail() {
  const { orgId: orgIdStr } = useParams<{ orgId: string }>()
  const orgId = parseInt(orgIdStr ?? '0', 10)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [addUserId, setAddUserId] = useState('')
  const [addRole, setAddRole] = useState('member')
  const [regSlug, setRegSlug] = useState('')
  const [regName, setRegName] = useState('')
  const [editName, setEditName] = useState('')
  const [showEditOrg, setShowEditOrg] = useState(false)

  const { data: org } = useQuery({
    queryKey: ['admin', 'org', orgId],
    queryFn: () => adminApi.listOrgs().then((orgs) => orgs.find((o) => o.id === orgId)),
  })

  const { data: members = [] } = useQuery<OrgMember[]>({
    queryKey: ['admin', 'orgs', orgId, 'members'],
    queryFn: () => adminApi.listOrgMembers(orgId),
  })

  const { data: projects = [] } = useQuery<ProjectRegistryEntry[]>({
    queryKey: ['admin', 'projects'],
    queryFn: adminApi.listRegistry,
    select: (all) => all.filter((p) => p.org_id === orgId),
  })

  const { data: allUsers = [] } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: adminApi.listUsers,
  })

  const addMemberMut = useMutation({
    mutationFn: () => adminApi.addOrgMember(orgId, parseInt(addUserId, 10), addRole),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs', orgId, 'members'] })
      setAddUserId('')
    },
  })

  const removeMemberMut = useMutation({
    mutationFn: (userId: number) => adminApi.removeOrgMember(orgId, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'orgs', orgId, 'members'] }),
  })

  const updateRoleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      adminApi.updateOrgMemberRole(orgId, userId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'orgs', orgId, 'members'] }),
  })

  const registerMut = useMutation({
    mutationFn: () => adminApi.registerProject(regSlug, orgId, regName || regSlug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'projects'] })
      setRegSlug('')
      setRegName('')
    },
  })

  const unregisterMut = useMutation({
    mutationFn: (slug: string) => adminApi.unregisterProject(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'projects'] }),
  })

  const updateOrgMut = useMutation({
    mutationFn: () => adminApi.updateOrg(orgId, editName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'org', orgId] })
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      setShowEditOrg(false)
    },
  })

  const nonMembers = allUsers.filter((u) => !members.some((m) => m.id === u.id))

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <button onClick={() => navigate('/admin')} className="text-xs text-muted hover:text-primary mb-4 block">
        ← Back to Admin
      </button>

      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-primary">{org?.name ?? 'Organisation'}</h1>
        <span className="text-xs text-muted font-mono">{org?.slug}</span>
        <button
          onClick={() => { setEditName(org?.name ?? ''); setShowEditOrg(true) }}
          className="text-xs text-brand hover:text-brand-light ml-auto"
        >
          Rename
        </button>
      </div>

      {showEditOrg && (
        <div className="flex gap-2 mb-6">
          <input
            className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <button
            onClick={() => updateOrgMut.mutate()}
            className="text-xs bg-brand text-white px-3 py-1 rounded"
          >
            Save
          </button>
          <button onClick={() => setShowEditOrg(false)} className="text-xs text-muted">Cancel</button>
        </div>
      )}

      {/* Members */}
      <div className="bg-surface-card rounded-lg border border-slate-800 mb-6">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Members</h2>
        </div>

        <div className="flex gap-2 px-4 py-3 border-b border-slate-800">
          <select
            className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
            value={addUserId}
            onChange={(e) => setAddUserId(e.target.value)}
          >
            <option value="">Select user to add…</option>
            {nonMembers.map((u) => (
              <option key={u.id} value={u.id}>{u.username} ({u.email})</option>
            ))}
          </select>
          <select
            className="bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
            value={addRole}
            onChange={(e) => setAddRole(e.target.value)}
          >
            <option value="member">member</option>
            <option value="org_admin">org_admin</option>
          </select>
          <button
            onClick={() => addMemberMut.mutate()}
            disabled={!addUserId}
            className="text-xs bg-brand text-white px-3 py-1 rounded disabled:opacity-40"
          >
            Add
          </button>
        </div>

        {members.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No members yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Org Role</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-slate-800 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-primary">{m.username}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{m.email}</td>
                  <td className="px-4 py-2">
                    <select
                      className="bg-transparent text-xs text-secondary border border-slate-700 rounded px-1"
                      value={m.org_role}
                      onChange={(e) =>
                        updateRoleMut.mutate({ userId: m.id, role: e.target.value })
                      }
                    >
                      <option value="member">member</option>
                      <option value="org_admin">org_admin</option>
                    </select>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Remove ${m.username} from org?`))
                          removeMemberMut.mutate(m.id)
                      }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Linked projects */}
      <div className="bg-surface-card rounded-lg border border-slate-800">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Linked Projects</h2>
        </div>
        <div className="flex gap-2 px-4 py-3 border-b border-slate-800">
          <input
            className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
            placeholder="project-slug"
            value={regSlug}
            onChange={(e) => setRegSlug(e.target.value)}
          />
          <input
            className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
            placeholder="Display name (optional)"
            value={regName}
            onChange={(e) => setRegName(e.target.value)}
          />
          <button
            onClick={() => registerMut.mutate()}
            disabled={!regSlug}
            className="text-xs bg-brand text-white px-3 py-1 rounded disabled:opacity-40"
          >
            Link
          </button>
        </div>
        {projects.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No projects linked.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Display Name</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="border-b border-slate-800 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-brand">{p.slug}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{p.display_name}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Unlink ${p.slug}?`)) unregisterMut.mutate(p.slug)
                      }}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Unlink
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
