import React from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

/**
 * ErrorBoundary — Catches uncaught React rendering errors and shows
 * a recovery UI instead of a blank white screen.
 *
 * Wraps the entire app (or any subtree) to prevent a single component
 * crash from taking down the whole page.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] Uncaught error:', error, errorInfo)

    // Report to backend for production visibility (fire-and-forget)
    try {
      const payload = {
        message: error?.message || String(error),
        stack: error?.stack?.slice(0, 2000),
        componentStack: errorInfo?.componentStack?.slice(0, 2000),
        url: window.location.href,
        timestamp: new Date().toISOString(),
      }
      navigator.sendBeacon?.('/api/client-errors', new Blob(
        [JSON.stringify(payload)],
        { type: 'application/json' }
      ))
    } catch {
      // Swallow — error reporting must never cause secondary failures
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
          <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center">
            <div className="mx-auto w-14 h-14 rounded-full bg-red-100 flex items-center justify-center mb-4">
              <AlertTriangle className="w-7 h-7 text-red-600" />
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              Something went wrong
            </h2>
            <p className="text-sm text-gray-500 mb-6">
              An unexpected error occurred. You can try again or reload the page.
            </p>
            {this.state.error && (
              <pre className="text-xs text-left bg-gray-100 rounded-lg p-3 mb-6 overflow-auto max-h-32 text-red-700">
                {this.state.error.message || String(this.state.error)}
              </pre>
            )}
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Try Again
              </button>
              <button
                onClick={this.handleReload}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors"
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
