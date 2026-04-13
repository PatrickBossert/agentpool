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
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('ap_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)
