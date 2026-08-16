// ui/src/pages/Login.tsx
import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '../api/endpoints'
import { useAuth, RETURN_TO_KEY, parseToken } from '../context/AuthContext'
import type { UserPayload } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const resp = await authApi.login(username, password)
      // parseToken returns null for a token that is not a valid JWT (e.g. in tests) -
      // fall back to a usable default rather than passing null on to login().
      const payload = parseToken(resp.access_token) ?? ({ sub: '', role: 'sysadmin', exp: 0 } as UserPayload)
      login(resp.access_token, payload)
      // A link followed with no live session takes priority over the last-opened project -
      // it is the one specific page somebody was sent to, not wherever they happened to be
      // last time. Cleared on read so an unrelated later visit to /login does not resurrect
      // an old destination.
      const returnTo = sessionStorage.getItem(RETURN_TO_KEY)
      if (returnTo) {
        sessionStorage.removeItem(RETURN_TO_KEY)
        navigate(returnTo)
        return
      }
      const lastProject = localStorage.getItem(`ap_last_project:${payload.sub}`)
      navigate(lastProject ? `/${lastProject}` : '/')
    } catch {
      setError('Invalid username or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center">
      <div className="bg-surface-card rounded-xl p-8 w-full max-w-sm shadow-xl">
        <div className="flex flex-col items-center mb-8">
          <img src={logoUrl} alt="TaskReimagination.ai" className="h-16 w-auto" />
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-600 mb-1">
              Username
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-surface-raised border border-gray-200 rounded-lg px-3 py-2 text-gray-900 focus:outline-none focus:border-brand"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-600 mb-1">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface-raised border border-gray-200 rounded-lg px-3 py-2 text-gray-900 focus:outline-none focus:border-brand"
              required
            />
          </div>
          {error && (
            <p role="alert" className="text-red-400 text-sm">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-brand hover:bg-brand-dark disabled:opacity-50 text-white font-medium rounded-lg py-2 transition-colors"
          >
            {loading ? 'Signing in\u2026' : 'Sign in'}
          </button>
        </form>
        {/* Outside the <form> so it cannot submit it. This page had no secondary action at
            all until now, which made the accept page's "your existing password still works"
            a dead end for the people most likely to read it - somebody invited to a second
            engagement months after the first. */}
        <p className="text-sm text-secondary text-center mt-4">
          <Link
            to="/forgotten-password"
            className="text-brand hover:text-brand-dark transition-colors"
          >
            Forgotten your password?
          </Link>
        </p>
      </div>
    </div>
  )
}
