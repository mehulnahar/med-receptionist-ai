import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30_000, // 30 seconds — prevent hung requests from blocking UI forever
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Send httpOnly cookies (refresh_token) with requests
})

// ---------------------------------------------------------------------------
// In-memory token store — NOT in localStorage (XSS-safe)
// ---------------------------------------------------------------------------
let _accessToken = null

export function setAccessToken(token) {
  _accessToken = token
}

export function getAccessToken() {
  return _accessToken
}

export function clearAccessToken() {
  _accessToken = null
}

// Request interceptor — attach JWT from in-memory store
api.interceptors.request.use(
  (config) => {
    if (_accessToken) {
      config.headers.Authorization = `Bearer ${_accessToken}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ---------------------------------------------------------------------------
// Response interceptor — auto-refresh access token on 401
// ---------------------------------------------------------------------------
let isRefreshing = false
let failedQueue = []

function processQueue(error, token = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error)
    } else {
      resolve(token)
    }
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config || {}

    // Network errors (no response at all) — skip refresh logic entirely
    if (!error.response) {
      return Promise.reject(error)
    }

    // Only try refresh on 401 for non-auth endpoints (avoid infinite loops)
    if (
      error.response.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/login') &&
      !originalRequest.url?.includes('/auth/refresh')
    ) {
      // If another request is already refreshing, queue this one
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return api(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        // Refresh token is sent automatically via httpOnly cookie.
        // IMPORTANT: Always use relative URL so the request goes through
        // the nginx proxy (same origin as the cookie domain).
        const { data } = await axios.post(
          '/api/auth/refresh',
          {},
          {
            headers: { 'Content-Type': 'application/json' },
            withCredentials: true,
          }
        )

        const newToken = data.access_token
        _accessToken = newToken

        originalRequest.headers.Authorization = `Bearer ${newToken}`

        processQueue(null, newToken)
        return api(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        // Refresh failed — clear token and redirect to login
        _accessToken = null
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // No refresh possible — clear and redirect on 401
    if (error.response?.status === 401) {
      _accessToken = null
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  }
)

export default api
