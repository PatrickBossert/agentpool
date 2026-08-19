// ui/src/pages/AdminDashboard.tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Globe, RotateCcw, Save } from 'lucide-react'
import { adminApi } from '../api/admin'
import { useAuth } from '../context/AuthContext'
import { describeError } from '../utils/describeError'
import type { Organisation, AdminUser, PlatformSettings } from '../types'

export default function AdminDashboard() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuth()
  // The router already restricts /admin to a sysadmin token (router.tsx's AdminRoute), so in
  // production this is always true - but a control that 403s on submit is worse than one that
  // is not there at all (CLAUDE.md, on StakeholderForm's grantable roles), so the panel below
  // gates itself on the role the token carries rather than trusting the route alone.
  const isSysadmin = user?.role === 'sysadmin'
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newOrgName, setNewOrgName] = useState('')
  const [showOrgForm, setShowOrgForm] = useState(false)

  const { data: orgs = [] } = useQuery<Organisation[]>({
    queryKey: ['admin', 'orgs'],
    queryFn: adminApi.listOrgs,
  })

  const { data: users = [] } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: () => adminApi.listUsers(),
  })

  const { data: platformSettings } = useQuery<PlatformSettings>({
    queryKey: ['admin', 'platform-settings'],
    queryFn: adminApi.getPlatformSettings,
    enabled: isSysadmin,
  })

  const [publicUrlDraft, setPublicUrlDraft] = useState('')
  const [publicUrlError, setPublicUrlError] = useState<string | null>(null)

  // Synced from the server, not merely initialised from it: after a save the server returns
  // the *normalised* form (no trailing slash, query/fragment/;params dropped silently), and
  // an administrator who typed one of those should see what was actually stored, not what
  // they typed.
  useEffect(() => {
    if (platformSettings) setPublicUrlDraft(platformSettings.public_url)
  }, [platformSettings])

  const savePublicUrlMut = useMutation({
    mutationFn: (url: string) => adminApi.setPlatformPublicUrl(url),
    onSuccess: (data) => {
      setPublicUrlError(null)
      qc.setQueryData(['admin', 'platform-settings'], data)
    },
    onError: (err) => setPublicUrlError(describeError(err, 'Could not save the public URL.')),
  })

  const revertPublicUrlMut = useMutation({
    mutationFn: () => adminApi.revertPlatformPublicUrl(),
    onSuccess: (data) => {
      setPublicUrlError(null)
      qc.setQueryData(['admin', 'platform-settings'], data)
    },
    onError: (err) =>
      setPublicUrlError(describeError(err, 'Could not revert to the environment default.')),
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
      <h1 className="text-xl font-bold text-gray-900 mb-6">Admin Dashboard</h1>

      {/* Organisations panel */}
      <div className="bg-surface-card rounded-lg border border-gray-200 mb-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Organisations</h2>
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
              className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900"
              placeholder="slug (e.g. acme)"
              value={newOrgSlug}
              onChange={(e) => setNewOrgSlug(e.target.value)}
            />
            <input
              className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900"
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
          <p className="px-4 py-3 text-sm text-gray-600">No organisations yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-600 border-b border-gray-200">
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
                  <td className="px-4 py-2 text-gray-900">{org.name}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">
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

      {/* Platform public URL panel - sysadmin only. Not one project's configuration: the
          address every interview invitation and welcome email on the whole deployment
          points at, so it is gated a tier tighter than the org panel above. */}
      {isSysadmin && (
        <div className="bg-surface-card rounded-lg border border-gray-200 mb-6">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
            <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Globe size={14} className="text-brand" aria-hidden="true" />
              Platform Public URL
            </h2>
          </div>

          <div className="px-4 py-3 space-y-3">
            <p className="text-xs text-gray-600 leading-relaxed">
              The address this deployment answers on. Every interview invitation, reminder,
              and welcome email links back here, so an administrator needs to know whether
              the value below is a saved setting or the environment's fallback - the two
              behave differently the next time the environment changes.
            </p>

            {platformSettings && (
              <p className="text-xs text-gray-600">
                Currently{' '}
                <span
                  className={
                    platformSettings.source === 'stored'
                      ? 'px-1.5 py-0.5 rounded-full font-medium bg-brand/10 text-teal-700'
                      : 'px-1.5 py-0.5 rounded-full font-medium bg-gray-100 text-gray-600'
                  }
                >
                  {platformSettings.source === 'stored'
                    ? 'a saved setting'
                    : 'inherited from the PUBLIC_URL environment variable'}
                </span>
                .
              </p>
            )}

            <div className="flex gap-2">
              <input
                aria-label="Platform public URL"
                className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900"
                placeholder="https://app.example.com"
                value={publicUrlDraft}
                onChange={(e) => setPublicUrlDraft(e.target.value)}
              />
              <button
                onClick={() => savePublicUrlMut.mutate(publicUrlDraft)}
                disabled={!publicUrlDraft || savePublicUrlMut.isPending}
                className="text-xs bg-brand text-white px-3 py-1 rounded disabled:opacity-40 flex items-center gap-1 whitespace-nowrap"
              >
                <Save size={12} aria-hidden="true" />
                Save
              </button>
              <button
                onClick={() => revertPublicUrlMut.mutate()}
                disabled={revertPublicUrlMut.isPending}
                title="Revert to the PUBLIC_URL environment variable"
                className="text-xs border border-gray-200 text-gray-700 px-3 py-1 rounded disabled:opacity-40 flex items-center gap-1 whitespace-nowrap"
              >
                <RotateCcw size={12} aria-hidden="true" />
                Revert to environment default
              </button>
            </div>

            {publicUrlError && <p className="text-xs text-red-500">{publicUrlError}</p>}
          </div>
        </div>
      )}

      {/* Skills panel */}
      <div className="bg-surface-card rounded-lg border border-gray-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Agent Skills Library</h2>
          <button
            onClick={() => navigate('/admin/skills')}
            className="text-xs text-brand hover:text-brand-light"
          >
            Manage skills →
          </button>
        </div>
        <p className="px-4 py-3 text-xs text-gray-600 leading-relaxed">
          Review suggested skills, manage the global library, and export / import skills bundles for new instances.
        </p>
      </div>

      {/* Users panel */}
      <div className="bg-surface-card rounded-lg border border-gray-200">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Users</h2>
          <button
            onClick={() => navigate('/admin/users/new')}
            className="text-xs text-brand hover:text-brand-light"
          >
            + New User
          </button>
        </div>

        {users.length === 0 ? (
          <p className="px-4 py-3 text-sm text-gray-600">No users yet.</p>
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
                  <td className="px-4 py-2 text-secondary text-xs">{u.email}</td>
                  <td className="px-4 py-2">
                    <RoleBadge role={u.role} />
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{u.created_at.slice(0, 10)}</td>
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
