import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import LoadingSpinner from './components/LoadingSpinner'
import Layout from './components/Layout'
import Login from './pages/Login'

// ---------------------------------------------------------------------------
// Lazy-loaded pages — each becomes its own JS chunk, loaded on demand.
// This keeps the initial bundle small (Login + Layout only) and defers
// heavy pages (Settings=2600 lines, Admin=2200 lines, Analytics=Recharts)
// until the user actually navigates there.
// ---------------------------------------------------------------------------
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Appointments = lazy(() => import('./pages/Appointments'))
const Patients = lazy(() => import('./pages/Patients'))
const Settings = lazy(() => import('./pages/Settings'))
const Calls = lazy(() => import('./pages/Calls'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Admin = lazy(() => import('./pages/Admin'))

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Suspense fallback={<LoadingSpinner fullPage message="Loading..." />}>
          <Routes>
            {/* Public route */}
            <Route path="/login" element={<Login />} />

            {/* Protected routes — all wrapped in Layout with sidebar/header */}
            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="appointments" element={<Appointments />} />
              <Route path="patients" element={<Patients />} />
              <Route
                path="settings"
                element={
                  <ProtectedRoute roles={['practice_admin', 'super_admin']}>
                    <Settings />
                  </ProtectedRoute>
                }
              />
              <Route path="calls" element={<Calls />} />
              <Route path="analytics" element={<Analytics />} />
              <Route
                path="admin"
                element={
                  <ProtectedRoute roles={['super_admin']}>
                    <Admin />
                  </ProtectedRoute>
                }
              />
            </Route>

            {/* Catch-all redirect */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
