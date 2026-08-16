// ui/src/pages/ForgottenPassword.tsx
//
// The self-service door onto a reset. Outside ProtectedRoute for the same reason
// AcceptInvite is: somebody who cannot remember their password cannot sign in to ask for a
// new one.
//
// The one rule this page exists to keep: it must never tell the visitor whether the address
// they typed has an account. POST /auth/reset-request answers 204 either way, deliberately -
// an unauthenticated door that distinguished the two would let anybody enumerate who holds a
// login here. So the acknowledgement below is conditional in its wording ("if that address
// has an account") and unconditional in when it appears, including when the request itself
// fails. That last part is not defensive coding: a page that showed an error on rejection
// and an acknowledgement on success would hand back exactly the distinction the 204 removes
// the moment the server ever started refusing anything.
//
// Nothing here can deliver the link yet either - FROM_EMAIL names a domain Resend has not
// verified - which is why the acknowledgement also names the way to get one today. The copy
// stays true once mail is wired; only the last line comes out.
import { useState, FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { KeyRound, MailCheck } from 'lucide-react'
import { authApi } from '../api/endpoints'
import logoUrl from '../assets/TR_Logo_strapiline.png'

export default function ForgottenPassword() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await authApi.requestReset(email)
    } catch {
      // Deliberately swallowed - see the note at the top of this file. There is no outcome
      // to report, because the server does not report one, and inventing a visible
      // difference here would undo the property the endpoint is built around.
    } finally {
      setLoading(false)
      setSubmitted(true)
    }
  }

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center">
      <div className="bg-surface-card rounded-xl p-8 w-full max-w-sm shadow-xl">
        <div className="flex flex-col items-center mb-8">
          <img src={logoUrl} alt="TaskReimagination.ai" className="h-16 w-auto" />
        </div>
        {submitted ? (
          <>
            <div className="flex items-center gap-2 justify-center mb-2 text-primary">
              <MailCheck size={18} className="text-brand" />
              <h1 className="text-lg font-semibold">Request received</h1>
            </div>
            <div className="bg-surface-raised border border-brand rounded-lg p-4 mb-6">
              <p className="text-sm text-primary">
                If that address has an account, a reset link is on its way. It is valid for
                seven days and can be used once.
              </p>
            </div>
            <p className="text-sm text-secondary mb-6">
              Nothing arrived? Ask your administrator to issue a reset link for you - they can
              do it from the Users page and send it to you directly.
            </p>
            <Link
              to="/login"
              className="block w-full bg-brand hover:bg-brand-dark text-white font-medium rounded-lg py-2 text-center transition-colors"
            >
              Back to sign in
            </Link>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 justify-center mb-2 text-primary">
              <KeyRound size={18} className="text-brand" />
              <h1 className="text-lg font-semibold">Reset your password</h1>
            </div>
            <p className="text-sm text-secondary text-center mb-6">
              Enter the email address you sign in with and we will send you a link to choose
              a new password.
            </p>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-600 mb-1">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-surface-raised border border-gray-200 rounded-lg px-3 py-2 text-gray-900 focus:outline-none focus:border-brand"
                  required
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-brand hover:bg-brand-dark disabled:opacity-50 text-white font-medium rounded-lg py-2 transition-colors"
              >
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
            {/* Outside the <form> so it cannot submit it. */}
            <p className="text-sm text-secondary text-center mt-4">
              <Link to="/login" className="text-brand hover:text-brand-dark transition-colors">
                Back to sign in
              </Link>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
