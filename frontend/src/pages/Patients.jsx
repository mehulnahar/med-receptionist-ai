import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import {
  Users,
  UserPlus,
  Search,
  Phone,
  X,
  AlertCircle,
  Loader2,
  ChevronRight,
  Edit3,
  Save,
  Calendar,
  Shield,
  FileText,
  Globe,
  MapPin,
  Stethoscope,
  CalendarPlus,
  Clock,
  Check,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a date string (ISO) to a readable format. */
function formatDOB(dateStr) {
  if (!dateStr) return '--'
  try {
    return format(parseISO(dateStr), 'MM/dd/yyyy')
  } catch {
    return dateStr
  }
}

/** Format a date string (ISO) to a long readable format. */
function formatDateLong(dateStr) {
  if (!dateStr) return '--'
  try {
    return format(parseISO(dateStr), 'MMMM d, yyyy')
  } catch {
    return dateStr
  }
}

/** Format a time string (HH:MM:SS or HH:MM) to a user-friendly format. */
function formatTime(timeStr) {
  if (!timeStr) return '--'
  const [hours, minutes] = timeStr.split(':').map(Number)
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return format(date, 'h:mm a')
}

/** Format phone for display. */
function formatPhone(phone) {
  if (!phone) return '--'
  // Simple US formatting if 10 digits
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`
  }
  if (digits.length === 11 && digits[0] === '1') {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`
  }
  return phone
}

/** Language display labels. */
const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
]

function languageLabel(value) {
  const match = LANGUAGE_OPTIONS.find((o) => o.value === value)
  return match ? match.label : value || '--'
}

// ---------------------------------------------------------------------------
// Appointment Status Badge (for the detail panel)
// ---------------------------------------------------------------------------

const APPT_STATUS_CONFIG = {
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
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    ring: 'ring-blue-600/20',
    dot: 'bg-blue-500',
  },
}

function ApptStatusBadge({ status }) {
  const config = APPT_STATUS_CONFIG[status] || APPT_STATUS_CONFIG.booked
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ring-inset',
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
// Add Patient Modal
// ---------------------------------------------------------------------------

function AddPatientModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    dob: '',
    phone: '',
    address: '',
    insurance_carrier: '',
    member_id: '',
    group_number: '',
    referring_physician: '',
    language_preference: 'en',
    notes: '',
  })
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState(null)

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
    // Clear field error on change
    if (errors[field]) {
      setErrors((prev) => {
        const copy = { ...prev }
        delete copy[field]
        return copy
      })
    }
  }

  function validate() {
    const newErrors = {}
    if (!form.first_name.trim()) newErrors.first_name = 'First name is required'
    if (!form.last_name.trim()) newErrors.last_name = 'Last name is required'
    if (!form.dob) newErrors.dob = 'Date of birth is required'
    return newErrors
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setApiError(null)

    const newErrors = validate()
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }

    setSubmitting(true)
    try {
      const body = {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        dob: form.dob,
      }
      if (form.phone.trim()) body.phone = form.phone.trim()
      if (form.address.trim()) body.address = form.address.trim()
      if (form.insurance_carrier.trim()) body.insurance_carrier = form.insurance_carrier.trim()
      if (form.member_id.trim()) body.member_id = form.member_id.trim()
      if (form.group_number.trim()) body.group_number = form.group_number.trim()
      if (form.referring_physician.trim()) body.referring_physician = form.referring_physician.trim()
      if (form.language_preference) body.language_preference = form.language_preference
      if (form.notes.trim()) body.notes = form.notes.trim()

      await api.post('/patients/', body)
      onCreated()
    } catch (err) {
      setApiError(
        err.response?.data?.detail ||
          'Failed to create patient. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary-100 flex items-center justify-center">
              <UserPlus className="w-5 h-5 text-primary-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                Add Patient
              </h2>
              <p className="text-sm text-gray-500">
                Register a new patient record
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* API Error */}
          {apiError && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{apiError}</span>
            </div>
          )}

          {/* Name row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                First Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={form.first_name}
                onChange={(e) => handleChange('first_name', e.target.value)}
                placeholder="John"
                className={clsx(
                  'w-full px-3 py-2.5 rounded-lg border text-sm bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                  'transition-colors',
                  errors.first_name ? 'border-red-300 bg-red-50/50' : 'border-gray-300'
                )}
              />
              {errors.first_name && (
                <p className="mt-1 text-xs text-red-600">{errors.first_name}</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Last Name <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={form.last_name}
                onChange={(e) => handleChange('last_name', e.target.value)}
                placeholder="Doe"
                className={clsx(
                  'w-full px-3 py-2.5 rounded-lg border text-sm bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                  'transition-colors',
                  errors.last_name ? 'border-red-300 bg-red-50/50' : 'border-gray-300'
                )}
              />
              {errors.last_name && (
                <p className="mt-1 text-xs text-red-600">{errors.last_name}</p>
              )}
            </div>
          </div>

          {/* DOB */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Date of Birth <span className="text-red-500">*</span>
            </label>
            <input
              type="date"
              value={form.dob}
              onChange={(e) => handleChange('dob', e.target.value)}
              max={format(new Date(), 'yyyy-MM-dd')}
              className={clsx(
                'w-full px-3 py-2.5 rounded-lg border text-sm bg-white',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                'transition-colors',
                errors.dob ? 'border-red-300 bg-red-50/50' : 'border-gray-300'
              )}
            />
            {errors.dob && (
              <p className="mt-1 text-xs text-red-600">{errors.dob}</p>
            )}
          </div>

          {/* Phone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Phone
            </label>
            <input
              type="tel"
              value={form.phone}
              onChange={(e) => handleChange('phone', e.target.value)}
              placeholder="(555) 123-4567"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
          </div>

          {/* Address */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Address
            </label>
            <input
              type="text"
              value={form.address}
              onChange={(e) => handleChange('address', e.target.value)}
              placeholder="123 Main St, City, State ZIP"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
          </div>

          {/* Insurance section */}
          <div className="border-t border-gray-100 pt-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              Insurance Information
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Insurance Carrier
                </label>
                <input
                  type="text"
                  value={form.insurance_carrier}
                  onChange={(e) => handleChange('insurance_carrier', e.target.value)}
                  placeholder="e.g. Blue Cross Blue Shield"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">
                    Member ID
                  </label>
                  <input
                    type="text"
                    value={form.member_id}
                    onChange={(e) => handleChange('member_id', e.target.value)}
                    placeholder="Member ID"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">
                    Group Number
                  </label>
                  <input
                    type="text"
                    value={form.group_number}
                    onChange={(e) => handleChange('group_number', e.target.value)}
                    placeholder="Group #"
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Additional section */}
          <div className="border-t border-gray-100 pt-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              Additional Information
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Referring Physician
                </label>
                <input
                  type="text"
                  value={form.referring_physician}
                  onChange={(e) => handleChange('referring_physician', e.target.value)}
                  placeholder="Dr. Smith"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Language Preference
                </label>
                <select
                  value={form.language_preference}
                  onChange={(e) => handleChange('language_preference', e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                >
                  {LANGUAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Notes
                </label>
                <textarea
                  value={form.notes}
                  onChange={(e) => handleChange('notes', e.target.value)}
                  rows={3}
                  placeholder="Any additional notes about this patient..."
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors resize-none"
                />
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className={clsx(
                'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white',
                'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                'transition-colors shadow-sm',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4" />
                  Add Patient
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Patient Detail Slide-Over Panel
// ---------------------------------------------------------------------------

function PatientDetailPanel({ patientId, onClose, onUpdated }) {
  const navigate = useNavigate()
  const [patient, setPatient] = useState(null)
  const [appointments, setAppointments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingAppts, setLoadingAppts] = useState(true)
  const [error, setError] = useState(null)

  // Edit mode
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Fetch patient details
  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get(`/patients/${patientId}`)
        if (!cancelled) {
          setPatient(res.data)
          setEditForm(buildEditForm(res.data))
        }
      } catch (err) {
        if (!cancelled && err.response?.status !== 401) {
          setError(
            err.response?.data?.detail ||
              'Failed to load patient details.'
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [patientId])

  // Fetch patient appointments
  useEffect(() => {
    let cancelled = false
    async function loadAppts() {
      setLoadingAppts(true)
      try {
        const res = await api.get('/appointments/', {
          params: { patient_id: patientId, limit: 10 },
        })
        if (!cancelled) {
          const list = Array.isArray(res.data)
            ? res.data
            : res.data.appointments || []
          // Sort by date descending (most recent first)
          list.sort((a, b) => {
            const dateCmp = (b.date || '').localeCompare(a.date || '')
            if (dateCmp !== 0) return dateCmp
            return (b.time || '').localeCompare(a.time || '')
          })
          setAppointments(list)
        }
      } catch (err) {
        // Silently fail for appointments — main data already loaded
        if (!cancelled) setAppointments([])
      } finally {
        if (!cancelled) setLoadingAppts(false)
      }
    }
    loadAppts()
    return () => { cancelled = true }
  }, [patientId])

  function buildEditForm(data) {
    return {
      first_name: data.first_name || '',
      last_name: data.last_name || '',
      dob: data.dob || '',
      phone: data.phone || '',
      address: data.address || '',
      insurance_carrier: data.insurance_carrier || '',
      member_id: data.member_id || '',
      group_number: data.group_number || '',
      referring_physician: data.referring_physician || '',
      language_preference: data.language_preference || 'en',
      notes: data.notes || '',
    }
  }

  function handleEditChange(field, value) {
    setEditForm((prev) => ({ ...prev, [field]: value }))
  }

  function handleCancelEdit() {
    setEditing(false)
    setSaveError(null)
    if (patient) {
      setEditForm(buildEditForm(patient))
    }
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const body = {
        first_name: editForm.first_name.trim(),
        last_name: editForm.last_name.trim(),
        dob: editForm.dob,
        phone: editForm.phone.trim() || null,
        address: editForm.address.trim() || null,
        insurance_carrier: editForm.insurance_carrier.trim() || null,
        member_id: editForm.member_id.trim() || null,
        group_number: editForm.group_number.trim() || null,
        referring_physician: editForm.referring_physician.trim() || null,
        language_preference: editForm.language_preference || null,
        notes: editForm.notes.trim() || null,
      }
      const res = await api.put(`/patients/${patientId}`, body)
      setPatient(res.data)
      setEditForm(buildEditForm(res.data))
      setEditing(false)
      setSaveSuccess(true)
      if (onUpdated) onUpdated()
      // Clear success message after 3 seconds
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      setSaveError(
        err.response?.data?.detail ||
          'Failed to save changes. Please try again.'
      )
    } finally {
      setSaving(false)
    }
  }

  const fullName = patient
    ? [patient.first_name, patient.last_name].filter(Boolean).join(' ')
    : ''

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg bg-white shadow-2xl border-l border-gray-200 flex flex-col animate-slide-in-right">
        {/* Panel Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0">
              <span className="text-sm font-bold text-primary-700 uppercase">
                {patient?.first_name?.[0] || '?'}{patient?.last_name?.[0] || ''}
              </span>
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-gray-900 truncate">
                {loading ? 'Loading...' : fullName || 'Patient Details'}
              </h2>
              {patient && (
                <div className="flex items-center gap-2 mt-0.5">
                  {patient.is_new ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-green-50 text-green-700 ring-1 ring-inset ring-green-600/20">
                      New Patient
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-600/20">
                      Existing
                    </span>
                  )}
                  <span className="text-xs text-gray-400">
                    ID: {patient.id}
                  </span>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {patient && !editing && (
              <button
                onClick={() => setEditing(true)}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
                  'text-primary-700 bg-primary-50 border border-primary-200',
                  'hover:bg-primary-100 active:bg-primary-200',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40',
                  'transition-colors'
                )}
              >
                <Edit3 className="w-3.5 h-3.5" />
                Edit
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Panel Body */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <LoadingSpinner
              fullPage={false}
              message="Loading patient details..."
              size="md"
            />
          ) : error ? (
            <div className="p-6">
              <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            </div>
          ) : patient ? (
            <div className="p-6 space-y-6">
              {/* Save feedback */}
              {saveSuccess && (
                <div className="flex items-center gap-2.5 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm font-medium">
                  <Check className="w-4 h-4 flex-shrink-0" />
                  Changes saved successfully.
                </div>
              )}

              {saveError && (
                <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
                  <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>{saveError}</span>
                </div>
              )}

              {/* ---- Personal Information ---- */}
              <section>
                <h3 className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                  <Users className="w-3.5 h-3.5" />
                  Personal Information
                </h3>
                <div className="bg-gray-50 rounded-xl p-4 space-y-3">
                  {editing ? (
                    <>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">
                            First Name
                          </label>
                          <input
                            type="text"
                            value={editForm.first_name}
                            onChange={(e) => handleEditChange('first_name', e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">
                            Last Name
                          </label>
                          <input
                            type="text"
                            value={editForm.last_name}
                            onChange={(e) => handleEditChange('last_name', e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                          />
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Date of Birth
                        </label>
                        <input
                          type="date"
                          value={editForm.dob}
                          onChange={(e) => handleEditChange('dob', e.target.value)}
                          max={format(new Date(), 'yyyy-MM-dd')}
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Phone
                        </label>
                        <input
                          type="tel"
                          value={editForm.phone}
                          onChange={(e) => handleEditChange('phone', e.target.value)}
                          placeholder="(555) 123-4567"
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Address
                        </label>
                        <input
                          type="text"
                          value={editForm.address}
                          onChange={(e) => handleEditChange('address', e.target.value)}
                          placeholder="123 Main St, City, State ZIP"
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <DetailRow
                        icon={Calendar}
                        label="Date of Birth"
                        value={formatDateLong(patient.dob)}
                      />
                      <DetailRow
                        icon={Phone}
                        label="Phone"
                        value={formatPhone(patient.phone)}
                      />
                      <DetailRow
                        icon={MapPin}
                        label="Address"
                        value={patient.address || '--'}
                      />
                      <DetailRow
                        icon={Globe}
                        label="Language"
                        value={languageLabel(patient.language_preference)}
                      />
                    </>
                  )}
                </div>
              </section>

              {/* ---- Insurance Information ---- */}
              <section>
                <h3 className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                  <Shield className="w-3.5 h-3.5" />
                  Insurance Information
                </h3>
                <div className="bg-gray-50 rounded-xl p-4 space-y-3">
                  {editing ? (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Insurance Carrier
                        </label>
                        <input
                          type="text"
                          value={editForm.insurance_carrier}
                          onChange={(e) => handleEditChange('insurance_carrier', e.target.value)}
                          placeholder="e.g. Blue Cross Blue Shield"
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">
                            Member ID
                          </label>
                          <input
                            type="text"
                            value={editForm.member_id}
                            onChange={(e) => handleEditChange('member_id', e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-500 mb-1">
                            Group Number
                          </label>
                          <input
                            type="text"
                            value={editForm.group_number}
                            onChange={(e) => handleEditChange('group_number', e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                          />
                        </div>
                      </div>
                    </>
                  ) : (
                    <>
                      <DetailRow
                        icon={Shield}
                        label="Carrier"
                        value={patient.insurance_carrier || '--'}
                      />
                      <DetailRow
                        icon={FileText}
                        label="Member ID"
                        value={patient.member_id || '--'}
                      />
                      <DetailRow
                        icon={FileText}
                        label="Group Number"
                        value={patient.group_number || '--'}
                      />
                    </>
                  )}
                </div>
              </section>

              {/* ---- Additional Information ---- */}
              <section>
                <h3 className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                  <FileText className="w-3.5 h-3.5" />
                  Additional Information
                </h3>
                <div className="bg-gray-50 rounded-xl p-4 space-y-3">
                  {editing ? (
                    <>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Referring Physician
                        </label>
                        <input
                          type="text"
                          value={editForm.referring_physician}
                          onChange={(e) => handleEditChange('referring_physician', e.target.value)}
                          placeholder="Dr. Smith"
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Language Preference
                        </label>
                        <select
                          value={editForm.language_preference}
                          onChange={(e) => handleEditChange('language_preference', e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                        >
                          {LANGUAGE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">
                          Notes
                        </label>
                        <textarea
                          value={editForm.notes}
                          onChange={(e) => handleEditChange('notes', e.target.value)}
                          rows={3}
                          placeholder="Patient notes..."
                          className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors resize-none"
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <DetailRow
                        icon={Stethoscope}
                        label="Referring Physician"
                        value={patient.referring_physician || '--'}
                      />
                      <DetailRow
                        icon={Clock}
                        label="Patient Since"
                        value={formatDateLong(patient.created_at)}
                      />
                      {patient.notes && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 mb-1">Notes</p>
                          <p className="text-sm text-gray-700 whitespace-pre-wrap">
                            {patient.notes}
                          </p>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </section>

              {/* Edit mode actions */}
              {editing && (
                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={handleCancelEdit}
                    className="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving}
                    className={clsx(
                      'inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white',
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
                        Save Changes
                      </>
                    )}
                  </button>
                </div>
              )}

              {/* ---- Quick Actions ---- */}
              {!editing && (
                <div>
                  <button
                    onClick={() => navigate('/appointments?action=book')}
                    className={clsx(
                      'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold w-full justify-center',
                      'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                      'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                      'transition-colors shadow-sm hover:shadow-md'
                    )}
                  >
                    <CalendarPlus className="w-4 h-4" />
                    Book Appointment
                  </button>
                </div>
              )}

              {/* ---- Recent Appointments ---- */}
              {!editing && (
                <section>
                  <h3 className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                    <Calendar className="w-3.5 h-3.5" />
                    Recent Appointments
                  </h3>
                  {loadingAppts ? (
                    <div className="flex items-center gap-2 text-sm text-gray-500 py-4">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Loading appointments...
                    </div>
                  ) : appointments.length === 0 ? (
                    <div className="bg-gray-50 rounded-xl p-4 text-center">
                      <p className="text-sm text-gray-500">
                        No appointments found for this patient.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {appointments.map((appt) => (
                        <div
                          key={appt.id}
                          className="bg-gray-50 rounded-xl px-4 py-3 flex items-center justify-between gap-3"
                        >
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900">
                              {appt.date
                                ? format(parseISO(appt.date), 'MMM d, yyyy')
                                : '--'}
                              {' at '}
                              {formatTime(appt.time)}
                            </p>
                            <p className="text-xs text-gray-500 truncate">
                              {appt.appointment_type_name || 'Appointment'}
                              {appt.duration_minutes
                                ? ` (${appt.duration_minutes} min)`
                                : ''}
                            </p>
                          </div>
                          <ApptStatusBadge status={appt.status} />
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {/* Slide-in animation style */}
      <style>{`
        @keyframes slide-in-right {
          from { transform: translateX(100%); }
          to   { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.25s ease-out;
        }
      `}</style>
    </>
  )
}

// ---------------------------------------------------------------------------
// Detail Row (used in the patient detail panel)
// ---------------------------------------------------------------------------

function DetailRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-gray-500">{label}</p>
        <p className="text-sm text-gray-900 break-words">{value}</p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Patients Component
// ---------------------------------------------------------------------------

export default function Patients() {
  const navigate = useNavigate()

  // Search state
  const [nameQuery, setNameQuery] = useState('')
  const [phoneQuery, setPhoneQuery] = useState('')
  const [activeSearch, setActiveSearch] = useState(false)

  // Data state
  const [patients, setPatients] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Selected patient panel
  const [selectedPatientId, setSelectedPatientId] = useState(null)

  // Add patient modal
  const [showAddModal, setShowAddModal] = useState(false)

  // Success feedback
  const [feedback, setFeedback] = useState(null)

  // Clear feedback after 4 seconds
  useEffect(() => {
    if (feedback) {
      const timer = setTimeout(() => setFeedback(null), 4000)
      return () => clearTimeout(timer)
    }
  }, [feedback])

  /**
   * Search patients from the API.
   */
  const searchPatients = useCallback(
    async (name, phone) => {
      setLoading(true)
      setError(null)

      try {
        const params = {}
        if (name.trim()) {
          const parts = name.trim().split(/\s+/)
          if (parts.length >= 2) {
            params.first_name = parts[0]
            params.last_name = parts.slice(1).join(' ')
          } else {
            params.first_name = parts[0]
          }
        }
        if (phone.trim()) {
          params.phone = phone.trim()
        }

        const res = await api.get('/patients/search', { params })
        const data = res.data
        const list = Array.isArray(data) ? data : data.patients || []
        const totalCount =
          typeof data.total === 'number' ? data.total : list.length

        setPatients(list)
        setTotal(totalCount)
        setActiveSearch(true)
      } catch (err) {
        if (err.response?.status !== 401) {
          setError(
            err.response?.data?.detail ||
              'Failed to search patients. Please try again.'
          )
        }
      } finally {
        setLoading(false)
      }
    },
    []
  )

  function handleSearch(e) {
    e.preventDefault()
    if (!nameQuery.trim() && !phoneQuery.trim()) return
    searchPatients(nameQuery, phoneQuery)
  }

  function handleClearSearch() {
    setNameQuery('')
    setPhoneQuery('')
    setPatients([])
    setTotal(0)
    setActiveSearch(false)
    setError(null)
  }

  function handlePatientCreated() {
    setShowAddModal(false)
    setFeedback({ type: 'success', message: 'Patient created successfully!' })
    // Re-run search if active, to show the new patient
    if (activeSearch) {
      searchPatients(nameQuery, phoneQuery)
    }
  }

  function handlePatientUpdated() {
    // Re-run search to refresh the list
    if (activeSearch) {
      searchPatients(nameQuery, phoneQuery)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* ==================================================================
          HEADER
          ================================================================== */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Patients
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Search and manage patient records
          </p>
        </div>

        <button
          onClick={() => setShowAddModal(true)}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
            'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
            'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
            'transition-colors shadow-sm hover:shadow-md'
          )}
        >
          <UserPlus className="w-4 h-4" />
          Add Patient
        </button>
      </div>

      {/* ==================================================================
          SEARCH BAR
          ================================================================== */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <form
          onSubmit={handleSearch}
          className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 px-5 py-4"
        >
          {/* Name search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={nameQuery}
              onChange={(e) => setNameQuery(e.target.value)}
              placeholder="Search by patient name..."
              className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
          </div>

          {/* Phone search */}
          <div className="relative sm:w-48">
            <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="tel"
              value={phoneQuery}
              onChange={(e) => setPhoneQuery(e.target.value)}
              placeholder="Phone number..."
              className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
            />
          </div>

          {/* Buttons */}
          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={loading || (!nameQuery.trim() && !phoneQuery.trim())}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold',
                'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                'transition-colors shadow-sm',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              Search
            </button>

            {activeSearch && (
              <button
                type="button"
                onClick={handleClearSearch}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg text-sm font-medium',
                  'text-gray-700 bg-white border border-gray-300',
                  'hover:bg-gray-50 active:bg-gray-100',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                  'transition-colors'
                )}
              >
                <X className="w-4 h-4" />
                Clear
              </button>
            )}
          </div>
        </form>
      </div>

      {/* ==================================================================
          FEEDBACK TOAST
          ================================================================== */}
      {feedback && (
        <div
          className={clsx(
            'flex items-center gap-2.5 rounded-xl px-5 py-3 text-sm font-medium shadow-sm border',
            feedback.type === 'success'
              ? 'bg-green-50 border-green-200 text-green-700'
              : 'bg-red-50 border-red-200 text-red-700'
          )}
        >
          {feedback.type === 'success' ? (
            <Check className="w-4 h-4 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
          )}
          {feedback.message}
          <button
            onClick={() => setFeedback(null)}
            className="ml-auto p-1 rounded hover:bg-black/5 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ==================================================================
          ERROR ALERT
          ================================================================== */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">Something went wrong</p>
            <p className="mt-0.5 text-red-600">{error}</p>
          </div>
          <button
            onClick={() => searchPatients(nameQuery, phoneQuery)}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* ==================================================================
          PATIENTS TABLE
          ================================================================== */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Table header bar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Patient Records
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {!activeSearch
                ? 'Search for patients using the search bar above'
                : loading
                  ? 'Searching...'
                  : total === 0
                    ? 'No patients found'
                    : `${total} patient${total === 1 ? '' : 's'} found`}
            </p>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <LoadingSpinner
            fullPage={false}
            message="Searching patients..."
            size="md"
          />
        ) : !activeSearch ? (
          <EmptyState
            icon={Search}
            title="Search for patients"
            description="Enter a patient name or phone number above to find patient records."
          />
        ) : patients.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No patients found"
            description="No patients matched your search criteria. Try a different search or add a new patient."
            actionLabel="Add Patient"
            onAction={() => setShowAddModal(true)}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px]">
              <thead>
                <tr className="bg-gray-50/80">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Name
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Date of Birth
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Phone
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Insurance
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Language
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Status
                  </th>
                  <th className="w-10 px-3 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {patients.map((patient) => {
                  const fullName = [patient.first_name, patient.last_name]
                    .filter(Boolean)
                    .join(' ')

                  return (
                    <tr
                      key={patient.id}
                      onClick={() => setSelectedPatientId(patient.id)}
                      className="group cursor-pointer hover:bg-primary-50/40 transition-colors duration-150"
                    >
                      {/* Name */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0">
                            <span className="text-xs font-bold text-primary-700 uppercase">
                              {patient.first_name?.[0] || '?'}
                              {patient.last_name?.[0] || ''}
                            </span>
                          </div>
                          <span className="text-sm font-medium text-gray-900 group-hover:text-primary-700 transition-colors">
                            {fullName || 'Unknown'}
                          </span>
                        </div>
                      </td>

                      {/* DOB */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <span className="text-sm text-gray-600">
                          {formatDOB(patient.dob)}
                        </span>
                      </td>

                      {/* Phone */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <span className="text-sm text-gray-600">
                          {formatPhone(patient.phone)}
                        </span>
                      </td>

                      {/* Insurance */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <span className="text-sm text-gray-600">
                          {patient.insurance_carrier || '--'}
                        </span>
                      </td>

                      {/* Language */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <span className="text-sm text-gray-600">
                          {languageLabel(patient.language_preference)}
                        </span>
                      </td>

                      {/* Status (New/Existing) */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        {patient.is_new ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ring-1 ring-inset bg-green-50 text-green-700 ring-green-600/20">
                            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                            New
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ring-1 ring-inset bg-blue-50 text-blue-700 ring-blue-600/20">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                            Existing
                          </span>
                        )}
                      </td>

                      {/* Chevron */}
                      <td className="px-3 py-3.5">
                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-primary-500 transition-colors" />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ==================================================================
          MODALS / PANELS
          ================================================================== */}

      {/* Add Patient Modal */}
      {showAddModal && (
        <AddPatientModal
          onClose={() => setShowAddModal(false)}
          onCreated={handlePatientCreated}
        />
      )}

      {/* Patient Detail Slide-Over */}
      {selectedPatientId && (
        <PatientDetailPanel
          patientId={selectedPatientId}
          onClose={() => setSelectedPatientId(null)}
          onUpdated={handlePatientUpdated}
        />
      )}
    </div>
  )
}
