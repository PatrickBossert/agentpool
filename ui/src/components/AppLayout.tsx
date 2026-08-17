// ui/src/components/AppLayout.tsx
import { useState, useEffect } from 'react'
import { NavLink, Outlet, useNavigate, useParams, Link } from 'react-router-dom'
import { Settings } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import NewProjectModal from './NewProjectModal'
import HeartbeatDot from './HeartbeatDot'
import type { Project } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'
import { SchedulerHeartbeatProvider } from '../context/SchedulerHeartbeatContext'

export default function AppLayout() {
  const { slug } = useParams<{ slug?: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)

  useEffect(() => {
    if (slug && user?.sub) {
      localStorage.setItem(`ap_last_project:${user.sub}`, slug)
    }
  }, [slug, user?.sub])

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
        { to: `/${slug}/team`, label: 'Team' },
        { to: `/${slug}/reviews`, label: 'Reviews', badge: pendingReviewCount > 0 ? pendingReviewCount : undefined },
        { to: `/${slug}/documents`, label: 'Documents' },
        { to: `/${slug}/runs`, label: 'Runs' },
      ]
    : [
        { to: '/', label: 'Dashboard', end: true },
      ]

  return (
    <SchedulerHeartbeatProvider>
    {/* h-screen, not min-h-screen, and this is the load-bearing half of the sidebar fix.
      *
      * With min-h-screen the shell's height stays *indefinite*: the browser resolves the
      * `flex-basis: 0%` that `flex-1` gives the row below against an auto height, a
      * percentage against an indefinite size behaves as `auto`, and the row is therefore
      * sized by its own content. Every "scroll inside me" class underneath then does
      * nothing, because nothing is ever taller than its box - measured in a real browser,
      * the aside came out 2423px tall inside a 600px viewport with `overflow-y-auto` on it
      * and a scrollHeight exactly equal to its clientHeight. `main`'s overflow-y-auto has
      * been inert for the same reason all along; the page has been the scroller.
      *
      * A definite 100vh is what makes the row 100vh minus the header, which is what lets
      * the aside and main each scroll their own contents. */}
    <div className="h-screen bg-gray-200 flex flex-col">
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
          <HeartbeatDot />
          <span className="text-xs text-gray-400">{user?.sub}</span>
          <Link
            to="/pitch"
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Pitch Deck
          </Link>
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
        {/* Sidebar
         *
         * Three nested pieces, and the nesting is the whole fix. The aside used to be a
         * single flex column with no overflow of its own, so a project list longer than the
         * viewport grew the sidebar rather than scrolling inside it - and `mt-auto` then
         * pinned Admin and "+ New Project" to the bottom of that grown column, which is
         * below the fold. Two people in one day concluded they had no rights to administer
         * users or create a project, because the controls that do both were the two things
         * pushed off screen, and nothing on screen suggested they existed. It gets strictly
         * worse with every project added.
         *
         * So: the aside is bounded (`min-h-0`, `overflow-hidden`) rather than free to grow,
         * the project list is the only part that scrolls (`flex-1 min-h-0 overflow-y-auto`),
         * and the controls sit in a `flex-shrink-0` footer that is a sibling of the
         * scroller rather than the last item inside it. `mt-auto` is gone: it pinned to the
         * bottom of the *content*, and what was wanted was the bottom of the *sidebar*. */}
        <aside className="w-44 bg-white border-r border-gray-200 flex flex-col flex-shrink-0 min-h-0 overflow-hidden">
          <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-1">
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
          </div>

          {/* Pinned footer - the controls that must never leave the viewport. */}
          <div className="flex-shrink-0 p-3 pt-0">
            {/* Admin nav */}
            {(user?.role === 'sysadmin' || user?.role === 'org_admin') && (
              <div className="pt-3 border-t border-gray-200">
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

            {/* New Project button. The border-t moves here for a caller with no Admin block,
             * so the footer is separated from the scrolling list either way. */}
            <div className={user?.role === 'sysadmin' || user?.role === 'org_admin' ? 'pt-3' : 'pt-3 border-t border-gray-200'}>
              <button
                onClick={() => setShowModal(true)}
                className="w-full text-xs text-gray-500 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded-lg px-2 py-1.5 transition-colors text-left"
              >
                + New Project
              </button>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden bg-gray-200 flex flex-col">
          <Outlet />
        </main>
      </div>

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
    </SchedulerHeartbeatProvider>
  )
}
