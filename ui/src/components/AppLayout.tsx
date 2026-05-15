// ui/src/components/AppLayout.tsx
import { useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import NewProjectModal from './NewProjectModal'
import type { Project } from '../types'

export default function AppLayout() {
  const { slug } = useParams<{ slug?: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    refetchInterval: 10_000,
  })

  const { data: reviews = [] } = useQuery({
    queryKey: ['reviews', slug],
    queryFn: () => projectsApi.listReviews(slug!),
    enabled: !!slug,
    refetchInterval: 5000,
  })
  const pendingReviewCount = reviews.length

  function handleLogout() {
    logout()
    navigate('/login')
  }

  type NavItem = { to: string; label: string; end?: boolean; badge?: number }

  const navItems: NavItem[] = slug
    ? [
        { to: `/${slug}`, label: 'Dashboard', end: true },
        { to: `/${slug}/value-chain`, label: 'Value Chain' },
        { to: `/${slug}/discovery`, label: 'Discovery' },
        { to: `/${slug}/value-propositions`, label: 'Value Propositions' },
        { to: `/${slug}/roadmap`, label: 'Roadmap' },
        { to: `/${slug}/business-plan`, label: 'Business Plan' },
        { to: `/${slug}/stakeholders`, label: 'Stakeholders' },
        { to: `/${slug}/templates`, label: 'Templates' },
        { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
        { to: `/${slug}/runs`, label: 'Runs' },
        { to: `/${slug}/documents`, label: 'Documents' },
      ]
    : [{ to: '/', label: 'Dashboard', end: true }]

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Top nav */}
      <header className="bg-surface-raised border-b border-slate-800 px-4 h-12 flex items-center gap-6">
        <span className="font-bold text-brand-light text-sm tracking-wide">FutureMomentum</span>
        <nav className="flex gap-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm pb-0.5 border-b-2 transition-colors flex items-center gap-1.5 ${
                  isActive
                    ? 'text-brand border-brand'
                    : 'text-slate-400 border-transparent hover:text-slate-200'
                }`
              }
            >
              {item.label}
              {item.badge !== undefined && (
                <span className="bg-amber-500 text-slate-900 text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {slug && (
            <>
              <a
                href="http://localhost:8001"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                Chainlit ↗
              </a>
              <a
                href="http://localhost:5678"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-300"
              >
                n8n ↗
              </a>
            </>
          )}
          <span className="text-xs text-slate-500">{user?.sub}</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-300">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-44 bg-surface-raised border-r border-slate-800 p-3 flex flex-col gap-1">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-2">
            Projects
          </p>
          {projects.map((p) => (
            <div key={p.slug} className="flex items-center gap-1">
              <button
                onClick={() => navigate(`/${p.slug}`)}
                className={`flex-1 text-left text-sm px-2 py-1.5 rounded transition-colors ${
                  slug === p.slug
                    ? 'bg-brand/10 text-brand'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {p.slug}
              </button>
              {slug === p.slug && (
                <button
                  onClick={() => navigate(`/${p.slug}/settings`)}
                  className="text-slate-500 hover:text-slate-300 text-sm px-1 flex-shrink-0"
                  title="Settings"
                >
                  ⚙
                </button>
              )}
            </div>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-slate-600 px-2">No projects yet</p>
          )}
          {/* New Project button — pinned to bottom of sidebar */}
          <div className="mt-auto pt-3">
            <button
              onClick={() => setShowModal(true)}
              className="w-full text-xs text-slate-500 hover:text-slate-200 border border-slate-700 hover:border-slate-500 rounded px-2 py-1.5 transition-colors text-left"
            >
              + New Project
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
  )
}
