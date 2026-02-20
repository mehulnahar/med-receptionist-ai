import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  format,
  parseISO,
  addDays,
  subDays,
  startOfWeek,
  endOfWeek,
  isToday,
  isBefore,
} from 'date-fns'
import {
  Calendar,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
  X,
  Check,
  XCircle,
  MessageSquare,
  AlertCircle,
  RefreshCw,
  Clock,
  User,
  FileText,
  Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'booked', label: 'Booked' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'completed', label: 'Completed' },
  { value: 'no_show', label: 'No Show' },
  { value: 'entered_in_ehr', label: 'In EHR' },
]

const STATUS_CONFIG = {
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
  no_show: {
    label: 'No Show',
    bg: 'bg-orange-50',
    text: 'text-orange-700',
    ring: 'ring-orange-600/20',
    dot: 'bg-orange-500',
  },
  entered_in_ehr: {
    label: 'In EHR',
    bg: 'bg-purple-50',
    text: 'text-purple-700',
    ring: 'ring-purple-600/20',
    dot: 'bg-purple-500',
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert an HH:MM:SS or HH:MM time string to a user-friendly format. */
function formatTime(timeStr) {
  if (!timeStr) return '--'
  const [hours, minutes] = timeStr.split(':').map(Number)
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return format(date, 'h:mm a')
}

/** Return a date string in yyyy-MM-dd format. */
function toDateStr(date) {
  return format(date, 'yyyy-MM-dd')
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.booked
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

// ---------------------------------------------------------------------------
// Book Appointment Modal
// ---------------------------------------------------------------------------

function BookAppointmentModal({ onClose, onBooked }) {
  const [patientQuery, setPatientQuery] = useState('')
  const [patientResults, setPatientResults] = useState([])
  const [searchingPatients, setSearchingPatients] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState(null)
  const [appointmentTypes, setAppointmentTypes] = useState([])
  const [loadingTypes, setLoadingTypes] = useState(true)
  const [selectedTypeId, setSelectedTypeId] = useState('')
  const [bookDate, setBookDate] = useState(toDateStr(new Date()))
  const [bookTime, setBookTime] = useState('')
  const [availableSlots, setAvailableSlots] = useState([])
  const [loadingSlots, setLoadingSlots] = useState(false)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [showPatientDropdown, setShowPatientDropdown] = useState(false)

  // Load appointment types on mount
  useEffect(() => {
    let cancelled = false
    async function loadTypes() {
      try {
        const res = await api.get('/practice/appointment-types/')
        if (!cancelled) {
          const types = res.data.appointment_types || res.data || []
          setAppointmentTypes(types)
          if (types.length > 0) {
            setSelectedTypeId(String(types[0].id))
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load appointment types:', err)
        }
      } finally {
        if (!cancelled) setLoadingTypes(false)
      }
    }
    loadTypes()
    return () => { cancelled = true }
  }, [])

  // Patient search with debounce
  useEffect(() => {
    if (!patientQuery.trim() || patientQuery.trim().length < 2) {
      setPatientResults([])
      setShowPatientDropdown(false)
      return
    }

    const timer = setTimeout(async () => {
      setSearchingPatients(true)
      try {
        // Split into first/last name parts
        const parts = patientQuery.trim().split(/\s+/)
        const params = {}
        if (parts.length >= 2) {
          params.first_name = parts[0]
          params.last_name = parts.slice(1).join(' ')
        } else {
          params.first_name = parts[0]
        }
        const res = await api.get('/patients/search', { params })
        const patients = res.data.patients || res.data || []
        setPatientResults(patients)
        setShowPatientDropdown(true)
      } catch (err) {
        console.error('Patient search failed:', err)
        setPatientResults([])
      } finally {
        setSearchingPatients(false)
      }
    }, 350)

    return () => clearTimeout(timer)
  }, [patientQuery])

  // Fetch available time slots when date changes
  useEffect(() => {
    if (!bookDate) {
      setAvailableSlots([])
      return
    }
    let cancelled = false
    async function loadSlots() {
      setLoadingSlots(true)
      setBookTime('')
      try {
        const res = await api.get('/schedule/availability', { params: { date: bookDate } })
        if (!cancelled) {
          setAvailableSlots(res.data.slots || [])
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load availability:', err)
          setAvailableSlots([])
        }
      } finally {
        if (!cancelled) setLoadingSlots(false)
      }
    }
    loadSlots()
    return () => { cancelled = true }
  }, [bookDate])

  function handleSelectPatient(patient) {
    setSelectedPatient(patient)
    const displayName = [patient.first_name, patient.last_name].filter(Boolean).join(' ')
    setPatientQuery(displayName)
    setShowPatientDropdown(false)
  }

  function handleClearPatient() {
    setSelectedPatient(null)
    setPatientQuery('')
    setPatientResults([])
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    if (!selectedPatient) {
      setError('Please search for and select a patient.')
      return
    }
    if (!selectedTypeId) {
      setError('Please select an appointment type.')
      return
    }
    if (!bookDate) {
      setError('Please select a date.')
      return
    }
    if (!bookTime) {
      setError('Please select a time.')
      return
    }

    setSubmitting(true)
    try {
      const body = {
        patient_id: selectedPatient.id,
        appointment_type_id: selectedTypeId,
        date: bookDate,
        time: bookTime,
      }
      if (notes.trim()) body.notes = notes.trim()

      await api.post('/appointments/book', body)
      onBooked()
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          'Failed to book appointment. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="book-appointment-title">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary-100 flex items-center justify-center">
              <CalendarPlus className="w-5 h-5 text-primary-600" />
            </div>
            <div>
              <h2 id="book-appointment-title" className="text-lg font-semibold text-gray-900">
                Book Appointment
              </h2>
              <p className="text-sm text-gray-500">
                Schedule a new appointment
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
          {/* Error */}
          {error && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Patient Search */}
          <div className="relative">
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Patient <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={patientQuery}
                onChange={(e) => {
                  setPatientQuery(e.target.value)
                  if (selectedPatient) setSelectedPatient(null)
                }}
                placeholder="Search by patient name..."
                className={clsx(
                  'w-full pl-10 pr-10 py-2.5 rounded-lg border text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                  'transition-colors',
                  selectedPatient
                    ? 'border-green-300 bg-green-50/50'
                    : 'border-gray-300 bg-white'
                )}
              />
              {selectedPatient && (
                <button
                  type="button"
                  onClick={handleClearPatient}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
              {searchingPatients && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 animate-spin" />
              )}
            </div>

            {/* Patient dropdown */}
            {showPatientDropdown && patientResults.length > 0 && (
              <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {patientResults.map((patient) => (
                  <button
                    key={patient.id}
                    type="button"
                    onClick={() => handleSelectPatient(patient)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 transition-colors text-left"
                  >
                    <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0">
                      <User className="w-4 h-4 text-gray-500" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {[patient.first_name, patient.last_name].filter(Boolean).join(' ')}
                      </p>
                      {patient.phone && (
                        <p className="text-xs text-gray-500">{patient.phone}</p>
                      )}
                      {patient.date_of_birth && (
                        <p className="text-xs text-gray-500">
                          DOB: {format(parseISO(patient.date_of_birth), 'MM/dd/yyyy')}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {showPatientDropdown && patientResults.length === 0 && !searchingPatients && patientQuery.trim().length >= 2 && (
              <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg px-4 py-3">
                <p className="text-sm text-gray-500">No patients found.</p>
              </div>
            )}

            {selectedPatient && (
              <p className="mt-1 text-xs text-green-600 flex items-center gap-1">
                <Check className="w-3 h-3" />
                Patient selected: {[selectedPatient.first_name, selectedPatient.last_name].filter(Boolean).join(' ')}
              </p>
            )}
          </div>

          {/* Appointment Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Appointment Type <span className="text-red-500">*</span>
            </label>
            {loadingTypes ? (
              <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading appointment types...
              </div>
            ) : (
              <select
                value={selectedTypeId}
                onChange={(e) => setSelectedTypeId(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
              >
                <option value="">Select type...</option>
                {appointmentTypes.map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name}{type.duration_minutes ? ` (${type.duration_minutes} min)` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Date & Time row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Date <span className="text-red-500">*</span>
              </label>
              <input
                type="date"
                value={bookDate}
                onChange={(e) => setBookDate(e.target.value)}
                min={toDateStr(new Date())}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Time <span className="text-red-500">*</span>
              </label>
              {loadingSlots ? (
                <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Loading available slots...
                </div>
              ) : availableSlots.length > 0 ? (
                <select
                  value={bookTime}
                  onChange={(e) => setBookTime(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                >
                  <option value="">Select a time slot...</option>
                  {availableSlots.map((slot) => (
                    <option key={slot.time || slot} value={slot.time || slot}>
                      {slot.time || slot}
                    </option>
                  ))}
                </select>
              ) : bookDate ? (
                <p className="text-sm text-amber-600 py-2">No available slots for this date.</p>
              ) : (
                <p className="text-sm text-gray-500 py-2">Select a date first.</p>
              )}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Optional notes about this appointment..."
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors resize-none"
            />
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
                  Booking...
                </>
              ) : (
                <>
                  <CalendarPlus className="w-4 h-4" />
                  Book Appointment
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
// Cancel Confirmation Dialog
// ---------------------------------------------------------------------------

function CancelDialog({ appointment, onClose, onCancelled }) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  async function handleConfirmCancel() {
    setSubmitting(true)
    setError(null)
    try {
      const body = {}
      if (reason.trim()) body.reason = reason.trim()
      await api.put(`/appointments/${appointment.id}/cancel`, body)
      onCancelled()
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          'Failed to cancel appointment. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="cancel-appointment-title">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-red-100 flex items-center justify-center">
              <XCircle className="w-5 h-5 text-red-600" />
            </div>
            <h2 id="cancel-appointment-title" className="text-lg font-semibold text-gray-900">
              Cancel Appointment
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <p className="text-sm text-gray-600">
            Are you sure you want to cancel this appointment?
          </p>

          {/* Appointment details summary */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <User className="w-4 h-4 text-gray-400" />
              <span className="font-medium text-gray-900">
                {appointment.patient_name || 'Unknown Patient'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <Calendar className="w-4 h-4 text-gray-400" />
              <span>
                {appointment.date
                  ? format(parseISO(appointment.date), 'EEEE, MMMM d, yyyy')
                  : '--'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <Clock className="w-4 h-4 text-gray-400" />
              <span>{formatTime(appointment.time)}</span>
              {appointment.duration_minutes && (
                <span className="text-gray-400">
                  ({appointment.duration_minutes} min)
                </span>
              )}
            </div>
            {appointment.appointment_type_name && (
              <div className="flex items-center gap-2 text-sm text-gray-600">
                <FileText className="w-4 h-4 text-gray-400" />
                <span>{appointment.appointment_type_name}</span>
              </div>
            )}
          </div>

          {/* Reason */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Reason for cancellation (optional)
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Enter reason..."
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-red-500/40 focus:border-red-500 transition-colors resize-none"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2 transition-colors"
          >
            Keep Appointment
          </button>
          <button
            type="button"
            onClick={handleConfirmCancel}
            disabled={submitting}
            className={clsx(
              'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white',
              'bg-red-600 hover:bg-red-700 active:bg-red-800',
              'focus:outline-none focus:ring-2 focus:ring-red-500/40 focus:ring-offset-2',
              'transition-colors shadow-sm',
              'disabled:opacity-60 disabled:cursor-not-allowed'
            )}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Cancelling...
              </>
            ) : (
              'Confirm Cancellation'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Appointments Component
// ---------------------------------------------------------------------------

export default function Appointments() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // ---- Week navigation state ----
  const [weekStart, setWeekStart] = useState(() =>
    startOfWeek(new Date(), { weekStartsOn: 1 })
  )
  const weekEnd = useMemo(() => endOfWeek(weekStart, { weekStartsOn: 1 }), [weekStart])

  // ---- Filters ----
  const [statusFilter, setStatusFilter] = useState('')

  // ---- Data state ----
  const [appointments, setAppointments] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)

  // ---- Action states ----
  const [confirmingId, setConfirmingId] = useState(null)
  const [sendingSmsId, setSendingSmsId] = useState(null)
  const [actionFeedback, setActionFeedback] = useState(null)

  // ---- Modals ----
  const [showBookModal, setShowBookModal] = useState(false)
  const [cancelTarget, setCancelTarget] = useState(null)

  // Open book modal if URL param ?action=book is present
  useEffect(() => {
    if (searchParams.get('action') === 'book') {
      setShowBookModal(true)
      // Clean the URL param so reopening page doesn't auto-open
      const newParams = new URLSearchParams(searchParams)
      newParams.delete('action')
      setSearchParams(newParams, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Fetch appointments ----
  const fetchAppointments = useCallback(
    async (isRefresh = false) => {
      if (isRefresh) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)

      try {
        const params = {
          from_date: toDateStr(weekStart),
          to_date: toDateStr(weekEnd),
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }
        if (statusFilter) params.status = statusFilter

        const res = await api.get('/appointments/', { params })
        const data = res.data
        const list = Array.isArray(data) ? data : data.appointments || []
        const totalCount =
          typeof data.total === 'number' ? data.total : list.length

        // Sort by date then time ascending
        list.sort((a, b) => {
          const dateCmp = (a.date || '').localeCompare(b.date || '')
          if (dateCmp !== 0) return dateCmp
          return (a.time || '').localeCompare(b.time || '')
        })

        setAppointments(list)
        setTotal(totalCount)
      } catch (err) {
        if (err.response?.status !== 401) {
          setError(
            err.response?.data?.detail ||
              'Failed to load appointments. Please try again.'
          )
        }
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    // Use string representations to avoid referential inequality on Date objects
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [toDateStr(weekStart), toDateStr(weekEnd), statusFilter, page]
  )

  useEffect(() => {
    fetchAppointments()
  }, [fetchAppointments])

  // Reset page when filters change
  useEffect(() => {
    setPage(0)
  }, [weekStart, statusFilter])

  // ---- Action handlers ----

  async function handleConfirm(appointmentId) {
    setConfirmingId(appointmentId)
    setActionFeedback(null)
    try {
      await api.put(`/appointments/${appointmentId}/confirm`)
      setActionFeedback({ type: 'success', message: 'Appointment confirmed.' })
      fetchAppointments(true)
    } catch (err) {
      setActionFeedback({
        type: 'error',
        message:
          err.response?.data?.detail || 'Failed to confirm appointment.',
      })
    } finally {
      setConfirmingId(null)
    }
  }

  async function handleSendSms(appointmentId) {
    setSendingSmsId(appointmentId)
    setActionFeedback(null)
    try {
      await api.post(`/sms/send-confirmation/${appointmentId}`)
      setActionFeedback({ type: 'success', message: 'SMS sent successfully.' })
      fetchAppointments(true)
    } catch (err) {
      setActionFeedback({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to send SMS.',
      })
    } finally {
      setSendingSmsId(null)
    }
  }

  // Clear feedback after 4 seconds
  useEffect(() => {
    if (actionFeedback) {
      const timer = setTimeout(() => setActionFeedback(null), 4000)
      return () => clearTimeout(timer)
    }
  }, [actionFeedback])

  // ---- Week navigation ----
  function goToPrevWeek() {
    setWeekStart((prev) => subDays(prev, 7))
  }

  function goToNextWeek() {
    setWeekStart((prev) => addDays(prev, 7))
  }

  function goToThisWeek() {
    setWeekStart(startOfWeek(new Date(), { weekStartsOn: 1 }))
  }

  // ---- Pagination ----
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const canGoBack = page > 0
  const canGoForward = page < totalPages - 1

  // ---- Derived ----
  const isCurrentWeek =
    toDateStr(weekStart) ===
    toDateStr(startOfWeek(new Date(), { weekStartsOn: 1 }))

  // ---- Render ----

  return (
    <div className="space-y-6">
      {/* ==================================================================
          HEADER
          ================================================================== */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Appointments
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage and schedule patient appointments
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => fetchAppointments(true)}
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
          <button
            onClick={() => setShowBookModal(true)}
            className={clsx(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
              'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
              'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
              'transition-colors shadow-sm hover:shadow-md'
            )}
          >
            <CalendarPlus className="w-4 h-4" />
            Book New
          </button>
        </div>
      </div>

      {/* ==================================================================
          DATE RANGE SELECTOR + FILTERS
          ================================================================== */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 px-5 py-4">
          {/* Week picker */}
          <div className="flex items-center gap-3">
            <button
              onClick={goToPrevWeek}
              className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 hover:text-gray-900 active:bg-gray-100 transition-colors"
              title="Previous week"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            <div className="text-center min-w-[220px]">
              <p className="text-sm font-semibold text-gray-900">
                {format(weekStart, 'MMM d')} &ndash;{' '}
                {format(weekEnd, 'MMM d, yyyy')}
              </p>
              {isCurrentWeek && (
                <p className="text-xs text-primary-600 font-medium">
                  Current Week
                </p>
              )}
            </div>

            <button
              onClick={goToNextWeek}
              className="p-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 hover:text-gray-900 active:bg-gray-100 transition-colors"
              title="Next week"
            >
              <ChevronRight className="w-4 h-4" />
            </button>

            {!isCurrentWeek && (
              <button
                onClick={goToThisWeek}
                className="ml-1 px-3 py-1.5 rounded-lg text-xs font-medium text-primary-700 bg-primary-50 hover:bg-primary-100 transition-colors"
              >
                Today
              </button>
            )}
          </div>

          {/* Status filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <div className="flex items-center gap-1 flex-wrap">
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
        </div>
      </div>

      {/* ==================================================================
          ACTION FEEDBACK TOAST
          ================================================================== */}
      {actionFeedback && (
        <div
          className={clsx(
            'flex items-center gap-2.5 rounded-xl px-5 py-3 text-sm font-medium shadow-sm border',
            actionFeedback.type === 'success'
              ? 'bg-green-50 border-green-200 text-green-700'
              : 'bg-red-50 border-red-200 text-red-700'
          )}
        >
          {actionFeedback.type === 'success' ? (
            <Check className="w-4 h-4 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
          )}
          {actionFeedback.message}
          <button
            onClick={() => setActionFeedback(null)}
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
            onClick={() => fetchAppointments(true)}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* ==================================================================
          APPOINTMENTS TABLE
          ================================================================== */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {/* Table header bar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              Schedule
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {loading
                ? 'Loading...'
                : total === 0
                  ? 'No appointments found'
                  : `${total} appointment${total === 1 ? '' : 's'} found`}
            </p>
          </div>
        </div>

        {loading ? (
          <LoadingSpinner
            fullPage={false}
            message="Loading appointments..."
            size="md"
          />
        ) : appointments.length === 0 ? (
          <EmptyState
            icon={Calendar}
            title="No appointments found"
            description="There are no appointments matching your current filters. Try adjusting the date range or status filter, or book a new appointment."
            actionLabel="Book Appointment"
            onAction={() => setShowBookModal(true)}
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px]">
                <thead>
                  <tr className="bg-gray-50/80">
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Date
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Time
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Patient
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Type
                    </th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Status
                    </th>
                    <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      SMS
                    </th>
                    <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {appointments.map((appt) => {
                    const dateObj = appt.date ? parseISO(appt.date) : null
                    const todayRow = dateObj ? isToday(dateObj) : false
                    const pastDate = dateObj ? isBefore(dateObj, new Date()) && !todayRow : false
                    const canConfirm = appt.status === 'booked'
                    const canCancel =
                      appt.status === 'booked' || appt.status === 'confirmed'

                    return (
                      <tr
                        key={appt.id}
                        className={clsx(
                          'group transition-colors duration-150',
                          todayRow
                            ? 'bg-primary-50/30 hover:bg-primary-50/60'
                            : 'hover:bg-gray-50/80'
                        )}
                      >
                        {/* Date */}
                        <td className="px-5 py-3.5 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span
                              className={clsx(
                                'text-sm font-medium',
                                todayRow
                                  ? 'text-primary-700'
                                  : pastDate
                                    ? 'text-gray-400'
                                    : 'text-gray-900'
                              )}
                            >
                              {dateObj
                                ? format(dateObj, 'EEE, MMM d')
                                : '--'}
                            </span>
                            {todayRow && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide bg-primary-100 text-primary-700">
                                Today
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Time */}
                        <td className="px-5 py-3.5 whitespace-nowrap">
                          <span className="text-sm font-medium text-gray-900">
                            {formatTime(appt.time)}
                          </span>
                          {appt.duration_minutes && (
                            <span className="ml-1.5 text-xs text-gray-400">
                              ({appt.duration_minutes}m)
                            </span>
                          )}
                        </td>

                        {/* Patient */}
                        <td className="px-5 py-3.5 whitespace-nowrap">
                          <span className="text-sm font-medium text-gray-900">
                            {appt.patient_name || 'Unknown Patient'}
                          </span>
                        </td>

                        {/* Type */}
                        <td className="px-5 py-3.5 whitespace-nowrap">
                          <span className="text-sm text-gray-600">
                            {appt.appointment_type_name || '--'}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="px-5 py-3.5 whitespace-nowrap">
                          <StatusBadge status={appt.status} />
                        </td>

                        {/* SMS */}
                        <td className="px-5 py-3.5 whitespace-nowrap text-center">
                          {appt.sms_confirmation_sent ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700">
                              <MessageSquare className="w-3.5 h-3.5" />
                              Sent
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">--</span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-5 py-3.5 whitespace-nowrap text-right">
                          <div className="flex items-center justify-end gap-2">
                            {/* Confirm */}
                            {canConfirm && (
                              <button
                                onClick={() => handleConfirm(appt.id)}
                                disabled={confirmingId === appt.id}
                                title="Confirm appointment"
                                className={clsx(
                                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
                                  'text-green-700 bg-green-50 border border-green-200',
                                  'hover:bg-green-100 active:bg-green-200',
                                  'focus:outline-none focus:ring-2 focus:ring-green-500/40',
                                  'transition-colors',
                                  'disabled:opacity-60 disabled:cursor-not-allowed'
                                )}
                              >
                                {confirmingId === appt.id ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <Check className="w-3.5 h-3.5" />
                                )}
                                Confirm
                              </button>
                            )}

                            {/* Cancel */}
                            {canCancel && (
                              <button
                                onClick={() => setCancelTarget(appt)}
                                title="Cancel appointment"
                                className={clsx(
                                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
                                  'text-red-700 bg-red-50 border border-red-200',
                                  'hover:bg-red-100 active:bg-red-200',
                                  'focus:outline-none focus:ring-2 focus:ring-red-500/40',
                                  'transition-colors'
                                )}
                              >
                                <XCircle className="w-3.5 h-3.5" />
                                Cancel
                              </button>
                            )}

                            {/* Send SMS */}
                            {!appt.sms_confirmation_sent &&
                              appt.status !== 'cancelled' && (
                                <button
                                  onClick={() => handleSendSms(appt.id)}
                                  disabled={sendingSmsId === appt.id}
                                  title="Send SMS confirmation"
                                  className={clsx(
                                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium',
                                    'text-blue-700 bg-blue-50 border border-blue-200',
                                    'hover:bg-blue-100 active:bg-blue-200',
                                    'focus:outline-none focus:ring-2 focus:ring-blue-500/40',
                                    'transition-colors',
                                    'disabled:opacity-60 disabled:cursor-not-allowed'
                                  )}
                                >
                                  {sendingSmsId === appt.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <MessageSquare className="w-3.5 h-3.5" />
                                  )}
                                  SMS
                                </button>
                              )}

                            {/* No actions available */}
                            {!canConfirm && !canCancel && (appt.sms_confirmation_sent || appt.status === 'cancelled') && (
                              <span className="text-xs text-gray-400 italic">
                                No actions
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
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

      {/* ==================================================================
          MODALS
          ================================================================== */}

      {/* Book Appointment Modal */}
      {showBookModal && (
        <BookAppointmentModal
          onClose={() => setShowBookModal(false)}
          onBooked={() => {
            setShowBookModal(false)
            setActionFeedback({
              type: 'success',
              message: 'Appointment booked successfully!',
            })
            fetchAppointments(true)
          }}
        />
      )}

      {/* Cancel Confirmation Dialog */}
      {cancelTarget && (
        <CancelDialog
          appointment={cancelTarget}
          onClose={() => setCancelTarget(null)}
          onCancelled={() => {
            setCancelTarget(null)
            setActionFeedback({
              type: 'success',
              message: 'Appointment cancelled.',
            })
            fetchAppointments(true)
          }}
        />
      )}
    </div>
  )
}
