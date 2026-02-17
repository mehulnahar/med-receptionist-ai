import { Navigate, useLocation } from 'react-router-dom'
import { ShieldAlert, Loader2 } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

/**
 * ProtectedRoute — route guard that wraps child components.
 *
 * Props:
 *   children   — the protected page content
 *   roles      — optional array of allowed role strings
 *                e.g. ['super_admin', 'practice_admin']
 *                If omitted, any authenticated user can access.
 *
 * Behavior:
 *   1. While auth is loading (initial session restore), show a full-screen spinner.
 *   2. If the user is not authenticated, redirect to /login (preserving the
 *      intended destination so we can redirect back after login).
 *   3. If a `roles` array is provided and the user's role is not included,
 *      show an "Access Denied" screen.
 *   4. Otherwise, render the children.
 */
export default function ProtectedRoute({ children, roles }) {
  const { user, isAuthenticated, loading } = useAuth()
  const location = useLocation()

  // ---- Loading state (session being restored) ----
  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50">
        <Loader2 className="w-10 h-10 text-primary-600 animate-spin" />
        <p className="mt-4 text-sm text-gray-500 font-medium">
          Loading your session...
        </p>
      </div>
    )
  }

  // ---- Not authenticated ----
  if (!isAuthenticated) {
    // Redirect to /login while saving the page they tried to visit
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  // ---- Role-based access check ----
  if (roles && roles.length > 0 && !roles.includes(user?.role)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-8 sm:p-10 max-w-md w-full text-center">
          {/* Icon */}
          <div className="mx-auto w-16 h-16 bg-red-100 rounded-2xl flex items-center justify-center mb-5">
            <ShieldAlert className="w-8 h-8 text-red-600" />
          </div>

          {/* Heading */}
          <h2 className="text-xl font-bold text-gray-900 mb-2">
            Access Denied
          </h2>

          {/* Message */}
          <p className="text-sm text-gray-500 mb-6">
            Your account does not have permission to view this page. If you
            believe this is an error, please contact your administrator.
          </p>

          {/* Details */}
          <div className="bg-gray-50 rounded-lg p-4 text-left text-sm space-y-2 mb-6">
            <div className="flex justify-between">
              <span className="text-gray-500">Your role</span>
              <span className="text-gray-900 font-medium capitalize">
                {user?.role?.replace(/_/g, ' ') || 'Unknown'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Required</span>
              <span className="text-gray-900 font-medium capitalize">
                {roles.map((r) => r.replace(/_/g, ' ')).join(', ')}
              </span>
            </div>
          </div>

          {/* Action */}
          <button
            onClick={() => window.history.back()}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2 transition-colors shadow-sm"
          >
            Go Back
          </button>
        </div>
      </div>
    )
  }

  // ---- Authorized ----
  return children
}
