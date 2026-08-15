// ui/src/context/AuthContext.tsx
import { createContext, useContext, useRef, useState, ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import type { UserPayload } from '../types'

const TOKEN_KEY = 'ap_token'
export const RETURN_TO_KEY = 'returnTo'

function parseToken(token: string): UserPayload | null {
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
  // Captured once, on first render, rather than read fresh on every render: rendering
  // <Navigate> changes this component's own location on the next pass (visible when it is
  // rendered outside a matched Route, as in this file's own test), and a fresh read then
  // would overwrite the real destination with "/login" itself.
  const attemptedPath = useRef(location.pathname + location.search)
  if (!token) {
    sessionStorage.setItem(RETURN_TO_KEY, attemptedPath.current)
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}
