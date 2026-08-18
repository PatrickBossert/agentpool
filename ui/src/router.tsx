// ui/src/router.tsx
import { createBrowserRouter, Navigate, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth, ProtectedRoute } from './context/AuthContext'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'
import AcceptInvite from './pages/AcceptInvite'
import ForgottenPassword from './pages/ForgottenPassword'
import ResetPassword from './pages/ResetPassword'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
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
import VoiceInterview from './pages/VoiceInterview'
import Templates from './pages/Templates'
import Report from './pages/Report'
import PamReport from './pages/PamReport'
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

type Role = 'sysadmin' | 'org_admin' | 'reviewer'

function AdminRoute({ children, allow }: { children: ReactNode; allow: Role[] }) {
  const { token, user } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (!user || !allow.includes(user.role as Role)) return <Navigate to="/" replace />
  return <>{children}</>
}

// The value chain page was retired - its Structure tab lives in Alex's Output tab now.
// Notification emails already sent and bookmarks made before the retirement still point at
// this route, so it redirects rather than 404s, landing on the same place a fresh
// notification link would: Alex selected, on his Output tab.
function ValueChainRedirect() {
  const { slug } = useParams<{ slug: string }>()
  return <Navigate to={`/${slug}?crew=discovery_mapping&tab=output`} replace />
}

// The assignment page was retired - the mapping is configuration, and it lives in Jordan's
// Setup tab now rather than on a page reachable only from a run parked in
// `awaiting_assignment`. Runs.tsx links straight to the tab, but bookmarks and the links in
// runs already listed still point here, so this redirects rather than 404s.
function AssignmentRedirect() {
  const { slug } = useParams<{ slug: string }>()
  return <Navigate to={`/${slug}?crew=stakeholder_management&tab=setup`} replace />
}

// The route array, exported so it can be mounted inside a MemoryRouter/createMemoryRouter in
// tests - createBrowserRouter itself cannot be. `router` below is built from this and stays
// the only thing anything outside this file imports.
export const routes = [
  {
    path: '/login',
    element: <Login />,
  },
  {
    // Somebody accepting an invite has no session yet - a route behind ProtectedRoute would
    // bounce them to login, and they cannot log in, because setting the password is what
    // they came here to do. Deliberately outside the guard, like /login itself.
    path: '/accept-invite/:token',
    element: <AcceptInvite />,
  },
  {
    // Both reset routes sit outside the guard for the same reason /accept-invite does:
    // somebody who has forgotten their password has no session and cannot get one until
    // this is done.
    path: '/forgotten-password',
    element: <ForgottenPassword />,
  },
  {
    path: '/reset-password/:token',
    element: <ResetPassword />,
  },
  {
    path: '/interview/:sessionToken',
    element: <VoiceInterview />,
  },
  {
    // Administrator-only, and it was not always. This route sat outside every guard - public
    // by omission rather than by design: nothing public has ever linked to it, its one link
    // lives in the header inside ProtectedRoute, and /architecture beside it was already
    // guarded. The page now names an engagement, resolves that engagement's processing mode,
    // and enumerates what its agents reach and read, so leaving it open was handing an
    // unauthenticated reader the shape of the client's data flows.
    //
    // AdminRoute rather than ProtectedRoute: the audience is whoever answers for the
    // deployment. It redirects to /login without a session and to / with a session that is
    // not an administrator's, and the endpoint behind the page refuses the same callers -
    // guarding the route alone would only have moved the omission.
    //
    // Two entries for one component. The bare path is the header link's destination and
    // whatever bookmarks exist, and it offers the engagements; the slug is the report. A
    // single optional-segment path would collapse them, but it would also make "no project
    // chosen" and "this project" the same route, which is the distinction the page turns on.
    path: '/data-architecture',
    element: (
      <AdminRoute allow={['sysadmin', 'org_admin']}>
        <DataArchitecture />
      </AdminRoute>
    ),
  },
  {
    path: '/data-architecture/:slug',
    element: (
      <AdminRoute allow={['sysadmin', 'org_admin']}>
        <DataArchitecture />
      </AdminRoute>
    ),
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
    path: '/:slug/pam-report',
    element: (
      <ProtectedRoute>
        <PamReport />
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
      { path: ':slug/value-chain', element: <ValueChainRedirect /> },
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
      { path: ':slug/assignment', element: <AssignmentRedirect /> },
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
]

export const router = createBrowserRouter(routes, { basename: '/dashboard' })
