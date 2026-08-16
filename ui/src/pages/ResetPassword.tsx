// ui/src/pages/ResetPassword.tsx
//
// Where a reset link lands. Modelled on AcceptInvite - the same token-in-URL shape, and
// outside ProtectedRoute for the same reason: somebody resetting a password has no session,
// so a guarded route would bounce them to a login they cannot complete, because choosing the
// password is what they came here to do.
//
// It differs from AcceptInvite in the one way that matters: redemption here has a single
// outcome. A reset token can only have been asked for by the account owner, to their own
// address, so the server always returns a real session (api/routers/invites.py) and there is
// no already-registered branch to render. A refusal is a genuine refusal - the token is
// spent, expired, or invented - and is shown as an error with a way to ask for another.
import { useState, FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { authApi } from '../api/endpoints'
import { useAuth, parseToken } from '../context/AuthContext'
import type { UserPayload } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'

export default function ResetPassword() {
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
      setError('This reset link is missing its token.')
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
      const resp = await authApi.resetPassword(token, password)
      // parseToken returns null for a token that is not a valid JWT (e.g. in tests) - fall
      // back to a usable default rather than passing null on to login().
      const payload =
        parseToken(resp.access_token) ?? ({ sub: '', role: 'reviewer', exp: 0 } as UserPayload)
      login(resp.access_token, payload)
      navigate('/')
    } catch {
      setError(
        'This reset link is invalid, has expired, or has already been used - ask for a new one.',
      )
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
          <h1 className="text-lg font-semibold">Choose a new password</h1>
        </div>
        <p className="text-sm text-secondary text-center mb-6">
          This replaces the password on your account, and signs you in straight away.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-600 mb-1">
              New password
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
            <label
              htmlFor="confirmPassword"
              className="block text-sm font-medium text-gray-600 mb-1"
            >
              Confirm new password
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
        {/* Outside the <form> so it cannot submit it - a submission here would spend the
            single-use token against a password nobody chose. */}
        <p className="text-sm text-secondary text-center mt-4">
          <Link
            to="/forgotten-password"
            className="text-brand hover:text-brand-dark transition-colors"
          >
            Ask for a new link
          </Link>
        </p>
      </div>
    </div>
  )
}
