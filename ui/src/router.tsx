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

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
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
      { path: ':slug/value-chain', element: <ValueChain /> },
      { path: ':slug/roadmap', element: <Roadmap /> },
      { path: ':slug/stakeholders', element: <Stakeholders /> },
      { path: ':slug/stakeholders/new', element: <StakeholderForm /> },
      { path: ':slug/stakeholders/:id/edit', element: <StakeholderForm /> },
      { path: ':slug/business-plan', element: <BusinessPlan /> },
      { path: ':slug/reviews', element: <Reviews /> },
      { path: ':slug/runs', element: <Runs /> },
      { path: ':slug/documents', element: <Documents /> },
      { path: ':slug/runs/:runId', element: <RunDetail /> },
      { path: ':slug/settings', element: <Settings /> },
    ],
  },
])
