import { useState, useEffect, useCallback } from 'react'
import clsx from 'clsx'
import {
  Link,
  Unlink,
  CheckCircle,
  XCircle,
  RefreshCw,
  Database,
  AlertTriangle,
} from 'lucide-react'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'

// ---------------------------------------------------------------------------
// EHR type definitions and credential field config
// ---------------------------------------------------------------------------
const EHR_TYPES = [
  { value: 'athenahealth', label: 'athenahealth' },
  { value: 'drchrono', label: 'DrChrono' },
  { value: 'medicscloud', label: 'MedicsCloud' },
]

const CREDENTIAL_FIELDS = {
  athenahealth: [
    { key: 'client_id', label: 'Client ID', type: 'text' },
    { key: 'client_secret', label: 'Client Secret', type: 'password' },
    { key: 'practice_id', label: 'Practice ID', type: 'text' },
  ],
  drchrono: [
    { key: 'access_token', label: 'Access Token', type: 'password' },
    { key: 'refresh_token', label: 'Refresh Token', type: 'password' },
  ],
  medicscloud: null, // coming soon
}

// ---------------------------------------------------------------------------
// Toast notification (auto-dismiss)
// ---------------------------------------------------------------------------
function Toast({ message, type, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 5000)
    return () => clearTimeout(timer)
  }, [onClose])

  return (
    <div
      role="alert"
      className={clsx(
        'fixed top-6 right-6 z-50 flex items-center gap-3 px-5 py-3 rounded-lg shadow-lg text-sm font-medium transition-all',
        type === 'error' && 'bg-red-50 text-red-800 border border-red-200',
        type === 'success' && 'bg-green-50 text-green-800 border border-green-200'
      )}
    >
      {type === 'error' ? (
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
      ) : (
        <CheckCircle className="w-4 h-4 flex-shrink-0" />
      )}
      <span>{message}</span>
      <button
        onClick={onClose}
        className="ml-2 text-current opacity-60 hover:opacity-100"
        aria-label="Dismiss"
      >
        <XCircle className="w-4 h-4" />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function EHRConnectionPanel() {
  // Connection status
  const [status, setStatus] = useState(null)
  const [providers, setProviders] = useState([])
  const [syncLogs, setSyncLogs] = useState([])

  // Form state
  const [ehrType, setEhrType] = useState('athenahealth')
  const [credentials, setCredentials] = useState({})

  // UI state
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [toast, setToast] = useState(null)

  // ------- helpers -------
  const showToast = useCallback((message, type = 'error') => {
    setToast({ message, type })
  }, [])

  const extractError = useCallback((err) => {
    return err?.response?.data?.detail || err?.message || 'An unexpected error occurred.'
  }, [])

  // ------- data fetching -------
  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/ehr/status')
      setStatus(data)
    } catch (err) {
      showToast(extractError(err))
    }
  }, [showToast, extractError])

  const fetchProviders = useCallback(async () => {
    try {
      const { data } = await api.get('/ehr/providers')
      setProviders(data.providers || [])
    } catch (err) {
      showToast(extractError(err))
    }
  }, [showToast, extractError])

  const fetchSyncLogs = useCallback(async () => {
    try {
      const { data } = await api.get('/ehr/sync-log', { params: { limit: 50 } })
      setSyncLogs((data.logs || []).slice(0, 10))
    } catch (err) {
      showToast(extractError(err))
    }
  }, [showToast, extractError])

  const loadAll = useCallback(async () => {
    setLoading(true)
    await fetchStatus()
    setLoading(false)
  }, [fetchStatus])

  // Load connected-state data whenever status changes to connected
  useEffect(() => {
    if (status?.connected) {
      fetchProviders()
      fetchSyncLogs()
    }
  }, [status?.connected, fetchProviders, fetchSyncLogs])

  // Initial load
  useEffect(() => {
    loadAll()
  }, [loadAll])

  // ------- actions -------
  const handleConnect = async () => {
    const fields = CREDENTIAL_FIELDS[ehrType]
    if (!fields) return

    // Validate all fields filled
    const missing = fields.filter((f) => !credentials[f.key]?.trim())
    if (missing.length > 0) {
      showToast(`Please fill in: ${missing.map((f) => f.label).join(', ')}`)
      return
    }

    setActionLoading(true)
    try {
      await api.post('/ehr/connect', { ehr_type: ehrType, credentials })
      showToast('EHR connected successfully.', 'success')
      setCredentials({})
      await fetchStatus()
    } catch (err) {
      showToast(extractError(err))
    } finally {
      setActionLoading(false)
    }
  }

  const handleDisconnect = async () => {
    setActionLoading(true)
    try {
      await api.delete('/ehr/disconnect')
      showToast('EHR disconnected.', 'success')
      setStatus({ connected: false, ehr_type: null, last_sync_at: null, sync_enabled: false })
      setProviders([])
      setSyncLogs([])
    } catch (err) {
      showToast(extractError(err))
    } finally {
      setActionLoading(false)
    }
  }

  const handleCredentialChange = (key, value) => {
    setCredentials((prev) => ({ ...prev, [key]: value }))
  }

  // ------- render helpers -------
  const formatTimestamp = (ts) => {
    if (!ts) return 'Never'
    try {
      return new Date(ts).toLocaleString()
    } catch {
      return ts
    }
  }

  // ------- loading state -------
  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <LoadingSpinner size="sm" message="Loading EHR status..." />
      </div>
    )
  }

  const isConnected = status?.connected

  return (
    <>
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-5">
          <div className="flex items-center gap-3">
            <div
              className={clsx(
                'w-10 h-10 rounded-lg flex items-center justify-center ring-4',
                isConnected
                  ? 'bg-green-100 ring-green-50'
                  : 'bg-gray-100 ring-gray-50'
              )}
            >
              <Database
                className={clsx(
                  'w-5 h-5',
                  isConnected ? 'text-green-600' : 'text-gray-400'
                )}
              />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">EHR Connection</h3>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className={clsx(
                    'inline-block w-2 h-2 rounded-full',
                    isConnected ? 'bg-green-500' : 'bg-gray-300'
                  )}
                />
                <span className="text-sm text-gray-500">
                  {isConnected ? `Connected to ${status.ehr_type}` : 'Not connected'}
                </span>
              </div>
            </div>
          </div>

          {isConnected && (
            <button
              onClick={handleDisconnect}
              disabled={actionLoading}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 transition-colors disabled:opacity-50"
            >
              {actionLoading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Unlink className="w-4 h-4" />
              )}
              Disconnect
            </button>
          )}
        </div>

        {/* ---- Connected View ---- */}
        {isConnected && (
          <>
            {/* Connection details */}
            <div className="px-6 py-4">
              <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                <div>
                  <dt className="font-medium text-gray-500">EHR System</dt>
                  <dd className="mt-1 text-gray-900 capitalize">{status.ehr_type}</dd>
                </div>
                <div>
                  <dt className="font-medium text-gray-500">Last Sync</dt>
                  <dd className="mt-1 text-gray-900">{formatTimestamp(status.last_sync_at)}</dd>
                </div>
                <div>
                  <dt className="font-medium text-gray-500">Auto-Sync</dt>
                  <dd className="mt-1">
                    <span
                      className={clsx(
                        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
                        status.sync_enabled
                          ? 'bg-green-50 text-green-700'
                          : 'bg-gray-100 text-gray-500'
                      )}
                    >
                      {status.sync_enabled ? (
                        <CheckCircle className="w-3 h-3" />
                      ) : (
                        <XCircle className="w-3 h-3" />
                      )}
                      {status.sync_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>

            {/* Providers */}
            {providers.length > 0 && (
              <div className="px-6 py-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Providers</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 border-b border-gray-100">
                        <th className="pb-2 font-medium">Name</th>
                        <th className="pb-2 font-medium">NPI</th>
                        <th className="pb-2 font-medium">Specialty</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {providers.map((p) => (
                        <tr key={p.ehr_id} className="text-gray-900">
                          <td className="py-2">{p.name}</td>
                          <td className="py-2 font-mono text-xs text-gray-600">{p.npi}</td>
                          <td className="py-2 text-gray-600">{p.specialty}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Sync Logs */}
            {syncLogs.length > 0 && (
              <div className="px-6 py-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Recent Sync Activity</h4>
                <ul className="space-y-2">
                  {syncLogs.map((log, idx) => (
                    <li
                      key={log.id || idx}
                      className="flex items-start gap-2 text-sm"
                    >
                      {log.status === 'success' ? (
                        <CheckCircle className="w-4 h-4 text-green-500 mt-0.5 flex-shrink-0" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <span className="text-gray-900">{log.message || log.action || 'Sync event'}</span>
                        {log.timestamp && (
                          <span className="ml-2 text-xs text-gray-400">
                            {formatTimestamp(log.timestamp)}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {/* ---- Disconnected View — Connection Form ---- */}
        {!isConnected && (
          <div className="px-6 py-5">
            <div className="space-y-4 max-w-lg">
              {/* EHR Type Selector */}
              <div>
                <label
                  htmlFor="ehr-type"
                  className="block text-sm font-medium text-gray-700 mb-1"
                >
                  EHR System
                </label>
                <select
                  id="ehr-type"
                  value={ehrType}
                  onChange={(e) => {
                    setEhrType(e.target.value)
                    setCredentials({})
                  }}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
                >
                  {EHR_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Credential Fields */}
              {CREDENTIAL_FIELDS[ehrType] ? (
                <>
                  {CREDENTIAL_FIELDS[ehrType].map((field) => (
                    <div key={field.key}>
                      <label
                        htmlFor={`ehr-${field.key}`}
                        className="block text-sm font-medium text-gray-700 mb-1"
                      >
                        {field.label}
                      </label>
                      <input
                        id={`ehr-${field.key}`}
                        type={field.type}
                        value={credentials[field.key] || ''}
                        onChange={(e) => handleCredentialChange(field.key, e.target.value)}
                        placeholder={field.label}
                        autoComplete="off"
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
                      />
                    </div>
                  ))}

                  <button
                    onClick={handleConnect}
                    disabled={actionLoading}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 shadow-sm transition-colors disabled:opacity-50"
                  >
                    {actionLoading ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Link className="w-4 h-4" />
                    )}
                    Connect
                  </button>
                </>
              ) : (
                <div className="flex items-center gap-3 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                  <AlertTriangle className="w-5 h-5 flex-shrink-0" />
                  <span>
                    MedicsCloud integration is coming soon. Contact support for manual setup options.
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  )
}
