# SP17b RBAC — Frontend Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin UI pages for sysadmin (org management, user management) and org_admin (team panel), with role-gated nav and routes. Depends on SP17a backend being complete.

**Architecture:** `UserPayload` gets `org_id?`; `useAuth()` already exposes it. A new `AdminRoute` component gates by role. New pages live inside `AppLayout` (no new layout needed). Admin API client in `ui/src/api/admin.ts`. Five new pages: AdminDashboard, OrgDetail, UserList, UserForm, OrgPanel.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3 (brand tokens), React Router v6, TanStack Query

---

## File map

| File | Action |
|------|--------|
| `ui/src/types.ts` | Add `org_id?: number` to `UserPayload`; add admin types |
| `ui/src/api/admin.ts` | **NEW** — admin API client |
| `ui/src/context/AuthContext.tsx` | Expose `role` shortcut from `user` |
| `ui/src/router.tsx` | Add `AdminRoute` + 7 new routes |
| `ui/src/pages/AdminDashboard.tsx` | **NEW** |
| `ui/src/pages/OrgDetail.tsx` | **NEW** |
| `ui/src/pages/UserList.tsx` | **NEW** |
| `ui/src/pages/UserForm.tsx` | **NEW** |
| `ui/src/pages/OrgPanel.tsx` | **NEW** |
| `ui/src/components/AppLayout.tsx` | Add Admin/Team nav items based on role |

---

### Task 1: TypeScript types + admin API client

**Files:**
- Modify: `ui/src/types.ts`
- Create: `ui/src/api/admin.ts`

- [ ] **Step 1: Add `org_id` to `UserPayload` and new admin types in `ui/src/types.ts`**

Find the `UserPayload` interface (~line 113) and update it:

```typescript
export interface UserPayload {
  sub: string
  role: 'sysadmin' | 'org_admin' | 'reviewer'
  org_id?: number
  exp: number
}
```

Append these new interfaces at the end of `ui/src/types.ts`:

```typescript
// ── Admin types ───────────────────────────────────────────────────────────────

export interface Organisation {
  id: number
  slug: string
  name: string
  created_at: string
}

export interface OrgMember {
  id: number
  username: string
  email: string
  role: string
  org_role: string
  created_at: string
}

export interface AdminUser {
  id: number
  username: string
  email: string
  role: string
  created_at: string
}

export interface ProjectRegistryEntry {
  id: number
  slug: string
  org_id: number
  display_name: string
  org_name?: string
  created_at: string
}

export interface ProjectMembership {
  id: number
  user_id: number
  project_slug: string
  created_at: string
}
```

- [ ] **Step 2: Create `ui/src/api/admin.ts`**

```typescript
// ui/src/api/admin.ts
import { apiClient } from './client'
import type {
  Organisation,
  OrgMember,
  AdminUser,
  ProjectRegistryEntry,
  ProjectMembership,
} from '../types'

export const adminApi = {
  // Organisations
  listOrgs: (): Promise<Organisation[]> =>
    apiClient.get<Organisation[]>('/auth/orgs').then((r) => r.data),

  createOrg: (slug: string, name: string): Promise<Organisation> =>
    apiClient.post<Organisation>('/auth/orgs', { slug, name }).then((r) => r.data),

  updateOrg: (orgId: number, name: string): Promise<Organisation> =>
    apiClient.patch<Organisation>(`/auth/orgs/${orgId}`, { name }).then((r) => r.data),

  deleteOrg: (orgId: number): Promise<void> =>
    apiClient.delete(`/auth/orgs/${orgId}`).then(() => undefined),

  // Org members
  listOrgMembers: (orgId: number): Promise<OrgMember[]> =>
    apiClient.get<OrgMember[]>(`/auth/orgs/${orgId}/members`).then((r) => r.data),

  addOrgMember: (orgId: number, userId: number, role: string): Promise<void> =>
    apiClient.post(`/auth/orgs/${orgId}/members`, { user_id: userId, role }).then(() => undefined),

  updateOrgMemberRole: (orgId: number, userId: number, role: string): Promise<void> =>
    apiClient
      .patch(`/auth/orgs/${orgId}/members/${userId}`, { role })
      .then(() => undefined),

  removeOrgMember: (orgId: number, userId: number): Promise<void> =>
    apiClient.delete(`/auth/orgs/${orgId}/members/${userId}`).then(() => undefined),

  // Project registry
  listRegistry: (): Promise<ProjectRegistryEntry[]> =>
    apiClient.get<ProjectRegistryEntry[]>('/auth/projects').then((r) => r.data),

  registerProject: (slug: string, orgId: number, displayName: string): Promise<void> =>
    apiClient
      .post('/auth/projects', { slug, org_id: orgId, display_name: displayName })
      .then(() => undefined),

  unregisterProject: (slug: string): Promise<void> =>
    apiClient.delete(`/auth/projects/${slug}`).then(() => undefined),

  // Users
  listUsers: (): Promise<AdminUser[]> =>
    apiClient.get<AdminUser[]>('/auth/users').then((r) => r.data),

  createUser: (data: {
    username: string
    email: string
    password: string
    role: string
    org_id?: number
  }): Promise<AdminUser> =>
    apiClient.post<AdminUser>('/auth/users', data).then((r) => r.data),

  updateUser: (
    userId: number,
    data: { email: string; role: string; password?: string }
  ): Promise<AdminUser> =>
    apiClient.patch<AdminUser>(`/auth/users/${userId}`, data).then((r) => r.data),

  deleteUser: (userId: number): Promise<void> =>
    apiClient.delete(`/auth/users/${userId}`).then(() => undefined),

  // Project memberships
  listUserProjects: (userId: number): Promise<ProjectMembership[]> =>
    apiClient
      .get<ProjectMembership[]>(`/auth/users/${userId}/projects`)
      .then((r) => r.data),

  grantProjectAccess: (userId: number, slug: string): Promise<void> =>
    apiClient.post(`/auth/users/${userId}/projects/${slug}`).then(() => undefined),

  revokeProjectAccess: (userId: number, slug: string): Promise<void> =>
    apiClient.delete(`/auth/users/${userId}/projects/${slug}`).then(() => undefined),
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/types.ts ui/src/api/admin.ts
git commit -m "feat: add admin TypeScript types and API client"
```

---

### Task 2: AdminRoute component + router updates

**Files:**
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Rewrite `ui/src/router.tsx` with AdminRoute and new routes**

```typescript
// ui/src/router.tsx
import { createBrowserRouter, Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import ValueChain from './pages/ValueChain'
import Roadmap from './pages/Roadmap'
import RunDetail from './pages/RunDetail'
import Settings from './pages/Settings'
import BusinessPlan from './pages/BusinessPlan'
import Reviews from './pages/Reviews'
import Runs from './pages/Runs'
import Stakeholders from './pages/Stakeholders'
import StakeholderForm from './pages/StakeholderForm'
import Discovery from './pages/Discovery'
import ValuePropositions from './pages/ValuePropositions'
import Assignment from './pages/Assignment'
import VoiceInterview from './pages/VoiceInterview'
import Templates from './pages/Templates'
import Report from './pages/Report'
import Architecture from './pages/Architecture'
import AdminDashboard from './pages/AdminDashboard'
import OrgDetail from './pages/OrgDetail'
import UserList from './pages/UserList'
import UserForm from './pages/UserForm'
import OrgPanel from './pages/OrgPanel'

type Role = 'sysadmin' | 'org_admin' | 'reviewer'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminRoute({ children, allow }: { children: ReactNode; allow: Role[] }) {
  const { token, user } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (!user || !allow.includes(user.role as Role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
  {
    path: '/architecture',
    element: (
      <ProtectedRoute>
        <Architecture />
      </ProtectedRoute>
    ),
  },
  {
    path: '/:slug/report',
    element: (
      <ProtectedRoute>
        <Report />
      </ProtectedRoute>
    ),
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: ':slug', element: <Dashboard /> },
      { path: ':slug/discovery', element: <Discovery /> },
      { path: ':slug/value-chain', element: <ValueChain /> },
      { path: ':slug/value-propositions', element: <ValuePropositions /> },
      { path: ':slug/roadmap', element: <Roadmap /> },
      { path: ':slug/stakeholders', element: <Stakeholders /> },
      { path: ':slug/stakeholders/new', element: <StakeholderForm /> },
      { path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
      { path: ':slug/business-plan', element: <BusinessPlan /> },
      { path: ':slug/reviews', element: <Reviews /> },
      { path: ':slug/runs', element: <Runs /> },
      { path: ':slug/documents', element: <Documents /> },
      { path: ':slug/runs/:runId', element: <RunDetail /> },
      { path: ':slug/assignment', element: <Assignment /> },
      { path: ':slug/templates', element: <Templates /> },
      { path: ':slug/settings', element: <Settings /> },
      // Admin routes — inside AppLayout
      {
        path: 'admin',
        element: (
          <AdminRoute allow={['sysadmin']}>
            <AdminDashboard />
          </AdminRoute>
        ),
      },
      {
        path: 'admin/orgs/:orgId',
        element: (
          <AdminRoute allow={['sysadmin']}>
            <OrgDetail />
          </AdminRoute>
        ),
      },
      {
        path: 'admin/users',
        element: (
          <AdminRoute allow={['sysadmin', 'org_admin']}>
            <UserList />
          </AdminRoute>
        ),
      },
      {
        path: 'admin/users/new',
        element: (
          <AdminRoute allow={['sysadmin', 'org_admin']}>
            <UserForm />
          </AdminRoute>
        ),
      },
      {
        path: 'admin/users/:userId/edit',
        element: (
          <AdminRoute allow={['sysadmin', 'org_admin']}>
            <UserForm />
          </AdminRoute>
        ),
      },
      {
        path: 'org',
        element: (
          <AdminRoute allow={['org_admin']}>
            <OrgPanel />
          </AdminRoute>
        ),
      },
    ],
  },
], { basename: '/dashboard' })
```

- [ ] **Step 2: Verify TypeScript compiles (pages don't exist yet — expect import errors only)**

```bash
cd ui && npx tsc --noEmit 2>&1 | grep -v "Cannot find module" | head -10
```

Expected: only "Cannot find module" errors for the new page imports — no type errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/router.tsx
git commit -m "feat: add AdminRoute guard and admin routes to router"
```

---

### Task 3: AdminDashboard page

**Files:**
- Create: `ui/src/pages/AdminDashboard.tsx`

- [ ] **Step 1: Create `ui/src/pages/AdminDashboard.tsx`**

```typescript
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
      <div className="bg-surface-card rounded-lg border border-slate-800 mb-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Organisations</h2>
          <button
            onClick={() => setShowOrgForm((v) => !v)}
            className="text-xs text-brand hover:text-brand-light"
          >
            + New Org
          </button>
        </div>

        {showOrgForm && (
          <div className="flex gap-2 px-4 py-3 border-b border-slate-800">
            <input
              className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
              placeholder="slug (e.g. acme)"
              value={newOrgSlug}
              onChange={(e) => setNewOrgSlug(e.target.value)}
            />
            <input
              className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
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
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id} className="border-b border-slate-800 hover:bg-surface-raised">
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
      <div className="bg-surface-card rounded-lg border border-slate-800">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
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
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-800 hover:bg-surface-raised">
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
    sysadmin: 'bg-violet-900/50 text-violet-300',
    org_admin: 'bg-teal-900/50 text-teal-300',
    reviewer: 'bg-slate-800 text-slate-300',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colours[role] ?? colours.reviewer}`}>
      {role}
    </span>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | grep -v "Cannot find module" | head -10
```

Expected: no new errors (OrgDetail/UserList/UserForm/OrgPanel still missing — that's fine).

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/AdminDashboard.tsx
git commit -m "feat: add AdminDashboard page (orgs + users panels)"
```

---

### Task 4: OrgDetail page

**Files:**
- Create: `ui/src/pages/OrgDetail.tsx`

- [ ] **Step 1: Create `ui/src/pages/OrgDetail.tsx`**

```typescript
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

        {/* Add member form */}
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
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | grep -v "Cannot find module" | head -10
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/pages/OrgDetail.tsx
git commit -m "feat: add OrgDetail page (members + linked projects management)"
```

---

### Task 5: UserList and UserForm pages

**Files:**
- Create: `ui/src/pages/UserList.tsx`
- Create: `ui/src/pages/UserForm.tsx`

- [ ] **Step 1: Create `ui/src/pages/UserList.tsx`**

```typescript
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
      sysadmin: 'bg-violet-900/50 text-violet-300',
      org_admin: 'bg-teal-900/50 text-teal-300',
      reviewer: 'bg-slate-800 text-slate-300',
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
        <h1 className="text-xl font-bold text-primary">Users</h1>
        <button
          onClick={() => navigate('/admin/users/new')}
          className="text-xs bg-brand text-white px-3 py-1.5 rounded"
        >
          + New User
        </button>
      </div>

      <div className="bg-surface-card rounded-lg border border-slate-800">
        {isLoading ? (
          <p className="px-4 py-6 text-sm text-muted">Loading…</p>
        ) : users.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">No users yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-slate-800">
                <th className="text-left px-4 py-2">Username</th>
                <th className="text-left px-4 py-2">Email</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-800 hover:bg-surface-raised">
                  <td className="px-4 py-2 font-mono text-xs text-primary">{u.username}</td>
                  <td className="px-4 py-2 text-secondary text-xs">{u.email || '—'}</td>
                  <td className="px-4 py-2">{roleBadge(u.role)}</td>
                  <td className="px-4 py-2 text-muted text-xs">{u.created_at.slice(0, 10)}</td>
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
```

- [ ] **Step 2: Create `ui/src/pages/UserForm.tsx`**

```typescript
// ui/src/pages/UserForm.tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
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

  // Populate form for edit
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
    onError: () => setError('Failed to create user — username may already exist.'),
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
      <button onClick={() => navigate('/admin/users')} className="text-xs text-muted hover:text-primary mb-4 block">
        ← Back to Users
      </button>

      <h1 className="text-xl font-bold text-primary mb-6">
        {isEdit ? 'Edit User' : 'New User'}
      </h1>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="text-xs text-muted block mb-1">Username</label>
          <input
            className="w-full bg-surface-raised border border-slate-700 rounded px-3 py-2 text-sm text-primary"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={isEdit}
            required={!isEdit}
          />
        </div>

        <div>
          <label className="text-xs text-muted block mb-1">Email</label>
          <input
            type="email"
            className="w-full bg-surface-raised border border-slate-700 rounded px-3 py-2 text-sm text-primary"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="text-xs text-muted block mb-1">
            {isEdit ? 'New Password (leave blank to keep current)' : 'Password'}
          </label>
          <input
            type="password"
            className="w-full bg-surface-raised border border-slate-700 rounded px-3 py-2 text-sm text-primary"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!isEdit}
          />
        </div>

        <div>
          <label className="text-xs text-muted block mb-1">Role</label>
          <select
            className="w-full bg-surface-raised border border-slate-700 rounded px-3 py-2 text-sm text-primary"
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
            <label className="text-xs text-muted block mb-1">Organisation (optional)</label>
            <select
              className="w-full bg-surface-raised border border-slate-700 rounded px-3 py-2 text-sm text-primary"
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

      {/* Project access grants — only shown in edit mode for reviewer role */}
      {isEdit && role === 'reviewer' && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-primary mb-3">Project Access</h2>
          <div className="flex gap-2 mb-3">
            <input
              className="flex-1 bg-surface-raised border border-slate-700 rounded px-2 py-1 text-sm text-primary"
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
            <p className="text-xs text-muted">No project access granted.</p>
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
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ui && npx tsc --noEmit 2>&1 | grep -v "Cannot find module" | head -10
```

- [ ] **Step 4: Commit**

```bash
git add ui/src/pages/UserList.tsx ui/src/pages/UserForm.tsx
git commit -m "feat: add UserList and UserForm pages"
```

---

### Task 6: OrgPanel page + AppLayout nav + final wiring

**Files:**
- Create: `ui/src/pages/OrgPanel.tsx`
- Modify: `ui/src/components/AppLayout.tsx`

- [ ] **Step 1: Create `ui/src/pages/OrgPanel.tsx`**

```typescript
// ui/src/pages/OrgPanel.tsx
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../api/admin'
import { useAuth } from '../context/AuthContext'
import type { OrgMember, ProjectRegistryEntry } from '../types'

export default function OrgPanel() {
  const { user } = useAuth()
  const orgId = user?.org_id
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: members = [] } = useQuery<OrgMember[]>({
    queryKey: ['admin', 'orgs', orgId, 'members'],
    queryFn: () => adminApi.listOrgMembers(orgId!),
    enabled: !!orgId,
  })

  const { data: projects = [] } = useQuery<ProjectRegistryEntry[]>({
    queryKey: ['admin', 'projects'],
    queryFn: adminApi.listRegistry,
    select: (all) => all.filter((p) => p.org_id === orgId),
    enabled: !!orgId,
  })

  const removeMemberMut = useMutation({
    mutationFn: (userId: number) => adminApi.removeOrgMember(orgId!, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'orgs', orgId, 'members'] }),
  })

  if (!orgId) return <p className="p-6 text-sm text-muted">No organisation assigned.</p>

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-primary mb-6">My Organisation — Team</h1>

      <div className="flex gap-4 mb-6">
        <button
          onClick={() => navigate('/admin/users/new')}
          className="text-xs bg-brand text-white px-3 py-1.5 rounded"
        >
          + Invite User
        </button>
        <button
          onClick={() => navigate('/admin/users')}
          className="text-xs border border-slate-700 text-secondary px-3 py-1.5 rounded hover:border-slate-500"
        >
          Manage Users
        </button>
      </div>

      {/* Members */}
      <div className="bg-surface-card rounded-lg border border-slate-800 mb-6">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Members ({members.length})</h2>
        </div>
        {members.length === 0 ? (
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
                  <td className="px-4 py-2 text-xs text-muted">{m.org_role}</td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => navigate(`/admin/users/${m.id}/edit`)}
                      className="text-xs text-brand hover:text-brand-light mr-3"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Remove ${m.username}?`)) removeMemberMut.mutate(m.id)
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

      {/* Projects */}
      <div className="bg-surface-card rounded-lg border border-slate-800">
        <div className="px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-primary">Projects ({projects.length})</h2>
        </div>
        {projects.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted">No projects linked to this org.</p>
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
                      onClick={() => navigate(`/${p.slug}`)}
                      className="text-xs text-brand hover:text-brand-light"
                    >
                      Open →
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
```

- [ ] **Step 2: Update `ui/src/components/AppLayout.tsx` to add Admin/Team nav**

In `AppLayout.tsx`, update the imports to include `useNavigate` (already there) and add role-gated sidebar items.

Find the sidebar section that currently ends with the "New Project" button (`<div className="mt-auto pt-3">`) and add before it:

```typescript
// Add at top of component, after const { user, logout } = useAuth()
const role = user?.role

// Then inside the sidebar <aside>, before the mt-auto div:
{(role === 'sysadmin' || role === 'org_admin') && (
  <div className="mt-4 pt-3 border-t border-slate-800">
    <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
      Admin
    </p>
    {role === 'sysadmin' && (
      <button
        onClick={() => navigate('/admin')}
        className="w-full text-left text-sm px-2 py-1.5 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
      >
        Admin Panel
      </button>
    )}
    {role === 'org_admin' && (
      <button
        onClick={() => navigate('/org')}
        className="w-full text-left text-sm px-2 py-1.5 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
      >
        Team
      </button>
    )}
    <button
      onClick={() => navigate('/admin/users')}
      className="w-full text-left text-sm px-2 py-1.5 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
    >
      Users
    </button>
  </div>
)}
```

- [ ] **Step 3: Build to verify no TypeScript or JSX errors**

```bash
cd ui && npm run build 2>&1 | tail -20
```

Expected: successful build with no errors.

- [ ] **Step 4: Start dev server and smoke test**

```bash
cd ui && npm run dev &
sleep 3
```

Manual checks:
1. Navigate to `http://localhost:3000/dashboard/login` — log in as admin
2. Verify "Admin Panel" appears in sidebar
3. Navigate to `/admin` — confirm AdminDashboard loads with Organisations and Users panels
4. Create an org (slug: `test-org`, name: `Test Org`) — confirm it appears in the list
5. Click "Manage" — confirm OrgDetail loads
6. Navigate to `/admin/users/new` — confirm UserForm loads, fill in and submit
7. Verify new user appears in user list
8. Log out, log in as the new user — verify "Admin Panel" is not visible if role is `reviewer`

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/OrgPanel.tsx ui/src/components/AppLayout.tsx
git commit -m "feat: add OrgPanel page + Admin/Team nav items in AppLayout"
```

- [ ] **Step 6: Final full test run**

```bash
pytest tests/ -q 2>&1 | tail -5
```

Expected: all tests passing.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: SP17b complete — RBAC admin UI (AdminDashboard, OrgDetail, UserList, UserForm, OrgPanel)"
```
