// ui/src/context/AuthContext.tsx
import { createContext, useContext, useState, ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import type { UserPayload } from '../types'

const TOKEN_KEY = 'ap_token'
export const RETURN_TO_KEY = 'returnTo'

// Exported so Login.tsx and AcceptInvite.tsx can decode a freshly-received access token
// into the payload useAuth().login() expects, without each keeping its own copy of this
// try/catch (they had, verbatim, including the comment below - now there is one to drift).
export function parseToken(token: string): UserPayload | null {
  try {
    return JSON.parse(atob(token.split('.')[1])) as UserPayload
  } catch {
    return null
  }
}

interface AuthState {
  token: string | null
  user: UserPayload | null
  login: (token: string, user: UserPayload) => void
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(TOKEN_KEY)
  )
  const [user, setUser] = useState<UserPayload | null>(() => {
    const t = localStorage.getItem(TOKEN_KEY)
    return t ? parseToken(t) : null
  })

  function login(newToken: string, newUser: UserPayload) {
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
    setUser(newUser)
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ token, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

// Guards every route that requires a session. PAM's notification emails are ordinary
// application URLs - a reviewer opening one with no live session must land back on that
// exact page after logging in, not on the dashboard home with no idea which of eighty-six
// scripts they were sent to. Storing the attempted path here, and consuming it in Login, is
// what makes that possible - sessionStorage rather than localStorage because the link should
// not still be "remembered" days later, after an unrelated later visit.
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth()
  const location = useLocation()
  if (!token) {
    // Read fresh, not captured once: in router.tsx this guard wraps AppLayout and every
    // nested child in a *single* instance that stays mounted across all in-app navigation
    // (matched at path '/' regardless of which :slug or tab is open underneath) - a value
    // captured only at first mount would freeze at wherever the app happened to be entered,
    // and quietly resurrect that stale destination on a later, unrelated sign-out.
    //
    // The one path deliberately not recorded is this component's own redirect target: when
    // it is mounted outside a matched Route (this file's own test renders it as a bare
    // child, so React Router never unmounts it on the next render the way a real route
    // match would), rendering <Navigate to="/login"> changes this component's own location
    // on the following render pass, and a fresh read would then overwrite the real
    // destination with "/login" itself.
    if (location.pathname !== '/login') {
      sessionStorage.setItem(RETURN_TO_KEY, location.pathname + location.search)
    }
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}
