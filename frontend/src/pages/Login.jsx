import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Stethoscope, Mail, Lock, LogIn, AlertCircle, Eye, EyeOff } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const navigate = useNavigate()
  const { login, isAuthenticated, loading: authLoading, error: authError, clearError } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState(null)

  // If already authenticated, redirect to dashboard
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  // Sync auth-level errors into local state
  useEffect(() => {
    if (authError) {
      setLocalError(authError)
    }
  }, [authError])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLocalError(null)
    clearError()

    // Client-side validation
    if (!email.trim()) {
      setLocalError('Please enter your email address.')
      return
    }
    if (!password) {
      setLocalError('Please enter your password.')
      return
    }

    setSubmitting(true)

    try {
      await login(email.trim(), password)
      // On success the isAuthenticated effect above will redirect
      navigate('/', { replace: true })
    } catch (err) {
      setLocalError(err.message || 'Login failed. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const isLoading = submitting || authLoading

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 via-white to-primary-100 flex items-center justify-center p-4">
      {/* Background decorative elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-primary-200/30 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-primary-300/20 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md">
        {/* Card */}
        <div className="bg-white rounded-2xl shadow-xl border border-primary-100 p-8 sm:p-10">
          {/* Header */}
          <div className="text-center mb-8">
            {/* Logo icon */}
            <div className="mx-auto w-16 h-16 bg-primary-600 rounded-2xl flex items-center justify-center shadow-lg mb-5">
              <Stethoscope className="w-8 h-8 text-white" strokeWidth={1.8} />
            </div>

            <h1 className="text-2xl font-bold text-gray-900">
              Welcome Back
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Sign in to the AI Medical Receptionist dashboard
            </p>
          </div>

          {/* Error alert */}
          {localError && (
            <div className="mb-6 flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
              <span>{localError}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email field */}
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700 mb-1.5"
              >
                Email Address
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <Mail className="w-5 h-5 text-gray-400" />
                </div>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@practice.com"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    setLocalError(null)
                  }}
                  disabled={isLoading}
                  className={clsx(
                    'block w-full pl-11 pr-4 py-2.5 rounded-lg border text-gray-900 placeholder-gray-400',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                    'transition-colors duration-150',
                    'disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed',
                    localError
                      ? 'border-red-300 focus:ring-red-500/40 focus:border-red-500'
                      : 'border-gray-300'
                  )}
                />
              </div>
            </div>

            {/* Password field */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 mb-1.5"
              >
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <Lock className="w-5 h-5 text-gray-400" />
                </div>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value)
                    setLocalError(null)
                  }}
                  disabled={isLoading}
                  className={clsx(
                    'block w-full pl-11 pr-12 py-2.5 rounded-lg border text-gray-900 placeholder-gray-400',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                    'transition-colors duration-150',
                    'disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed',
                    localError
                      ? 'border-red-300 focus:ring-red-500/40 focus:border-red-500'
                      : 'border-gray-300'
                  )}
                />
                {/* Show / hide password toggle */}
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-gray-400 hover:text-gray-600 transition-colors"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Submit button */}
            <button
              type="submit"
              disabled={isLoading}
              className={clsx(
                'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg',
                'text-sm font-semibold text-white',
                'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                'transition-all duration-150',
                'disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:bg-primary-600',
                'shadow-sm hover:shadow-md'
              )}
            >
              {isLoading ? (
                <>
                  {/* Spinner */}
                  <svg
                    className="animate-spin h-5 w-5 text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  <span>Signing in...</span>
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  <span>Sign In</span>
                </>
              )}
            </button>
          </form>

          {/* Divider */}
          <div className="mt-8 border-t border-gray-100" />

          {/* Footer */}
          <p className="mt-6 text-center text-xs text-gray-400">
            Powered by AI &middot; Built for modern medical practices
          </p>
        </div>
      </div>
    </div>
  )
}
