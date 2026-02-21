import { useEffect, useRef, useState, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'

const SESSION_TIMEOUT_MS = 15 * 60 * 1000   // 15 minutes
const WARNING_BEFORE_MS = 2 * 60 * 1000     // Show warning 2 min before timeout
const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'scroll', 'touchstart', 'mousemove']
const THROTTLE_MS = 30_000                   // Only update activity every 30s

/**
 * SessionTimeoutProvider — HIPAA-compliant session timeout.
 *
 * - Tracks user activity (mouse, keyboard, scroll, touch)
 * - Shows warning modal at 13 minutes of inactivity
 * - Auto-logs out at 15 minutes
 * - Clears all local state on timeout
 */
export default function SessionTimeoutProvider({ children }) {
  const { isAuthenticated, logout } = useAuth()
  const [showWarning, setShowWarning] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const lastActivityRef = useRef(Date.now())
  const warningTimerRef = useRef(null)
  const logoutTimerRef = useRef(null)
  const countdownRef = useRef(null)
  const throttleRef = useRef(0)

  const resetTimers = useCallback(() => {
    lastActivityRef.current = Date.now()
    setShowWarning(false)

    // Clear existing timers
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
    if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current)
    if (countdownRef.current) clearInterval(countdownRef.current)

    // Set new warning timer (fires at 13 minutes)
    warningTimerRef.current = setTimeout(() => {
      setShowWarning(true)
      setSecondsLeft(WARNING_BEFORE_MS / 1000)

      // Start countdown
      countdownRef.current = setInterval(() => {
        setSecondsLeft(prev => {
          if (prev <= 1) {
            clearInterval(countdownRef.current)
            return 0
          }
          return prev - 1
        })
      }, 1000)
    }, SESSION_TIMEOUT_MS - WARNING_BEFORE_MS)

    // Set logout timer (fires at 15 minutes)
    logoutTimerRef.current = setTimeout(() => {
      setShowWarning(false)
      handleTimeout()
    }, SESSION_TIMEOUT_MS)
  }, [])

  const handleTimeout = useCallback(async () => {
    // Clear all intervals
    if (countdownRef.current) clearInterval(countdownRef.current)
    if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
    if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current)

    // Log out
    await logout()
    window.location.href = '/login?reason=timeout'
  }, [logout])

  const handleContinue = useCallback(() => {
    setShowWarning(false)
    resetTimers()
  }, [resetTimers])

  // Activity listener
  const handleActivity = useCallback(() => {
    const now = Date.now()
    // Throttle to prevent excessive timer resets
    if (now - throttleRef.current < THROTTLE_MS) return
    throttleRef.current = now

    if (!showWarning) {
      resetTimers()
    }
  }, [showWarning, resetTimers])

  // Set up event listeners
  useEffect(() => {
    if (!isAuthenticated) return

    resetTimers()

    ACTIVITY_EVENTS.forEach(event => {
      document.addEventListener(event, handleActivity, { passive: true })
    })

    return () => {
      ACTIVITY_EVENTS.forEach(event => {
        document.removeEventListener(event, handleActivity)
      })
      if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
      if (logoutTimerRef.current) clearTimeout(logoutTimerRef.current)
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [isAuthenticated, handleActivity, resetTimers])

  return (
    <>
      {children}
      {showWarning && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md mx-4">
            <div className="flex items-center mb-4">
              <svg className="w-8 h-8 text-amber-500 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <h2 className="text-lg font-semibold text-gray-900">Session Timeout Warning</h2>
            </div>
            <p className="text-gray-600 mb-2">
              Your session will expire in <span className="font-bold text-red-600">{Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, '0')}</span> due to inactivity.
            </p>
            <p className="text-sm text-gray-500 mb-6">
              For HIPAA compliance, sessions are automatically ended after 15 minutes of inactivity.
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleContinue}
                className="flex-1 bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 font-medium transition-colors"
              >
                Continue Session
              </button>
              <button
                onClick={handleTimeout}
                className="flex-1 bg-gray-200 text-gray-700 py-2 px-4 rounded-lg hover:bg-gray-300 font-medium transition-colors"
              >
                Log Out Now
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
