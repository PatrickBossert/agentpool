// ui/src/components/AppLayout.tsx
import { useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { Settings } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import NewProjectModal from './NewProjectModal'
import type { Project } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'

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
        { to: `/${slug}/schedule`, label: 'Schedule' },
        { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
        { to: `/${slug}/documents`, label: 'Documents' },
        { to: `/${slug}/runs`, label: 'Runs' },
      ]
    : [
        { to: '/', label: 'Dashboard', end: true },
      ]

  return (
    <div className="min-h-screen bg-gray-200 flex flex-col">
      {/* Top nav */}
      <header className="bg-white border-b border-gray-200 px-4 h-12 flex items-center gap-6">
        <img src={logoUrl} alt="TaskReimagination.ai" className="h-7 w-auto flex-shrink-0" />
        <nav className="flex gap-4 overflow-x-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm pb-0.5 border-b-2 transition-colors flex items-center gap-1.5 whitespace-nowrap ${
                  isActive
                    ? 'text-brand border-brand'
                    : 'text-gray-500 border-transparent hover:text-gray-800'
                }`
              }
            >
              {item.label}
              {item.badge !== undefined && (
                <span className="bg-amber-500 text-white text-xs font-bold rounded-full px-1.5 leading-4 min-w-[18px] text-center">
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 flex-shrink-0">
          {slug && (
            <>
              <a
                href="http://localhost:8001"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Chainlit ↗
              </a>
              <a
                href="http://localhost:5678"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                n8n ↗
              </a>
            </>
          )}
          <span className="text-xs text-gray-400">{user?.sub}</span>
          <a
            href="/dashboard/data-architecture"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Data &amp; Privacy ↗
          </a>
          <button onClick={handleLogout} className="text-xs text-gray-400 hover:text-gray-600">
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-44 bg-white border-r border-gray-200 p-3 flex flex-col gap-1 flex-shrink-0">
          <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">
            Projects
          </p>
          {projects.map((p) => (
            <div key={p.slug} className="flex items-center gap-1">
              <button
                onClick={() => navigate(`/${p.slug}`)}
                className={`flex-1 text-left text-sm px-2 py-1.5 rounded-lg transition-colors ${
                  slug === p.slug
                    ? 'bg-brand/10 text-teal-700 font-medium'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                {p.slug}
              </button>
              {slug === p.slug && (
                <button
                  onClick={() => navigate(`/${p.slug}/settings`)}
                  className="text-gray-400 hover:text-gray-600 text-sm px-1 flex-shrink-0"
                  title="Settings"
                >
                  <Settings size={14} />
                </button>
              )}
            </div>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-gray-400 px-2">No projects yet</p>
          )}

          {/* Admin nav */}
          {(user?.role === 'sysadmin' || user?.role === 'org_admin') && (
            <div className="mt-auto pt-3 border-t border-gray-200">
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2 px-2">
                Admin
              </p>
              {user.role === 'sysadmin' && (
                <button
                  onClick={() => navigate('/admin')}
                  className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                >
                  Admin Panel
                </button>
              )}
              {user.role === 'org_admin' && (
                <button
                  onClick={() => navigate('/org')}
                  className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                >
                  Team
                </button>
              )}
              <button
                onClick={() => navigate('/admin/users')}
                className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              >
                Users
              </button>
            </div>
          )}

          {/* New Project button */}
          <div className={user?.role === 'sysadmin' || user?.role === 'org_admin' ? 'pt-3' : 'mt-auto pt-3'}>
            <button
              onClick={() => setShowModal(true)}
              className="w-full text-xs text-gray-500 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded-lg px-2 py-1.5 transition-colors text-left"
            >
              + New Project
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden bg-gray-200 flex flex-col">
          <Outlet />
        </main>
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
  )
}
