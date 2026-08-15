// ui/src/api/client.ts
import axios, { AxiosResponse } from 'axios'

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

apiClient.interceptors.response.use(
  storeRefreshedToken,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('ap_token')
      window.location.href = '/dashboard/login'
    }
    return Promise.reject(error)
  }
)
