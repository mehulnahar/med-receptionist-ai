import { useState, useEffect, useCallback } from 'react'
import { format, parseISO } from 'date-fns'
import {
  Shield,
  Building2,
  Cog,
  Users as UsersIcon,
  Plus,
  Edit3,
  Save,
  Loader2,
  AlertCircle,
  Check,
  X,
  Eye,
  EyeOff,
  CheckCircle,
  XCircle,
  ToggleLeft,
  ToggleRight,
  Phone,
  Search,
  ChevronDown,
  ChevronRight,
  Trash2,
  RefreshCw,
  Bot,
  MessageSquare,
  Mic,
  CreditCard,
  Calendar,
  PhoneCall,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import { useAuth } from '../contexts/AuthContext'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ADMIN_TABS = [
  { id: 'practices', label: 'Practices', icon: Building2 },
  { id: 'config', label: 'Practice Config', icon: Cog },
  { id: 'users', label: 'Users', icon: UsersIcon },
]

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

const USER_ROLES = [
  { value: 'super_admin', label: 'Super Admin' },
  { value: 'practice_admin', label: 'Practice Admin' },
  { value: 'secretary', label: 'Secretary' },
]

const US_TIMEZONES = [
  { value: 'America/New_York', label: 'Eastern Time (ET)' },
  { value: 'America/Chicago', label: 'Central Time (CT)' },
  { value: 'America/Denver', label: 'Mountain Time (MT)' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (PT)' },
  { value: 'America/Anchorage', label: 'Alaska Time (AKT)' },
  { value: 'Pacific/Honolulu', label: 'Hawaii Time (HT)' },
  { value: 'America/Phoenix', label: 'Arizona (no DST)' },
]

const DEFAULT_SYSTEM_PROMPT = `You are a friendly and professional AI medical receptionist. Your role is to:

1. Greet callers warmly and identify yourself as the practice's AI assistant
2. Collect the caller's name, date of birth, and reason for calling
3. Check appointment availability and help schedule appointments
4. Verify insurance information when needed
5. Handle prescription refill requests by taking down details
6. Transfer calls to staff when the request requires human assistance
7. Provide basic office information (hours, location, accepted insurance)

Important guidelines:
- Always be empathetic and patient
- Never provide medical advice or diagnoses
- If the caller seems to have a medical emergency, advise them to call 911 or go to the nearest ER
- Confirm all details before booking appointments
- If you cannot help with something, offer to transfer to a staff member
- Support both English and Spanish speakers`

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
        'fixed top-4 right-4 z-50 flex items-center gap-2.5 rounded-xl px-5 py-3 text-sm font-medium shadow-lg border max-w-md',
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
      <span className="flex-1">{message}</span>
      <button
        onClick={onClose}
        className="ml-auto p-1 rounded hover:bg-black/5 transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

function SectionCard({ title, description, icon: Icon, children }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {(title || description) && (
        <div className="px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            {Icon && (
              <div className="w-8 h-8 rounded-lg bg-primary-100 flex items-center justify-center flex-shrink-0">
                <Icon className="w-4 h-4 text-primary-600" />
              </div>
            )}
            <div>
              {title && (
                <h3 className="text-base font-semibold text-gray-900">{title}</h3>
              )}
              {description && (
                <p className="text-sm text-gray-500 mt-0.5">{description}</p>
              )}
            </div>
          </div>
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

function SelectInput({ id, value, onChange, options, disabled, placeholder, className: extra }) {
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
      {placeholder && (
        <option value="">{placeholder}</option>
      )}
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

function MaskedInput({ id, value, onChange, placeholder, disabled }) {
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
            : 'border-gray-300'
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

function StatusBadge({ status }) {
  const config = {
    active: { label: 'Active', bg: 'bg-green-50', text: 'text-green-700', dot: 'bg-green-500' },
    suspended: { label: 'Suspended', bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
  }
  const c = config[status] || config.active
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold',
        c.bg, c.text
      )}
    >
      <span className={clsx('w-1.5 h-1.5 rounded-full', c.dot)} />
      {c.label}
    </span>
  )
}

function RoleBadge({ role }) {
  const config = {
    super_admin: { label: 'Super Admin', bg: 'bg-purple-100', text: 'text-purple-700' },
    practice_admin: { label: 'Practice Admin', bg: 'bg-primary-100', text: 'text-primary-700' },
    secretary: { label: 'Secretary', bg: 'bg-green-100', text: 'text-green-700' },
  }
  const c = config[role] || { label: role, bg: 'bg-gray-100', text: 'text-gray-700' }
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
        c.bg, c.text
      )}
    >
      {c.label}
    </span>
  )
}

function Modal({ open, onClose, title, children, wide }) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="admin-modal-title">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Dialog */}
      <div
        className={clsx(
          'relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full overflow-hidden',
          wide ? 'max-w-2xl' : 'max-w-lg'
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h3 id="admin-modal-title" className="text-lg font-semibold text-gray-900">{title}</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        {/* Body */}
        <div className="px-6 py-5 max-h-[70vh] overflow-y-auto">
          {children}
        </div>
      </div>
    </div>
  )
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  try {
    return format(parseISO(dateStr), 'MMM d, yyyy')
  } catch {
    return dateStr
  }
}

// ---------------------------------------------------------------------------
// Tab 1: Practices
// ---------------------------------------------------------------------------

function PracticesTab({ practices, setPractices, selectedPractice, setSelectedPractice, onRefresh, loading, setToast }) {
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm, setAddForm] = useState({
    name: '', slug: '', phone: '', address: '', timezone: 'America/New_York', npi: '', tax_id: '',
  })
  const [adding, setAdding] = useState(false)

  // Inline editing
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [savingId, setSavingId] = useState(null)

  function resetAddForm() {
    setAddForm({ name: '', slug: '', phone: '', address: '', timezone: 'America/New_York', npi: '', tax_id: '' })
  }

  async function handleAddPractice() {
    if (!addForm.name.trim()) {
      setToast({ type: 'error', message: 'Practice name is required.' })
      return
    }
    if (!addForm.slug.trim()) {
      setToast({ type: 'error', message: 'Practice slug is required.' })
      return
    }
    setAdding(true)
    try {
      const body = {
        name: addForm.name.trim(),
        slug: addForm.slug.trim(),
      }
      if (addForm.phone.trim()) body.phone = addForm.phone.trim()
      if (addForm.address.trim()) body.address = addForm.address.trim()
      if (addForm.timezone) body.timezone = addForm.timezone
      if (addForm.npi.trim()) body.npi = addForm.npi.trim()
      if (addForm.tax_id.trim()) body.tax_id = addForm.tax_id.trim()

      await api.post('/admin/practices', body)
      setToast({ type: 'success', message: 'Practice created successfully.' })
      setShowAddModal(false)
      resetAddForm()
      onRefresh()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to create practice.',
      })
    } finally {
      setAdding(false)
    }
  }

  function startEdit(practice) {
    setEditingId(practice.id)
    setEditForm({
      name: practice.name || '',
      phone: practice.phone || '',
      address: practice.address || '',
      timezone: practice.timezone || 'America/New_York',
      npi: practice.npi || '',
      tax_id: practice.tax_id || '',
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm({})
  }

  async function saveEdit(id) {
    if (!editForm.name.trim()) {
      setToast({ type: 'error', message: 'Practice name is required.' })
      return
    }
    setSavingId(id)
    try {
      await api.put(`/admin/practices/${id}`, {
        name: editForm.name.trim(),
        phone: editForm.phone.trim() || undefined,
        address: editForm.address.trim() || undefined,
        timezone: editForm.timezone || undefined,
        npi: editForm.npi.trim() || undefined,
        tax_id: editForm.tax_id.trim() || undefined,
      })
      setToast({ type: 'success', message: 'Practice updated successfully.' })
      setEditingId(null)
      onRefresh()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update practice.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function toggleStatus(practice) {
    setSavingId(practice.id)
    try {
      const newStatus = practice.status === 'active' ? 'suspended' : 'active'
      await api.put(`/admin/practices/${practice.id}`, { status: newStatus })
      setToast({
        type: 'success',
        message: `Practice ${newStatus === 'active' ? 'activated' : 'suspended'} successfully.`,
      })
      onRefresh()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update practice status.',
      })
    } finally {
      setSavingId(null)
    }
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading practices..." size="md" />
  }

  return (
    <div className="space-y-4">
      {/* Header with Add button */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {practices.length} practice{practices.length !== 1 ? 's' : ''} registered
        </p>
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
            'transition-colors shadow-sm'
          )}
        >
          <Plus className="w-4 h-4" />
          Add Practice
        </button>
      </div>

      {/* Practices list */}
      {practices.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No practices found"
          description="Create your first practice to get started."
          actionLabel="Add Practice"
          onAction={() => setShowAddModal(true)}
        />
      ) : (
        <div className="space-y-3">
          {practices.map((practice) => {
            const isSelected = selectedPractice?.id === practice.id
            const isEditing = editingId === practice.id

            return (
              <div
                key={practice.id}
                className={clsx(
                  'rounded-xl border transition-all duration-200',
                  isSelected && !isEditing
                    ? 'border-primary-300 bg-primary-50/40 shadow-sm'
                    : isEditing
                      ? 'border-primary-300 bg-primary-50/30'
                      : 'border-gray-200 bg-white hover:border-gray-300'
                )}
              >
                {isEditing ? (
                  /* Inline editing mode */
                  <div className="p-5 space-y-4">
                    <p className="text-sm font-semibold text-gray-900">
                      Edit Practice
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <FieldLabel required>Practice Name</FieldLabel>
                        <TextInput
                          value={editForm.name}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, name: e.target.value }))}
                          placeholder="Enter practice name"
                        />
                      </div>
                      <div>
                        <FieldLabel>Phone</FieldLabel>
                        <TextInput
                          type="tel"
                          value={editForm.phone}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, phone: e.target.value }))}
                          placeholder="(555) 123-4567"
                        />
                      </div>
                      <div>
                        <FieldLabel>Timezone</FieldLabel>
                        <SelectInput
                          value={editForm.timezone}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, timezone: e.target.value }))}
                          options={US_TIMEZONES}
                        />
                      </div>
                      <div>
                        <FieldLabel>Address</FieldLabel>
                        <TextInput
                          value={editForm.address}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, address: e.target.value }))}
                          placeholder="123 Main St, City, State"
                        />
                      </div>
                      <div>
                        <FieldLabel>NPI</FieldLabel>
                        <TextInput
                          value={editForm.npi}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, npi: e.target.value }))}
                          placeholder="NPI Number"
                        />
                      </div>
                      <div>
                        <FieldLabel>Tax ID</FieldLabel>
                        <TextInput
                          value={editForm.tax_id}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, tax_id: e.target.value }))}
                          placeholder="Tax ID"
                        />
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2 pt-2">
                      <button
                        type="button"
                        onClick={cancelEdit}
                        className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => saveEdit(practice.id)}
                        disabled={savingId === practice.id}
                        className={clsx(
                          'inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-white',
                          'bg-primary-600 hover:bg-primary-700',
                          'transition-colors',
                          'disabled:opacity-60 disabled:cursor-not-allowed'
                        )}
                      >
                        {savingId === practice.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Check className="w-3.5 h-3.5" />
                        )}
                        Save
                      </button>
                    </div>
                  </div>
                ) : (
                  /* Display mode */
                  <div
                    className="p-5 cursor-pointer"
                    onClick={() => setSelectedPractice(isSelected ? null : practice)}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-4 min-w-0 flex-1">
                        {/* Expand indicator */}
                        <div className="pt-0.5 flex-shrink-0">
                          {isSelected ? (
                            <ChevronDown className="w-4 h-4 text-primary-500" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-gray-400" />
                          )}
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-3 flex-wrap">
                            <h4 className="text-sm font-semibold text-gray-900">
                              {practice.name}
                            </h4>
                            <StatusBadge status={practice.status || 'active'} />
                          </div>
                          <div className="flex items-center gap-4 mt-1.5 flex-wrap">
                            {practice.phone && (
                              <span className="text-xs text-gray-500 flex items-center gap-1">
                                <Phone className="w-3 h-3" />
                                {practice.phone}
                              </span>
                            )}
                            {practice.slug && (
                              <span className="text-xs text-gray-400">
                                slug: {practice.slug}
                              </span>
                            )}
                            <span className="text-xs text-gray-400">
                              Created {formatDate(practice.created_at)}
                            </span>
                          </div>

                          {/* Expanded details */}
                          {isSelected && (
                            <div className="mt-4 pt-4 border-t border-gray-100">
                              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                                <div>
                                  <span className="text-gray-500">Address</span>
                                  <p className="text-gray-900 font-medium mt-0.5">
                                    {practice.address || '--'}
                                  </p>
                                </div>
                                <div>
                                  <span className="text-gray-500">NPI</span>
                                  <p className="text-gray-900 font-medium mt-0.5">
                                    {practice.npi || '--'}
                                  </p>
                                </div>
                                <div>
                                  <span className="text-gray-500">Tax ID</span>
                                  <p className="text-gray-900 font-medium mt-0.5">
                                    {practice.tax_id || '--'}
                                  </p>
                                </div>
                                <div>
                                  <span className="text-gray-500">Timezone</span>
                                  <p className="text-gray-900 font-medium mt-0.5">
                                    {practice.timezone || '--'}
                                  </p>
                                </div>
                                <div>
                                  <span className="text-gray-500">ID</span>
                                  <p className="text-gray-900 font-medium mt-0.5 font-mono text-xs">
                                    {practice.id}
                                  </p>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => toggleStatus(practice)}
                          disabled={savingId === practice.id}
                          title={practice.status === 'active' ? 'Suspend' : 'Activate'}
                          className={clsx(
                            'p-1.5 rounded-lg transition-colors',
                            practice.status === 'active'
                              ? 'text-green-600 hover:bg-green-50'
                              : 'text-red-500 hover:bg-red-50',
                            'disabled:opacity-50 disabled:cursor-not-allowed'
                          )}
                        >
                          {savingId === practice.id ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : practice.status === 'active' ? (
                            <ToggleRight className="w-5 h-5" />
                          ) : (
                            <ToggleLeft className="w-5 h-5" />
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => startEdit(practice)}
                          className="p-1.5 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                          title="Edit"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Add Practice Modal */}
      <Modal
        open={showAddModal}
        onClose={() => { setShowAddModal(false); resetAddForm() }}
        title="Add New Practice"
        wide
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <FieldLabel required>Practice Name</FieldLabel>
              <TextInput
                value={addForm.name}
                onChange={(e) => setAddForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="e.g. Dr. Smith's Medical Office"
              />
            </div>
            <div>
              <FieldLabel required>Slug</FieldLabel>
              <TextInput
                value={addForm.slug}
                onChange={(e) => setAddForm((prev) => ({
                  ...prev,
                  slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'),
                }))}
                placeholder="e.g. dr-smiths-office"
              />
              <p className="mt-1 text-xs text-gray-400">
                URL-friendly identifier (lowercase, hyphens only)
              </p>
            </div>
            <div>
              <FieldLabel>Phone</FieldLabel>
              <TextInput
                type="tel"
                value={addForm.phone}
                onChange={(e) => setAddForm((prev) => ({ ...prev, phone: e.target.value }))}
                placeholder="(555) 123-4567"
              />
            </div>
            <div>
              <FieldLabel>Timezone</FieldLabel>
              <SelectInput
                value={addForm.timezone}
                onChange={(e) => setAddForm((prev) => ({ ...prev, timezone: e.target.value }))}
                options={US_TIMEZONES}
              />
            </div>
            <div className="sm:col-span-2">
              <FieldLabel>Address</FieldLabel>
              <TextInput
                value={addForm.address}
                onChange={(e) => setAddForm((prev) => ({ ...prev, address: e.target.value }))}
                placeholder="123 Main St, City, State ZIP"
              />
            </div>
            <div>
              <FieldLabel>NPI Number</FieldLabel>
              <TextInput
                value={addForm.npi}
                onChange={(e) => setAddForm((prev) => ({ ...prev, npi: e.target.value }))}
                placeholder="NPI Number"
              />
            </div>
            <div>
              <FieldLabel>Tax ID</FieldLabel>
              <TextInput
                value={addForm.tax_id}
                onChange={(e) => setAddForm((prev) => ({ ...prev, tax_id: e.target.value }))}
                placeholder="Tax ID"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={() => { setShowAddModal(false); resetAddForm() }}
              className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAddPractice}
              disabled={adding}
              className={clsx(
                'inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white',
                'bg-primary-600 hover:bg-primary-700',
                'transition-colors',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {adding ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4" />
                  Create Practice
                </>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2: Practice Config
// ---------------------------------------------------------------------------

function PracticeConfigTab({ selectedPractice, setToast }) {
  const [loading, setLoading] = useState(false)
  const [config, setConfig] = useState(null)

  // Section save states
  const [vapiSaving, setVapiSaving] = useState(false)
  const [twilioSaving, setTwilioSaving] = useState(false)
  const [stediSaving, setStediSaving] = useState(false)
  const [bookingSaving, setBookingSaving] = useState(false)

  // Vapi form
  const [vapiForm, setVapiForm] = useState({
    vapi_api_key: '',
    vapi_assistant_id: '',
    vapi_phone_number_id: '',
    vapi_system_prompt: DEFAULT_SYSTEM_PROMPT,
    vapi_first_message: '',
    vapi_model_provider: 'openai',
    vapi_model_name: 'gpt-4o-mini',
    vapi_voice_provider: '11labs',
    vapi_voice_id: '',
  })

  // Twilio form
  const [twilioForm, setTwilioForm] = useState({
    twilio_account_sid: '',
    twilio_auth_token: '',
    twilio_phone_number: '',
    sms_enabled: false,
  })

  // Stedi form
  const [stediForm, setStediForm] = useState({
    stedi_api_key: '',
    stedi_enabled: false,
  })

  // Booking form
  const [bookingForm, setBookingForm] = useState({
    slot_duration_minutes: 30,
    booking_horizon_days: 30,
    allow_overbooking: false,
    max_overbooking_per_slot: 1,
    transfer_number: '',
  })

  const fetchConfig = useCallback(async () => {
    if (!selectedPractice) return
    setLoading(true)
    try {
      const res = await api.get(`/admin/practices/${selectedPractice.id}/config`)
      const data = res.data
      setConfig(data)

      // Populate forms from config
      setVapiForm({
        vapi_api_key: data.vapi_api_key || '',
        vapi_assistant_id: data.vapi_assistant_id || '',
        vapi_phone_number_id: data.vapi_phone_number_id || '',
        vapi_system_prompt: data.vapi_system_prompt || DEFAULT_SYSTEM_PROMPT,
        vapi_first_message: data.vapi_first_message || '',
        vapi_model_provider: data.vapi_model_provider || 'openai',
        vapi_model_name: data.vapi_model_name || 'gpt-4o-mini',
        vapi_voice_provider: data.vapi_voice_provider || '11labs',
        vapi_voice_id: data.vapi_voice_id || '',
      })

      setTwilioForm({
        twilio_account_sid: data.twilio_account_sid || '',
        twilio_auth_token: data.twilio_auth_token || '',
        twilio_phone_number: data.twilio_phone_number || '',
        sms_enabled: data.sms_enabled ?? false,
      })

      setStediForm({
        stedi_api_key: data.stedi_api_key || '',
        stedi_enabled: data.stedi_enabled ?? false,
      })

      setBookingForm({
        slot_duration_minutes: data.slot_duration_minutes ?? 30,
        booking_horizon_days: data.booking_horizon_days ?? 30,
        allow_overbooking: data.allow_overbooking ?? false,
        max_overbooking_per_slot: data.max_overbooking_per_slot ?? 1,
        transfer_number: data.transfer_number || '',
      })
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to load practice configuration.',
      })
    } finally {
      setLoading(false)
    }
  }, [selectedPractice, setToast])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  async function saveSection(sectionData, setSaving, successMsg) {
    if (!selectedPractice) return
    setSaving(true)
    try {
      await api.put(`/admin/practices/${selectedPractice.id}/config`, sectionData)
      setToast({ type: 'success', message: successMsg })
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to save configuration.',
      })
    } finally {
      setSaving(false)
    }
  }

  async function saveVapi() {
    await saveSection(
      {
        vapi_api_key: vapiForm.vapi_api_key.trim() || undefined,
        vapi_assistant_id: vapiForm.vapi_assistant_id.trim() || undefined,
        vapi_phone_number_id: vapiForm.vapi_phone_number_id.trim() || undefined,
        vapi_system_prompt: vapiForm.vapi_system_prompt.trim() || undefined,
        vapi_first_message: vapiForm.vapi_first_message.trim() || undefined,
        vapi_model_provider: vapiForm.vapi_model_provider || undefined,
        vapi_model_name: vapiForm.vapi_model_name || undefined,
        vapi_voice_provider: vapiForm.vapi_voice_provider || undefined,
        vapi_voice_id: vapiForm.vapi_voice_id.trim() || undefined,
      },
      setVapiSaving,
      'Vapi configuration saved successfully.'
    )
  }

  async function saveTwilio() {
    await saveSection(
      {
        twilio_account_sid: twilioForm.twilio_account_sid.trim() || undefined,
        twilio_auth_token: twilioForm.twilio_auth_token.trim() || undefined,
        twilio_phone_number: twilioForm.twilio_phone_number.trim() || undefined,
        sms_enabled: twilioForm.sms_enabled,
      },
      setTwilioSaving,
      'Twilio configuration saved successfully.'
    )
  }

  async function saveStedi() {
    await saveSection(
      {
        stedi_api_key: stediForm.stedi_api_key.trim() || undefined,
        stedi_enabled: stediForm.stedi_enabled,
      },
      setStediSaving,
      'Stedi configuration saved successfully.'
    )
  }

  async function saveBooking() {
    await saveSection(
      {
        slot_duration_minutes: parseInt(bookingForm.slot_duration_minutes, 10) || 30,
        booking_horizon_days: parseInt(bookingForm.booking_horizon_days, 10) || 30,
        allow_overbooking: bookingForm.allow_overbooking,
        max_overbooking_per_slot: parseInt(bookingForm.max_overbooking_per_slot, 10) || 1,
        transfer_number: bookingForm.transfer_number.trim() || undefined,
      },
      setBookingSaving,
      'Booking settings saved successfully.'
    )
  }

  if (!selectedPractice) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
        <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center mb-5">
          <Cog className="w-8 h-8 text-gray-400" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">
          Select a Practice First
        </h3>
        <p className="text-sm text-gray-500 max-w-sm">
          Go to the Practices tab and click on a practice to view and edit its configuration.
        </p>
      </div>
    )
  }

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading practice configuration..." size="md" />
  }

  return (
    <div className="space-y-6">
      {/* Selected practice indicator */}
      <div className="flex items-center gap-3 bg-primary-50 border border-primary-200 rounded-xl px-5 py-3">
        <Building2 className="w-5 h-5 text-primary-600 flex-shrink-0" />
        <div>
          <p className="text-sm font-semibold text-primary-900">
            Configuring: {selectedPractice.name}
          </p>
          <p className="text-xs text-primary-600">
            Changes apply only to this practice
          </p>
        </div>
      </div>

      {/* Vapi Configuration */}
      <SectionCard
        title="Vapi Configuration"
        description="Voice AI assistant settings powered by Vapi.ai"
        icon={Bot}
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="vapi-key">API Key</FieldLabel>
              <MaskedInput
                id="vapi-key"
                value={vapiForm.vapi_api_key}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_api_key: e.target.value }))}
                placeholder="Vapi API Key"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-assistant">Assistant ID</FieldLabel>
              <TextInput
                id="vapi-assistant"
                value={vapiForm.vapi_assistant_id}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_assistant_id: e.target.value }))}
                placeholder="Vapi Assistant ID"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-phone">Phone Number ID</FieldLabel>
              <TextInput
                id="vapi-phone"
                value={vapiForm.vapi_phone_number_id}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_phone_number_id: e.target.value }))}
                placeholder="Vapi Phone Number ID"
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-voice-id">Voice ID</FieldLabel>
              <TextInput
                id="vapi-voice-id"
                value={vapiForm.vapi_voice_id}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_voice_id: e.target.value }))}
                placeholder="Voice ID (e.g. ElevenLabs voice)"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
            <div>
              <FieldLabel htmlFor="vapi-model-provider">Model Provider</FieldLabel>
              <SelectInput
                id="vapi-model-provider"
                value={vapiForm.vapi_model_provider}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_model_provider: e.target.value }))}
                options={MODEL_PROVIDERS}
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-model-name">Model Name</FieldLabel>
              <SelectInput
                id="vapi-model-name"
                value={vapiForm.vapi_model_name}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_model_name: e.target.value }))}
                options={MODEL_NAMES}
              />
            </div>
            <div>
              <FieldLabel htmlFor="vapi-voice-provider">Voice Provider</FieldLabel>
              <SelectInput
                id="vapi-voice-provider"
                value={vapiForm.vapi_voice_provider}
                onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_voice_provider: e.target.value }))}
                options={VOICE_PROVIDERS}
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="vapi-first-message">First Message</FieldLabel>
            <TextInput
              id="vapi-first-message"
              value={vapiForm.vapi_first_message}
              onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_first_message: e.target.value }))}
              placeholder="e.g. Hello! Thank you for calling Dr. Smith's office. How can I help you today?"
            />
            <p className="mt-1 text-xs text-gray-400">
              The opening message the AI assistant says when answering a call
            </p>
          </div>

          <div>
            <FieldLabel htmlFor="vapi-system-prompt">System Prompt</FieldLabel>
            <textarea
              id="vapi-system-prompt"
              value={vapiForm.vapi_system_prompt}
              onChange={(e) => setVapiForm((prev) => ({ ...prev, vapi_system_prompt: e.target.value }))}
              rows={12}
              placeholder="Enter the AI assistant's system prompt..."
              className={clsx(
                'w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500',
                'transition-colors resize-y font-mono'
              )}
            />
            <p className="mt-1 text-xs text-gray-400">
              Full personality and behavior prompt for the AI assistant. This defines how it interacts with callers.
            </p>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton saving={vapiSaving} onClick={saveVapi} label="Save Vapi Settings" />
          </div>
        </div>
      </SectionCard>

      {/* Twilio Configuration */}
      <SectionCard
        title="Twilio Configuration"
        description="Voice calls and SMS telephony settings"
        icon={PhoneCall}
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="tw-sid">Account SID</FieldLabel>
              <TextInput
                id="tw-sid"
                value={twilioForm.twilio_account_sid}
                onChange={(e) => setTwilioForm((prev) => ({ ...prev, twilio_account_sid: e.target.value }))}
                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              />
            </div>
            <div>
              <FieldLabel htmlFor="tw-token">Auth Token</FieldLabel>
              <MaskedInput
                id="tw-token"
                value={twilioForm.twilio_auth_token}
                onChange={(e) => setTwilioForm((prev) => ({ ...prev, twilio_auth_token: e.target.value }))}
                placeholder="Twilio Auth Token"
              />
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="tw-phone">Phone Number</FieldLabel>
            <div className="sm:w-72">
              <TextInput
                id="tw-phone"
                type="tel"
                value={twilioForm.twilio_phone_number}
                onChange={(e) => setTwilioForm((prev) => ({ ...prev, twilio_phone_number: e.target.value }))}
                placeholder="+15551234567"
              />
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Twilio phone number in E.164 format
            </p>
          </div>

          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">SMS Enabled</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Enable sending SMS confirmations for appointments
                </p>
              </div>
              <Toggle
                enabled={twilioForm.sms_enabled}
                onChange={(val) => setTwilioForm((prev) => ({ ...prev, sms_enabled: val }))}
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton saving={twilioSaving} onClick={saveTwilio} label="Save Twilio Settings" />
          </div>
        </div>
      </SectionCard>

      {/* Stedi Configuration */}
      <SectionCard
        title="Stedi Configuration"
        description="Insurance eligibility verification via Stedi"
        icon={CreditCard}
      >
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Stedi Enabled</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Enable real-time insurance eligibility checks
              </p>
            </div>
            <Toggle
              enabled={stediForm.stedi_enabled}
              onChange={(val) => setStediForm((prev) => ({ ...prev, stedi_enabled: val }))}
            />
          </div>

          <div>
            <FieldLabel htmlFor="stedi-key">API Key</FieldLabel>
            <div className="sm:w-96">
              <MaskedInput
                id="stedi-key"
                value={stediForm.stedi_api_key}
                onChange={(e) => setStediForm((prev) => ({ ...prev, stedi_api_key: e.target.value }))}
                placeholder="Stedi API Key"
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton saving={stediSaving} onClick={saveStedi} label="Save Stedi Settings" />
          </div>
        </div>
      </SectionCard>

      {/* Booking Settings */}
      <SectionCard
        title="Booking Settings"
        description="Appointment scheduling and staff transfer configuration"
        icon={Calendar}
      >
        <div className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <FieldLabel htmlFor="cfg-slot">Slot Duration (minutes)</FieldLabel>
              <TextInput
                id="cfg-slot"
                type="number"
                min="5"
                max="240"
                step="5"
                value={bookingForm.slot_duration_minutes}
                onChange={(e) => setBookingForm((prev) => ({ ...prev, slot_duration_minutes: e.target.value }))}
              />
              <p className="mt-1 text-xs text-gray-400">Duration of each appointment slot</p>
            </div>
            <div>
              <FieldLabel htmlFor="cfg-horizon">Booking Horizon (days)</FieldLabel>
              <TextInput
                id="cfg-horizon"
                type="number"
                min="1"
                max="365"
                value={bookingForm.booking_horizon_days}
                onChange={(e) => setBookingForm((prev) => ({ ...prev, booking_horizon_days: e.target.value }))}
              />
              <p className="mt-1 text-xs text-gray-400">How far in advance patients can book</p>
            </div>
          </div>

          <div className="border-t border-gray-100 pt-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700">Allow Overbooking</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Allow multiple patients per time slot
                </p>
              </div>
              <Toggle
                enabled={bookingForm.allow_overbooking}
                onChange={(val) => setBookingForm((prev) => ({ ...prev, allow_overbooking: val }))}
              />
            </div>

            {bookingForm.allow_overbooking && (
              <div className="mt-4 ml-0 sm:ml-6">
                <FieldLabel htmlFor="cfg-max-overbook">Max Overbooking Per Slot</FieldLabel>
                <TextInput
                  id="cfg-max-overbook"
                  type="number"
                  min="1"
                  max="10"
                  value={bookingForm.max_overbooking_per_slot}
                  onChange={(e) => setBookingForm((prev) => ({ ...prev, max_overbooking_per_slot: e.target.value }))}
                  className="sm:w-32"
                />
              </div>
            )}
          </div>

          <div className="border-t border-gray-100 pt-5">
            <FieldLabel htmlFor="cfg-transfer">Transfer Number</FieldLabel>
            <div className="relative sm:w-72">
              <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <TextInput
                id="cfg-transfer"
                type="tel"
                value={bookingForm.transfer_number}
                onChange={(e) => setBookingForm((prev) => ({ ...prev, transfer_number: e.target.value }))}
                placeholder="(555) 123-4567"
                className="pl-10"
              />
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Phone number to transfer calls to when a human staff member is needed
            </p>
          </div>

          <div className="flex justify-end pt-2">
            <SaveButton saving={bookingSaving} onClick={saveBooking} label="Save Booking Settings" />
          </div>
        </div>
      </SectionCard>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3: Users
// ---------------------------------------------------------------------------

function UsersTab({ practices, setToast }) {
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState([])
  const [total, setTotal] = useState(0)

  // Filters
  const [filterPractice, setFilterPractice] = useState('')
  const [filterRole, setFilterRole] = useState('')

  // Add user modal
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm, setAddForm] = useState({
    email: '',
    password: '',
    first_name: '',
    last_name: '',
    role: 'secretary',
    practice_id: '',
  })
  const [adding, setAdding] = useState(false)

  // Inline editing
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [savingId, setSavingId] = useState(null)

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterPractice) params.practice_id = filterPractice
      if (filterRole) params.role = filterRole

      const res = await api.get('/admin/users', { params })
      const data = res.data
      setUsers(data.users || [])
      setTotal(data.total || 0)
    } catch (err) {
      if (err.response?.status !== 401) {
        setToast({
          type: 'error',
          message: err.response?.data?.detail || 'Failed to load users.',
        })
      }
    } finally {
      setLoading(false)
    }
  }, [filterPractice, filterRole, setToast])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  function resetAddForm() {
    setAddForm({
      email: '',
      password: '',
      first_name: '',
      last_name: '',
      role: 'secretary',
      practice_id: '',
    })
  }

  async function handleAddUser() {
    if (!addForm.email.trim()) {
      setToast({ type: 'error', message: 'Email is required.' })
      return
    }
    if (!addForm.password.trim()) {
      setToast({ type: 'error', message: 'Password is required.' })
      return
    }
    if (!addForm.first_name.trim()) {
      setToast({ type: 'error', message: 'First name is required.' })
      return
    }
    if (!addForm.last_name.trim()) {
      setToast({ type: 'error', message: 'Last name is required.' })
      return
    }

    setAdding(true)
    try {
      const body = {
        email: addForm.email.trim(),
        password: addForm.password,
        first_name: addForm.first_name.trim(),
        last_name: addForm.last_name.trim(),
        role: addForm.role,
      }
      if (addForm.practice_id) {
        body.practice_id = addForm.practice_id
      }

      await api.post('/admin/users', body)
      setToast({ type: 'success', message: 'User created successfully.' })
      setShowAddModal(false)
      resetAddForm()
      fetchUsers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to create user.',
      })
    } finally {
      setAdding(false)
    }
  }

  function startEdit(user) {
    setEditingId(user.id)
    setEditForm({
      email: user.email || '',
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      role: user.role || 'secretary',
      practice_id: user.practice_id || '',
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm({})
  }

  async function saveEdit(id) {
    if (!editForm.email.trim()) {
      setToast({ type: 'error', message: 'Email is required.' })
      return
    }
    setSavingId(id)
    try {
      const body = {
        email: editForm.email.trim(),
        first_name: editForm.first_name.trim() || undefined,
        last_name: editForm.last_name.trim() || undefined,
        role: editForm.role,
      }
      if (editForm.practice_id) {
        body.practice_id = editForm.practice_id
      }

      await api.put(`/admin/users/${id}`, body)
      setToast({ type: 'success', message: 'User updated successfully.' })
      setEditingId(null)
      fetchUsers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update user.',
      })
    } finally {
      setSavingId(null)
    }
  }

  async function toggleUserActive(user) {
    setSavingId(user.id)
    try {
      if (user.is_active) {
        // Deactivate
        await api.delete(`/admin/users/${user.id}`)
        setToast({ type: 'success', message: 'User deactivated successfully.' })
      } else {
        // Reactivate
        await api.put(`/admin/users/${user.id}`, { is_active: true })
        setToast({ type: 'success', message: 'User activated successfully.' })
      }
      fetchUsers()
    } catch (err) {
      setToast({
        type: 'error',
        message: err.response?.data?.detail || 'Failed to update user status.',
      })
    } finally {
      setSavingId(null)
    }
  }

  function getPracticeName(practiceId) {
    if (!practiceId) return '--'
    const p = practices.find((pr) => pr.id === practiceId)
    return p ? p.name : practiceId
  }

  const practiceOptions = practices.map((p) => ({
    value: p.id,
    label: p.name,
  }))

  return (
    <div className="space-y-4">
      {/* Filters and Add button */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="w-48">
            <SelectInput
              value={filterPractice}
              onChange={(e) => setFilterPractice(e.target.value)}
              options={practiceOptions}
              placeholder="All Practices"
            />
          </div>
          <div className="w-40">
            <SelectInput
              value={filterRole}
              onChange={(e) => setFilterRole(e.target.value)}
              options={USER_ROLES}
              placeholder="All Roles"
            />
          </div>
          <p className="text-sm text-gray-500">
            {total} user{total !== 1 ? 's' : ''} found
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
            'transition-colors shadow-sm'
          )}
        >
          <Plus className="w-4 h-4" />
          Add User
        </button>
      </div>

      {/* Users list */}
      {loading ? (
        <LoadingSpinner fullPage={false} message="Loading users..." size="md" />
      ) : users.length === 0 ? (
        <EmptyState
          icon={UsersIcon}
          title="No users found"
          description="No users match the current filters. Try adjusting the filters or create a new user."
          actionLabel="Add User"
          onAction={() => setShowAddModal(true)}
        />
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px]">
              <thead>
                <tr className="bg-gray-50/80">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    User
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Role
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Practice
                  </th>
                  <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Created
                  </th>
                  <th className="text-right text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {users.map((u) => {
                  const isEditing = editingId === u.id

                  if (isEditing) {
                    return (
                      <tr key={u.id} className="bg-primary-50/30">
                        <td colSpan={6} className="px-5 py-4">
                          <div className="space-y-4">
                            <p className="text-sm font-semibold text-gray-900">
                              Edit User
                            </p>
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                              <div>
                                <FieldLabel required>Email</FieldLabel>
                                <TextInput
                                  type="email"
                                  value={editForm.email}
                                  onChange={(e) => setEditForm((prev) => ({ ...prev, email: e.target.value }))}
                                  placeholder="user@example.com"
                                />
                              </div>
                              <div>
                                <FieldLabel>First Name</FieldLabel>
                                <TextInput
                                  value={editForm.first_name}
                                  onChange={(e) => setEditForm((prev) => ({ ...prev, first_name: e.target.value }))}
                                  placeholder="First name"
                                />
                              </div>
                              <div>
                                <FieldLabel>Last Name</FieldLabel>
                                <TextInput
                                  value={editForm.last_name}
                                  onChange={(e) => setEditForm((prev) => ({ ...prev, last_name: e.target.value }))}
                                  placeholder="Last name"
                                />
                              </div>
                              <div>
                                <FieldLabel>Role</FieldLabel>
                                <SelectInput
                                  value={editForm.role}
                                  onChange={(e) => setEditForm((prev) => ({ ...prev, role: e.target.value }))}
                                  options={USER_ROLES}
                                />
                              </div>
                              <div>
                                <FieldLabel>Practice</FieldLabel>
                                <SelectInput
                                  value={editForm.practice_id}
                                  onChange={(e) => setEditForm((prev) => ({ ...prev, practice_id: e.target.value }))}
                                  options={practiceOptions}
                                  placeholder="No practice"
                                />
                              </div>
                            </div>
                            <div className="flex items-center justify-end gap-2 pt-2">
                              <button
                                type="button"
                                onClick={cancelEdit}
                                className="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
                              >
                                Cancel
                              </button>
                              <button
                                type="button"
                                onClick={() => saveEdit(u.id)}
                                disabled={savingId === u.id}
                                className={clsx(
                                  'inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold text-white',
                                  'bg-primary-600 hover:bg-primary-700',
                                  'transition-colors',
                                  'disabled:opacity-60 disabled:cursor-not-allowed'
                                )}
                              >
                                {savingId === u.id ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <Check className="w-3.5 h-3.5" />
                                )}
                                Save
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )
                  }

                  return (
                    <tr key={u.id} className="hover:bg-gray-50/50 transition-colors">
                      {/* User */}
                      <td className="px-5 py-3.5">
                        <div>
                          <p className="text-sm font-medium text-gray-900">
                            {[u.first_name, u.last_name].filter(Boolean).join(' ') || '--'}
                          </p>
                          <p className="text-xs text-gray-500">{u.email}</p>
                        </div>
                      </td>

                      {/* Role */}
                      <td className="px-5 py-3.5">
                        <RoleBadge role={u.role} />
                      </td>

                      {/* Practice */}
                      <td className="px-5 py-3.5">
                        <span className="text-sm text-gray-600">
                          {getPracticeName(u.practice_id)}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="px-5 py-3.5 text-center">
                        <span
                          className={clsx(
                            'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold',
                            u.is_active
                              ? 'bg-green-50 text-green-700'
                              : 'bg-gray-100 text-gray-500'
                          )}
                        >
                          <span
                            className={clsx(
                              'w-1.5 h-1.5 rounded-full',
                              u.is_active ? 'bg-green-500' : 'bg-gray-400'
                            )}
                          />
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>

                      {/* Created */}
                      <td className="px-5 py-3.5">
                        <span className="text-sm text-gray-500">
                          {formatDate(u.created_at)}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-5 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleUserActive(u)}
                            disabled={savingId === u.id}
                            title={u.is_active ? 'Deactivate' : 'Activate'}
                            className={clsx(
                              'p-1.5 rounded-lg transition-colors',
                              u.is_active
                                ? 'text-green-600 hover:bg-green-50'
                                : 'text-gray-400 hover:bg-gray-100',
                              'disabled:opacity-50 disabled:cursor-not-allowed'
                            )}
                          >
                            {savingId === u.id ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : u.is_active ? (
                              <ToggleRight className="w-5 h-5" />
                            ) : (
                              <ToggleLeft className="w-5 h-5" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => startEdit(u)}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                            title="Edit"
                          >
                            <Edit3 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add User Modal */}
      <Modal
        open={showAddModal}
        onClose={() => { setShowAddModal(false); resetAddForm() }}
        title="Add New User"
        wide
      >
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <FieldLabel required>Email</FieldLabel>
              <TextInput
                type="email"
                value={addForm.email}
                onChange={(e) => setAddForm((prev) => ({ ...prev, email: e.target.value }))}
                placeholder="user@example.com"
              />
            </div>
            <div>
              <FieldLabel required>Password</FieldLabel>
              <MaskedInput
                value={addForm.password}
                onChange={(e) => setAddForm((prev) => ({ ...prev, password: e.target.value }))}
                placeholder="Minimum 8 characters"
              />
            </div>
            <div>
              <FieldLabel required>First Name</FieldLabel>
              <TextInput
                value={addForm.first_name}
                onChange={(e) => setAddForm((prev) => ({ ...prev, first_name: e.target.value }))}
                placeholder="First name"
              />
            </div>
            <div>
              <FieldLabel required>Last Name</FieldLabel>
              <TextInput
                value={addForm.last_name}
                onChange={(e) => setAddForm((prev) => ({ ...prev, last_name: e.target.value }))}
                placeholder="Last name"
              />
            </div>
            <div>
              <FieldLabel>Role</FieldLabel>
              <SelectInput
                value={addForm.role}
                onChange={(e) => setAddForm((prev) => ({ ...prev, role: e.target.value }))}
                options={USER_ROLES}
              />
            </div>
            <div>
              <FieldLabel>Practice</FieldLabel>
              <SelectInput
                value={addForm.practice_id}
                onChange={(e) => setAddForm((prev) => ({ ...prev, practice_id: e.target.value }))}
                options={practiceOptions}
                placeholder="No practice (for super admins)"
              />
              <p className="mt-1 text-xs text-gray-400">
                Super admins typically do not need a practice assignment
              </p>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={() => { setShowAddModal(false); resetAddForm() }}
              className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAddUser}
              disabled={adding}
              className={clsx(
                'inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold text-white',
                'bg-primary-600 hover:bg-primary-700',
                'transition-colors',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {adding ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4" />
                  Create User
                </>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Admin Component
// ---------------------------------------------------------------------------

export default function Admin() {
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState('practices')
  const [toast, setToast] = useState(null)

  // Practices data (shared between tabs)
  const [practices, setPractices] = useState([])
  const [practicesLoading, setPracticesLoading] = useState(true)
  const [selectedPractice, setSelectedPractice] = useState(null)

  const fetchPractices = useCallback(async () => {
    setPracticesLoading(true)
    try {
      const res = await api.get('/admin/practices', {
        params: { skip: 0, limit: 50 },
      })
      const data = res.data
      const list = data.practices || []
      setPractices(list)

      // If a practice was previously selected, update it with fresh data
      if (selectedPractice) {
        const updated = list.find((p) => p.id === selectedPractice.id)
        if (updated) {
          setSelectedPractice(updated)
        } else {
          setSelectedPractice(null)
        }
      }
    } catch (err) {
      if (err.response?.status !== 401) {
        setToast({
          type: 'error',
          message: err.response?.data?.detail || 'Failed to load practices.',
        })
      }
    } finally {
      setPracticesLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (user?.role === 'super_admin') {
      fetchPractices()
    }
  }, [user?.role, fetchPractices])

  // When selecting a practice, auto-switch to config tab if on config
  function handleSelectPractice(practice) {
    setSelectedPractice(practice)
    if (practice && activeTab !== 'practices') {
      // Stay on current tab
    }
  }

  // Access control
  if (!user || user.role !== 'super_admin') {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="w-16 h-16 rounded-2xl bg-red-100 flex items-center justify-center mb-5">
          <Shield className="w-8 h-8 text-red-500" />
        </div>
        <h2 className="text-xl font-semibold text-gray-900 mb-2">
          Access Denied
        </h2>
        <p className="text-sm text-gray-500 max-w-sm">
          This page is restricted to super administrators. Please contact your
          system administrator if you believe this is an error.
        </p>
        {user && (
          <div className="mt-4 bg-gray-50 rounded-lg p-4 text-sm">
            <div className="flex justify-between gap-8">
              <span className="text-gray-500">Your role</span>
              <span className="text-gray-900 font-medium capitalize">
                {user.role?.replace(/_/g, ' ') || 'Unknown'}
              </span>
            </div>
          </div>
        )}
      </div>
    )
  }

  function renderTab() {
    switch (activeTab) {
      case 'practices':
        return (
          <PracticesTab
            practices={practices}
            setPractices={setPractices}
            selectedPractice={selectedPractice}
            setSelectedPractice={handleSelectPractice}
            onRefresh={fetchPractices}
            loading={practicesLoading}
            setToast={setToast}
          />
        )
      case 'config':
        return (
          <PracticeConfigTab
            selectedPractice={selectedPractice}
            setToast={setToast}
          />
        )
      case 'users':
        return (
          <UsersTab
            practices={practices}
            setToast={setToast}
          />
        )
      default:
        return null
    }
  }

  return (
    <div className="space-y-6">
      {/* Toast notification */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Super Admin
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage all practices, configurations, and platform users
          </p>
        </div>
        <button
          onClick={fetchPractices}
          disabled={practicesLoading}
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
            className={clsx('w-4 h-4', practicesLoading && 'animate-spin')}
          />
          {practicesLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Tab navigation */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="border-b border-gray-200 overflow-x-auto">
          <nav className="flex min-w-max px-2" aria-label="Admin tabs">
            {ADMIN_TABS.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              const showPracticeBadge = tab.id === 'config' && selectedPractice

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
                  {showPracticeBadge && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary-100 text-primary-700 max-w-[120px] truncate">
                      {selectedPractice.name}
                    </span>
                  )}
                </button>
              )
            })}
          </nav>
        </div>
      </div>

      {/* Selected practice indicator (when not on config tab) */}
      {selectedPractice && activeTab !== 'config' && (
        <div className="flex items-center justify-between bg-primary-50 border border-primary-200 rounded-xl px-5 py-3">
          <div className="flex items-center gap-3">
            <Building2 className="w-5 h-5 text-primary-600 flex-shrink-0" />
            <p className="text-sm text-primary-900">
              <span className="font-medium">Selected practice:</span>{' '}
              {selectedPractice.name}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab('config')}
              className="text-xs font-semibold text-primary-700 hover:text-primary-800 hover:underline transition-colors"
            >
              View Config
            </button>
            <button
              type="button"
              onClick={() => setSelectedPractice(null)}
              className="p-1 rounded text-primary-400 hover:text-primary-600 transition-colors"
              title="Clear selection"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Active tab content */}
      {renderTab()}
    </div>
  )
}
