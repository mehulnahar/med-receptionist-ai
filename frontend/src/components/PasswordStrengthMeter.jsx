import { useMemo } from 'react'

/**
 * Password Strength Meter — visual indicator for HIPAA-compliant passwords.
 *
 * Shows a colored bar and text indicating password strength.
 * Requirements: 12+ chars, uppercase, lowercase, number, special char.
 */
export default function PasswordStrengthMeter({ password = '' }) {
  const analysis = useMemo(() => {
    if (!password) return { score: 0, label: '', color: '', errors: [] }

    let score = 0
    const errors = []

    // Length checks
    if (password.length >= 8) score += 10
    if (password.length >= 12) score += 15
    if (password.length >= 16) score += 10
    if (password.length >= 20) score += 5
    if (password.length < 12) errors.push('At least 12 characters')

    // Character variety
    if (/[a-z]/.test(password)) score += 10
    else errors.push('Lowercase letter')

    if (/[A-Z]/.test(password)) score += 10
    else errors.push('Uppercase letter')

    if (/\d/.test(password)) score += 10
    else errors.push('Number')

    if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(password)) score += 15
    else errors.push('Special character')

    // Diversity
    const unique = new Set(password).size
    if (unique >= 8) score += 5
    if (unique >= 12) score += 5
    if (unique >= 16) score += 5

    score = Math.min(score, 100)

    let label, color
    if (score >= 80) { label = 'Strong'; color = 'bg-green-500' }
    else if (score >= 60) { label = 'Good'; color = 'bg-blue-500' }
    else if (score >= 40) { label = 'Fair'; color = 'bg-yellow-500' }
    else if (score >= 20) { label = 'Weak'; color = 'bg-orange-500' }
    else { label = 'Very Weak'; color = 'bg-red-500' }

    return { score, label, color, errors }
  }, [password])

  if (!password) return null

  return (
    <div className="mt-2">
      {/* Strength bar */}
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${analysis.color}`}
          style={{ width: `${analysis.score}%` }}
        />
      </div>

      {/* Label */}
      <div className="flex justify-between items-center mt-1">
        <span className="text-xs text-gray-500">
          Password strength: <span className="font-medium">{analysis.label}</span>
        </span>
        <span className="text-xs text-gray-400">{analysis.score}%</span>
      </div>

      {/* Missing requirements */}
      {analysis.errors.length > 0 && (
        <div className="mt-2">
          <p className="text-xs text-gray-500 mb-1">Missing:</p>
          <ul className="text-xs text-red-500 space-y-0.5">
            {analysis.errors.map((err, i) => (
              <li key={i} className="flex items-center">
                <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
                {err}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
