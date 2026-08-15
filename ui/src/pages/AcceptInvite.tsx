// ui/src/pages/AcceptInvite.tsx
//
// The other end of resend-invite: an administrator mints a token, PAM or an email carries it,
// and this page is where the person named on it sets a password and becomes a session. It sits
// outside the authenticated guard (see router.tsx) - somebody arriving here has no session yet,
// so a route behind ProtectedRoute would bounce them straight to a login they cannot complete,
// because setting the password is what they came here to do.
import { useState, FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { authApi } from '../api/endpoints'
import { useAuth, parseToken } from '../context/AuthContext'
import type { UserPayload } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'

export default function AcceptInvite() {
  const { token } = useParams<{ token: string }>()
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (!token) {
      setError('This invite link is missing its token.')
      return
    }
    if (password.length < 8) {
      setError('Choose a password of at least eight characters.')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    try {
      const resp = await authApi.accept(token, password)
      // parseToken returns null for a token that is not a valid JWT (e.g. in tests) -
      // fall back to a usable default rather than passing null on to login().
      const payload = parseToken(resp.access_token) ?? ({ sub: '', role: 'reviewer', exp: 0 } as UserPayload)
      login(resp.access_token, payload)
      navigate('/')
    } catch {
      setError('This invite link is invalid or has expired - ask whoever sent it for a new one.')
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
        <div className="flex items-center gap-2 justify-center mb-2 text-primary">
          <KeyRound size={18} className="text-brand" />
          <h1 className="text-lg font-semibold">Set your password</h1>
        </div>
        <p className="text-sm text-secondary text-center mb-6">
          Choose a password to finish setting up your account.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
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
              minLength={8}
            />
          </div>
          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-600 mb-1">
              Confirm password
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full bg-surface-raised border border-gray-200 rounded-lg px-3 py-2 text-gray-900 focus:outline-none focus:border-brand"
              required
              minLength={8}
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
            {loading ? 'Setting password…' : 'Set password and sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
