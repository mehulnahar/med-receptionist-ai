import { Inbox } from 'lucide-react'
import clsx from 'clsx'

/**
 * EmptyState - Placeholder shown when a list or section has no data.
 *
 * Props:
 *   icon          - Lucide icon component (defaults to Inbox)
 *   title         - Heading text (e.g. "No appointments found")
 *   description   - Supporting description text
 *   actionLabel   - Optional button label (e.g. "Create Appointment")
 *   onAction      - Callback when the action button is clicked
 *   className     - Additional className for the wrapper
 */
export default function EmptyState({
  icon: Icon = Inbox,
  title = 'No data found',
  description,
  actionLabel,
  onAction,
  className,
}) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center py-16 px-6 text-center',
        className
      )}
    >
      {/* Icon circle */}
      <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center mb-5">
        <Icon className="w-8 h-8 text-gray-400" />
      </div>

      {/* Title */}
      <h3 className="text-lg font-semibold text-gray-900 mb-1">{title}</h3>

      {/* Description */}
      {description && (
        <p className="text-sm text-gray-500 max-w-sm mb-6">{description}</p>
      )}

      {/* Action button */}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2 transition-colors shadow-sm"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
