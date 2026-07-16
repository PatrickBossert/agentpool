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
import PitchDeck from './pages/PitchDeck'
import AdminDashboard from './pages/AdminDashboard'
import AdminSkills from './pages/AdminSkills'
import OrgDetail from './pages/OrgDetail'
import UserList from './pages/UserList'
import UserForm from './pages/UserForm'
import OrgPanel from './pages/OrgPanel'
import Team from './pages/Team'
import Schedule from './pages/Schedule'
import DataArchitecture from './pages/DataArchitecture'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

type Role = 'sysadmin' | 'org_admin' | 'reviewer'

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
    path: '/data-architecture',
    element: <DataArchitecture />,
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
    path: '/pitch',
    element: (
      <ProtectedRoute>
        <PitchDeck />
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
      { path: ':slug/schedule', element: <Schedule /> },
      { path: ':slug/team', element: <Team /> },
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
        path: 'admin/skills',
        element: (
          <AdminRoute allow={['sysadmin']}>
            <AdminSkills />
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
