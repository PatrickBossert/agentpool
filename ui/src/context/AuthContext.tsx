// ui/src/context/AuthContext.tsx
import { createContext, useContext, useState, ReactNode } from 'react'
import type { UserPayload } from '../types'

const TOKEN_KEY = 'ap_token'

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
