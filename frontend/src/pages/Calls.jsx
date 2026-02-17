import { useState, useEffect, useCallback, Fragment } from 'react'
import { format, parseISO, formatDistanceToNow } from 'date-fns'
import {
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Search,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Calendar,
  Clock,
  DollarSign,
  FileText,
  Mic,
  Play,
  Pause,
  X,
  Info,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50

const DIRECTION_OPTIONS = [
  { value: '', label: 'All Directions' },
  { value: 'inbound', label: 'Inbound' },
  { value: 'outbound', label: 'Outbound' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'in-progress', label: 'In Progress' },
  { value: 'ended', label: 'Ended' },
]

const CALL_STATUS_CONFIG = {
  ringing: {
    label: 'Ringing',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    ring: 'ring-amber-600/20',
    dot: 'bg-amber-500',
  },
  'in-progress': {
    label: 'In Progress',
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    ring: 'ring-blue-600/20',
    dot: 'bg-blue-500',
  },
  ended: {
    label: 'Ended',
    bg: 'bg-gray-100',
    text: 'text-gray-600',
    ring: 'ring-gray-500/20',
    dot: 'bg-gray-400',
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format seconds into "Xm Ys" string. */
function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '--'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins === 0) return `${secs}s`
  return `${mins}m ${secs}s`
}

/** Format a cost value as currency. */
function formatCost(cost) {
  if (cost == null) return '--'
  return `$${Number(cost).toFixed(4)}`
}

/** Format a phone number for display. */
function formatPhone(phone) {
  if (!phone) return 'Unknown'
  // Simple US format: +1XXXXXXXXXX -> (XXX) XXX-XXXX
  const cleaned = phone.replace(/\D/g, '')
  if (cleaned.length === 11 && cleaned.startsWith('1')) {
    return `(${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7)}`
  }
  if (cleaned.length === 10) {
    return `(${cleaned.slice(0, 3)}) ${cleaned.slice(3, 6)}-${cleaned.slice(6)}`
  }
  return phone
}

/** Return yyyy-MM-dd from a Date object. */
function toDateStr(date) {
  return format(date, 'yyyy-MM-dd')
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CallStatusBadge({ status }) {
  const config = CALL_STATUS_CONFIG[status] || CALL_STATUS_CONFIG.ended
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

function DirectionIcon({ direction }) {
  if (direction === 'inbound') {
    return (
      <span className="inline-flex items-center gap-1.5 text-green-700">
        <PhoneIncoming className="w-4 h-4" />
        <span className="text-xs font-medium">Inbound</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-blue-700">
      <PhoneOutgoing className="w-4 h-4" />
      <span className="text-xs font-medium">Outbound</span>
    </span>
  )
}

/** Audio player for call recordings. */
function RecordingPlayer({ url }) {
  const [playing, setPlaying] = useState(false)
  const [audioRef, setAudioRef] = useState(null)

  function togglePlay() {
    if (!audioRef) return
    if (playing) {
      audioRef.pause()
    } else {
      audioRef.play()
    }
    setPlaying(!playing)
  }

  return (
    <div className="flex items-center gap-3">
      <audio
        ref={(el) => setAudioRef(el)}
        src={url}
        onEnded={() => setPlaying(false)}
        onPause={() => setPlaying(false)}
        onPlay={() => setPlaying(true)}
        preload="none"
      />
      <button
        onClick={togglePlay}
        className={clsx(
          'inline-flex items-center justify-center w-9 h-9 rounded-full transition-colors',
          playing
            ? 'bg-red-100 text-red-700 hover:bg-red-200'
            : 'bg-primary-100 text-primary-700 hover:bg-primary-200'
        )}
        title={playing ? 'Pause' : 'Play recording'}
      >
        {playing ? (
          <Pause className="w-4 h-4" />
        ) : (
          <Play className="w-4 h-4 ml-0.5" />
        )}
      </button>
      <span className="text-sm text-gray-500">
        {playing ? 'Playing...' : 'Play recording'}
      </span>
    </div>
  )
}

/** Expandable call detail panel. */
function CallDetail({ call }) {
  return (
    <tr>
      <td colSpan={7} className="px-0 py-0">
        <div className="bg-gray-50/80 border-t border-gray-100 px-5 py-5">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left column: Transcript */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-gray-400" />
                <h4 className="text-sm font-semibold text-gray-900">
                  Transcript
                </h4>
              </div>
              {call.transcript ? (
                <div className="bg-white rounded-lg border border-gray-200 p-4 max-h-64 overflow-y-auto">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
                    {call.transcript}
                  </p>
                </div>
              ) : (
                <div className="bg-white rounded-lg border border-gray-200 p-4">
                  <p className="text-sm text-gray-400 italic">
                    No transcript available for this call.
                  </p>
                </div>
              )}
            </div>

            {/* Right column: Summary, Recording, Cost */}
            <div className="space-y-5">
              {/* AI Summary */}
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Mic className="w-4 h-4 text-gray-400" />
                  <h4 className="text-sm font-semibold text-gray-900">
                    AI Summary
                  </h4>
                </div>
                {call.summary ? (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <p className="text-sm text-gray-700 leading-relaxed">
                      {call.summary}
                    </p>
                  </div>
                ) : (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <p className="text-sm text-gray-400 italic">
                      No AI summary available.
                    </p>
                  </div>
                )}
              </div>

              {/* Recording */}
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Play className="w-4 h-4 text-gray-400" />
                  <h4 className="text-sm font-semibold text-gray-900">
                    Recording
                  </h4>
                </div>
                {call.recording_url ? (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <RecordingPlayer url={call.recording_url} />
                  </div>
                ) : (
                  <div className="bg-white rounded-lg border border-gray-200 p-4">
                    <p className="text-sm text-gray-400 italic">
                      No recording available.
                    </p>
                  </div>
                )}
              </div>

              {/* Cost breakdown */}
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-gray-400" />
                  <h4 className="text-sm font-semibold text-gray-900">
                    Cost Details
                  </h4>
                </div>
                <div className="bg-white rounded-lg border border-gray-200 p-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <p className="text-xs text-gray-500 mb-0.5">Total Cost</p>
                      <p className="text-sm font-semibold text-gray-900">
                        {formatCost(call.cost)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 mb-0.5">Duration</p>
                      <p className="text-sm font-semibold text-gray-900">
                        {formatDuration(call.duration_seconds)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 mb-0.5">Started</p>
                      <p className="text-sm text-gray-700">
                        {call.started_at
                          ? format(parseISO(call.started_at), 'MMM d, yyyy h:mm:ss a')
                          : '--'}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 mb-0.5">Ended</p>
                      <p className="text-sm text-gray-700">
                        {call.ended_at
                          ? format(parseISO(call.ended_at), 'MMM d, yyyy h:mm:ss a')
                          : '--'}
                      </p>
                    </div>
                  </div>
                  {call.vapi_call_id && (
                    <div className="mt-3 pt-3 border-t border-gray-100">
                      <p className="text-xs text-gray-400">
                        Vapi Call ID: {call.vapi_call_id}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// API-not-ready banner
// ---------------------------------------------------------------------------

function ApiComingSoonBanner() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
          Call Log
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          View and manage all voice AI calls
        </p>
      </div>

      {/* Banner */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
          <div className="w-16 h-16 rounded-2xl bg-primary-100 flex items-center justify-center mb-5">
            <Phone className="w-8 h-8 text-primary-600" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            Call Log API Coming Soon
          </h3>
          <p className="text-sm text-gray-500 max-w-md mb-2">
            The call log feature is being developed. Once the backend API is
            ready, this page will display all inbound and outbound voice AI
            calls with transcripts, summaries, and recordings.
          </p>
          <div className="mt-4 flex items-center gap-2 text-xs text-gray-400">
            <Info className="w-4 h-4" />
            <span>Endpoint: GET /api/webhooks/calls</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Calls Component
// ---------------------------------------------------------------------------

export default function Calls() {
  // ---- Filter state ----
  const [fromDate, setFromDate] = useState(() =>
    toDateStr(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000))
  )
  const [toDate, setToDate] = useState(() => toDateStr(new Date()))
  const [directionFilter, setDirectionFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // ---- Data state ----
  const [calls, setCalls] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [apiNotReady, setApiNotReady] = useState(false)

  // ---- UI state ----
  const [expandedId, setExpandedId] = useState(null)

  // ---- Debounce search query ----
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim())
    }, 400)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // ---- Reset page when filters change ----
  useEffect(() => {
    setPage(0)
  }, [fromDate, toDate, directionFilter, statusFilter, debouncedSearch])

  // ---- Fetch calls ----
  const fetchCalls = useCallback(
    async (isRefresh = false) => {
      if (apiNotReady) return

      if (isRefresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)

      try {
        const params = {
          from_date: fromDate,
          to_date: toDate,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }
        if (directionFilter) params.direction = directionFilter
        if (statusFilter) params.status = statusFilter
        if (debouncedSearch) params.search = debouncedSearch

        const res = await api.get('/webhooks/calls', { params })
        const data = res.data
        const list = Array.isArray(data) ? data : data.calls || []
        const totalCount =
          typeof data.total === 'number' ? data.total : list.length

        setCalls(list)
        setTotal(totalCount)
      } catch (err) {
        // 401 is handled by axios interceptor
        if (err.response?.status === 401) return

        // If 404, the endpoint doesn't exist yet
        if (err.response?.status === 404) {
          setApiNotReady(true)
          return
        }

        setError(
          err.response?.data?.detail ||
            'Failed to load call log. Please try again.'
        )
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [fromDate, toDate, directionFilter, statusFilter, debouncedSearch, page, apiNotReady]
  )

  useEffect(() => {
    fetchCalls()
  }, [fetchCalls])

  // ---- Toggle row expansion ----
  function toggleExpand(callId) {
    setExpandedId((prev) => (prev === callId ? null : callId))
  }

  // ---- Pagination ----
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const canGoBack = page > 0
  const canGoForward = page < totalPages - 1

  // ---- If API is not ready, show banner ----
  if (apiNotReady) {
    return <ApiComingSoonBanner />
  }

  // ---- Render ----
  return (
    <div className="space-y-6">
      {/* ================================================================
          HEADER
          ================================================================ */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Call Log
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            View and manage all voice AI calls
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Date range */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-gray-400" />
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="px-2.5 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
              />
            </div>
            <span className="text-gray-400 text-sm">to</span>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg border border-gray-200 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
          </div>

          {/* Refresh */}
          <button
            onClick={() => fetchCalls(true)}
            disabled={refreshing}
            className={clsx(
              'inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium',
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
            <span className="hidden sm:inline">
              {refreshing ? 'Refreshing...' : 'Refresh'}
            </span>
          </button>
        </div>
      </div>

      {/* ================================================================
          FILTERS BAR
          ================================================================ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 px-5 py-4">
          {/* Direction filter */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1">
              {DIRECTION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setDirectionFilter(opt.value)}
                  className={clsx(
                    'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    directionFilter === opt.value
                      ? 'bg-primary-600 text-white shadow-sm'
                      : 'text-gray-600 bg-gray-100 hover:bg-gray-200'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <div className="w-px h-6 bg-gray-200 hidden lg:block" />

            {/* Status filter */}
            <div className="flex items-center gap-1">
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setStatusFilter(opt.value)}
                  className={clsx(
                    'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    statusFilter === opt.value
                      ? 'bg-primary-600 text-white shadow-sm'
                      : 'text-gray-600 bg-gray-100 hover:bg-gray-200'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Phone search */}
          <div className="relative w-full lg:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by phone number..."
              className="w-full pl-10 pr-9 py-2 rounded-lg border border-gray-200 text-sm text-gray-700 bg-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ================================================================
          ERROR ALERT
          ================================================================ */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">Something went wrong</p>
            <p className="mt-0.5 text-red-600">{error}</p>
          </div>
          <button
            onClick={() => fetchCalls(true)}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* ================================================================
          CALLS TABLE
          ================================================================ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Table header bar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Calls</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {loading
                ? 'Loading...'
                : total === 0
                  ? 'No calls found'
                  : `${total} call${total === 1 ? '' : 's'} found`}
            </p>
          </div>
          {!loading && total > 0 && (
            <p className="text-xs text-gray-400">
              Click a row to view details
            </p>
          )}
        </div>

        {loading ? (
          <LoadingSpinner
            fullPage={false}
            message="Loading calls..."
            size="md"
          />
        ) : calls.length === 0 ? (
          <EmptyState
            icon={Phone}
            title="No calls found"
            description="There are no calls matching your current filters. Try adjusting the date range, direction, or status filters."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px]">
                <thead>
                  <tr className="bg-gray-50/80">
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Time
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Direction
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Caller Number
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Patient
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Duration
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Status
                    </th>
                    <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Cost
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {calls.map((call) => {
                    const isExpanded = expandedId === call.id
                    const startedAt = call.started_at
                      ? parseISO(call.started_at)
                      : call.created_at
                        ? parseISO(call.created_at)
                        : null

                    return (
                      <Fragment key={call.id}>
                        <tr
                          onClick={() => toggleExpand(call.id)}
                          className={clsx(
                            'group cursor-pointer transition-colors duration-150',
                            isExpanded
                              ? 'bg-primary-50/40'
                              : 'hover:bg-gray-50/80'
                          )}
                        >
                          {/* Time */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <div className="flex items-center gap-2">
                              {isExpanded ? (
                                <ChevronUp className="w-4 h-4 text-gray-400 flex-shrink-0" />
                              ) : (
                                <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                              )}
                              <div>
                                <p className="text-sm font-medium text-gray-900">
                                  {startedAt
                                    ? format(startedAt, 'MMM d, h:mm a')
                                    : '--'}
                                </p>
                                {startedAt && (
                                  <p className="text-xs text-gray-400">
                                    {formatDistanceToNow(startedAt, {
                                      addSuffix: true,
                                    })}
                                  </p>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* Direction */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <DirectionIcon direction={call.direction} />
                          </td>

                          {/* Caller Number */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <span className="text-sm font-mono text-gray-700">
                              {formatPhone(call.caller_number)}
                            </span>
                          </td>

                          {/* Patient */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <span className="text-sm font-medium text-gray-900">
                              {call.patient_name || (
                                <span className="text-gray-400 font-normal">
                                  Unidentified
                                </span>
                              )}
                            </span>
                          </td>

                          {/* Duration */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              <Clock className="w-3.5 h-3.5 text-gray-400" />
                              <span className="text-sm text-gray-700">
                                {formatDuration(call.duration_seconds)}
                              </span>
                            </div>
                          </td>

                          {/* Status */}
                          <td className="px-5 py-3.5 whitespace-nowrap">
                            <CallStatusBadge status={call.status} />
                          </td>

                          {/* Cost */}
                          <td className="px-5 py-3.5 whitespace-nowrap text-right">
                            <span className="text-sm font-medium text-gray-700">
                              {formatCost(call.cost)}
                            </span>
                          </td>
                        </tr>

                        {/* Expanded detail row */}
                        {isExpanded && (
                          <CallDetail call={call} />
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-5 py-4 border-t border-gray-100">
                <p className="text-sm text-gray-500">
                  Showing{' '}
                  <span className="font-medium text-gray-700">
                    {page * PAGE_SIZE + 1}
                  </span>{' '}
                  to{' '}
                  <span className="font-medium text-gray-700">
                    {Math.min((page + 1) * PAGE_SIZE, total)}
                  </span>{' '}
                  of{' '}
                  <span className="font-medium text-gray-700">{total}</span>{' '}
                  results
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={!canGoBack}
                    className={clsx(
                      'inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium',
                      'border border-gray-200 bg-white text-gray-700',
                      'hover:bg-gray-50 active:bg-gray-100',
                      'transition-colors',
                      'disabled:opacity-40 disabled:cursor-not-allowed'
                    )}
                  >
                    <ChevronLeft className="w-4 h-4" />
                    Previous
                  </button>
                  <span className="text-sm text-gray-500 px-2">
                    Page {page + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() =>
                      setPage((p) => Math.min(totalPages - 1, p + 1))
                    }
                    disabled={!canGoForward}
                    className={clsx(
                      'inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium',
                      'border border-gray-200 bg-white text-gray-700',
                      'hover:bg-gray-50 active:bg-gray-100',
                      'transition-colors',
                      'disabled:opacity-40 disabled:cursor-not-allowed'
                    )}
                  >
                    Next
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
