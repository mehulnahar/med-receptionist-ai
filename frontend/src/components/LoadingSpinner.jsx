import { Loader2 } from 'lucide-react'
import clsx from 'clsx'

/**
 * LoadingSpinner - Full-page or inline loading indicator.
 *
 * Props:
 *   fullPage  - If true, renders a centered full-screen overlay. If false (default),
 *               renders an inline centered spinner.
 *   message   - Optional text displayed beneath the spinner.
 *   size      - "sm" | "md" | "lg" - spinner size. Defaults to "md".
 *   className - Additional className for the wrapper.
 */
export default function LoadingSpinner({
  fullPage = false,
  message,
  size = 'md',
  className,
}) {
  const sizeClasses = {
    sm: 'w-5 h-5',
    md: 'w-8 h-8',
    lg: 'w-12 h-12',
  }

  const spinner = (
    <div
      className={clsx(
        'flex flex-col items-center justify-center gap-3',
        className
      )}
    >
      <div className="relative">
        {/* Faded background ring */}
        <div
          className={clsx(
            'rounded-full border-4 border-primary-100',
            sizeClasses[size]
          )}
        />
        {/* Spinning foreground icon */}
        <Loader2
          className={clsx(
            'absolute inset-0 text-primary-600 animate-spin',
            sizeClasses[size]
          )}
        />
      </div>
      {message && (
        <p
          className={clsx(
            'font-medium text-gray-500',
            size === 'sm' ? 'text-xs' : 'text-sm'
          )}
        >
          {message}
        </p>
      )}
    </div>
  )

  if (fullPage) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/80 backdrop-blur-sm">
        {spinner}
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center py-12">
      {spinner}
    </div>
  )
}
