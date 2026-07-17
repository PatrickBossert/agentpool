// ui/src/pages/UserForm.tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import { useAuth } from '../context/AuthContext'
import type { Organisation, AdminUser, ProjectMembership } from '../types'

export default function UserForm() {
  const { userId: userIdStr } = useParams<{ userId?: string }>()
  const userId = userIdStr ? parseInt(userIdStr, 10) : null
  const isEdit = userId !== null
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user: authUser } = useAuth()
  const isSysadmin = authUser?.role === 'sysadmin'

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('reviewer')
  const [orgId, setOrgId] = useState<number | ''>('')
  const [error, setError] = useState('')

  const { data: orgs = [] } = useQuery<Organisation[]>({
    queryKey: ['admin', 'orgs'],
    queryFn: adminApi.listOrgs,
    enabled: isSysadmin,
  })

  const { data: allUsers = [] } = useQuery<AdminUser[]>({
    queryKey: ['admin', 'users'],
    queryFn: adminApi.listUsers,
  })

  const { data: userProjects = [] } = useQuery<ProjectMembership[]>({
    queryKey: ['admin', 'user', userId, 'projects'],
    queryFn: () => adminApi.listUserProjects(userId!),
    enabled: isEdit,
  })

  useEffect(() => {
    if (isEdit && allUsers.length > 0) {
      const u = allUsers.find((u) => u.id === userId)
      if (u) {
        setUsername(u.username)
        setEmail(u.email)
        setRole(u.role)
      }
    }
  }, [isEdit, userId, allUsers])

  const createMut = useMutation({
    mutationFn: () =>
      adminApi.createUser({
        username,
        email,
        password,
        role,
        org_id: orgId !== '' ? orgId : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      navigate('/admin/users')
    },
    onError: () => setError('Failed to create user - username may already exist.'),
  })

  const updateMut = useMutation({
    mutationFn: () =>
      adminApi.updateUser(userId!, {
        email,
        role,
        password: password || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      navigate('/admin/users')
    },
    onError: () => setError('Failed to update user.'),
  })

  const grantMut = useMutation({
    mutationFn: (slug: string) => adminApi.grantProjectAccess(userId!, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'user', userId, 'projects'] }),
  })

  const revokeMut = useMutation({
    mutationFn: (slug: string) => adminApi.revokeProjectAccess(userId!, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'user', userId, 'projects'] }),
  })

  const [grantSlug, setGrantSlug] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (isEdit) updateMut.mutate()
    else createMut.mutate()
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      <button onClick={() => navigate('/admin/users')} className="text-xs text-gray-600 hover:text-gray-900 mb-4 block">
        <span className="flex items-center gap-1"><ArrowLeft size={14} />Back to Users</span>
      </button>

      <h1 className="text-xl font-bold text-gray-900 mb-6">
        {isEdit ? 'Edit User' : 'New User'}
      </h1>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="text-xs text-gray-600 block mb-1">Username</label>
          <input
            className="w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={isEdit}
            required={!isEdit}
          />
        </div>

        <div>
          <label className="text-xs text-gray-600 block mb-1">Email</label>
          <input
            type="email"
            className="w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="text-xs text-gray-600 block mb-1">
            {isEdit ? 'New Password (leave blank to keep current)' : 'Password'}
          </label>
          <input
            type="password"
            className="w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!isEdit}
          />
        </div>

        <div>
          <label className="text-xs text-gray-600 block mb-1">Role</label>
          <select
            className="w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {isSysadmin && <option value="sysadmin">sysadmin</option>}
            <option value="org_admin">org_admin</option>
            <option value="reviewer">reviewer</option>
          </select>
        </div>

        {!isEdit && isSysadmin && (
          <div>
            <label className="text-xs text-gray-600 block mb-1">Organisation (optional)</label>
            <select
              className="w-full bg-white border border-gray-200 rounded px-3 py-2 text-sm text-gray-900"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value === '' ? '' : parseInt(e.target.value, 10))}
            >
              <option value="">None</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
        )}

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button
          type="submit"
          className="w-full bg-brand text-white py-2 rounded text-sm font-medium"
        >
          {isEdit ? 'Save Changes' : 'Create User'}
        </button>
      </form>

      {isEdit && role === 'reviewer' && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Project Access</h2>
          <div className="flex gap-2 mb-3">
            <input
              className="flex-1 bg-white border border-gray-200 rounded px-2 py-1 text-sm text-gray-900"
              placeholder="project-slug"
              value={grantSlug}
              onChange={(e) => setGrantSlug(e.target.value)}
            />
            <button
              onClick={() => { if (grantSlug) { grantMut.mutate(grantSlug); setGrantSlug('') } }}
              className="text-xs bg-brand text-white px-3 py-1 rounded"
            >
              Grant
            </button>
          </div>
          {userProjects.length === 0 ? (
            <p className="text-xs text-gray-600">No project access granted.</p>
          ) : (
            <ul className="space-y-1">
              {userProjects.map((p) => (
                <li key={p.id} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs text-brand">{p.project_slug}</span>
                  <button
                    onClick={() => revokeMut.mutate(p.project_slug)}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
