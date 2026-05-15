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
