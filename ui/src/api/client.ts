// ui/src/api/client.ts
import axios from 'axios'

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

apiClient.interceptors.response.use(
  (response) => {
    // The session rolls forward on every authenticated request (api/main.py's
    // roll_session middleware) - store whatever the server just re-issued so the thirtieth
    // day never arrives as a cliff for somebody mid-review. Header names are lower-cased by
    // axios/fetch regardless of how the server wrote them.
    const refreshed = response.headers['x-refreshed-token']
    if (refreshed) {
      localStorage.setItem('ap_token', refreshed)
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('ap_token')
      window.location.href = '/dashboard/login'
    }
    return Promise.reject(error)
  }
)
