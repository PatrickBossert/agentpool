// ui/src/api/admin.ts
import { apiClient } from './client'
import type {
  Organisation,
  OrgMember,
  AdminUser,
  ProjectRegistryEntry,
  ProjectMembership,
  ResetLinkResponse,
  PlatformSettings,
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

  // Users. `project` selects the lens a name is read through - without it the server returns
  // every account the caller may administer and no `person` field at all, because a name only
  // exists relative to an engagement.
  listUsers: (project?: string): Promise<AdminUser[]> =>
    apiClient
      .get<AdminUser[]>('/auth/users', project ? { params: { project } } : undefined)
      .then((r) => r.data),

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

  issueResetLink: (userId: number): Promise<ResetLinkResponse> =>
    apiClient.post<ResetLinkResponse>(`/auth/users/${userId}/reset-link`).then((r) => r.data),

  // Project memberships
  listUserProjects: (userId: number): Promise<ProjectMembership[]> =>
    apiClient
      .get<ProjectMembership[]>(`/auth/users/${userId}/projects`)
      .then((r) => r.data),

  grantProjectAccess: (userId: number, slug: string): Promise<void> =>
    apiClient.post(`/auth/users/${userId}/projects/${slug}`).then(() => undefined),

  revokeProjectAccess: (userId: number, slug: string): Promise<void> =>
    apiClient.delete(`/auth/users/${userId}/projects/${slug}`).then(() => undefined),

  // Platform settings - sysadmin only, api/routers/platform_settings.py. The address this
  // deployment answers on, which every interview invitation and welcome email points at.
  getPlatformSettings: (): Promise<PlatformSettings> =>
    apiClient.get<PlatformSettings>('/admin/platform-settings').then((r) => r.data),

  setPlatformPublicUrl: (publicUrl: string): Promise<PlatformSettings> =>
    apiClient
      .patch<PlatformSettings>('/admin/platform-settings', { public_url: publicUrl })
      .then((r) => r.data),

  // Reverts to inheriting PUBLIC_URL from the environment - the DELETE door I2 added, not a
  // PATCH carrying an empty string (the server's scheme rule refuses "" on purpose).
  revertPlatformPublicUrl: (): Promise<PlatformSettings> =>
    apiClient.delete<PlatformSettings>('/admin/platform-settings').then((r) => r.data),
}
