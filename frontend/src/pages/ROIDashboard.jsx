import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Phone,
  DollarSign,
  Clock,
  TrendingUp,
  Shield,
  ThumbsUp,
  BarChart3,
  CalendarCheck,
  RefreshCw,
  AlertCircle,
} from 'lucide-react'
import { format, parseISO } from 'date-fns'
import clsx from 'clsx'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import StatsCard from '../components/StatsCard'
import LoadingSpinner from '../components/LoadingSpinner'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a number as currency with $ sign and commas, no decimals. */
function formatMoney(value) {
  if (value == null || isNaN(value)) return '$0'
  return '$' + Math.round(value).toLocaleString('en-US')
}

/** Format a number with commas. */
function formatNumber(value) {
  if (value == null || isNaN(value)) return '0'
  return Number(value).toLocaleString('en-US')
}

/** Format seconds into a human-readable duration string. */
function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0m 0s'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

/** Format a percentage with one decimal place. */
function formatPercent(value) {
  if (value == null || isNaN(value)) return '0%'
  return `${Number(value).toFixed(1)}%`
}

// ---------------------------------------------------------------------------
// TrendBarChart — lightweight inline SVG bar chart
// ---------------------------------------------------------------------------

const CHART_COLORS = {
  totalCalls: '#3b82f6',    // blue-500
  aiResolved: '#10b981',    // emerald-500
  appointments: '#6366f1',  // indigo-500
}

function TrendBarChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-56 text-sm text-gray-400">
        No trend data available
      </div>
    )
  }

  const maxValue = Math.max(
    ...data.map((d) => Math.max(d.total_calls || 0, d.ai_resolved || 0, d.ai_booked_appointments || 0)),
    1
  )

  const chartWidth = 720
  const chartHeight = 200
  const barGroupWidth = chartWidth / data.length
  const barWidth = Math.max(barGroupWidth * 0.2, 6)
  const gap = 4
  const paddingBottom = 28

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${chartWidth} ${chartHeight + paddingBottom}`}
        className="w-full h-auto min-w-[480px]"
        role="img"
        aria-label="Weekly trend bar chart"
      >
        {/* Horizontal grid lines */}
        {[0.25, 0.5, 0.75, 1].map((fraction) => {
          const y = chartHeight - fraction * chartHeight
          return (
            <g key={fraction}>
              <line
                x1={0}
                y1={y}
                x2={chartWidth}
                y2={y}
                stroke="#e5e7eb"
                strokeDasharray="4 4"
              />
              <text
                x={4}
                y={y - 4}
                fill="#9ca3af"
                fontSize="10"
                fontFamily="sans-serif"
              >
                {Math.round(maxValue * fraction)}
              </text>
            </g>
          )
        })}

        {/* Baseline */}
        <line
          x1={0}
          y1={chartHeight}
          x2={chartWidth}
          y2={chartHeight}
          stroke="#d1d5db"
        />

        {/* Bar groups */}
        {data.map((week, i) => {
          const groupX = i * barGroupWidth + barGroupWidth / 2
          const totalH = maxValue > 0 ? ((week.total_calls || 0) / maxValue) * chartHeight : 0
          const resolvedH = maxValue > 0 ? ((week.ai_resolved || 0) / maxValue) * chartHeight : 0
          const apptH = maxValue > 0 ? ((week.ai_booked_appointments || 0) / maxValue) * chartHeight : 0

          const weekLabel = week.week_start
            ? format(parseISO(week.week_start), 'MMM d')
            : `W${i + 1}`

          return (
            <g key={i}>
              {/* Total calls bar */}
              <rect
                x={groupX - barWidth * 1.5 - gap}
                y={chartHeight - totalH}
                width={barWidth}
                height={Math.max(totalH, 0)}
                fill={CHART_COLORS.totalCalls}
                rx={2}
              />
              {/* AI resolved bar */}
              <rect
                x={groupX - barWidth * 0.5}
                y={chartHeight - resolvedH}
                width={barWidth}
                height={Math.max(resolvedH, 0)}
                fill={CHART_COLORS.aiResolved}
                rx={2}
              />
              {/* Appointments bar */}
              <rect
                x={groupX + barWidth * 0.5 + gap}
                y={chartHeight - apptH}
                width={barWidth}
                height={Math.max(apptH, 0)}
                fill={CHART_COLORS.appointments}
                rx={2}
              />
              {/* Week label */}
              <text
                x={groupX}
                y={chartHeight + 16}
                textAnchor="middle"
                fill="#6b7280"
                fontSize="11"
                fontFamily="sans-serif"
              >
                {weekLabel}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-3">
        <div className="flex items-center gap-1.5">
          <span
            className="w-3 h-3 rounded-sm inline-block"
            style={{ backgroundColor: CHART_COLORS.totalCalls }}
          />
          <span className="text-xs text-gray-500">Total Calls</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-3 h-3 rounded-sm inline-block"
            style={{ backgroundColor: CHART_COLORS.aiResolved }}
          />
          <span className="text-xs text-gray-500">AI Resolved</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="w-3 h-3 rounded-sm inline-block"
            style={{ backgroundColor: CHART_COLORS.appointments }}
          />
          <span className="text-xs text-gray-500">Appointments Booked</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ROIDashboard Component
// ---------------------------------------------------------------------------

export default function ROIDashboard() {
  const { user } = useAuth()
  const mountedRef = useRef(true)

  const [period, setPeriod] = useState('month')
  const [summary, setSummary] = useState(null)
  const [trends, setTrends] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  // -------------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------------

  const fetchSummary = useCallback(async (selectedPeriod, isRefresh = false) => {
    try {
      const res = await api.get('/roi/summary', {
        params: { period: selectedPeriod },
      })
      if (!mountedRef.current) return
      setSummary(res.data)
    } catch (err) {
      if (!mountedRef.current) return
      if (err.response?.status !== 401) {
        throw err
      }
    }
  }, [])

  const fetchTrends = useCallback(async () => {
    try {
      const res = await api.get('/roi/trends', {
        params: { weeks: 8 },
      })
      if (!mountedRef.current) return
      setTrends(res.data || [])
    } catch (err) {
      if (!mountedRef.current) return
      if (err.response?.status !== 401) {
        console.error('Failed to fetch trends:', err)
      }
    }
  }, [])

  const fetchAll = useCallback(async (selectedPeriod, isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)

    try {
      await Promise.all([
        fetchSummary(selectedPeriod, isRefresh),
        fetchTrends(),
      ])
    } catch (err) {
      if (mountedRef.current && err.response?.status !== 401) {
        setError(
          err.response?.data?.detail ||
            'Failed to load ROI data. Please try again.'
        )
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [fetchSummary, fetchTrends])

  // Initial load and period change
  useEffect(() => {
    fetchAll(period)
  }, [period, fetchAll])

  const handleRefresh = () => {
    fetchAll(period, true)
  }

  const handlePeriodChange = (newPeriod) => {
    setPeriod(newPeriod)
  }

  // -------------------------------------------------------------------------
  // Derived values from summary
  // -------------------------------------------------------------------------

  const calls = summary?.calls || {}
  const appointments = summary?.appointments || {}
  const savings = summary?.savings || {}
  const insurance = summary?.insurance || {}
  const reminders = summary?.reminders || {}
  const satisfaction = summary?.satisfaction || {}

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (loading) {
    return (
      <LoadingSpinner
        fullPage={false}
        message="Loading ROI dashboard..."
        size="lg"
      />
    )
  }

  return (
    <div className="space-y-8">
      {/* ================================================================
          HEADER
          ================================================================ */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            ROI Dashboard
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {summary?.period || 'This Month'} -- AI performance and cost savings overview
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Period toggle */}
          <div className="inline-flex items-center rounded-lg border border-gray-200 bg-white shadow-sm p-0.5">
            <button
              onClick={() => handlePeriodChange('week')}
              className={clsx(
                'px-4 py-1.5 rounded-md text-sm font-medium transition-colors',
                period === 'week'
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              )}
            >
              This Week
            </button>
            <button
              onClick={() => handlePeriodChange('month')}
              className={clsx(
                'px-4 py-1.5 rounded-md text-sm font-medium transition-colors',
                period === 'month'
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              )}
            >
              This Month
            </button>
          </div>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
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
            onClick={handleRefresh}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* ================================================================
          KEY METRIC CARDS
          ================================================================ */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <StatsCard
          title="Total Calls"
          value={formatNumber(calls.total)}
          icon={Phone}
          color="blue"
          subtitle={`${formatNumber(calls.ai_resolved)} resolved by AI, ${formatNumber(calls.transferred)} transferred`}
        />
        <StatsCard
          title="AI Resolution Rate"
          value={formatPercent(calls.resolution_rate)}
          icon={TrendingUp}
          color="green"
          subtitle={`Avg duration: ${formatDuration(calls.avg_duration_seconds)}`}
        />
        <StatsCard
          title="Staff Hours Saved"
          value={`${(savings.staff_hours_saved || 0).toFixed(1)}h`}
          icon={Clock}
          color="purple"
          subtitle={`Worth ${formatMoney(savings.staff_cost_saved)} in labor costs`}
        />
        <StatsCard
          title="Monthly Savings"
          value={formatMoney(savings.estimated_monthly_savings)}
          icon={DollarSign}
          color="green"
          subtitle={`AI cost: ${formatMoney(savings.ai_monthly_cost)}/mo`}
        />
        <StatsCard
          title="No-Shows Prevented"
          value={formatNumber(savings.noshows_prevented)}
          icon={CalendarCheck}
          color="blue"
          subtitle={`${formatMoney(savings.revenue_protected)} revenue protected`}
        />
        <StatsCard
          title="Satisfaction Score"
          value={
            satisfaction.total_surveys > 0
              ? `${(satisfaction.average_score || 0).toFixed(1)}/5`
              : '--'
          }
          icon={ThumbsUp}
          color="green"
          subtitle={`${formatNumber(satisfaction.total_surveys)} survey responses`}
        />
      </div>

      {/* ================================================================
          WEEKLY TRENDS CHART
          ================================================================ */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
          <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
            <BarChart3 className="w-4 h-4 text-blue-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Weekly Trends
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Last {trends.length || 8} weeks of call and appointment activity
            </p>
          </div>
        </div>
        <div className="p-5">
          <TrendBarChart data={trends} />
        </div>
      </div>

      {/* ================================================================
          BOTTOM ROW: Insurance + Savings Comparison
          ================================================================ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Insurance Verification Stats */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
            <div className="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center">
              <Shield className="w-4 h-4 text-green-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                Insurance Verification
              </h2>
              <p className="text-sm text-gray-500 mt-0.5">
                Automated eligibility checks
              </p>
            </div>
          </div>
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Total Verifications</span>
              <span className="text-sm font-semibold text-gray-900">
                {formatNumber(insurance.total_verifications)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Successful</span>
              <span className="text-sm font-semibold text-green-600">
                {formatNumber(insurance.successful)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Success Rate</span>
              <span className="text-sm font-semibold text-gray-900">
                {insurance.total_verifications > 0
                  ? formatPercent(
                      (insurance.successful / insurance.total_verifications) * 100
                    )
                  : '--'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Reminders Sent</span>
              <span className="text-sm font-semibold text-gray-900">
                {formatNumber(reminders.sent)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">AI-Booked Appointments</span>
              <span className="text-sm font-semibold text-blue-600">
                {formatNumber(appointments.ai_booked)}
              </span>
            </div>

            {/* Success rate bar */}
            {insurance.total_verifications > 0 && (
              <div className="pt-2">
                <div className="w-full bg-gray-100 rounded-full h-2.5">
                  <div
                    className="bg-green-500 rounded-full h-2.5 transition-all duration-500"
                    style={{
                      width: `${Math.min(
                        (insurance.successful / insurance.total_verifications) * 100,
                        100
                      )}%`,
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Savings Comparison: AI vs Human */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
              <DollarSign className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                Cost Comparison
              </h2>
              <p className="text-sm text-gray-500 mt-0.5">
                AI receptionist vs. human receptionist
              </p>
            </div>
          </div>
          <div className="p-5 space-y-5">
            {/* Comparison bars */}
            <div className="space-y-3">
              {/* Human receptionist cost */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm text-gray-600">Human Receptionist</span>
                  <span className="text-sm font-semibold text-gray-900">
                    {formatMoney(savings.vs_human_receptionist)}/mo
                  </span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-3">
                  <div
                    className="bg-gray-400 rounded-full h-3 transition-all duration-500"
                    style={{
                      width: savings.vs_human_receptionist > 0 ? '100%' : '0%',
                    }}
                  />
                </div>
              </div>

              {/* AI cost */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm text-gray-600">AI Receptionist</span>
                  <span className="text-sm font-semibold text-green-600">
                    {formatMoney(savings.ai_monthly_cost)}/mo
                  </span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-3">
                  <div
                    className="bg-green-500 rounded-full h-3 transition-all duration-500"
                    style={{
                      width:
                        savings.vs_human_receptionist > 0
                          ? `${Math.min(
                              ((savings.ai_monthly_cost || 0) /
                                savings.vs_human_receptionist) *
                                100,
                              100
                            )}%`
                          : '0%',
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Savings highlight */}
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-green-800">
                    Monthly Savings
                  </p>
                  <p className="text-xs text-green-600 mt-0.5">
                    Compared to full-time receptionist
                  </p>
                </div>
                <p className="text-2xl font-bold text-green-700">
                  {formatMoney(savings.estimated_monthly_savings)}
                </p>
              </div>
            </div>

            {/* Additional savings detail */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">Staff Cost Saved</p>
                <p className="text-lg font-bold text-gray-900 mt-1">
                  {formatMoney(savings.staff_cost_saved)}
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">Revenue Protected</p>
                <p className="text-lg font-bold text-gray-900 mt-1">
                  {formatMoney(savings.revenue_protected)}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
