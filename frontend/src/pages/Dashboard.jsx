import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Calendar,
  CheckCircle,
  Clock,
  XCircle,
  CalendarPlus,
  Search,
  AlertCircle,
  RefreshCw,
  MessageSquare,
  ArrowRight,
  Phone,
  PhoneOff,
  PhoneForwarded,
  PhoneIncoming,
} from 'lucide-react'
import { format, isToday, parseISO, formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import StatsCard from '../components/StatsCard'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Return a greeting string based on the current hour. */
function getGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

/** Format today's date for display, e.g. "Tuesday, February 17, 2026". */
function formattedToday() {
  return format(new Date(), 'EEEE, MMMM d, yyyy')
}

/** Convert an HH:MM:SS or HH:MM time string to a user-friendly format. */
function formatTime(timeStr) {
  if (!timeStr) return '--'
  const [hours, minutes] = timeStr.split(':').map(Number)
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return format(date, 'h:mm a')
}

/** Status badge configuration. */
const STATUS_CONFIG = {
  booked: {
    label: 'Booked',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    ring: 'ring-amber-600/20',
    dot: 'bg-amber-500',
  },
  confirmed: {
    label: 'Confirmed',
    bg: 'bg-green-50',
    text: 'text-green-700',
    ring: 'ring-green-600/20',
    dot: 'bg-green-500',
  },
  cancelled: {
    label: 'Cancelled',
    bg: 'bg-red-50',
    text: 'text-red-700',
    ring: 'ring-red-600/20',
    dot: 'bg-red-500',
  },
  completed: {
    label: 'Completed',
    bg: 'bg-primary-50',
    text: 'text-primary-700',
    ring: 'ring-primary-600/20',
    dot: 'bg-primary-500',
  },
}

function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.booked
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ring-1 ring-inset',
        config.bg,
        config.text,
        config.ring
      )}
    >
      <span className={clsx('w-1.5 h-1.5 rounded-full', config.dot)} />
      {config.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Dashboard Component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const mountedRef = useRef(true)

  // Cleanup on unmount — prevents state updates after navigation away
  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  const [appointments, setAppointments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Call stats & callbacks state
  const [callStats, setCallStats] = useState(null)
  const [callbacks, setCallbacks] = useState([])
  const [callbacksLoading, setCallbacksLoading] = useState(true)

  const todayStr = format(new Date(), 'yyyy-MM-dd')

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  /**
   * Fetch today's appointments from the API.
   * We request a generous limit to capture the full day.
   */
  const fetchAppointments = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)

    try {
      const response = await api.get('/appointments/', {
        params: {
          from_date: todayStr,
          to_date: todayStr,
          limit: 200,
        },
      })

      const data = response.data
      const list = Array.isArray(data) ? data : data.appointments || []

      // Sort by time ascending
      list.sort((a, b) => (a.time || '').localeCompare(b.time || ''))

      if (!mountedRef.current) return
      setAppointments(list)
    } catch (err) {
      if (!mountedRef.current) return
      // Don't set error for 401 — the axios interceptor handles redirect
      if (err.response?.status !== 401) {
        setError(
          err.response?.data?.detail ||
            'Failed to load appointments. Please try again.'
        )
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [todayStr])

  /** Fetch call statistics from the webhooks API. */
  const fetchCallStats = useCallback(async () => {
    try {
      const res = await api.get('/webhooks/calls/stats')
      if (!mountedRef.current) return
      setCallStats(res.data)
    } catch (err) {
      // Silently ignore 401 (auth redirect) and 404 (endpoint not deployed yet)
      if (err.response?.status !== 401 && err.response?.status !== 404) {
        console.error('Failed to fetch call stats:', err)
      }
    }
  }, [])

  /** Fetch pending callbacks from the webhooks API. */
  const fetchCallbacks = useCallback(async () => {
    setCallbacksLoading(true)
    try {
      const res = await api.get('/webhooks/callbacks', { params: { limit: 10 } })
      if (!mountedRef.current) return
      setCallbacks(res.data.callbacks || [])
    } catch (err) {
      // Silently ignore 401 (auth redirect) and 404 (endpoint not deployed yet)
      if (err.response?.status !== 401 && err.response?.status !== 404) {
        console.error('Failed to fetch callbacks:', err)
      }
    } finally {
      if (mountedRef.current) {
        setCallbacksLoading(false)
      }
    }
  }, [])

  // Initial data load
  useEffect(() => {
    fetchAppointments()
    fetchCallStats()
    fetchCallbacks()
  }, [fetchAppointments, fetchCallStats, fetchCallbacks])

  // Auto-refresh every 30 seconds — pauses when the tab is hidden to avoid
  // wasting ~8,640 API calls if someone leaves the dashboard open overnight.
  useEffect(() => {
    let interval = null

    function startPolling() {
      stopPolling()
      interval = setInterval(() => {
        fetchAppointments(true)
        fetchCallStats()
        fetchCallbacks()
      }, 30000)
    }

    function stopPolling() {
      if (interval) {
        clearInterval(interval)
        interval = null
      }
    }

    function handleVisibility() {
      if (document.hidden) {
        stopPolling()
      } else {
        // Refresh immediately when user returns, then resume polling
        fetchAppointments(true)
        fetchCallStats()
        fetchCallbacks()
        startPolling()
      }
    }

    startPolling()
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      stopPolling()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [fetchAppointments, fetchCallStats, fetchCallbacks])

  // ---------------------------------------------------------------------------
  // Callback completion handler
  // ---------------------------------------------------------------------------

  const handleCompleteCallback = async (callId) => {
    try {
      await api.patch(`/webhooks/calls/${callId}/callback`, {
        callback_completed: true,
      })
      // Remove from list optimistically
      setCallbacks((prev) => prev.filter((c) => c.id !== callId))
      // Refresh stats to update pending count
      fetchCallStats()
    } catch (err) {
      console.error('Failed to complete callback:', err)
    }
  }

  // ---------------------------------------------------------------------------
  // Refresh all handler (for the Refresh button)
  // ---------------------------------------------------------------------------

  const handleRefreshAll = () => {
    fetchAppointments(true)
    fetchCallStats()
    fetchCallbacks()
  }

  // ---------------------------------------------------------------------------
  // Derived appointment stats
  // ---------------------------------------------------------------------------

  const nonCancelledCount = appointments.filter(
    (a) => a.status !== 'cancelled'
  ).length

  const confirmedCount = appointments.filter(
    (a) => a.status === 'confirmed'
  ).length

  const pendingCount = appointments.filter(
    (a) => a.status === 'booked'
  ).length

  const cancelledCount = appointments.filter(
    (a) => a.status === 'cancelled'
  ).length

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <LoadingSpinner
        fullPage={false}
        message="Loading dashboard..."
        size="lg"
      />
    )
  }

  return (
    <div className="space-y-8">
      {/* ================================================================
          HEADER SECTION
          ================================================================ */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            {getGreeting()},{' '}
            <span className="text-primary-600">
              {user?.first_name || 'there'}
            </span>
          </h1>
          <p className="mt-1 text-sm text-gray-500">{formattedToday()}</p>
        </div>

        <button
          onClick={handleRefreshAll}
          disabled={refreshing}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
            'border border-gray-200 bg-white text-gray-700',
            'hover:bg-gray-50 active:bg-gray-100',
            'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          <RefreshCw
            className={clsx('w-4 h-4', refreshing && 'animate-spin')}
          />
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* ================================================================
          ERROR ALERT
          ================================================================ */}
      {error && (
        error.toLowerCase().includes('no practice') && user?.role === 'super_admin' ? (
          <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 text-blue-700 rounded-xl px-5 py-4 text-sm shadow-sm">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium">Super Admin View</p>
              <p className="mt-0.5 text-blue-600">
                You are not assigned to a practice. Use the{' '}
                <a href="/admin" className="underline font-medium hover:text-blue-800">
                  Super Admin panel
                </a>{' '}
                to manage practices and users.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium">Something went wrong</p>
              <p className="mt-0.5 text-red-600">{error}</p>
            </div>
            <button
              onClick={() => fetchAppointments(true)}
              className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
            >
              Try again
            </button>
          </div>
        )
      )}

      {/* ================================================================
          APPOINTMENT STATS CARDS
          ================================================================ */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Today's Appointments"
          value={nonCancelledCount}
          icon={Calendar}
          color="blue"
          subtitle={`${appointments.length} total scheduled`}
        />
        <StatsCard
          title="Confirmed"
          value={confirmedCount}
          icon={CheckCircle}
          color="green"
          subtitle={
            nonCancelledCount > 0
              ? `${Math.round((confirmedCount / nonCancelledCount) * 100)}% of active`
              : 'No active appointments'
          }
        />
        <StatsCard
          title="Pending"
          value={pendingCount}
          icon={Clock}
          color="yellow"
          subtitle="Awaiting confirmation"
        />
        <StatsCard
          title="Cancellations"
          value={cancelledCount}
          icon={XCircle}
          color="red"
          subtitle="Cancelled today"
        />
      </div>

      {/* ================================================================
          CALL STATS CARDS (only render when data is available)
          ================================================================ */}
      {callStats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatsCard
            title="Calls Today"
            value={callStats.total_calls_today}
            icon={Phone}
            color="indigo"
            subtitle={`${callStats.total_calls_week} this week`}
          />
          <StatsCard
            title="Missed Calls"
            value={callStats.missed_calls_today}
            icon={PhoneOff}
            color="red"
            subtitle="Dropped or unanswered"
          />
          <StatsCard
            title="Callbacks Pending"
            value={callStats.callbacks_pending}
            icon={PhoneForwarded}
            color="orange"
            subtitle="Need follow-up"
          />
          <StatsCard
            title="Avg Duration"
            value={
              callStats.avg_duration_seconds > 0
                ? `${Math.floor(callStats.avg_duration_seconds / 60)}m ${Math.round(callStats.avg_duration_seconds % 60)}s`
                : '--'
            }
            icon={Clock}
            color="purple"
            subtitle={
              callStats.total_cost_today > 0
                ? `$${callStats.total_cost_today.toFixed(2)} today`
                : 'No calls yet'
            }
          />
        </div>
      )}

      {/* ================================================================
          CALLBACKS NEEDED
          ================================================================ */}
      {callbacks.length > 0 && (
        <div className="bg-white rounded-xl border border-orange-200 shadow-sm overflow-hidden">
          {/* Section header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-orange-100 bg-orange-50/50">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-orange-100 flex items-center justify-center">
                <PhoneForwarded className="w-4 h-4 text-orange-600" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-gray-900">
                  Callbacks Needed
                </h2>
                <p className="text-sm text-gray-500 mt-0.5">
                  {callbacks.length} call{callbacks.length === 1 ? '' : 's'}{' '}
                  need{callbacks.length === 1 ? 's' : ''} follow-up
                </p>
              </div>
            </div>
            <Link
              to="/calls?filter=callbacks"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-orange-600 hover:text-orange-700 transition-colors"
            >
              View all
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {/* Callback list */}
          <div className="divide-y divide-gray-100">
            {callbacks.map((cb) => (
              <div
                key={cb.id}
                className="flex items-center justify-between px-5 py-3.5 hover:bg-orange-50/30 transition-colors"
              >
                <div className="flex items-center gap-4 min-w-0 flex-1">
                  <div className="w-10 h-10 rounded-full bg-orange-100 flex items-center justify-center flex-shrink-0">
                    <PhoneIncoming className="w-5 h-5 text-orange-600" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-gray-900 truncate">
                        {cb.caller_name || 'Unknown Caller'}
                      </p>
                      {cb.ended_reason && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20">
                          {cb.ended_reason
                            .replace(/-/g, ' ')
                            .replace(/\b\w/g, (c) => c.toUpperCase())}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-xs text-gray-500">
                        {cb.caller_number || cb.caller_phone || 'No number'}
                      </span>
                      {cb.started_at && (
                        <span className="text-xs text-gray-400">
                          {formatDistanceToNow(parseISO(cb.started_at), {
                            addSuffix: true,
                          })}
                        </span>
                      )}
                    </div>
                    {cb.summary && (
                      <p className="text-xs text-gray-500 mt-1 line-clamp-1">
                        {cb.summary}
                      </p>
                    )}
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                  {(cb.caller_number || cb.caller_phone) && (
                    <a
                      href={`tel:${cb.caller_number || cb.caller_phone}`}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-green-700 bg-green-50 hover:bg-green-100 ring-1 ring-inset ring-green-600/20 transition-colors"
                    >
                      <Phone className="w-3.5 h-3.5" />
                      Call
                    </a>
                  )}
                  <button
                    onClick={() => handleCompleteCallback(cb.id)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 ring-1 ring-inset ring-gray-300 transition-colors"
                  >
                    <CheckCircle className="w-3.5 h-3.5" />
                    Done
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ================================================================
          TODAY'S APPOINTMENTS TABLE
          ================================================================ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Table header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Today's Appointments
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {appointments.length === 0
                ? 'Nothing scheduled for today'
                : `${appointments.length} appointment${appointments.length === 1 ? '' : 's'} scheduled`}
            </p>
          </div>
          <Link
            to="/appointments"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700 transition-colors"
          >
            View all
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        {appointments.length === 0 ? (
          <EmptyState
            icon={Calendar}
            title="No appointments today"
            description="There are no appointments scheduled for today. Book a new appointment to get started."
            actionLabel="Book Appointment"
            onAction={() => navigate('/appointments?action=book')}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead>
                <tr className="bg-gray-50/80">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Time
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Patient Name
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Type
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Status
                  </th>
                  <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    SMS Sent
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Booked By
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {appointments.map((appt) => (
                  <tr
                    key={appt.id}
                    onClick={() => navigate('/appointments')}
                    className="group cursor-pointer hover:bg-primary-50/40 transition-colors duration-150"
                  >
                    {/* Time */}
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm font-medium text-gray-900">
                        {formatTime(appt.time)}
                      </span>
                      {appt.duration_minutes && (
                        <span className="ml-1.5 text-xs text-gray-400">
                          ({appt.duration_minutes}m)
                        </span>
                      )}
                    </td>

                    {/* Patient Name */}
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm font-medium text-gray-900 group-hover:text-primary-700 transition-colors">
                        {appt.patient_name || 'Unknown Patient'}
                      </span>
                    </td>

                    {/* Appointment Type */}
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {appt.appointment_type_name || '--'}
                      </span>
                    </td>

                    {/* Status */}
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <StatusBadge status={appt.status} />
                    </td>

                    {/* SMS Confirmation */}
                    <td className="px-5 py-3.5 whitespace-nowrap text-center">
                      {appt.sms_confirmation_sent ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700">
                          <MessageSquare className="w-3.5 h-3.5" />
                          Sent
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">--</span>
                      )}
                    </td>

                    {/* Booked By */}
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {appt.booked_by || '--'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ================================================================
          QUICK ACTIONS
          ================================================================ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-4">
          Quick Actions
        </h2>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/appointments?action=book"
            className={clsx(
              'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold',
              'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
              'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
              'transition-colors shadow-sm hover:shadow-md'
            )}
          >
            <CalendarPlus className="w-4.5 h-4.5" />
            Book Appointment
          </Link>
          <Link
            to="/patients"
            className={clsx(
              'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold',
              'text-gray-700 bg-white border border-gray-300',
              'hover:bg-gray-50 active:bg-gray-100',
              'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
              'transition-colors shadow-sm'
            )}
          >
            <Search className="w-4.5 h-4.5" />
            Search Patient
          </Link>
        </div>
      </div>
    </div>
  )
}
