// ui/src/pages/AcceptInvite.tsx
//
// The other end of resend-invite: an administrator mints a token, PAM or an email carries it,
// and this page is where the person named on it sets a password and becomes a session. It sits
// outside the authenticated guard (see router.tsx) - somebody arriving here has no session yet,
// so a route behind ProtectedRoute would bounce them straight to a login they cannot complete,
// because setting the password is what they came here to do.
//
// Redemption has two outcomes and the form cannot tell which one it is heading for. If the
// email already has a login, the server grants the membership and refuses the session, and the
// password typed here is discarded - deliberately, since otherwise anybody able to add your
// address as a stakeholder could overwrite your password. The page's job is to say so before
// submission and unmissably after it; it must never ask which case this is in advance, because
// an answer to that question is an account-existence oracle for any administrator with a
// project. Both of those constraints are load-bearing - see the comments where each lands.
import { useState, FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CheckCircle, KeyRound } from 'lucide-react'
import { authApi } from '../api/endpoints'
import { useAuth, parseToken } from '../context/AuthContext'
import type { UserPayload } from '../types'
import logoUrl from '../assets/TR_Logo_strapiline.png'

export default function AcceptInvite() {
  const { token } = useParams<{ token: string }>()
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Distinct from `error`: this is not a failure, just a different, non-session outcome -
  // the invite named an email that already has a login, so only the membership was granted
  // (see api/routers/invites.py's CRITICAL note). Styling it as an error would tell someone
  // whose access genuinely was granted that something went wrong.
  const [alreadyRegisteredMessage, setAlreadyRegisteredMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setAlreadyRegisteredMessage(null)

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
      if (!resp.access_token) {
        // A membership was granted, but this email already has a login - accepting an
        // invite for a known email is a membership grant, not an authentication event.
        // Sending them to /login (rather than signing them in) is the point, not a
        // fallback: only the account's own password may authenticate as that account.
        //
        // The wording is the server's, rendered verbatim, so there is exactly one place
        // this outcome is worded (_already_registered_response in api/routers/invites.py).
        // The literal below is only for a response that carried no detail at all; keep it
        // saying the same thing, and change the server's copy rather than this.
        setAlreadyRegisteredMessage(
          resp.detail ??
            'An account already exists for this email address, so this invite granted ' +
            'your access only. The password you just entered was not set - your existing ' +
            'password still works, and it is the one to sign in with.',
        )
        return
      }
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
        {alreadyRegisteredMessage ? (
          <>
            <div className="flex items-center gap-2 justify-center mb-2 text-primary">
              <CheckCircle size={18} className="text-brand" />
              <h1 className="text-lg font-semibold">Access granted</h1>
            </div>
            {/* Deliberately a callout rather than the muted single line this used to be.
                Somebody who has just chosen a password twice arrives at this panel reading
                "Access granted" and nothing else; the part that matters - that the password
                was discarded - has to be the part that is hard to skip past. The password
                fields are unmounted rather than disabled or cleared: nothing renders the
                form again from here (alreadyRegisteredMessage is only reset inside
                handleSubmit, which only the form can call), so an unmounted field cannot be
                edited or resubmitted, and blanking state nothing can reach would be a
                gesture rather than a safeguard. */}
            <div className="bg-surface-raised border border-brand rounded-lg p-4 mb-6">
              <p className="text-sm text-primary">{alreadyRegisteredMessage}</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="w-full bg-brand hover:bg-brand-dark text-white font-medium rounded-lg py-2 transition-colors"
            >
              Go to sign in
            </button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 justify-center mb-2 text-primary">
              <KeyRound size={18} className="text-brand" />
              <h1 className="text-lg font-semibold">Set your password</h1>
            </div>
            <p className="text-sm text-secondary text-center mb-4">
              Choose a password to finish setting up your account.
            </p>
            {/* Stated up front because the page cannot find out which case this is until
                after the token is redeemed, and must not try: an administrator can mint an
                invite for any address on their own project, so anything that answered
                "does this email have an account?" before submission would be an
                account-existence oracle. The sentence is therefore generic - true for
                every visitor, and revealing nothing about this particular address. */}
            <p className="text-sm text-muted text-center mb-6">
              If an account already exists for this email address, this invite grants your
              access only - the password you choose here will not be used, and your current
              password stays as it is.
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
            {/* The door out for somebody who knows they already have an account. Without it
                the only way off this page is to invent a password, submit it, and be told
                it was discarded. Secondary to the main action, and outside the <form> so it
                cannot submit it. */}
            <p className="text-sm text-secondary text-center mt-4">
              <Link to="/login" className="text-brand hover:text-brand-dark transition-colors">
                Sign in instead
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
