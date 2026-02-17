import { useState, useEffect, useCallback } from 'react'
import { format, parseISO } from 'date-fns'
import {
  Settings as SettingsIcon,
  Building2,
  CalendarCog,
  CalendarDays,
  Stethoscope,
  Shield,
  Plug,
  Save,
  Loader2,
  AlertCircle,
  Check,
  X,
  Plus,
  Edit3,
  Phone,
  Clock,
  ToggleLeft,
  ToggleRight,
  Eye,
  EyeOff,
  CheckCircle,
  XCircle,
  GripVertical,
  Trash2,
  Bot,
  PhoneCall,
  CreditCard,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import { useAuth } from '../contexts/AuthContext'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const US_TIMEZONES = [
  { value: 'America/New_York', label: 'Eastern Time (ET)' },
  { value: 'America/Chicago', label: 'Central Time (CT)' },
  { value: 'America/Denver', label: 'Mountain Time (MT)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (PT)' },
  { value: 'America/Anchorage', label: 'Alaska Time (AKT)' },
  { value: 'Pacific/Honolulu', label: 'Hawaii Time (HT)' },
  { value: 'America/Phoenix', label: 'Arizona (no DST)' },
  { value: 'America/Indiana/Indianapolis', label: 'Indiana (Eastern)' },
  { value: 'America/Puerto_Rico', label: 'Atlantic Time (Puerto Rico)' },
]

const DAY_NAMES = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
]

const DAY_NAMES_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const MODEL_PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
]

const MODEL_NAMES = [
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
]

const VOICE_PROVIDERS = [
  { value: '11labs', label: 'ElevenLabs' },
  { value: 'deepgram', label: 'Deepgram' },
  { value: 'openai', label: 'OpenAI' },
]

const TABS = [
  { id: 'practice', label: 'Practice Info', icon: Building2 },
  { id: 'booking', label: 'Booking', icon: CalendarCog },
  { id: 'schedule', label: 'Schedule', icon: CalendarDays },
  { id: 'appointment-types', label: 'Appt Types', icon: Stethoscope },
  { id: 'insurance', label: 'Insurance', icon: Shield },
  { id: 'integrations', label: 'Integrations', icon: Plug },
]

// ---------------------------------------------------------------------------
// Shared UI helpers
// ---------------------------------------------------------------------------

function Toast({ message, type = 'success', onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 4000)
    return () => clearTimeout(timer)
  }, [onClose])

  return (
    <div
      className={clsx(
        'flex items-center gap-2.5 rounded-xl px-5 py-3 text-sm font-medium shadow-sm border',
        type === 'success'
          ? 'bg-green-50 border-green-200 text-green-700'
          : 'bg-red-50 border-red-200 text-red-700'
      )}
    >
      {type === 'success' ? (
        <Check className="w-4 h-4 flex-shrink-0" />
      ) : (
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
      )}
      {message}
      <button
        onClick={onClose}
        className="ml-auto p-1 rounded hover:bg-black/5 transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

function SectionCard({ title, description, children }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {(title || description) && (
        <div className="px-6 py-4 border-b border-gray-100">
          {title && (
            <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          )}
          {description && (
            <p className="text-sm text-gray-500 mt-0.5">{description}</p>
          )}
        </div>
      )}
      <div className="p-6">{children}</div>
    </div>
  )
}

function FieldLabel({ children, required, htmlFor }) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-sm font-medium text-gray-700 mb-1.5"
    >
      {children}
      {required && <span className="text-red-500 ml-0.5">*</span>}
    </label>
  )
}

function TextInput({ id, value, onChange, placeholder, type = 'text', disabled, className: extra, ...rest }) {
  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      disabled={disabled}
      className={clsx(
        'w-full px-3 py-2.5 rounded-lg border text-sm bg-white',
        'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
        'transition-colors',
        disabled
          ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
          : 'border-gray-300',
        extra
      )}
      {...rest}
    />
  )
}

function SelectInput({ id, value, onChange, options, disabled, className: extra }) {
  return (
    <select
      id={id}
      value={value}
      onChange={onChange}
      disabled={disabled}
      className={clsx(
        'w-full px-3 py-2.5 rounded-lg border text-sm bg-white',
        'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
        'transition-colors',
        disabled
          ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
          : 'border-gray-300',
        extra
      )}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

function Toggle({ enabled, onChange, disabled }) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!enabled)}
      disabled={disabled}
      className={clsx(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
        enabled ? 'bg-primary-600' : 'bg-gray-300',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <span
        className={clsx(
          'inline-block h-4 w-4 transform rounded-full bg-white transition-transform shadow-sm',
          enabled ? 'translate-x-6' : 'translate-x-1'
        )}
      />
    </button>
  )
}

function MaskedInput({ id, value, onChange, placeholder, disabled, className: extra }) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="relative">
      <input
        id={id}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
        className={clsx(
          'w-full px-3 py-2.5 pr-10 rounded-lg border text-sm bg-white',
          'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
          'transition-colors',
          disabled
            ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
            : 'border-gray-300',
          extra
        )}
      />
      <button
        type="button"
        onClick={() => setVisible((prev) => !prev)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
        title={visible ? 'Hide' : 'Show'}
      >
        {visible ? (
          <EyeOff className="w-4 h-4" />
        ) : (
          <Eye className="w-4 h-4" />
        )}
      </button>
    </div>
  )
}

function SaveButton({ saving, onClick, label = 'Save Changes', disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={saving || disabled}
      className={clsx(
        'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white',
        'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
        'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
        'transition-colors shadow-sm',
        'disabled:opacity-60 disabled:cursor-not-allowed'
      )}
    >
      {saving ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          Saving...
        </>
      ) : (
        <>
          <Save className="w-4 h-4" />
          {label}
        </>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Tab 1: Practice Info
// ---------------------------------------------------------------------------

function PracticeInfoTab() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)

  const [form, setForm] = useState({
    name: '',
    phone: '',
    address: '',
    timezone: 'America/New_York',
  })
  const [readOnly, setReadOnly] = useState({
    npi: '',
    tax_id: '',
    created_at: '',
  })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/practice/settings')
        const data = res.data
        if (!cancelled) {
          setForm({
            name: data.name || '',
            phone: data.phone || '',
            address: data.address || '',
            timezone: data.timezone || 'America/New_York',
          })
          setReadOnly({
            npi: data.npi || '',
            tax_id: data.tax_id || '',
            created_at: data.created_at || '',
          })
        }
      } catch (err) {
        if (!cancelled && err.response?.status !== 401) {
          setError(
            err.response?.data?.detail || 'Failed to load practice info.'
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setToast(null)
    try {
      await api.put('/practice/settings', {
        name: form.name.trim() || undefined,
        phone: form.phone.trim() || undefined,
        address: form.address.trim() || undefined,
        timezone: form.timezone || undefined,
      })
      setToast({ type: 'success', message: 'Practice info updated successfully.' })
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save practice info.',
      })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading practice info..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <SectionCard
        title="Practice Details"
        description="Basic information about your practice"
      >
        <div className="space-y-5">
          <div>
            <FieldLabel htmlFor="practice-name" required>
              Practice Name
            </FieldLabel>
            <TextInput
              id="practice-name"
              value={form.name}
              onChange={(e) => handleChange('name', e.target.value)}
              placeholder="Enter practice name"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="practice-phone">Phone</FieldLabel>
              <TextInput
                id="practice-phone"
                type="tel"
                value={form.phone}
                onChange={(e) => handleChange('phone', e.target.value)}
                placeholder="(555) 123-4567"
              />
            </div>
            <div>
              <FieldLabel htmlFor="practice-timezone">Timezone</FieldLabel>
              <SelectInput
                id="practice-timezone"
                value={form.timezone}
                onChange={(e) => handleChange('timezone', e.target.value)}
                options={US_TIMEZONES}
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="practice-address">Address</FieldLabel>
            <TextInput
              id="practice-address"
              value={form.address}
              onChange={(e) => handleChange('address', e.target.value)}
              placeholder="123 Main St, City, State ZIP"
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Identifiers"
        description="Read-only identification numbers (contact support to update)"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <FieldLabel>NPI Number</FieldLabel>
            <TextInput value={readOnly.npi || '--'} disabled />
          </div>
          <div>
            <FieldLabel>Tax ID</FieldLabel>
            <TextInput value={readOnly.tax_id || '--'} disabled />
          </div>
        </div>
        {readOnly.created_at && (
          <p className="mt-4 text-xs text-gray-400">
            Practice created on{' '}
            {(() => {
              try {
                return format(parseISO(readOnly.created_at), 'MMMM d, yyyy')
              } catch {
                return readOnly.created_at
              }
            })()}
          </p>
        )}
      </SectionCard>

      <div className="flex justify-end">
        <SaveButton saving={saving} onClick={handleSave} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2: Booking Settings
// ---------------------------------------------------------------------------

function BookingSettingsTab() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)

  const [form, setForm] = useState({
    slot_duration_minutes: 30,
    booking_horizon_days: 30,
    allow_overbooking: false,
    max_overbooking_per_slot: 1,
    transfer_number: '',
  })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/practice/config/')
        const data = res.data
        if (!cancelled) {
          setForm({
            slot_duration_minutes: data.slot_duration_minutes ?? 30,
            booking_horizon_days: data.booking_horizon_days ?? 30,
            allow_overbooking: data.allow_overbooking ?? false,
            max_overbooking_per_slot: data.max_overbooking_per_slot ?? 1,
            transfer_number: data.transfer_number || '',
          })
        }
      } catch (err) {
        if (!cancelled && err.response?.status !== 401) {
          setError(
            err.response?.data?.detail || 'Failed to load booking settings.'
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setToast(null)
    try {
      await api.put('/practice/config/', {
        slot_duration_minutes: parseInt(form.slot_duration_minutes, 10) || 30,
        booking_horizon_days: parseInt(form.booking_horizon_days, 10) || 30,
        allow_overbooking: form.allow_overbooking,
        max_overbooking_per_slot: parseInt(form.max_overbooking_per_slot, 10) || 1,
        transfer_number: form.transfer_number.trim() || undefined,
      })
      setToast({ type: 'success', message: 'Booking settings saved successfully.' })
    } catch (err) {
      setToast({
        type: 'error',
        message:
          err.response?.data?.detail || 'Failed to save booking settings.',
      })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading booking settings..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <SectionCard
        title="Scheduling Configuration"
        description="Control how appointment slots are generated"
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="slot-duration">
                Slot Duration (minutes)
              </FieldLabel>
              <TextInput
                id="slot-duration"
                type="number"
                min="5"
                max="240"
                step="5"
                value={form.slot_duration_minutes}
                onChange={(e) =>
                  handleChange('slot_duration_minutes', e.target.value)
                }
              />
              <p className="mt-1 text-xs text-gray-400">
                Duration of each appointment slot
              </p>
            </div>
            <div>
              <FieldLabel htmlFor="booking-horizon">
                Booking Horizon (days)
              </FieldLabel>
              <TextInput
                id="booking-horizon"
                type="number"
                min="1"
                max="365"
                value={form.booking_horizon_days}
                onChange={(e) =>
                  handleChange('booking_horizon_days', e.target.value)
                }
              />
              <p className="mt-1 text-xs text-gray-400">
                How far in advance patients can book
              </p>
            </div>
          </div>

          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">
                  Allow Overbooking
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Allow multiple patients per time slot
                </p>
              </div>
              <Toggle
                enabled={form.allow_overbooking}
                onChange={(val) => handleChange('allow_overbooking', val)}
              />
            </div>

            {form.allow_overbooking && (
              <div className="mt-4 ml-0 sm:ml-6">
                <FieldLabel htmlFor="max-overbook">
                  Max Overbooking Per Slot
                </FieldLabel>
                <TextInput
                  id="max-overbook"
                  type="number"
                  min="1"
                  max="10"
                  value={form.max_overbooking_per_slot}
                  onChange={(e) =>
                    handleChange('max_overbooking_per_slot', e.target.value)
                  }
                  className="sm:w-32"
                />
              </div>
            )}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Staff Transfer"
        description="Phone number for live staff transfers during AI calls"
      >
        <div>
          <FieldLabel htmlFor="transfer-number">Transfer Number</FieldLabel>
          <div className="relative sm:w-72">
            <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <TextInput
              id="transfer-number"
              type="tel"
              value={form.transfer_number}
              onChange={(e) => handleChange('transfer_number', e.target.value)}
              placeholder="(555) 123-4567"
              className="pl-10"
            />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            When the AI needs to transfer a call to a human, it will dial this
            number
          </p>
        </div>
      </SectionCard>

      <div className="flex justify-end">
        <SaveButton saving={saving} onClick={handleSave} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3: Schedule
// ---------------------------------------------------------------------------

function ScheduleTab() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)

  // schedules: array of { day_of_week: 0-6, is_enabled, start_time, end_time }
  const [schedules, setSchedules] = useState([])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/practice/schedule/')
        const data = res.data.schedules || res.data || []
        if (!cancelled) {
          // Ensure we have entries for all 7 days
          const full = Array.from({ length: 7 }, (_, i) => {
            const existing = data.find((s) => s.day_of_week === i)
            return (
              existing || {
                day_of_week: i,
                is_enabled: false,
                start_time: '09:00',
                end_time: '17:00',
              }
            )
          })
          setSchedules(full)
        }
      } catch (err) {
        if (!cancelled && err.response?.status !== 401) {
          setError(
            err.response?.data?.detail || 'Failed to load schedule.'
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  function updateDay(dayIndex, field, value) {
    setSchedules((prev) =>
      prev.map((s) =>
        s.day_of_week === dayIndex ? { ...s, [field]: value } : s
      )
    )
  }

  async function handleSave() {
    setSaving(true)
    setToast(null)
    try {
      await api.put('/practice/schedule/', schedules)
      setToast({ type: 'success', message: 'Schedule saved successfully.' })
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save schedule.',
      })
    } finally {
      setSaving(false)
    }
  }

  /** Convert HH:MM to a percentage position (0-100) in a 24h bar. */
  function timeToPercent(timeStr) {
    if (!timeStr) return 0
    const [h, m] = timeStr.split(':').map(Number)
    return ((h * 60 + m) / (24 * 60)) * 100
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading schedule..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <SectionCard
        title="Weekly Schedule"
        description="Set your practice hours for each day of the week"
      >
        <div className="space-y-3">
          {/* Header row */}
          <div className="hidden sm:grid sm:grid-cols-[140px_56px_1fr_1fr_1fr] gap-3 items-center px-2">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Day
            </span>
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider text-center">
              Open
            </span>
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Start
            </span>
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              End
            </span>
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Hours
            </span>
          </div>

          {schedules.map((day) => {
            const startPct = timeToPercent(day.start_time)
            const endPct = timeToPercent(day.end_time)
            const widthPct = Math.max(0, endPct - startPct)

            return (
              <div
                key={day.day_of_week}
                className={clsx(
                  'rounded-lg border p-3 sm:p-2 transition-colors',
                  day.is_enabled
                    ? 'border-primary-200 bg-primary-50/30'
                    : 'border-gray-100 bg-gray-50/50'
                )}
              >
                <div className="grid grid-cols-1 sm:grid-cols-[140px_56px_1fr_1fr_1fr] gap-3 items-center">
                  {/* Day name */}
                  <span
                    className={clsx(
                      'text-sm font-semibold',
                      day.is_enabled ? 'text-gray-900' : 'text-gray-400'
                    )}
                  >
                    {DAY_NAMES[day.day_of_week]}
                  </span>

                  {/* Toggle */}
                  <div className="flex justify-center">
                    <Toggle
                      enabled={day.is_enabled}
                      onChange={(val) =>
                        updateDay(day.day_of_week, 'is_enabled', val)
                      }
                    />
                  </div>

                  {/* Start time */}
                  <div>
                    <label className="sr-only">
                      Start time for {DAY_NAMES[day.day_of_week]}
                    </label>
                    <input
                      type="time"
                      value={day.start_time}
                      onChange={(e) =>
                        updateDay(day.day_of_week, 'start_time', e.target.value)
                      }
                      disabled={!day.is_enabled}
                      className={clsx(
                        'w-full px-3 py-2 rounded-lg border text-sm',
                        'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                        'transition-colors',
                        !day.is_enabled
                          ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                          : 'border-gray-300 bg-white'
                      )}
                    />
                  </div>

                  {/* End time */}
                  <div>
                    <label className="sr-only">
                      End time for {DAY_NAMES[day.day_of_week]}
                    </label>
                    <input
                      type="time"
                      value={day.end_time}
                      onChange={(e) =>
                        updateDay(day.day_of_week, 'end_time', e.target.value)
                      }
                      disabled={!day.is_enabled}
                      className={clsx(
                        'w-full px-3 py-2 rounded-lg border text-sm',
                        'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                        'transition-colors',
                        !day.is_enabled
                          ? 'border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed'
                          : 'border-gray-300 bg-white'
                      )}
                    />
                  </div>

                  {/* Visual bar */}
                  <div className="hidden sm:block">
                    <div className="h-6 bg-gray-200 rounded-full overflow-hidden relative">
                      {day.is_enabled && widthPct > 0 && (
                        <div
                          className="absolute top-0 bottom-0 bg-primary-500 rounded-full"
                          style={{
                            left: `${startPct}%`,
                            width: `${widthPct}%`,
                          }}
                        />
                      )}
                      {/* 12pm marker */}
                      <div className="absolute top-0 bottom-0 left-1/2 w-px bg-gray-300/60" />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Legend */}
        <div className="mt-4 flex items-center gap-4 text-xs text-gray-400">
          <span className="hidden sm:inline-flex items-center gap-1.5">
            <span className="w-3 h-3 rounded bg-primary-500 inline-block" />
            Working hours
          </span>
          <span className="hidden sm:inline-flex items-center gap-1.5">
            <span className="w-px h-3 bg-gray-400 inline-block" />
            12:00 PM
          </span>
        </div>
      </SectionCard>

      <div className="flex justify-end">
        <SaveButton saving={saving} onClick={handleSave} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 4: Appointment Types
// ---------------------------------------------------------------------------

function AppointmentTypesTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [types, setTypes] = useState([])

  // Inline editing
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({ name: '', duration_minutes: 30, is_active: true, sort_order: 0 })
  const [savingId, setSavingId] = useState(null)

  // Add new
  const [showAdd, setShowAdd] = useState(false)
  const [addForm, setAddForm] = useState({ name: '', duration_minutes: 30, is_active: true, sort_order: 0 })
  const [adding, setAdding] = useState(false)

  const fetchTypes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get('/practice/appointment-types/')
      const data = res.data.appointment_types || res.data || []
      // Sort by sort_order then name
      data.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0) || (a.name || '').localeCompare(b.name || ''))
      setTypes(data)
    } catch (err) {
      if (err.response?.status !== 401) {
        setError(
          err.response?.data?.detail || 'Failed to load appointment types.'
        )
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTypes()
  }, [fetchTypes])

  function startEdit(type) {
    setEditingId(type.id)
    setEditForm({
      name: type.name || '',
      duration_minutes: type.duration_minutes ?? 30,
      is_active: type.is_active ?? true,
      sort_order: type.sort_order ?? 0,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm({ name: '', duration_minutes: 30, is_active: true, sort_order: 0 })
  }

  async function saveEdit(id) {
    if (!editForm.name.trim()) {
      setToast({ type: 'error', message: 'Appointment type name is required.' })
      return
    }
    setSavingId(id)
    setToast(null)
    try {
      await api.put(`/practice/appointment-types/${id}`, {
        name: editForm.name.trim(),
        duration_minutes: parseInt(editForm.duration_minutes, 10) || 30,
        is_active: editForm.is_active,
        sort_order: parseInt(editForm.sort_order, 10) || 0,
      })
      setToast({ type: 'success', message: 'Appointment type updated.' })
      setEditingId(null)
      fetchTypes()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update appointment type.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function toggleActive(type) {
    setSavingId(type.id)
    try {
      await api.put(`/practice/appointment-types/${type.id}`, {
        is_active: !type.is_active,
      })
      fetchTypes()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to toggle status.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function handleAdd() {
    if (!addForm.name.trim()) {
      setToast({ type: 'error', message: 'Name is required for new appointment type.' })
      return
    }
    setAdding(true)
    setToast(null)
    try {
      await api.post('/practice/appointment-types/', {
        name: addForm.name.trim(),
        duration_minutes: parseInt(addForm.duration_minutes, 10) || 30,
        is_active: addForm.is_active,
        sort_order: parseInt(addForm.sort_order, 10) || 0,
      })
      setToast({ type: 'success', message: 'Appointment type created.' })
      setShowAdd(false)
      setAddForm({ name: '', duration_minutes: 30, is_active: true, sort_order: 0 })
      fetchTypes()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to create appointment type.',
      })
    } finally {
      setAdding(false)
    }
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading appointment types..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <SectionCard
        title="Appointment Types"
        description="Define the types of appointments your practice offers"
      >
        {/* Types list */}
        <div className="space-y-2">
          {types.length === 0 && !showAdd && (
            <p className="text-sm text-gray-500 text-center py-8">
              No appointment types configured. Add your first one below.
            </p>
          )}

          {types.map((type) => (
            <div
              key={type.id}
              className={clsx(
                'rounded-lg border p-4 transition-colors',
                editingId === type.id
                  ? 'border-primary-300 bg-primary-50/30'
                  : type.is_active
                    ? 'border-gray-200 bg-white'
                    : 'border-gray-100 bg-gray-50/50'
              )}
            >
              {editingId === type.id ? (
                /* Editing mode */
                <div className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <FieldLabel required>Name</FieldLabel>
                      <TextInput
                        value={editForm.name}
                        onChange={(e) =>
                          setEditForm((prev) => ({ ...prev, name: e.target.value }))
                        }
                        placeholder="e.g. Follow-up Visit"
                      />
                    </div>
                    <div>
                      <FieldLabel>Duration (min)</FieldLabel>
                      <TextInput
                        type="number"
                        min="5"
                        max="480"
                        step="5"
                        value={editForm.duration_minutes}
                        onChange={(e) =>
                          setEditForm((prev) => ({
                            ...prev,
                            duration_minutes: e.target.value,
                          }))
                        }
                      />
                    </div>
                    <div>
                      <FieldLabel>Sort Order</FieldLabel>
                      <TextInput
                        type="number"
                        min="0"
                        value={editForm.sort_order}
                        onChange={(e) =>
                          setEditForm((prev) => ({
                            ...prev,
                            sort_order: e.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Toggle
                        enabled={editForm.is_active}
                        onChange={(val) =>
                          setEditForm((prev) => ({ ...prev, is_active: val }))
                        }
                      />
                      <span className="text-sm text-gray-600">
                        {editForm.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={cancelEdit}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => saveEdit(type.id)}
                        disabled={savingId === type.id}
                        className={clsx(
                          'inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold text-white',
                          'bg-primary-600 hover:bg-primary-700',
                          'transition-colors',
                          'disabled:opacity-60 disabled:cursor-not-allowed'
                        )}
                      >
                        {savingId === type.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                        Save
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                /* Display mode */
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4 min-w-0">
                    <div className="min-w-0">
                      <p
                        className={clsx(
                          'text-sm font-semibold truncate',
                          type.is_active ? 'text-gray-900' : 'text-gray-400'
                        )}
                      >
                        {type.name}
                      </p>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs text-gray-500 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {type.duration_minutes} min
                        </span>
                        <span
                          className={clsx(
                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
                            type.is_active
                              ? 'bg-green-50 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          )}
                        >
                          <span
                            className={clsx(
                              'w-1.5 h-1.5 rounded-full',
                              type.is_active ? 'bg-green-500' : 'bg-gray-400'
                            )}
                          />
                          {type.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => toggleActive(type)}
                      disabled={savingId === type.id}
                      title={type.is_active ? 'Deactivate' : 'Activate'}
                      className={clsx(
                        'p-1.5 rounded-lg transition-colors',
                        type.is_active
                          ? 'text-green-600 hover:bg-green-50'
                          : 'text-gray-400 hover:bg-gray-100',
                        'disabled:opacity-50 disabled:cursor-not-allowed'
                      )}
                    >
                      {savingId === type.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : type.is_active ? (
                        <ToggleRight className="w-5 h-5" />
                      ) : (
                        <ToggleLeft className="w-5 h-5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => startEdit(type)}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                      title="Edit"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Add new form */}
          {showAdd && (
            <div className="rounded-lg border border-dashed border-primary-300 bg-primary-50/20 p-4">
              <div className="space-y-3">
                <p className="text-sm font-semibold text-gray-900">
                  New Appointment Type
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <FieldLabel required>Name</FieldLabel>
                    <TextInput
                      value={addForm.name}
                      onChange={(e) =>
                        setAddForm((prev) => ({ ...prev, name: e.target.value }))
                      }
                      placeholder="e.g. New Patient Consult"
                    />
                  </div>
                  <div>
                    <FieldLabel>Duration (min)</FieldLabel>
                    <TextInput
                      type="number"
                      min="5"
                      max="480"
                      step="5"
                      value={addForm.duration_minutes}
                      onChange={(e) =>
                        setAddForm((prev) => ({
                          ...prev,
                          duration_minutes: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel>Sort Order</FieldLabel>
                    <TextInput
                      type="number"
                      min="0"
                      value={addForm.sort_order}
                      onChange={(e) =>
                        setAddForm((prev) => ({
                          ...prev,
                          sort_order: e.target.value,
                        }))
                      }
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Toggle
                      enabled={addForm.is_active}
                      onChange={(val) =>
                        setAddForm((prev) => ({ ...prev, is_active: val }))
                      }
                    />
                    <span className="text-sm text-gray-600">
                      {addForm.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setShowAdd(false)
                        setAddForm({ name: '', duration_minutes: 30, is_active: true, sort_order: 0 })
                      }}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleAdd}
                      disabled={adding}
                      className={clsx(
                        'inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold text-white',
                        'bg-primary-600 hover:bg-primary-700',
                        'transition-colors',
                        'disabled:opacity-60 disabled:cursor-not-allowed'
                      )}
                    >
                      {adding ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Plus className="w-3.5 h-3.5" />
                      )}
                      Add Type
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Add button (outside the list) */}
        {!showAdd && (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => setShowAdd(true)}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
                'text-primary-700 bg-primary-50 border border-primary-200',
                'hover:bg-primary-100 active:bg-primary-200',
                'transition-colors'
              )}
            >
              <Plus className="w-4 h-4" />
              Add Appointment Type
            </button>
          </div>
        )}
      </SectionCard>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 5: Insurance Carriers
// ---------------------------------------------------------------------------

function InsuranceCarriersTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [carriers, setCarriers] = useState([])

  // Inline editing
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({
    name: '',
    stedi_payer_id: '',
    aliases: '',
    is_active: true,
  })
  const [savingId, setSavingId] = useState(null)

  // Add new
  const [showAdd, setShowAdd] = useState(false)
  const [addForm, setAddForm] = useState({
    name: '',
    stedi_payer_id: '',
    aliases: '',
    is_active: true,
  })
  const [adding, setAdding] = useState(false)

  const fetchCarriers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get('/practice/insurance-carriers/')
      const data = res.data.carriers || res.data || []
      data.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
      setCarriers(data)
    } catch (err) {
      if (err.response?.status !== 401) {
        setError(
          err.response?.data?.detail || 'Failed to load insurance carriers.'
        )
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCarriers()
  }, [fetchCarriers])

  function aliasesToString(aliases) {
    if (!aliases) return ''
    if (Array.isArray(aliases)) return aliases.join(', ')
    return String(aliases)
  }

  function stringToAliases(str) {
    if (!str || !str.trim()) return []
    return str
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }

  function startEdit(carrier) {
    setEditingId(carrier.id)
    setEditForm({
      name: carrier.name || '',
      stedi_payer_id: carrier.stedi_payer_id || '',
      aliases: aliasesToString(carrier.aliases),
      is_active: carrier.is_active ?? true,
    })
  }

  function cancelEdit() {
    setEditingId(null)
  }

  async function saveEdit(id) {
    if (!editForm.name.trim()) {
      setToast({ type: 'error', message: 'Carrier name is required.' })
      return
    }
    setSavingId(id)
    setToast(null)
    try {
      await api.put(`/practice/insurance-carriers/${id}`, {
        name: editForm.name.trim(),
        stedi_payer_id: editForm.stedi_payer_id.trim() || undefined,
        aliases: stringToAliases(editForm.aliases),
        is_active: editForm.is_active,
      })
      setToast({ type: 'success', message: 'Insurance carrier updated.' })
      setEditingId(null)
      fetchCarriers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update carrier.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function toggleActive(carrier) {
    setSavingId(carrier.id)
    try {
      await api.put(`/practice/insurance-carriers/${carrier.id}`, {
        is_active: !carrier.is_active,
      })
      fetchCarriers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to toggle status.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function handleAdd() {
    if (!addForm.name.trim()) {
      setToast({ type: 'error', message: 'Carrier name is required.' })
      return
    }
    setAdding(true)
    setToast(null)
    try {
      await api.post('/practice/insurance-carriers/', {
        name: addForm.name.trim(),
        stedi_payer_id: addForm.stedi_payer_id.trim() || undefined,
        aliases: stringToAliases(addForm.aliases),
        is_active: addForm.is_active,
      })
      setToast({ type: 'success', message: 'Insurance carrier created.' })
      setShowAdd(false)
      setAddForm({ name: '', stedi_payer_id: '', aliases: '', is_active: true })
      fetchCarriers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to create carrier.',
      })
    } finally {
      setAdding(false)
    }
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading insurance carriers..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      <SectionCard
        title="Insurance Carriers"
        description="Manage accepted insurance carriers and their Stedi payer IDs"
      >
        <div className="space-y-2">
          {carriers.length === 0 && !showAdd && (
            <p className="text-sm text-gray-500 text-center py-8">
              No insurance carriers configured. Add your first one below.
            </p>
          )}

          {carriers.map((carrier) => (
            <div
              key={carrier.id}
              className={clsx(
                'rounded-lg border p-4 transition-colors',
                editingId === carrier.id
                  ? 'border-primary-300 bg-primary-50/30'
                  : carrier.is_active
                    ? 'border-gray-200 bg-white'
                    : 'border-gray-100 bg-gray-50/50'
              )}
            >
              {editingId === carrier.id ? (
                /* Editing mode */
                <div className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <FieldLabel required>Carrier Name</FieldLabel>
                      <TextInput
                        value={editForm.name}
                        onChange={(e) =>
                          setEditForm((prev) => ({ ...prev, name: e.target.value }))
                        }
                        placeholder="e.g. Blue Cross Blue Shield"
                      />
                    </div>
                    <div>
                      <FieldLabel>Stedi Payer ID</FieldLabel>
                      <TextInput
                        value={editForm.stedi_payer_id}
                        onChange={(e) =>
                          setEditForm((prev) => ({
                            ...prev,
                            stedi_payer_id: e.target.value,
                          }))
                        }
                        placeholder="e.g. BCBS_001"
                      />
                    </div>
                  </div>
                  <div>
                    <FieldLabel>Aliases (comma-separated)</FieldLabel>
                    <TextInput
                      value={editForm.aliases}
                      onChange={(e) =>
                        setEditForm((prev) => ({
                          ...prev,
                          aliases: e.target.value,
                        }))
                      }
                      placeholder="e.g. BCBS, Blue Cross, BC/BS"
                    />
                    <p className="mt-1 text-xs text-gray-400">
                      Alternative names patients might use
                    </p>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Toggle
                        enabled={editForm.is_active}
                        onChange={(val) =>
                          setEditForm((prev) => ({ ...prev, is_active: val }))
                        }
                      />
                      <span className="text-sm text-gray-600">
                        {editForm.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={cancelEdit}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => saveEdit(carrier.id)}
                        disabled={savingId === carrier.id}
                        className={clsx(
                          'inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold text-white',
                          'bg-primary-600 hover:bg-primary-700',
                          'transition-colors',
                          'disabled:opacity-60 disabled:cursor-not-allowed'
                        )}
                      >
                        {savingId === carrier.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                        Save
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                /* Display mode */
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p
                      className={clsx(
                        'text-sm font-semibold truncate',
                        carrier.is_active ? 'text-gray-900' : 'text-gray-400'
                      )}
                    >
                      {carrier.name}
                    </p>
                    <div className="flex items-center gap-3 mt-0.5 flex-wrap">
                      {carrier.stedi_payer_id && (
                        <span className="text-xs text-gray-500">
                          Payer ID: {carrier.stedi_payer_id}
                        </span>
                      )}
                      {carrier.aliases &&
                        (Array.isArray(carrier.aliases)
                          ? carrier.aliases.length > 0
                          : carrier.aliases) && (
                          <span className="text-xs text-gray-400">
                            Aliases:{' '}
                            {Array.isArray(carrier.aliases)
                              ? carrier.aliases.join(', ')
                              : carrier.aliases}
                          </span>
                        )}
                      <span
                        className={clsx(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
                          carrier.is_active
                            ? 'bg-green-50 text-green-700'
                            : 'bg-gray-100 text-gray-500'
                        )}
                      >
                        <span
                          className={clsx(
                            'w-1.5 h-1.5 rounded-full',
                            carrier.is_active ? 'bg-green-500' : 'bg-gray-400'
                          )}
                        />
                        {carrier.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => toggleActive(carrier)}
                      disabled={savingId === carrier.id}
                      title={carrier.is_active ? 'Deactivate' : 'Activate'}
                      className={clsx(
                        'p-1.5 rounded-lg transition-colors',
                        carrier.is_active
                          ? 'text-green-600 hover:bg-green-50'
                          : 'text-gray-400 hover:bg-gray-100',
                        'disabled:opacity-50 disabled:cursor-not-allowed'
                      )}
                    >
                      {savingId === carrier.id ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : carrier.is_active ? (
                        <ToggleRight className="w-5 h-5" />
                      ) : (
                        <ToggleLeft className="w-5 h-5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => startEdit(carrier)}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                      title="Edit"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Add new form */}
          {showAdd && (
            <div className="rounded-lg border border-dashed border-primary-300 bg-primary-50/20 p-4">
              <div className="space-y-3">
                <p className="text-sm font-semibold text-gray-900">
                  New Insurance Carrier
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <FieldLabel required>Carrier Name</FieldLabel>
                    <TextInput
                      value={addForm.name}
                      onChange={(e) =>
                        setAddForm((prev) => ({ ...prev, name: e.target.value }))
                      }
                      placeholder="e.g. Aetna"
                    />
                  </div>
                  <div>
                    <FieldLabel>Stedi Payer ID</FieldLabel>
                    <TextInput
                      value={addForm.stedi_payer_id}
                      onChange={(e) =>
                        setAddForm((prev) => ({
                          ...prev,
                          stedi_payer_id: e.target.value,
                        }))
                      }
                      placeholder="e.g. AETNA_001"
                    />
                  </div>
                </div>
                <div>
                  <FieldLabel>Aliases (comma-separated)</FieldLabel>
                  <TextInput
                    value={addForm.aliases}
                    onChange={(e) =>
                      setAddForm((prev) => ({
                        ...prev,
                        aliases: e.target.value,
                      }))
                    }
                    placeholder="e.g. Aetna Health, Aetna PPO"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Toggle
                      enabled={addForm.is_active}
                      onChange={(val) =>
                        setAddForm((prev) => ({ ...prev, is_active: val }))
                      }
                    />
                    <span className="text-sm text-gray-600">
                      {addForm.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setShowAdd(false)
                        setAddForm({ name: '', stedi_payer_id: '', aliases: '', is_active: true })
                      }}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleAdd}
                      disabled={adding}
                      className={clsx(
                        'inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold text-white',
                        'bg-primary-600 hover:bg-primary-700',
                        'transition-colors',
                        'disabled:opacity-60 disabled:cursor-not-allowed'
                      )}
                    >
                      {adding ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Plus className="w-3.5 h-3.5" />
                      )}
                      Add Carrier
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Add button */}
        {!showAdd && (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => setShowAdd(true)}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium',
                'text-primary-700 bg-primary-50 border border-primary-200',
                'hover:bg-primary-100 active:bg-primary-200',
                'transition-colors'
              )}
            >
              <Plus className="w-4 h-4" />
              Add Insurance Carrier
            </button>
          </div>
        )}
      </SectionCard>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 6: Integrations
// ---------------------------------------------------------------------------

function IntegrationsTab() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Vapi state
  const [vapiForm, setVapiForm] = useState({
    vapi_api_key: '',
    vapi_assistant_id: '',
    vapi_phone_number_id: '',
    vapi_model_provider: 'openai',
    vapi_model_name: 'gpt-4o-mini',
    vapi_voice_provider: '11labs',
    vapi_voice_id: '',
    vapi_first_message: '',
    vapi_system_prompt: '',
  })
  const [vapiSaving, setVapiSaving] = useState(false)
  const [vapiToast, setVapiToast] = useState(null)

  // Twilio state
  const [twilioForm, setTwilioForm] = useState({
    twilio_account_sid: '',
    twilio_auth_token: '',
    twilio_phone_number: '',
    sms_confirmation_enabled: false,
    sms_confirmation_template: '',
  })
  const [twilioSaving, setTwilioSaving] = useState(false)
  const [twilioToast, setTwilioToast] = useState(null)

  // Stedi state
  const [stediForm, setStediForm] = useState({
    stedi_enabled: false,
    stedi_api_key: '',
  })
  const [stediSaving, setStediSaving] = useState(false)
  const [stediToast, setStediToast] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/practice/config/')
        const data = res.data
        if (!cancelled) {
          setVapiForm({
            vapi_api_key: data.vapi_api_key || '',
            vapi_assistant_id: data.vapi_assistant_id || '',
            vapi_phone_number_id: data.vapi_phone_number_id || '',
            vapi_model_provider: data.vapi_model_provider || 'openai',
            vapi_model_name: data.vapi_model_name || 'gpt-4o-mini',
            vapi_voice_provider: data.vapi_voice_provider || '11labs',
            vapi_voice_id: data.vapi_voice_id || '',
            vapi_first_message: data.vapi_first_message || '',
            vapi_system_prompt: data.vapi_system_prompt || '',
          })
          setTwilioForm({
            twilio_account_sid: data.twilio_account_sid || '',
            twilio_auth_token: data.twilio_auth_token || '',
            twilio_phone_number: data.twilio_phone_number || '',
            sms_confirmation_enabled: data.sms_confirmation_enabled ?? false,
            sms_confirmation_template: data.sms_confirmation_template || '',
          })
          setStediForm({
            stedi_enabled: data.stedi_enabled ?? false,
            stedi_api_key: data.stedi_api_key || '',
          })
        }
      } catch (err) {
        if (!cancelled && err.response?.status !== 401) {
          setError(
            err.response?.data?.detail || 'Failed to load integration settings.'
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // ---- Save functions ----

  async function saveVapi() {
    setVapiSaving(true)
    setVapiToast(null)
    try {
      await api.put('/practice/config/', {
        vapi_api_key: vapiForm.vapi_api_key.trim() || undefined,
        vapi_assistant_id: vapiForm.vapi_assistant_id.trim() || undefined,
        vapi_phone_number_id: vapiForm.vapi_phone_number_id.trim() || undefined,
        vapi_model_provider: vapiForm.vapi_model_provider || undefined,
        vapi_model_name: vapiForm.vapi_model_name || undefined,
        vapi_voice_provider: vapiForm.vapi_voice_provider || undefined,
        vapi_voice_id: vapiForm.vapi_voice_id.trim() || undefined,
        vapi_first_message: vapiForm.vapi_first_message.trim() || undefined,
        vapi_system_prompt: vapiForm.vapi_system_prompt.trim() || undefined,
      })
      setVapiToast({ type: 'success', message: 'Vapi settings saved successfully.' })
    } catch (err) {
      setVapiToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save Vapi settings.',
      })
    } finally {
      setVapiSaving(false)
    }
  }

  async function saveTwilio() {
    setTwilioSaving(true)
    setTwilioToast(null)
    try {
      await api.put('/practice/config/', {
        twilio_account_sid: twilioForm.twilio_account_sid.trim() || undefined,
        twilio_auth_token: twilioForm.twilio_auth_token.trim() || undefined,
        twilio_phone_number: twilioForm.twilio_phone_number.trim() || undefined,
        sms_confirmation_enabled: twilioForm.sms_confirmation_enabled,
        sms_confirmation_template: twilioForm.sms_confirmation_template.trim() || undefined,
      })
      setTwilioToast({ type: 'success', message: 'Twilio settings saved successfully.' })
    } catch (err) {
      setTwilioToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save Twilio settings.',
      })
    } finally {
      setTwilioSaving(false)
    }
  }

  async function saveStedi() {
    setStediSaving(true)
    setStediToast(null)
    try {
      await api.put('/practice/config/', {
        stedi_enabled: stediForm.stedi_enabled,
        stedi_api_key: stediForm.stedi_api_key.trim() || undefined,
      })
      setStediToast({ type: 'success', message: 'Stedi settings saved successfully.' })
    } catch (err) {
      setStediToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save Stedi settings.',
      })
    } finally {
      setStediSaving(false)
    }
  }

  // ---- Status helpers ----

  function isVapiConfigured() {
    return !!(vapiForm.vapi_api_key && vapiForm.vapi_assistant_id)
  }

  function isTwilioConfigured() {
    return !!(
      twilioForm.twilio_account_sid &&
      twilioForm.twilio_auth_token &&
      twilioForm.twilio_phone_number
    )
  }

  function isStediConfigured() {
    return !!stediForm.stedi_api_key
  }

  function StatusBadge({ configured }) {
    return (
      <span
        className={clsx(
          'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold',
          configured
            ? 'bg-green-50 text-green-700 ring-1 ring-inset ring-green-600/20'
            : 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20'
        )}
      >
        {configured ? (
          <>
            <CheckCircle className="w-3 h-3" />
            Configured
          </>
        ) : (
          <>
            <XCircle className="w-3 h-3" />
            Not Configured
          </>
        )}
      </span>
    )
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading integrations..." size="md" />
  }

  if (error) {
    return (
      <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
        <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Failed to load</p>
          <p className="mt-0.5 text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* ---- Vapi Section ---- */}
      {vapiToast && (
        <Toast
          message={vapiToast.message}
          type={vapiToast.type}
          onClose={() => setVapiToast(null)}
        />
      )}

      <SectionCard
        title={
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
              <Bot className="w-4 h-4 text-violet-600" />
            </div>
            <span>Vapi</span>
            <StatusBadge configured={isVapiConfigured()} />
          </div>
        }
        description="Voice AI assistant powered by Vapi.ai"
      >
        <div className="space-y-5">
          {/* API credentials */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="vapi-key">API Key</FieldLabel>
              <MaskedInput
                id="vapi-key"
                value={vapiForm.vapi_api_key}
                onChange={(e) =>
                  setVapiForm((prev) => ({ ...prev, vapi_api_key: e.target.value }))
                }
                placeholder="Your Vapi API key"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-assistant">Assistant ID</FieldLabel>
              <TextInput
                id="vapi-assistant"
                value={vapiForm.vapi_assistant_id}
                onChange={(e) =>
                  setVapiForm((prev) => ({ ...prev, vapi_assistant_id: e.target.value }))
                }
                placeholder="Vapi Assistant ID"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-phone-id">Phone Number ID</FieldLabel>
              <TextInput
                id="vapi-phone-id"
                value={vapiForm.vapi_phone_number_id}
                onChange={(e) =>
                  setVapiForm((prev) => ({ ...prev, vapi_phone_number_id: e.target.value }))
                }
                placeholder="Vapi Phone Number ID"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-voice-id">Voice ID</FieldLabel>
              <TextInput
                id="vapi-voice-id"
                value={vapiForm.vapi_voice_id}
                onChange={(e) =>
                  setVapiForm((prev) => ({ ...prev, vapi_voice_id: e.target.value }))
                }
                placeholder="e.g. ElevenLabs voice ID"
              />
            </div>
          </div>

          {/* AI model & voice settings */}
          <div className="border-t border-gray-100 pt-5">
            <p className="text-sm font-medium text-gray-700 mb-4">
              AI Model & Voice
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              <div>
                <FieldLabel htmlFor="vapi-model-provider">Model Provider</FieldLabel>
                <SelectInput
                  id="vapi-model-provider"
                  value={vapiForm.vapi_model_provider}
                  onChange={(e) =>
                    setVapiForm((prev) => ({ ...prev, vapi_model_provider: e.target.value }))
                  }
                  options={MODEL_PROVIDERS}
                />
              </div>
              <div>
                <FieldLabel htmlFor="vapi-model-name">Model Name</FieldLabel>
                <SelectInput
                  id="vapi-model-name"
                  value={vapiForm.vapi_model_name}
                  onChange={(e) =>
                    setVapiForm((prev) => ({ ...prev, vapi_model_name: e.target.value }))
                  }
                  options={MODEL_NAMES}
                />
              </div>
              <div>
                <FieldLabel htmlFor="vapi-voice-provider">Voice Provider</FieldLabel>
                <SelectInput
                  id="vapi-voice-provider"
                  value={vapiForm.vapi_voice_provider}
                  onChange={(e) =>
                    setVapiForm((prev) => ({ ...prev, vapi_voice_provider: e.target.value }))
                  }
                  options={VOICE_PROVIDERS}
                />
              </div>
            </div>
          </div>

          {/* First message & System prompt */}
          <div className="border-t border-gray-100 pt-5">
            <p className="text-sm font-medium text-gray-700 mb-4">
              Conversation Settings
            </p>
            <div className="space-y-5">
              <div>
                <FieldLabel htmlFor="vapi-first-message">First Message</FieldLabel>
                <TextInput
                  id="vapi-first-message"
                  value={vapiForm.vapi_first_message}
                  onChange={(e) =>
                    setVapiForm((prev) => ({ ...prev, vapi_first_message: e.target.value }))
                  }
                  placeholder="e.g. Hello! Thank you for calling Dr. Smith's office. How can I help you today?"
                />
                <p className="mt-1 text-xs text-gray-400">
                  The opening message the AI says when answering a call
                </p>
              </div>
              <div>
                <FieldLabel htmlFor="vapi-system-prompt">System Prompt</FieldLabel>
                <textarea
                  id="vapi-system-prompt"
                  value={vapiForm.vapi_system_prompt}
                  onChange={(e) =>
                    setVapiForm((prev) => ({ ...prev, vapi_system_prompt: e.target.value }))
                  }
                  rows={8}
                  placeholder="Enter the AI assistant's personality and behavior instructions..."
                  className={clsx(
                    'w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                    'transition-colors resize-y font-mono'
                  )}
                />
                <p className="mt-1 text-xs text-gray-400">
                  Full personality and behavior prompt for the AI assistant
                </p>
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton
              saving={vapiSaving}
              onClick={saveVapi}
              label="Save Vapi Settings"
            />
          </div>
        </div>
      </SectionCard>

      {/* ---- Twilio Section ---- */}
      {twilioToast && (
        <Toast
          message={twilioToast.message}
          type={twilioToast.type}
          onClose={() => setTwilioToast(null)}
        />
      )}

      <SectionCard
        title={
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
              <PhoneCall className="w-4 h-4 text-blue-600" />
            </div>
            <span>Twilio</span>
            <StatusBadge configured={isTwilioConfigured()} />
          </div>
        }
        description="Voice calls and SMS via Twilio"
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="twilio-sid">Account SID</FieldLabel>
              <TextInput
                id="twilio-sid"
                value={twilioForm.twilio_account_sid}
                onChange={(e) =>
                  setTwilioForm((prev) => ({
                    ...prev,
                    twilio_account_sid: e.target.value,
                  }))
                }
                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              />
            </div>
            <div>
              <FieldLabel htmlFor="twilio-token">Auth Token</FieldLabel>
              <MaskedInput
                id="twilio-token"
                value={twilioForm.twilio_auth_token}
                onChange={(e) =>
                  setTwilioForm((prev) => ({
                    ...prev,
                    twilio_auth_token: e.target.value,
                  }))
                }
                placeholder="Your Twilio auth token"
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="twilio-phone">Twilio Phone Number</FieldLabel>
            <div className="sm:w-72">
              <TextInput
                id="twilio-phone"
                type="tel"
                value={twilioForm.twilio_phone_number}
                onChange={(e) =>
                  setTwilioForm((prev) => ({
                    ...prev,
                    twilio_phone_number: e.target.value,
                  }))
                }
                placeholder="+15551234567"
              />
            </div>
            <p className="mt-1 text-xs text-gray-400">
              The Twilio phone number used for calls and SMS (E.164 format)
            </p>
          </div>

          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">
                  SMS Confirmations
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Automatically send SMS confirmations when appointments are
                  booked
                </p>
              </div>
              <Toggle
                enabled={twilioForm.sms_confirmation_enabled}
                onChange={(val) =>
                  setTwilioForm((prev) => ({
                    ...prev,
                    sms_confirmation_enabled: val,
                  }))
                }
              />
            </div>

            {twilioForm.sms_confirmation_enabled && (
              <div className="mt-4">
                <FieldLabel htmlFor="sms-template">SMS Template</FieldLabel>
                <textarea
                  id="sms-template"
                  value={twilioForm.sms_confirmation_template}
                  onChange={(e) =>
                    setTwilioForm((prev) => ({
                      ...prev,
                      sms_confirmation_template: e.target.value,
                    }))
                  }
                  rows={3}
                  placeholder="Hi {patient_name}, your appointment is confirmed for {date} at {time}. Reply CANCEL to cancel."
                  className={clsx(
                    'w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                    'transition-colors resize-none'
                  )}
                />
                <p className="mt-1 text-xs text-gray-400">
                  Available variables: {'{patient_name}'}, {'{date}'},{' '}
                  {'{time}'}, {'{practice_name}'}, {'{appointment_type}'}
                </p>
              </div>
            )}
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton
              saving={twilioSaving}
              onClick={saveTwilio}
              label="Save Twilio Settings"
            />
          </div>
        </div>
      </SectionCard>

      {/* ---- Stedi Section ---- */}
      {stediToast && (
        <Toast
          message={stediToast.message}
          type={stediToast.type}
          onClose={() => setStediToast(null)}
        />
      )}

      <SectionCard
        title={
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center flex-shrink-0">
              <CreditCard className="w-4 h-4 text-emerald-600" />
            </div>
            <span>Stedi</span>
            <StatusBadge configured={isStediConfigured()} />
          </div>
        }
        description="Insurance eligibility verification via Stedi"
      >
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">
                Stedi Integration
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                Enable real-time insurance eligibility checks
              </p>
            </div>
            <Toggle
              enabled={stediForm.stedi_enabled}
              onChange={(val) =>
                setStediForm((prev) => ({ ...prev, stedi_enabled: val }))
              }
            />
          </div>

          <div>
            <FieldLabel htmlFor="stedi-key">API Key</FieldLabel>
            <div className="sm:w-96">
              <MaskedInput
                id="stedi-key"
                value={stediForm.stedi_api_key}
                onChange={(e) =>
                  setStediForm((prev) => ({
                    ...prev,
                    stedi_api_key: e.target.value,
                  }))
                }
                placeholder="Your Stedi API key"
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton
              saving={stediSaving}
              onClick={saveStedi}
              label="Save Stedi Settings"
            />
          </div>
        </div>
      </SectionCard>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Settings Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('practice')

  // Access control: only practice_admin and super_admin
  const allowed = user && ['practice_admin', 'super_admin'].includes(user.role)

  if (!allowed) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 rounded-2xl bg-red-100 flex items-center justify-center mb-5">
          <Shield className="w-8 h-8 text-red-500" />
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">
          Access Denied
        </h2>
        <p className="text-sm text-gray-500 max-w-sm">
          You do not have permission to access practice settings. Please contact
          your administrator for access.
        </p>
      </div>
    )
  }

  function renderTab() {
    switch (activeTab) {
      case 'practice':
        return <PracticeInfoTab />
      case 'booking':
        return <BookingSettingsTab />
      case 'schedule':
        return <ScheduleTab />
      case 'appointment-types':
        return <AppointmentTypesTab />
      case 'insurance':
        return <InsuranceCarriersTab />
      case 'integrations':
        return <IntegrationsTab />
      default:
        return <PracticeInfoTab />
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
          Settings
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your practice configuration, integrations, and preferences
        </p>
      </div>

      {/* Tab navigation */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="border-b border-gray-200 overflow-x-auto">
          <nav className="flex min-w-max px-2" aria-label="Settings tabs">
            {TABS.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={clsx(
                    'flex items-center gap-2 px-4 py-3.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
                    isActive
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              )
            })}
          </nav>
        </div>
      </div>

      {/* Active tab content */}
      {renderTab()}
    </div>
  )
}
