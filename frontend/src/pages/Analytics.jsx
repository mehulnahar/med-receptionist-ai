import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Phone, Calendar, TrendingUp, Zap, RefreshCw, BarChart3,
  Clock, Users, ArrowRight, AlertCircle,
} from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { format, subDays, parseISO } from 'date-fns'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DATE_RANGES = [
  { label: 'Today', days: 0 },
  { label: '7 Days', days: 7 },
  { label: '30 Days', days: 30 },
  { label: '90 Days', days: 90 },
]

const COLORS = {
  blue: '#2563eb',
  blueFill: '#3b82f6',
  blueLight: '#dbeafe',
  green: '#10b981',
  purple: '#8b5cf6',
  amber: '#f59e0b',
  red: '#ef4444',
  gray: '#6b7280',
  grayLight: '#f3f4f6',
}

const PIE_COLORS = [
  COLORS.blue,
  COLORS.green,
  COLORS.purple,
  COLORS.amber,
  COLORS.red,
  '#06b6d4',
  '#ec4899',
  '#14b8a6',
]

const FUNNEL_COLORS = [
  COLORS.blue,
  '#60a5fa',
  COLORS.green,
  '#34d399',
  '#6ee7b7',
]

const AUTO_REFRESH_INTERVAL = 60000 // 60 seconds

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function computeDateRange(rangeDays) {
  const toDate = format(new Date(), 'yyyy-MM-dd')
  const fromDate = format(subDays(new Date(), rangeDays), 'yyyy-MM-dd')
  return { fromDate, toDate }
}

function periodFromDays(days) {
  if (days <= 0) return 'today'
  if (days <= 7) return 'week'
  return 'month'
}

function formatHour(hour) {
  if (hour === 0) return '12 AM'
  if (hour === 12) return '12 PM'
  if (hour < 12) return `${hour} AM`
  return `${hour - 12} PM`
}

function formatPercent(value, total) {
  if (!total || total === 0) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** KPI card used in the overview row. */
function KPICard({ title, value, subtitle, icon: Icon, colorClass }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-shadow duration-200">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-500 truncate">{title}</p>
          <p className="mt-2 text-3xl font-bold text-gray-900 tracking-tight">
            {value ?? '--'}
          </p>
          {subtitle && (
            <p className="mt-1 text-sm text-gray-400">{subtitle}</p>
          )}
        </div>
        {Icon && (
          <div
            className={clsx(
              'flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center ring-4',
              colorClass
            )}
          >
            <Icon className="w-6 h-6" />
          </div>
        )}
      </div>
    </div>
  )
}

/** Section wrapper with title and optional subtitle. */
function ChartSection({ title, subtitle, children, className }) {
  return (
    <div
      className={clsx(
        'bg-white rounded-xl border border-gray-200 shadow-sm p-5',
        className
      )}
    >
      <div className="mb-4">
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        {subtitle && (
          <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
        )}
      </div>
      {children}
    </div>
  )
}

/** Skeleton placeholder for a chart while loading. */
function ChartSkeleton({ height = 300 }) {
  return (
    <div
      className="animate-pulse bg-gray-100 rounded-lg w-full"
      style={{ height }}
    />
  )
}

/** Empty data placeholder inside a chart section. */
function ChartEmpty({ message = 'No data available for this period' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
        <BarChart3 className="w-6 h-6 text-gray-400" />
      </div>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  )
}

/** Custom tooltip for recharts. */
function CustomTooltip({ active, payload, label, formatter }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-4 py-3 text-sm">
      <p className="font-medium text-gray-900 mb-1">{label}</p>
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-gray-600">{entry.name}:</span>
          <span className="font-semibold text-gray-900">
            {formatter ? formatter(entry.value) : entry.value}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Custom label for pie chart slices. */
function renderPieLabel({ name, percent }) {
  if (percent < 0.05) return null
  return `${name} ${(percent * 100).toFixed(0)}%`
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function Analytics() {
  // Date range state
  const [selectedRangeIdx, setSelectedRangeIdx] = useState(2) // default: 30 Days
  const selectedRange = DATE_RANGES[selectedRangeIdx]
  const { fromDate, toDate } = computeDateRange(selectedRange.days)

  // Data states
  const [overview, setOverview] = useState(null)
  const [callVolume, setCallVolume] = useState([])
  const [peakHours, setPeakHours] = useState([])
  const [bookingConversion, setBookingConversion] = useState(null)
  const [callOutcomes, setCallOutcomes] = useState(null)
  const [appointmentTypes, setAppointmentTypes] = useState([])

  // UI states
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)

  // Ref for auto-refresh interval
  const refreshIntervalRef = useRef(null)
  const fetchDataRef = useRef(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchData = useCallback(
    async (isRefresh = false) => {
      if (isRefresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)

      try {
        const params = { from_date: fromDate, to_date: toDate }
        const period = periodFromDays(selectedRange.days)

        const [
          overviewRes,
          volumeRes,
          peakRes,
          conversionRes,
          outcomesRes,
          typesRes,
        ] = await Promise.all([
          api.get('/analytics/overview', { params: { period } }).catch(() => null),
          api.get('/analytics/call-volume', { params }).catch(() => null),
          api.get('/analytics/peak-hours', { params }).catch(() => null),
          api.get('/analytics/booking-conversion', { params }).catch(() => null),
          api.get('/analytics/call-outcomes', { params }).catch(() => null),
          api.get('/analytics/appointment-types', { params }).catch(() => null),
        ])

        // Overview KPIs
        if (overviewRes?.data) {
          setOverview(overviewRes.data)
        }

        // Call volume timeline
        if (volumeRes?.data) {
          const raw = volumeRes.data.data || volumeRes.data || []
          setCallVolume(
            Array.isArray(raw)
              ? raw.map((d) => ({
                  ...d,
                  date: d.date || d.day,
                  dateFormatted: d.date
                    ? format(parseISO(d.date), 'MMM d')
                    : d.day || '',
                }))
              : []
          )
        }

        // Peak hours
        if (peakRes?.data) {
          const raw = peakRes.data.data || peakRes.data || []
          setPeakHours(
            Array.isArray(raw)
              ? raw.map((d) => ({
                  ...d,
                  hourLabel: formatHour(d.hour ?? d.hour_of_day ?? 0),
                  count: d.count ?? d.call_count ?? 0,
                }))
              : []
          )
        }

        // Booking conversion funnel
        if (conversionRes?.data) {
          setBookingConversion(conversionRes.data)
        }

        // Call outcomes / intents
        if (outcomesRes?.data) {
          setCallOutcomes(outcomesRes.data)
        }

        // Appointment types — normalize to {name, value} for Recharts
        if (typesRes?.data) {
          const raw = typesRes.data.data || typesRes.data || []
          setAppointmentTypes(
            Array.isArray(raw)
              ? raw.map((d) => ({
                  name: d.type_name || d.name || 'Unknown',
                  value: d.count || d.value || 0,
                  percentage: d.percentage || 0,
                }))
              : []
          )
        }
      } catch (err) {
        if (err.response?.status !== 401) {
          setError('Failed to load analytics data. Please try again.')
          console.error('Analytics fetch error:', err)
        }
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [fromDate, toDate, selectedRange.days]
  )

  // Fetch on mount and when date range changes
  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Keep ref current so the interval always calls the latest fetchData
  useEffect(() => {
    fetchDataRef.current = fetchData
  }, [fetchData])

  // Auto-refresh every 60 seconds (stable interval, no re-creation)
  useEffect(() => {
    refreshIntervalRef.current = setInterval(() => {
      fetchDataRef.current?.(true)
    }, AUTO_REFRESH_INTERVAL)

    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
      }
    }
  }, [])

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  // Build funnel stages from bookingConversion
  const funnelStages = (() => {
    if (!bookingConversion) return []
    const bc = bookingConversion
    const totalCalls = bc.total_calls ?? 0
    const intentToBook = bc.calls_with_intent_book ?? 0
    const booked = bc.appointments_booked ?? 0
    const confirmed = bc.appointments_confirmed ?? 0
    const completed = bc.appointments_completed ?? 0

    const stages = [
      { name: 'Total Calls', value: totalCalls },
      { name: 'Intent to Book', value: intentToBook },
      { name: 'Booked', value: booked },
      { name: 'Confirmed', value: confirmed },
      { name: 'Completed', value: completed },
    ]

    return stages.map((s) => ({
      ...s,
      percent: formatPercent(s.value, totalCalls),
    }))
  })()

  // Intent distribution from callOutcomes — normalize to {name, value} for Recharts
  const intentData = (() => {
    if (!callOutcomes) return []
    const raw = callOutcomes.intents || []
    return Array.isArray(raw)
      ? raw.map((d) => ({
          name: d.intent || d.name || 'Unknown',
          value: d.count || d.value || 0,
        }))
      : []
  })()

  // Language distribution from callOutcomes — normalize to {name, value}
  const languageData = (() => {
    if (!callOutcomes) return []
    const raw = callOutcomes.languages || []
    const langNames = { en: 'English', es: 'Spanish', el: 'Greek' }
    return Array.isArray(raw)
      ? raw.map((d) => ({
          name: langNames[d.language] || d.language || d.name || 'Unknown',
          value: d.count || d.value || 0,
        }))
      : []
  })()

  // Peak hour highlight
  const peakHourEntry = peakHours.reduce(
    (max, entry) => (entry.count > (max?.count ?? 0) ? entry : max),
    null
  )

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <LoadingSpinner
        fullPage={false}
        message="Loading analytics..."
        size="lg"
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* ================================================================
          HEADER
          ================================================================ */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Analytics
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Call volume, booking conversion, and performance insights
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Date range buttons */}
          <div className="inline-flex rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
            {DATE_RANGES.map((range, idx) => (
              <button
                key={range.label}
                onClick={() => setSelectedRangeIdx(idx)}
                className={clsx(
                  'px-3.5 py-2 text-sm font-medium transition-colors',
                  idx === selectedRangeIdx
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
                  idx > 0 && 'border-l border-gray-200'
                )}
              >
                {range.label}
              </button>
            ))}
          </div>

          {/* Refresh button */}
          <button
            onClick={() => fetchData(true)}
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
            onClick={() => fetchData(true)}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* ================================================================
          ROW 1: OVERVIEW KPI CARDS
          ================================================================ */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Total Calls"
          value={overview?.calls?.total ?? overview?.total_calls ?? '--'}
          subtitle={`${selectedRange.label} period`}
          icon={Phone}
          colorClass="bg-blue-100 ring-blue-50 text-blue-600"
        />
        <KPICard
          title="Appointments Booked"
          value={overview?.appointments?.booked ?? overview?.appointments_booked ?? '--'}
          subtitle="Via AI receptionist"
          icon={Calendar}
          colorClass="bg-green-100 ring-green-50 text-green-600"
        />
        <KPICard
          title="Booking Conversion"
          value={(() => {
            const total = overview?.calls?.total ?? 0
            const booked = overview?.appointments?.booked ?? 0
            if (total > 0) return `${Math.round((booked / total) * 100)}%`
            return '--'
          })()}
          subtitle="Calls that led to bookings"
          icon={TrendingUp}
          colorClass="bg-purple-100 ring-purple-50 text-purple-600"
        />
        <KPICard
          title="AI Success Rate"
          value={
            overview?.ai_performance?.success_rate != null
              ? `${Math.round(overview.ai_performance.success_rate)}%`
              : '--'
          }
          subtitle="Handled without escalation"
          icon={Zap}
          colorClass="bg-amber-100 ring-amber-50 text-amber-600"
        />
      </div>

      {/* ================================================================
          ROW 2: CALL VOLUME CHART (full width)
          ================================================================ */}
      <ChartSection
        title="Call Volume"
        subtitle={`${format(parseISO(fromDate), 'MMM d, yyyy')} - ${format(parseISO(toDate), 'MMM d, yyyy')}`}
      >
        {callVolume.length === 0 ? (
          <ChartEmpty message="No call volume data for this period" />
        ) : (
          <div style={{ width: '100%', height: 300 }}>
            <ResponsiveContainer>
              <AreaChart
                data={callVolume}
                margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="gradientBlue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={COLORS.blue} stopOpacity={0.15} />
                    <stop offset="95%" stopColor={COLORS.blue} stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#e5e7eb"
                  vertical={false}
                />
                <XAxis
                  dataKey="dateFormatted"
                  tick={{ fontSize: 12, fill: COLORS.gray }}
                  tickLine={false}
                  axisLine={{ stroke: '#e5e7eb' }}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: COLORS.gray }}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  content={
                    <CustomTooltip
                      formatter={(v) => v.toLocaleString()}
                    />
                  }
                />
                <Area
                  type="monotone"
                  dataKey="total"
                  name="Total Calls"
                  stroke={COLORS.blue}
                  strokeWidth={2.5}
                  fill="url(#gradientBlue)"
                  dot={false}
                  activeDot={{ r: 5, strokeWidth: 2, fill: '#fff' }}
                />
                <Area
                  type="monotone"
                  dataKey="missed"
                  name="Missed"
                  stroke={COLORS.red}
                  strokeWidth={2}
                  fill="none"
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, fill: '#fff' }}
                  strokeDasharray="4 2"
                />
                <Legend
                  verticalAlign="top"
                  align="right"
                  iconType="line"
                  wrapperStyle={{ fontSize: 12, paddingBottom: 8 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartSection>

      {/* ================================================================
          ROW 3: PEAK HOURS + BOOKING FUNNEL (side by side)
          ================================================================ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Peak Hours Bar Chart */}
        <ChartSection
          title="Peak Hours"
          subtitle={
            peakHourEntry
              ? `Busiest: ${peakHourEntry.hourLabel} (${peakHourEntry.count} calls)`
              : 'Call distribution by hour'
          }
        >
          {peakHours.length === 0 ? (
            <ChartEmpty message="No peak hours data available" />
          ) : (
            <div style={{ width: '100%', height: 280 }}>
              <ResponsiveContainer>
                <BarChart
                  data={peakHours}
                  margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#e5e7eb"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="hourLabel"
                    tick={{ fontSize: 11, fill: COLORS.gray }}
                    tickLine={false}
                    axisLine={{ stroke: '#e5e7eb' }}
                    interval={2}
                  />
                  <YAxis
                    tick={{ fontSize: 12, fill: COLORS.gray }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    content={<CustomTooltip />}
                  />
                  <Bar
                    dataKey="count"
                    name="Calls"
                    radius={[4, 4, 0, 0]}
                    maxBarSize={32}
                  >
                    {peakHours.map((entry, idx) => {
                      const isPeak =
                        peakHourEntry &&
                        (entry.hour ?? entry.hour_of_day) ===
                          (peakHourEntry.hour ?? peakHourEntry.hour_of_day)
                      // Intensity: deeper blue for more calls
                      const maxCount = peakHourEntry?.count || 1
                      const ratio = entry.count / maxCount
                      const opacity = Math.max(0.25, ratio)
                      return (
                        <Cell
                          key={idx}
                          fill={isPeak ? COLORS.blue : COLORS.blueFill}
                          fillOpacity={isPeak ? 1 : opacity}
                          stroke={isPeak ? COLORS.blue : 'none'}
                          strokeWidth={isPeak ? 2 : 0}
                        />
                      )
                    })}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartSection>

        {/* Booking Conversion Funnel */}
        <ChartSection
          title="Booking Funnel"
          subtitle="From call to completed appointment"
        >
          {funnelStages.length === 0 ||
          funnelStages.every((s) => s.value === 0) ? (
            <ChartEmpty message="No booking funnel data available" />
          ) : (
            <div className="space-y-3 py-2">
              {funnelStages.map((stage, idx) => {
                const maxVal = funnelStages[0]?.value || 1
                const widthPercent = Math.max(
                  12,
                  (stage.value / maxVal) * 100
                )
                return (
                  <div key={stage.name} className="group">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        {idx > 0 && (
                          <ArrowRight className="w-3.5 h-3.5 text-gray-300 -ml-0.5" />
                        )}
                        <span className="text-sm font-medium text-gray-700">
                          {stage.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-gray-900">
                          {stage.value.toLocaleString()}
                        </span>
                        <span className="text-xs text-gray-400">
                          {stage.percent}
                        </span>
                      </div>
                    </div>
                    <div className="w-full bg-gray-100 rounded-full h-7 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500 ease-out"
                        style={{
                          width: `${widthPercent}%`,
                          backgroundColor:
                            FUNNEL_COLORS[idx % FUNNEL_COLORS.length],
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </ChartSection>
      </div>

      {/* ================================================================
          ROW 4: CALL OUTCOMES + APPOINTMENT TYPES (side by side)
          ================================================================ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Caller Intent Distribution */}
        <ChartSection
          title="Caller Intent Distribution"
          subtitle="What callers are asking about"
        >
          {intentData.length === 0 && languageData.length === 0 ? (
            <ChartEmpty message="No caller intent data available" />
          ) : (
            <div className="space-y-6">
              {/* Pie chart for intents */}
              {intentData.length > 0 && (
                <div style={{ width: '100%', height: 220 }}>
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie
                        data={intentData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={85}
                        innerRadius={45}
                        paddingAngle={2}
                        label={renderPieLabel}
                        labelLine={{ stroke: '#d1d5db', strokeWidth: 1 }}
                      >
                        {intentData.map((_, idx) => (
                          <Cell
                            key={idx}
                            fill={PIE_COLORS[idx % PIE_COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value, name) => [
                          value.toLocaleString(),
                          name,
                        ]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Language distribution bars */}
              {languageData.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                    Language Distribution
                  </p>
                  <div className="space-y-2">
                    {languageData.map((lang, idx) => {
                      const total = languageData.reduce(
                        (sum, l) => sum + (l.value || l.count || 0),
                        0
                      )
                      const val = lang.value || lang.count || 0
                      const pct = total > 0 ? (val / total) * 100 : 0
                      return (
                        <div key={lang.name || lang.language || idx}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-sm text-gray-700 font-medium">
                              {lang.name || lang.language || 'Unknown'}
                            </span>
                            <span className="text-sm text-gray-500">
                              {val.toLocaleString()} ({Math.round(pct)}%)
                            </span>
                          </div>
                          <div className="w-full bg-gray-100 rounded-full h-2.5">
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{
                                width: `${Math.max(2, pct)}%`,
                                backgroundColor:
                                  PIE_COLORS[idx % PIE_COLORS.length],
                              }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </ChartSection>

        {/* Appointment Types Distribution */}
        <ChartSection
          title="Appointment Types"
          subtitle="Distribution of appointment categories"
        >
          {appointmentTypes.length === 0 ? (
            <ChartEmpty message="No appointment type data available" />
          ) : (
            <div className="space-y-4">
              {/* Pie chart */}
              <div style={{ width: '100%', height: 220 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie
                      data={appointmentTypes}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={85}
                      innerRadius={45}
                      paddingAngle={2}
                      label={renderPieLabel}
                      labelLine={{ stroke: '#d1d5db', strokeWidth: 1 }}
                    >
                      {appointmentTypes.map((_, idx) => (
                        <Cell
                          key={idx}
                          fill={PIE_COLORS[idx % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value, name) => [
                        value.toLocaleString(),
                        name,
                      ]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              {/* Legend / detail list */}
              <div className="grid grid-cols-2 gap-2">
                {appointmentTypes.map((type, idx) => {
                  const total = appointmentTypes.reduce(
                    (sum, t) => sum + (t.value || t.count || 0),
                    0
                  )
                  const val = type.value || type.count || 0
                  return (
                    <div
                      key={type.name || idx}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50"
                    >
                      <span
                        className="w-3 h-3 rounded-full flex-shrink-0"
                        style={{
                          backgroundColor:
                            PIE_COLORS[idx % PIE_COLORS.length],
                        }}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-700 truncate">
                          {type.name}
                        </p>
                        <p className="text-xs text-gray-500">
                          {val.toLocaleString()} ({formatPercent(val, total)})
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </ChartSection>
      </div>
    </div>
  )
}
