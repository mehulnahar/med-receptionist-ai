import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import api, { setAccessToken, getAccessToken, clearAccessToken } from '../services/api'

const AuthContext = createContext(null)

/**
 * AuthProvider — wraps the app and provides authentication state + actions.
 *
 * Security: Access tokens are kept in-memory only (not localStorage) to prevent
 * XSS-based token theft. Refresh tokens are stored in httpOnly secure cookies
 * set by the backend — not accessible to JavaScript at all.
 *
 * Trade-off: Refreshing the tab loses the access token, but the auto-refresh
 * interceptor in api.js will silently obtain a new one via the cookie.
 *
 * State shape:
 *   user     — { id, email, role, practice_id, first_name, last_name } | null
 *   token    — JWT access token string | null
 *   loading  — true while initial session restore or login is in flight
 *   error    — most recent auth error message string | null
 *
 * Exposed via useAuth():
 *   user, token, loading, error, login(), logout(), clearError()
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  /**
   * Fetch the current user profile from the API.
   * Returns the user object on success, or null on failure.
   * On 429 (rate limit), retries up to 3 times with exponential backoff.
   */
  const fetchUser = useCallback(async (retries = 3, signal) => {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await api.get('/auth/me', { signal })
        const userData = response.data
        // Backend returns a single "name" field — split into first/last for the UI
        const nameParts = (userData.name || '').trim().split(/\s+/)
        const first_name = nameParts[0] || ''
        const last_name = nameParts.slice(1).join(' ') || ''
        setUser({
          id: userData.id,
          email: userData.email,
          role: userData.role,
          practice_id: userData.practice_id,
          name: userData.name,
          first_name,
          last_name,
          password_change_required: userData.password_change_required || false,
        })
        return userData
      } catch (err) {
        // If the request was intentionally aborted, bail out silently
        if (err.name === 'CanceledError' || signal?.aborted) {
          return null
        }
        // On 429 (rate limit), retry after a delay instead of treating as auth failure
        if (err.response && err.response.status === 429 && attempt < retries) {
          const delay = Math.min(2000 * Math.pow(2, attempt), 10000)
          await new Promise(resolve => setTimeout(resolve, delay))
          continue
        }
        if (err.response && err.response.status === 401) {
          clearAccessToken()
          setToken(null)
          setUser(null)
        }
        return null
      }
    }
    return null
  }, [])

  /**
   * On mount: try to restore the session by refreshing the access token
   * via the httpOnly refresh cookie. If the cookie exists and is valid,
   * the backend will return a new access token.
   */
  useEffect(() => {
    const abortController = new AbortController()
    let cancelled = false

    const restoreSession = async () => {
      try {
        // Try to get a new access token using the refresh cookie.
        // Use absolute path so it goes through the nginx proxy (same origin
        // as the cookie domain) instead of directly to the backend baseURL.
        const { data } = await axios.post('/api/auth/refresh', {}, {
          headers: { 'Content-Type': 'application/json' },
          withCredentials: true,
          signal: abortController.signal,
        })
        if (data.access_token) {
          setAccessToken(data.access_token)
          setToken(data.access_token)

          const userData = await fetchUser(3, abortController.signal)
          if (!cancelled && !userData) {
            clearAccessToken()
            setToken(null)
            setUser(null)
          }
        }
      } catch (err) {
        // Ignore abort errors
        if (err?.name === 'CanceledError' || abortController.signal.aborted) return

        // Only clear auth state on definitive auth failures (401/403).
        // Network errors or 5xx mean the server is temporarily unreachable —
        // don't log the user out for transient issues.
        const status = err?.response?.status
        const isAuthFailure = status === 401 || status === 403
        if (!cancelled && isAuthFailure) {
          clearAccessToken()
          setToken(null)
          setUser(null)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    restoreSession()

    return () => {
      cancelled = true
      abortController.abort()
    }
  }, [fetchUser])

  /**
   * login(email, password)
   *
   * 1. POST /api/auth/login -> receive { access_token, token_type, user }
   *    (refresh_token is set as httpOnly cookie by the backend)
   * 2. Store access_token in memory only
   * 3. Fetch user profile from /api/auth/me
   */
  const login = useCallback(async (email, password) => {
    setLoading(true)
    setError(null)

    try {
      const response = await api.post('/auth/login', { email, password })
      const { access_token } = response.data

      // Store access token in memory only (NOT localStorage)
      setAccessToken(access_token)
      setToken(access_token)

      // Now fetch the full user profile
      const userData = await fetchUser()

      if (!userData) {
        throw new Error('Failed to load user profile after login.')
      }

      setLoading(false)
      return userData
    } catch (err) {
      // Build a human-readable error message
      let message = 'An unexpected error occurred. Please try again.'

      if (err.response) {
        const data = err.response.data
        if (typeof data === 'string') {
          message = data
        } else if (data?.detail) {
          message = typeof data.detail === 'string'
            ? data.detail
            : 'Invalid credentials. Please check your email and password.'
        } else if (err.response.status === 401) {
          message = 'Invalid email or password.'
        } else if (err.response.status === 422) {
          message = 'Please enter a valid email address and password.'
        } else if (err.response.status >= 500) {
          message = 'Server error. Please try again later.'
        }
      } else if (err.message) {
        message = err.message
      }

      // Clean up on failure
      clearAccessToken()
      setToken(null)
      setUser(null)
      setError(message)
      setLoading(false)

      throw new Error(message)
    }
  }, [fetchUser])

  /**
   * logout() — clear all auth state and call backend to clear refresh cookie.
   */
  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // Ignore errors — we clear client state regardless
    }
    clearAccessToken()
    setToken(null)
    setUser(null)
    setError(null)
  }, [])

  /**
   * clearError() — dismiss the current error message.
   */
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const value = {
    user,
    token,
    loading,
    error,
    login,
    logout,
    clearError,
    isAuthenticated: !!user && !!token,
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

/**
 * useAuth() — convenience hook to consume AuthContext.
 * Must be used inside an <AuthProvider>.
 */
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export default AuthContext
