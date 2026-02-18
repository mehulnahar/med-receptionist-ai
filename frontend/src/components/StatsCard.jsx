import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import clsx from 'clsx'

const COLOR_MAP = {
  blue: {
    iconBg: 'bg-primary-100',
    iconText: 'text-primary-600',
    ring: 'ring-primary-50',
  },
  green: {
    iconBg: 'bg-green-100',
    iconText: 'text-green-600',
    ring: 'ring-green-50',
  },
  red: {
    iconBg: 'bg-red-100',
    iconText: 'text-red-600',
    ring: 'ring-red-50',
  },
  yellow: {
    iconBg: 'bg-amber-100',
    iconText: 'text-amber-600',
    ring: 'ring-amber-50',
  },
  purple: {
    iconBg: 'bg-purple-100',
    iconText: 'text-purple-600',
    ring: 'ring-purple-50',
  },
  indigo: {
    iconBg: 'bg-indigo-100',
    iconText: 'text-indigo-600',
    ring: 'ring-indigo-50',
  },
  orange: {
    iconBg: 'bg-orange-100',
    iconText: 'text-orange-600',
    ring: 'ring-orange-50',
  },
}

const TREND_CONFIG = {
  up: {
    icon: TrendingUp,
    text: 'text-green-600',
    bg: 'bg-green-50',
  },
  down: {
    icon: TrendingDown,
    text: 'text-red-600',
    bg: 'bg-red-50',
  },
  neutral: {
    icon: Minus,
    text: 'text-gray-500',
    bg: 'bg-gray-50',
  },
}

/**
 * StatsCard - Reusable stats display card.
 *
 * Props:
 *   title       - Card title (e.g. "Today's Appointments")
 *   value       - Primary value to display (number or string)
 *   subtitle    - Optional secondary text beneath value
 *   icon        - Lucide icon component
 *   trend       - "up" | "down" | "neutral" - direction indicator
 *   trendValue  - Text for the trend badge (e.g. "+15%")
 *   color       - "blue" | "green" | "red" | "yellow" | "purple" | "indigo" | "orange"
 *   className   - Additional container className
 */
export default function StatsCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  trendValue,
  color = 'blue',
  className,
}) {
  const colors = COLOR_MAP[color] || COLOR_MAP.blue
  const trendConfig = trend ? TREND_CONFIG[trend] : null
  const TrendIcon = trendConfig?.icon

  return (
    <div
      className={clsx(
        'bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-shadow duration-200',
        className
      )}
    >
      <div className="flex items-start justify-between">
        {/* Left: title + value */}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-500 truncate">{title}</p>
          <p className="mt-2 text-3xl font-bold text-gray-900 tracking-tight">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-gray-400">{subtitle}</p>
          )}
        </div>

        {/* Right: icon */}
        {Icon && (
          <div
            className={clsx(
              'flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center ring-4',
              colors.iconBg,
              colors.ring
            )}
          >
            <Icon className={clsx('w-6 h-6', colors.iconText)} />
          </div>
        )}
      </div>

      {/* Trend indicator */}
      {trendConfig && trendValue && (
        <div className="mt-4 flex items-center gap-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
              trendConfig.bg,
              trendConfig.text
            )}
          >
            {TrendIcon && <TrendIcon className="w-3.5 h-3.5" />}
            {trendValue}
          </span>
          {subtitle ? null : (
            <span className="text-xs text-gray-400">vs last period</span>
          )}
        </div>
      )}
    </div>
  )
}
