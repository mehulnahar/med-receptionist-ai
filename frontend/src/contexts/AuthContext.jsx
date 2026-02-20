import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import api from '../services/api'

const AuthContext = createContext(null)

/**
 * AuthProvider — wraps the app and provides authentication state + actions.
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
  const [token, setToken] = useState(() => localStorage.getItem('access_token'))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  /**
   * Fetch the current user profile from the API.
   * Returns the user object on success, or null on failure.
   * On 429 (rate limit), retries up to 3 times with exponential backoff.
   */
  const fetchUser = useCallback(async (retries = 3) => {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await api.get('/auth/me')
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
        })
        return userData
      } catch (err) {
        // On 429 (rate limit), retry after a delay instead of treating as auth failure
        if (err.response && err.response.status === 429 && attempt < retries) {
          const delay = Math.min(2000 * Math.pow(2, attempt), 10000)
          await new Promise(resolve => setTimeout(resolve, delay))
          continue
        }
        // If the token is invalid / expired the axios interceptor in api.js
        // will already clear localStorage and redirect on 401, but we also
        // clean up local state here for completeness.
        if (err.response && err.response.status === 401) {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          setToken(null)
          setUser(null)
        }
        return null
      }
    }
    return null
  }, [])

  /**
   * On mount: if a token exists in localStorage, try to restore the session
   * by fetching the current user profile.
   */
  useEffect(() => {
    let cancelled = false

    const restoreSession = async () => {
      if (!token) {
        setLoading(false)
        return
      }

      const userData = await fetchUser()

      if (!cancelled) {
        if (!userData) {
          // Token was invalid — clean up
          setToken(null)
          setUser(null)
        }
        setLoading(false)
      }
    }

    restoreSession()

    return () => {
      cancelled = true
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * login(email, password)
   *
   * 1. POST /api/auth/login  -> receive { access_token, refresh_token?, token_type }
   * 2. Store access_token in localStorage
   * 3. Fetch user profile from /api/auth/me
   */
  const login = useCallback(async (email, password) => {
    setLoading(true)
    setError(null)

    try {
      const response = await api.post('/auth/login', { email, password })
      const { access_token, refresh_token } = response.data

      // Persist tokens
      localStorage.setItem('access_token', access_token)
      if (refresh_token) {
        localStorage.setItem('refresh_token', refresh_token)
      }

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
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      setToken(null)
      setUser(null)
      setError(message)
      setLoading(false)

      throw new Error(message)
    }
  }, [fetchUser])

  /**
   * logout() — clear all auth state and localStorage.
   */
  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
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
