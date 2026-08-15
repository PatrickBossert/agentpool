// ui/src/api/client.ts
import axios, { AxiosResponse } from 'axios'
import { RETURN_TO_KEY } from '../context/AuthContext'

export const API_BASE = 'http://localhost:8000'

export const apiClient = axios.create({ baseURL: API_BASE })

// Inject stored token on every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('ap_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// The session rolls forward on every authenticated request (api/main.py's roll_session
// middleware) - store whatever the server just re-issued so the thirtieth day never arrives
// as a cliff for somebody mid-review. Header names are lower-cased by axios/fetch regardless
// of how the server wrote them.
//
// Exported, and kept as a standalone function rather than inlined into
// interceptors.response.use, so a test can drive it directly against a fake response - this
// is the read half of the round trip whose write half is
// tests/test_rolling_session.py's header assertion; a class of bug (a middleware emitting a
// header that is truthy but not a usable token) is invisible unless both halves are proven.
export function storeRefreshedToken(response: AxiosResponse): AxiosResponse {
  const refreshed = response.headers['x-refreshed-token']
  if (refreshed) {
    localStorage.setItem('ap_token', refreshed)
  }
  return response
}

// A session can end in two ways, and only one of them went through ProtectedRoute. A cold
// click on a PAM link with no session at all is a route match the guard sees, and it records
// the destination. A session expiring mid-read is not: this interceptor clears the token and
// changes window.location itself, which unloads the app before any React guard renders - so
// without the write below the destination was simply lost, and the design's headline
// scenario ("a reviewer clicking a link to one script three weeks later") only survived in
// the case where the reviewer had not yet started reading.
//
// Same key the guard writes and Login reads, imported rather than repeated, so the three
// cannot drift apart. window.location.pathname, not React Router's location: this code runs
// outside the router, and the real URL carries the '/dashboard' basename that router.tsx
// strips - which Login's navigate() adds back, so the stored value must be basename-free.
const BASENAME = '/dashboard'

apiClient.interceptors.response.use(
  storeRefreshedToken,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('ap_token')
      const { pathname, search } = window.location
      const destination = (pathname.startsWith(BASENAME) ? pathname.slice(BASENAME.length) : pathname) || '/'
      if (destination !== '/login') {
        sessionStorage.setItem(RETURN_TO_KEY, destination + search)
      }
      window.location.href = `${BASENAME}/login`
    }
    return Promise.reject(error)
  }
)
