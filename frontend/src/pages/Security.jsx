import { useState, useEffect } from 'react'
import { ShieldCheck, ShieldOff, Key, Lock, Eye, EyeOff, CheckCircle2, XCircle, AlertCircle, Copy, Check } from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'

/**
 * Security page — MFA setup/disable + Change Password with strength meter.
 * HIPAA compliance features accessible to all authenticated users.
 */
export default function Security() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Security Settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage your two-factor authentication and password
        </p>
      </div>

      <MFASection />
      <ChangePasswordSection />
    </div>
  )
}

// ─────────────────────────────────────────────
// MFA Section
// ─────────────────────────────────────────────
function MFASection() {
  const [mfaEnabled, setMfaEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [setupMode, setSetupMode] = useState(false)
  const [secret, setSecret] = useState('')
  const [uri, setUri] = useState('')
  const [code, setCode] = useState('')
  const [backupCodes, setBackupCodes] = useState([])
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [disableCode, setDisableCode] = useState('')
  const [showDisable, setShowDisable] = useState(false)
  const [copiedCodes, setCopiedCodes] = useState(false)

  useEffect(() => {
    fetchMFAStatus()
  }, [])

  const fetchMFAStatus = async () => {
    try {
      const { data } = await api.get('/hipaa/mfa/status')
      setMfaEnabled(data.mfa_enabled)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const handleSetup = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const { data } = await api.post('/hipaa/mfa/setup')
      setSecret(data.secret)
      setUri(data.uri)
      setSetupMode(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start MFA setup')
    } finally {
      setSubmitting(false)
    }
  }

  const handleVerifySetup = async (e) => {
    e.preventDefault()
    if (code.length !== 6) {
      setError('Please enter a 6-digit code')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      const { data } = await api.post('/hipaa/mfa/verify-setup', { code })
      setBackupCodes(data.backup_codes || [])
      setMfaEnabled(true)
      setSetupMode(false)
      setSuccess('MFA enabled successfully! Save your backup codes.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid code. Try again.')
      setCode('')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDisable = async (e) => {
    e.preventDefault()
    if (disableCode.length !== 6) {
      setError('Please enter a 6-digit code')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await api.post('/hipaa/mfa/disable', { code: disableCode })
      setMfaEnabled(false)
      setShowDisable(false)
      setDisableCode('')
      setSuccess('MFA has been disabled.')
      setBackupCodes([])
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid code.')
      setDisableCode('')
    } finally {
      setSubmitting(false)
    }
  }

  const copyBackupCodes = () => {
    navigator.clipboard.writeText(backupCodes.join('\n'))
    setCopiedCodes(true)
    setTimeout(() => setCopiedCodes(false), 2000)
  }

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="animate-pulse flex gap-4">
          <div className="w-12 h-12 bg-gray-200 rounded-lg" />
          <div className="flex-1 space-y-2">
            <div className="h-4 bg-gray-200 rounded w-1/3" />
            <div className="h-3 bg-gray-100 rounded w-2/3" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
      <div className="flex items-start gap-4">
        <div className={clsx(
          'w-12 h-12 rounded-lg flex items-center justify-center',
          mfaEnabled ? 'bg-green-100' : 'bg-gray-100'
        )}>
          {mfaEnabled ? (
            <ShieldCheck className="w-6 h-6 text-green-600" />
          ) : (
            <ShieldOff className="w-6 h-6 text-gray-400" />
          )}
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-gray-900">Two-Factor Authentication</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {mfaEnabled
              ? 'Your account is protected with TOTP two-factor authentication.'
              : 'Add an extra layer of security to your account using Google Authenticator or similar apps.'
            }
          </p>
        </div>
        <span className={clsx(
          'px-3 py-1 rounded-full text-xs font-medium',
          mfaEnabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
        )}>
          {mfaEnabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>

      {/* Error/Success messages */}
      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">
          <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Setup mode */}
      {setupMode && (
        <div className="border border-amber-200 bg-amber-50 rounded-lg p-5 space-y-4">
          <h3 className="text-sm font-semibold text-amber-900">Setup Instructions</h3>
          <ol className="text-sm text-amber-800 space-y-2 list-decimal list-inside">
            <li>Open Google Authenticator (or any TOTP app) on your phone</li>
            <li>Add a new account manually using this secret key:</li>
          </ol>
          <div className="bg-white border border-amber-300 rounded-lg px-4 py-3 font-mono text-center text-lg tracking-wider text-gray-900 select-all">
            {secret}
          </div>
          <p className="text-xs text-amber-700">Or scan this URI in your authenticator app</p>
          <form onSubmit={handleVerifySetup} className="flex gap-3">
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="Enter 6-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-center font-mono text-lg tracking-widest focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
            />
            <button
              type="submit"
              disabled={submitting || code.length !== 6}
              className="px-5 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Verifying...' : 'Verify'}
            </button>
          </form>
          <button
            type="button"
            onClick={() => { setSetupMode(false); setCode(''); setError(null) }}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Backup codes display */}
      {backupCodes.length > 0 && (
        <div className="border border-green-200 bg-green-50 rounded-lg p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-green-900">Backup Codes</h3>
            <button
              onClick={copyBackupCodes}
              className="flex items-center gap-1 text-xs text-green-700 hover:text-green-900 transition-colors"
            >
              {copiedCodes ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copiedCodes ? 'Copied!' : 'Copy all'}
            </button>
          </div>
          <p className="text-xs text-green-700">
            Save these codes securely. Each can be used once if you lose access to your authenticator app.
          </p>
          <div className="grid grid-cols-2 gap-2">
            {backupCodes.map((code, i) => (
              <div key={i} className="bg-white border border-green-200 rounded px-3 py-1.5 font-mono text-sm text-center text-gray-800">
                {code}
              </div>
            ))}
          </div>
          <button
            onClick={() => setBackupCodes([])}
            className="text-xs text-green-600 hover:text-green-800"
          >
            I've saved my codes — dismiss
          </button>
        </div>
      )}

      {/* Disable MFA */}
      {mfaEnabled && !setupMode && showDisable && (
        <form onSubmit={handleDisable} className="border border-red-200 bg-red-50 rounded-lg p-5 space-y-3">
          <h3 className="text-sm font-semibold text-red-900">Disable Two-Factor Authentication</h3>
          <p className="text-xs text-red-700">Enter your current authenticator code to disable MFA.</p>
          <div className="flex gap-3">
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="6-digit code"
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-center font-mono text-lg tracking-widest focus:ring-2 focus:ring-red-500/40 focus:border-red-500"
            />
            <button
              type="submit"
              disabled={submitting || disableCode.length !== 6}
              className="px-5 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Disabling...' : 'Disable'}
            </button>
          </div>
          <button
            type="button"
            onClick={() => { setShowDisable(false); setDisableCode(''); setError(null) }}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
        </form>
      )}

      {/* Action buttons */}
      {!setupMode && !showDisable && (
        <div className="flex gap-3">
          {!mfaEnabled ? (
            <button
              onClick={handleSetup}
              disabled={submitting}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors shadow-sm"
            >
              <ShieldCheck className="w-4 h-4" />
              Enable MFA
            </button>
          ) : (
            <button
              onClick={() => setShowDisable(true)}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-red-300 text-red-600 hover:bg-red-50 rounded-lg text-sm font-medium transition-colors"
            >
              <ShieldOff className="w-4 h-4" />
              Disable MFA
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────
// Change Password Section
// ─────────────────────────────────────────────
function ChangePasswordSection() {
  const { user } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // Password strength calculation
  const getStrength = (pw) => {
    if (!pw) return { score: 0, label: '', color: 'gray' }
    let score = 0
    if (pw.length >= 8) score += 10
    if (pw.length >= 12) score += 15
    if (pw.length >= 16) score += 10
    if (pw.length >= 20) score += 5
    if (/[a-z]/.test(pw)) score += 10
    if (/[A-Z]/.test(pw)) score += 10
    if (/\d/.test(pw)) score += 10
    if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(pw)) score += 15
    const unique = new Set(pw).size
    if (unique >= 8) score += 5
    if (unique >= 12) score += 5
    if (unique >= 16) score += 5
    score = Math.min(score, 100)

    if (score < 30) return { score, label: 'Weak', color: 'red' }
    if (score < 60) return { score, label: 'Fair', color: 'amber' }
    if (score < 80) return { score, label: 'Good', color: 'yellow' }
    return { score, label: 'Strong', color: 'green' }
  }

  const strength = getStrength(newPassword)

  const requirements = [
    { met: newPassword.length >= 12, text: 'At least 12 characters' },
    { met: /[A-Z]/.test(newPassword), text: 'Uppercase letter' },
    { met: /[a-z]/.test(newPassword), text: 'Lowercase letter' },
    { met: /\d/.test(newPassword), text: 'Number' },
    { met: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(newPassword), text: 'Special character' },
  ]

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)

    if (!currentPassword) {
      setError('Please enter your current password')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match')
      return
    }
    if (newPassword.length < 12) {
      setError('Password must be at least 12 characters')
      return
    }
    if (!requirements.every(r => r.met)) {
      setError('Password does not meet all requirements')
      return
    }

    setSubmitting(true)
    try {
      await api.put('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setSuccess('Password changed successfully!')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to change password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-lg flex items-center justify-center bg-blue-100">
          <Key className="w-6 h-6 text-blue-600" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Change Password</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            HIPAA requires passwords to be changed every 90 days with strong complexity requirements.
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">
          <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{success}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Current password */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Current Password</label>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Lock className="w-4 h-4 text-gray-400" />
            </div>
            <input
              type={showCurrent ? 'text' : 'password'}
              value={currentPassword}
              onChange={(e) => { setCurrentPassword(e.target.value); setError(null) }}
              className="w-full pl-10 pr-10 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 text-sm"
              placeholder="Enter current password"
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowCurrent(p => !p)}
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
            >
              {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {/* New password */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">New Password</label>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Lock className="w-4 h-4 text-gray-400" />
            </div>
            <input
              type={showNew ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => { setNewPassword(e.target.value); setError(null) }}
              className="w-full pl-10 pr-10 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 text-sm"
              placeholder="Enter new password (min 12 characters)"
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowNew(p => !p)}
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
            >
              {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          {/* Strength bar */}
          {newPassword && (
            <div className="mt-2 space-y-2">
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className={clsx('h-full rounded-full transition-all duration-300', {
                      'bg-red-500': strength.color === 'red',
                      'bg-amber-500': strength.color === 'amber',
                      'bg-yellow-500': strength.color === 'yellow',
                      'bg-green-500': strength.color === 'green',
                    })}
                    style={{ width: `${strength.score}%` }}
                  />
                </div>
                <span className={clsx('text-xs font-medium', {
                  'text-red-600': strength.color === 'red',
                  'text-amber-600': strength.color === 'amber',
                  'text-yellow-600': strength.color === 'yellow',
                  'text-green-600': strength.color === 'green',
                })}>
                  {strength.label}
                </span>
              </div>

              {/* Requirements checklist */}
              <div className="grid grid-cols-2 gap-1">
                {requirements.map((req, i) => (
                  <div key={i} className="flex items-center gap-1.5 text-xs">
                    {req.met ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-gray-300" />
                    )}
                    <span className={req.met ? 'text-green-700' : 'text-gray-400'}>{req.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Confirm new password */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Confirm New Password</label>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Lock className="w-4 h-4 text-gray-400" />
            </div>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => { setConfirmPassword(e.target.value); setError(null) }}
              className={clsx(
                'w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 text-sm',
                confirmPassword && confirmPassword !== newPassword ? 'border-red-300' : 'border-gray-300'
              )}
              placeholder="Confirm new password"
            />
          </div>
          {confirmPassword && confirmPassword !== newPassword && (
            <p className="text-xs text-red-600 mt-1">Passwords do not match</p>
          )}
        </div>

        <button
          type="submit"
          disabled={submitting || !currentPassword || !newPassword || newPassword !== confirmPassword || !requirements.every(r => r.met)}
          className="flex items-center gap-2 px-5 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
        >
          {submitting ? 'Changing...' : 'Change Password'}
        </button>
      </form>
    </div>
  )
}
