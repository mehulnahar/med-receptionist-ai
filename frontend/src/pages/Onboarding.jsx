import { useState, useEffect, useCallback } from 'react'
import {
  Key,
  Bot,
  Phone,
  MessageSquare,
  Brain,
  Shield,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Eye,
  EyeOff,
  AlertCircle,
  ExternalLink,
  ChevronDown,
  Sparkles,
  AlertTriangle,
  Wand2,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = [
  { id: 1, label: 'Vapi API Key', icon: Key },
  { id: 2, label: 'Create AI Assistant', icon: Bot },
  { id: 3, label: 'Assign Phone Number', icon: Phone },
  { id: 4, label: 'Twilio SMS Setup', icon: MessageSquare },
  { id: 5, label: 'OpenAI API Key', icon: Brain },
  { id: 6, label: 'Claude AI Key', icon: Wand2 },
  { id: 7, label: 'Stedi Insurance Key', icon: Shield },
  { id: 8, label: 'Review & Activate', icon: CheckCircle },
]

const STATUS_KEYS = [
  'vapi_key',
  'vapi_assistant',
  'vapi_phone',
  'twilio_credentials',
  'twilio_phone',
  'openai_key',
  'anthropic_key',
  'stedi_key',
]

/** Map step number to the status key(s) that indicate completion. */
const STEP_STATUS_MAP = {
  1: ['vapi_key'],
  2: ['vapi_assistant'],
  3: ['vapi_phone'],
  4: ['twilio_credentials', 'twilio_phone'],
  5: ['openai_key'],
  6: ['anthropic_key'],
  7: ['stedi_key'],
}

/** Required steps (steps 6 and 7 are optional). */
const REQUIRED_STEPS = [1, 2, 3, 4, 5]

// ---------------------------------------------------------------------------
// Shared UI helpers
// ---------------------------------------------------------------------------

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
          'w-full px-3 py-2 pr-10 rounded-lg border text-sm bg-white',
          'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
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
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  )
}

function InlineMessage({ type, message }) {
  if (!message) return null
  const isError = type === 'error'
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded-lg px-4 py-3 text-sm mt-4',
        isError
          ? 'bg-red-50 border border-red-200 text-red-700'
          : 'bg-green-50 border border-green-200 text-green-700'
      )}
    >
      {isError ? (
        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
      ) : (
        <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
      )}
      <span>{message}</span>
    </div>
  )
}

function maskApiKey(key) {
  if (!key || key.length < 10) return key || '--'
  return `${key.slice(0, 4)}***...***${key.slice(-4)}`
}

// ---------------------------------------------------------------------------
// Step Components
// ---------------------------------------------------------------------------

function StepVapiKey({ stepStatus, setStepStatus, setStepDetail }) {
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const handleValidate = async () => {
    if (!apiKey.trim()) {
      setMessage('Please enter your Vapi API key.')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/validate-vapi', { api_key: apiKey.trim() })
      if (res.data.valid) {
        setMessage(`API key validated successfully. Account: ${res.data.account_name || 'Connected'}`)
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 1: true }))
        setStepDetail((prev) => ({ ...prev, 1: apiKey.trim() }))
      } else {
        setMessage(res.data.message || 'Invalid API key. Please check and try again.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to validate API key. Please try again.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">Vapi API Key</h2>
      <p className="text-sm text-gray-500 mt-1">
        Enter your Vapi API key to connect to the voice AI platform.
      </p>
      <a
        href="https://dashboard.vapi.ai"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700 mt-2"
      >
        Get your key from dashboard.vapi.ai
        <ExternalLink className="w-3.5 h-3.5" />
      </a>

      <div className="mt-5">
        <label htmlFor="vapi-api-key" className="block text-sm font-medium text-gray-700 mb-1.5">
          API Key
        </label>
        <MaskedInput
          id="vapi-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Enter your Vapi API key"
          disabled={loading}
        />
      </div>

      <div className="mt-4">
        <button
          type="button"
          onClick={handleValidate}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            'Validate & Save'
          )}
        </button>
      </div>

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepCreateAssistant({ stepStatus, setStepStatus, setStepDetail }) {
  const [showCustomize, setShowCustomize] = useState(false)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [firstMessage, setFirstMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')
  const [assistantInfo, setAssistantInfo] = useState(null)

  const handleCreate = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const body = {}
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim()
      if (firstMessage.trim()) body.first_message = firstMessage.trim()

      const res = await api.post('/practice/onboarding/create-assistant', body)
      if (res.data.success) {
        setAssistantInfo({
          id: res.data.assistant_id,
          name: res.data.assistant_name,
        })
        setMessage(res.data.message || 'Assistant created successfully.')
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 2: true }))
        setStepDetail((prev) => ({ ...prev, 2: res.data.assistant_id }))
      } else {
        setMessage(res.data.message || 'Failed to create assistant.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to create assistant. Please try again.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">Create AI Assistant</h2>
      <p className="text-sm text-gray-500 mt-1">
        Create your AI receptionist assistant on Vapi. Default settings work great for most practices.
      </p>

      <div className="mt-5">
        <button
          type="button"
          onClick={() => setShowCustomize(!showCustomize)}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-800 transition-colors"
        >
          <ChevronDown
            className={clsx(
              'w-4 h-4 transition-transform',
              showCustomize && 'rotate-180'
            )}
          />
          Customize (optional)
        </button>

        {showCustomize && (
          <div className="mt-4 space-y-4 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
            <div>
              <label htmlFor="assistant-system-prompt" className="block text-sm font-medium text-gray-700 mb-1.5">
                Custom System Prompt
              </label>
              <textarea
                id="assistant-system-prompt"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={6}
                placeholder="Leave blank to use the default system prompt..."
                className={clsx(
                  'w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'transition-colors resize-y font-mono'
                )}
              />
            </div>
            <div>
              <label htmlFor="assistant-first-message" className="block text-sm font-medium text-gray-700 mb-1.5">
                Custom First Message
              </label>
              <input
                id="assistant-first-message"
                type="text"
                value={firstMessage}
                onChange={(e) => setFirstMessage(e.target.value)}
                placeholder="e.g. Hello! Thank you for calling. How can I help you today?"
                className={clsx(
                  'w-full px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white',
                  'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                  'transition-colors'
                )}
              />
            </div>
          </div>
        )}
      </div>

      <div className="mt-5">
        <button
          type="button"
          onClick={handleCreate}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating Assistant...
            </>
          ) : (
            <>
              <Bot className="w-4 h-4" />
              Create Assistant
            </>
          )}
        </button>
      </div>

      {assistantInfo && (
        <div className="mt-4 bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle className="w-4 h-4 text-green-600" />
            <span className="text-sm font-semibold text-gray-900">Assistant Created</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-gray-500">Name: </span>
              <span className="font-medium text-gray-900">{assistantInfo.name}</span>
            </div>
            <div>
              <span className="text-gray-500">ID: </span>
              <span className="font-mono text-xs text-gray-900">{assistantInfo.id}</span>
            </div>
          </div>
        </div>
      )}

      <InlineMessage type={messageType} message={!assistantInfo ? message : null} />
    </div>
  )
}

function StepAssignPhone({ stepStatus, setStepStatus, setStepDetail }) {
  const [phones, setPhones] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedPhone, setSelectedPhone] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const fetchPhones = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/practice/onboarding/vapi-phones')
      setPhones(res.data.phone_numbers || [])
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to load phone numbers.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPhones()
  }, [fetchPhones])

  const handleAssign = async () => {
    if (!selectedPhone) {
      setMessage('Please select a phone number.')
      setMessageType('error')
      return
    }
    setAssigning(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/assign-phone', { phone_number_id: selectedPhone })
      if (res.data.success) {
        setMessage(res.data.message || `Phone number ${res.data.phone_number || ''} assigned successfully.`)
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 3: true }))
        setStepDetail((prev) => ({ ...prev, 3: res.data.phone_number || selectedPhone }))
      } else {
        setMessage(res.data.message || 'Failed to assign phone number.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to assign phone number. Please try again.')
      setMessageType('error')
    } finally {
      setAssigning(false)
    }
  }

  if (loading) {
    return (
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Assign Phone Number</h2>
        <p className="text-sm text-gray-500 mt-1">Loading available phone numbers...</p>
        <div className="mt-6">
          <LoadingSpinner fullPage={false} message="Fetching phone numbers..." size="sm" />
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">Assign Phone Number</h2>
      <p className="text-sm text-gray-500 mt-1">
        Select a phone number for your AI assistant to answer calls on.
      </p>

      {phones.length === 0 ? (
        <div className="mt-6 text-center py-8 bg-gray-50 rounded-lg border border-gray-200">
          <Phone className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-700">No phone numbers found</p>
          <p className="text-xs text-gray-500 mt-1">
            Import a phone number in your Vapi dashboard first, then return here.
          </p>
          <button
            type="button"
            onClick={fetchPhones}
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 bg-blue-50 rounded-lg transition-colors"
          >
            Refresh
          </button>
        </div>
      ) : (
        <>
          <div className="mt-5 border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wider w-10" />
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Number
                  </th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden sm:table-cell">
                    Provider
                  </th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wider hidden sm:table-cell">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {phones.map((phone) => (
                  <tr
                    key={phone.id}
                    onClick={() => setSelectedPhone(phone.id)}
                    className={clsx(
                      'cursor-pointer transition-colors',
                      selectedPhone === phone.id
                        ? 'bg-blue-50'
                        : 'hover:bg-gray-50'
                    )}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="radio"
                        name="vapi-phone"
                        value={phone.id}
                        checked={selectedPhone === phone.id}
                        onChange={() => setSelectedPhone(phone.id)}
                        className="h-4 w-4 text-blue-600 border-gray-300 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-medium text-gray-900">{phone.number || phone.name || phone.id}</span>
                      {phone.name && phone.number && (
                        <span className="block text-xs text-gray-500 sm:hidden">{phone.provider || '--'}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-600 hidden sm:table-cell">
                      {phone.provider || '--'}
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      {phone.assigned_assistant_id ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
                          Assigned
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700">
                          Available
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4">
            <button
              type="button"
              onClick={handleAssign}
              disabled={assigning || !selectedPhone}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
                'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
                'transition-colors shadow-sm',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {assigning ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Assigning...
                </>
              ) : (
                'Assign Number'
              )}
            </button>
          </div>
        </>
      )}

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepTwilioSetup({ stepStatus, setStepStatus, setStepDetail }) {
  const [accountSid, setAccountSid] = useState('')
  const [authToken, setAuthToken] = useState('')
  const [validating, setValidating] = useState(false)
  const [validated, setValidated] = useState(false)
  const [twilioPhones, setTwilioPhones] = useState([])
  const [selectedTwilioPhone, setSelectedTwilioPhone] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const handleValidate = async () => {
    if (!accountSid.trim() || !authToken.trim()) {
      setMessage('Please enter both Account SID and Auth Token.')
      setMessageType('error')
      return
    }
    setValidating(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/validate-twilio', {
        account_sid: accountSid.trim(),
        auth_token: authToken.trim(),
      })
      if (res.data.valid) {
        setMessage(`Twilio account validated. Account: ${res.data.account_name || 'Connected'}`)
        setMessageType('success')
        setValidated(true)
        // Fetch Twilio phone numbers
        try {
          const phonesRes = await api.get('/practice/onboarding/twilio-phones', {
            params: { account_sid: accountSid.trim(), auth_token: authToken.trim() },
          })
          setTwilioPhones(phonesRes.data.phone_numbers || [])
        } catch {
          // Non-blocking: user can still enter phone manually
        }
      } else {
        setMessage(res.data.message || 'Invalid Twilio credentials.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to validate Twilio credentials.')
      setMessageType('error')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!selectedTwilioPhone) {
      setMessage('Please select a phone number.')
      setMessageType('error')
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/save-twilio', {
        account_sid: accountSid.trim(),
        auth_token: authToken.trim(),
        phone_number: selectedTwilioPhone,
      })
      if (res.data.success) {
        setMessage(res.data.message || 'Twilio configuration saved successfully.')
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 4: true }))
        setStepDetail((prev) => ({ ...prev, 4: selectedTwilioPhone }))
      } else {
        setMessage(res.data.message || 'Failed to save Twilio configuration.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to save Twilio configuration.')
      setMessageType('error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">Twilio SMS Setup</h2>
      <p className="text-sm text-gray-500 mt-1">
        Configure Twilio for SMS appointment confirmations and reminders.
      </p>
      <a
        href="https://console.twilio.com"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700 mt-2"
      >
        Get credentials from console.twilio.com
        <ExternalLink className="w-3.5 h-3.5" />
      </a>

      <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="twilio-sid" className="block text-sm font-medium text-gray-700 mb-1.5">
            Account SID
          </label>
          <input
            id="twilio-sid"
            type="text"
            value={accountSid}
            onChange={(e) => { setAccountSid(e.target.value); setValidated(false) }}
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            disabled={validating}
            className={clsx(
              'w-full px-3 py-2 rounded-lg border text-sm bg-white',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
              'transition-colors',
              validating ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed' : 'border-gray-300'
            )}
          />
        </div>
        <div>
          <label htmlFor="twilio-token" className="block text-sm font-medium text-gray-700 mb-1.5">
            Auth Token
          </label>
          <MaskedInput
            id="twilio-token"
            value={authToken}
            onChange={(e) => { setAuthToken(e.target.value); setValidated(false) }}
            placeholder="Twilio Auth Token"
            disabled={validating}
          />
        </div>
      </div>

      <div className="mt-4">
        <button
          type="button"
          onClick={handleValidate}
          disabled={validating}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {validating ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            'Validate'
          )}
        </button>
      </div>

      {validated && (
        <div className="mt-5 pt-5 border-t border-gray-200">
          <label htmlFor="twilio-phone-select" className="block text-sm font-medium text-gray-700 mb-1.5">
            Select Phone Number
          </label>
          {twilioPhones.length > 0 ? (
            <select
              id="twilio-phone-select"
              value={selectedTwilioPhone}
              onChange={(e) => setSelectedTwilioPhone(e.target.value)}
              className={clsx(
                'w-full sm:w-72 px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'transition-colors'
              )}
            >
              <option value="">Select a phone number</option>
              {twilioPhones.map((p) => (
                <option key={p.sid || p.phone_number} value={p.phone_number}>
                  {p.friendly_name || p.phone_number}
                  {p.sms_enabled ? ' (SMS)' : ''}
                  {p.voice_enabled ? ' (Voice)' : ''}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="twilio-phone-select"
              type="tel"
              value={selectedTwilioPhone}
              onChange={(e) => setSelectedTwilioPhone(e.target.value)}
              placeholder="+15551234567"
              className={clsx(
                'w-full sm:w-72 px-3 py-2 rounded-lg border border-gray-300 text-sm bg-white',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'transition-colors'
              )}
            />
          )}

          <div className="mt-4">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
                'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
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
                'Save Configuration'
              )}
            </button>
          </div>
        </div>
      )}

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepOpenAIKey({ stepStatus, setStepStatus, setStepDetail }) {
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const handleValidate = async () => {
    if (!apiKey.trim()) {
      setMessage('Please enter your OpenAI API key.')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/validate-openai', { api_key: apiKey.trim() })
      if (res.data.valid) {
        setMessage('OpenAI API key validated successfully.')
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 5: true }))
        setStepDetail((prev) => ({ ...prev, 5: apiKey.trim() }))
      } else {
        setMessage(res.data.message || 'Invalid OpenAI API key.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to validate OpenAI API key.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">OpenAI API Key</h2>
      <p className="text-sm text-gray-500 mt-1">
        Enter your OpenAI API key for call recording analysis and AI-powered feedback.
      </p>
      <a
        href="https://platform.openai.com/api-keys"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700 mt-2"
      >
        Get your key from platform.openai.com/api-keys
        <ExternalLink className="w-3.5 h-3.5" />
      </a>

      <div className="mt-5">
        <label htmlFor="openai-api-key" className="block text-sm font-medium text-gray-700 mb-1.5">
          API Key
        </label>
        <MaskedInput
          id="openai-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-..."
          disabled={loading}
        />
        <p className="mt-1.5 text-xs text-gray-400">
          This key is used for call recording analysis and AI prompt optimization.
        </p>
      </div>

      <div className="mt-4">
        <button
          type="button"
          onClick={handleValidate}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            'Validate & Save'
          )}
        </button>
      </div>

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepAnthropicKey({ stepStatus, setStepStatus, setStepDetail, goNext }) {
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const handleValidate = async () => {
    if (!apiKey.trim()) {
      setMessage('Please enter your Anthropic API key.')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/validate-anthropic', { api_key: apiKey.trim() })
      if (res.data.valid) {
        setMessage('Anthropic API key validated successfully. Claude is ready for prompt generation.')
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 6: true }))
        setStepDetail((prev) => ({ ...prev, 6: apiKey.trim() }))
      } else {
        setMessage(res.data.message || 'Invalid Anthropic API key.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to validate Anthropic API key.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  const handleSkip = () => {
    setStepStatus((prev) => ({ ...prev, 6: 'skipped' }))
    goNext()
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Claude AI Key (Anthropic)</h2>
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">
          Optional
        </span>
      </div>
      <p className="text-sm text-gray-500 mt-1">
        Enter your Anthropic API key to use Claude for higher-quality prompt generation.
        If not configured, GPT-4o will be used instead.
      </p>
      <a
        href="https://console.anthropic.com/settings/keys"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700 mt-2"
      >
        Get your key from console.anthropic.com
        <ExternalLink className="w-3.5 h-3.5" />
      </a>

      <div className="mt-4 bg-purple-50 border border-purple-200 rounded-lg p-3">
        <div className="flex items-start gap-2">
          <Wand2 className="w-4 h-4 text-purple-600 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-purple-800">
            <span className="font-medium">Recommended model: claude-sonnet-4-20250514</span>
            <p className="text-purple-600 mt-0.5">
              Best balance of quality and speed for prompt generation. Will be used automatically when this key is configured.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-5">
        <label htmlFor="anthropic-api-key" className="block text-sm font-medium text-gray-700 mb-1.5">
          API Key
        </label>
        <MaskedInput
          id="anthropic-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="sk-ant-..."
          disabled={loading}
        />
        <p className="mt-1.5 text-xs text-gray-400">
          This key is used for AI-powered prompt generation in the Training pipeline.
        </p>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={handleValidate}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-purple-600 hover:bg-purple-700 active:bg-purple-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            'Validate & Save'
          )}
        </button>
        <button
          type="button"
          onClick={handleSkip}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
        >
          Skip
        </button>
      </div>

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepStediKey({ stepStatus, setStepStatus, setStepDetail, goNext }) {
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('success')

  const handleValidate = async () => {
    if (!apiKey.trim()) {
      setMessage('Please enter your Stedi API key.')
      setMessageType('error')
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const res = await api.post('/practice/onboarding/validate-stedi', { api_key: apiKey.trim() })
      if (res.data.valid) {
        setMessage('Stedi API key validated successfully.')
        setMessageType('success')
        setStepStatus((prev) => ({ ...prev, 7: true }))
        setStepDetail((prev) => ({ ...prev, 7: apiKey.trim() }))
      } else {
        setMessage(res.data.message || 'Invalid Stedi API key.')
        setMessageType('error')
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Failed to validate Stedi API key.')
      setMessageType('error')
    } finally {
      setLoading(false)
    }
  }

  const handleSkip = () => {
    setStepStatus((prev) => ({ ...prev, 7: 'skipped' }))
    goNext()
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-900">Stedi Insurance Key</h2>
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
          Optional
        </span>
      </div>
      <p className="text-sm text-gray-500 mt-1">
        Enter your Stedi API key for real-time insurance eligibility verification.
      </p>
      <a
        href="https://www.stedi.com"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700 mt-2"
      >
        Get your key from stedi.com
        <ExternalLink className="w-3.5 h-3.5" />
      </a>

      <div className="mt-5">
        <label htmlFor="stedi-api-key" className="block text-sm font-medium text-gray-700 mb-1.5">
          API Key
        </label>
        <MaskedInput
          id="stedi-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Enter your Stedi API key"
          disabled={loading}
        />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={handleValidate}
          disabled={loading}
          className={clsx(
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white',
            'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
            'transition-colors shadow-sm',
            'disabled:opacity-60 disabled:cursor-not-allowed'
          )}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            'Validate & Save'
          )}
        </button>
        <button
          type="button"
          onClick={handleSkip}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
        >
          Skip
        </button>
      </div>

      <InlineMessage type={messageType} message={message} />
    </div>
  )
}

function StepReview({ stepStatus, stepDetail, setCurrentStep }) {
  const allRequired = REQUIRED_STEPS.every((s) => stepStatus[s] === true)

  const reviewItems = [
    { step: 1, label: 'Vapi API Key', required: true },
    { step: 2, label: 'AI Assistant', required: true },
    { step: 3, label: 'Vapi Phone Number', required: true },
    { step: 4, label: 'Twilio SMS', required: true },
    { step: 5, label: 'OpenAI API Key', required: true },
    { step: 6, label: 'Claude AI (Anthropic)', required: false },
    { step: 7, label: 'Stedi Insurance', required: false },
  ]

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-900">Review & Activate</h2>
      <p className="text-sm text-gray-500 mt-1">
        Review your configuration below. All required steps must be completed before activation.
      </p>

      <div className="mt-6 space-y-3">
        {reviewItems.map((item) => {
          const status = stepStatus[item.step]
          const isCompleted = status === true
          const isSkipped = status === 'skipped'
          const detail = stepDetail[item.step]

          return (
            <div
              key={item.step}
              className={clsx(
                'flex items-center justify-between rounded-lg border px-4 py-3',
                isCompleted
                  ? 'border-green-200 bg-green-50/50'
                  : isSkipped
                    ? 'border-amber-200 bg-amber-50/50'
                    : 'border-gray-200 bg-white'
              )}
            >
              <div className="flex items-center gap-3 min-w-0">
                {isCompleted ? (
                  <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
                ) : isSkipped ? (
                  <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0" />
                ) : (
                  <div className="w-5 h-5 rounded-full border-2 border-gray-300 flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{item.label}</span>
                    {!item.required && (
                      <span className="text-xs text-gray-400">(Optional)</span>
                    )}
                  </div>
                  {isCompleted && detail && (
                    <p className="text-xs text-gray-500 mt-0.5 truncate font-mono">
                      {maskApiKey(detail)}
                    </p>
                  )}
                  {isSkipped && (
                    <p className="text-xs text-amber-600 mt-0.5">Skipped</p>
                  )}
                </div>
              </div>

              {!isCompleted && !isSkipped && (
                <button
                  type="button"
                  onClick={() => setCurrentStep(item.step)}
                  className="text-sm font-medium text-blue-600 hover:text-blue-700 whitespace-nowrap flex-shrink-0"
                >
                  Complete This Step
                </button>
              )}
            </div>
          )
        })}
      </div>

      {allRequired ? (
        <div className="mt-6 bg-green-50 border border-green-200 rounded-xl p-5 text-center">
          <Sparkles className="w-8 h-8 text-green-600 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-green-800">All Set!</h3>
          <p className="text-sm text-green-700 mt-1">
            Your AI receptionist is fully configured and ready to handle calls.
          </p>
        </div>
      ) : (
        <div className="mt-6 bg-amber-50 border border-amber-200 rounded-xl p-5 text-center">
          <AlertTriangle className="w-8 h-8 text-amber-500 mx-auto mb-2" />
          <h3 className="text-base font-semibold text-amber-800">Almost There</h3>
          <p className="text-sm text-amber-700 mt-1">
            Complete all required steps above to activate your AI receptionist.
          </p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar Stepper
// ---------------------------------------------------------------------------

function Stepper({ steps, currentStep, stepStatus, setCurrentStep, isMobile }) {
  if (isMobile) {
    return (
      <div className="flex items-center justify-between overflow-x-auto pb-2 gap-1">
        {steps.map((step) => {
          const Icon = step.icon
          const isActive = currentStep === step.id
          const isCompleted = stepStatus[step.id] === true
          const isSkipped = stepStatus[step.id] === 'skipped'

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => setCurrentStep(step.id)}
              className={clsx(
                'flex flex-col items-center gap-1 px-2 py-1.5 rounded-lg transition-colors min-w-0 flex-shrink-0',
                isActive && 'bg-blue-50'
              )}
              title={step.label}
            >
              <div
                className={clsx(
                  'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0',
                  isCompleted
                    ? 'bg-green-100'
                    : isActive
                      ? 'bg-blue-100'
                      : isSkipped
                        ? 'bg-amber-100'
                        : 'bg-gray-100'
                )}
              >
                {isCompleted ? (
                  <CheckCircle className="w-4 h-4 text-green-600" />
                ) : (
                  <Icon
                    className={clsx(
                      'w-4 h-4',
                      isActive ? 'text-blue-600' : isSkipped ? 'text-amber-500' : 'text-gray-400'
                    )}
                  />
                )}
              </div>
              <span
                className={clsx(
                  'text-[10px] font-medium truncate max-w-[60px]',
                  isActive ? 'text-blue-700' : isCompleted ? 'text-green-700' : 'text-gray-500'
                )}
              >
                {step.id}
              </span>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <nav className="space-y-1" aria-label="Onboarding steps">
      {steps.map((step) => {
        const Icon = step.icon
        const isActive = currentStep === step.id
        const isCompleted = stepStatus[step.id] === true
        const isSkipped = stepStatus[step.id] === 'skipped'

        return (
          <button
            key={step.id}
            type="button"
            onClick={() => setCurrentStep(step.id)}
            className={clsx(
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors',
              isActive
                ? 'bg-blue-50 border border-blue-200'
                : 'hover:bg-gray-50 border border-transparent'
            )}
          >
            <div
              className={clsx(
                'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0',
                isCompleted
                  ? 'bg-green-100'
                  : isActive
                    ? 'bg-blue-100'
                    : isSkipped
                      ? 'bg-amber-100'
                      : 'bg-gray-100'
              )}
            >
              {isCompleted ? (
                <CheckCircle className="w-4 h-4 text-green-600" />
              ) : (
                <Icon
                  className={clsx(
                    'w-4 h-4',
                    isActive ? 'text-blue-600' : isSkipped ? 'text-amber-500' : 'text-gray-400'
                  )}
                />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <span
                className={clsx(
                  'text-sm font-medium block truncate',
                  isActive
                    ? 'text-blue-700'
                    : isCompleted
                      ? 'text-green-700'
                      : 'text-gray-700'
                )}
              >
                {step.label}
              </span>
              {isCompleted && (
                <span className="text-xs text-green-600">Completed</span>
              )}
              {isSkipped && (
                <span className="text-xs text-amber-500">Skipped</span>
              )}
            </div>
          </button>
        )
      })}
    </nav>
  )
}

// ---------------------------------------------------------------------------
// Main Onboarding Component
// ---------------------------------------------------------------------------

export default function Onboarding() {
  const { user } = useAuth()
  const [currentStep, setCurrentStep] = useState(1)
  const [stepStatus, setStepStatus] = useState({})
  const [stepDetail, setStepDetail] = useState({})
  const [initialLoading, setInitialLoading] = useState(true)
  const [error, setError] = useState(null)

  // Fetch onboarding status on mount
  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get('/practice/onboarding/status')
      const data = res.data
      const newStatus = {}

      // Map API response to step completion status
      if (data.vapi_key?.completed) newStatus[1] = true
      if (data.vapi_assistant?.completed) newStatus[2] = true
      if (data.vapi_phone?.completed) newStatus[3] = true
      if (data.twilio_credentials?.completed && data.twilio_phone?.completed) newStatus[4] = true
      else if (data.twilio_credentials?.completed) newStatus[4] = false // partially done
      if (data.openai_key?.completed) newStatus[5] = true
      if (data.anthropic_key?.completed) newStatus[6] = true
      if (data.stedi_key?.completed) newStatus[7] = true

      setStepStatus(newStatus)

      // Populate details from API response
      const newDetail = {}
      if (data.vapi_key?.detail) newDetail[1] = data.vapi_key.detail
      if (data.vapi_assistant?.detail) newDetail[2] = data.vapi_assistant.detail
      if (data.vapi_phone?.detail) newDetail[3] = data.vapi_phone.detail
      if (data.twilio_phone?.detail) newDetail[4] = data.twilio_phone.detail
      if (data.openai_key?.detail) newDetail[5] = data.openai_key.detail
      if (data.anthropic_key?.detail) newDetail[6] = data.anthropic_key.detail
      if (data.stedi_key?.detail) newDetail[7] = data.stedi_key.detail
      setStepDetail(newDetail)

      // Set current step to the first incomplete required step
      const firstIncomplete = REQUIRED_STEPS.find((s) => !newStatus[s])
      if (firstIncomplete) {
        setCurrentStep(firstIncomplete)
      } else if (!newStatus[6]) {
        setCurrentStep(6) // Anthropic (optional)
      } else if (!newStatus[7]) {
        setCurrentStep(7) // Stedi (optional)
      } else {
        setCurrentStep(8) // Review
      }
    } catch (err) {
      if (err.response?.status !== 401) {
        setError(err.response?.data?.detail || 'Failed to load onboarding status.')
      }
    } finally {
      setInitialLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const goNext = () => {
    if (currentStep < 8) setCurrentStep(currentStep + 1)
  }

  const goPrev = () => {
    if (currentStep > 1) setCurrentStep(currentStep - 1)
  }

  // Render current step content
  const renderStep = () => {
    switch (currentStep) {
      case 1:
        return (
          <StepVapiKey
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
          />
        )
      case 2:
        return (
          <StepCreateAssistant
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
          />
        )
      case 3:
        return (
          <StepAssignPhone
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
          />
        )
      case 4:
        return (
          <StepTwilioSetup
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
          />
        )
      case 5:
        return (
          <StepOpenAIKey
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
          />
        )
      case 6:
        return (
          <StepAnthropicKey
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
            goNext={goNext}
          />
        )
      case 7:
        return (
          <StepStediKey
            stepStatus={stepStatus}
            setStepStatus={setStepStatus}
            setStepDetail={setStepDetail}
            goNext={goNext}
          />
        )
      case 8:
        return (
          <StepReview
            stepStatus={stepStatus}
            stepDetail={stepDetail}
            setCurrentStep={setCurrentStep}
          />
        )
      default:
        return null
    }
  }

  if (initialLoading) {
    return (
      <LoadingSpinner
        fullPage={false}
        message="Loading onboarding status..."
        size="lg"
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
          Setup Wizard
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure your AI receptionist step by step. Complete each section to get your practice up and running.
        </p>
      </div>

      {/* Error alert */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">Something went wrong</p>
            <p className="mt-0.5 text-red-600">{error}</p>
          </div>
          <button
            onClick={() => { setError(null); fetchStatus() }}
            className="text-red-700 hover:text-red-800 underline text-sm font-medium whitespace-nowrap"
          >
            Try again
          </button>
        </div>
      )}

      {/* Progress bar */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">
            Progress
          </span>
          <span className="text-sm text-gray-500">
            {Object.values(stepStatus).filter((v) => v === true).length} of {STEPS.length - 1} steps completed
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-500"
            style={{
              width: `${(Object.values(stepStatus).filter((v) => v === true).length / (STEPS.length - 1)) * 100}%`,
            }}
          />
        </div>
      </div>

      {/* Mobile stepper */}
      <div className="lg:hidden bg-white rounded-xl border border-gray-200 shadow-sm p-3">
        <Stepper
          steps={STEPS}
          currentStep={currentStep}
          stepStatus={stepStatus}
          setCurrentStep={setCurrentStep}
          isMobile
        />
      </div>

      {/* Main layout: sidebar + content */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Desktop sidebar */}
        <div className="hidden lg:block w-64 flex-shrink-0">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sticky top-6">
            <Stepper
              steps={STEPS}
              currentStep={currentStep}
              stepStatus={stepStatus}
              setCurrentStep={setCurrentStep}
              isMobile={false}
            />
          </div>
        </div>

        {/* Content area */}
        <div className="flex-1 min-w-0">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
            {/* Step indicator badge */}
            <div className="flex items-center gap-2 mb-5">
              <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                {currentStep}
              </span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Step {currentStep} of {STEPS.length}
              </span>
              {stepStatus[currentStep] === true && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700">
                  <CheckCircle className="w-3 h-3" />
                  Completed
                </span>
              )}
            </div>

            {/* Step content */}
            {renderStep()}

            {/* Navigation */}
            <div className="flex items-center justify-between mt-8 pt-5 border-t border-gray-200">
              <button
                type="button"
                onClick={goPrev}
                disabled={currentStep === 1}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium',
                  'bg-gray-100 text-gray-700 hover:bg-gray-200',
                  'transition-colors',
                  'disabled:opacity-40 disabled:cursor-not-allowed'
                )}
              >
                <ChevronLeft className="w-4 h-4" />
                Previous
              </button>
              <button
                type="button"
                onClick={goNext}
                disabled={currentStep === 8}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-white',
                  'bg-blue-600 hover:bg-blue-700 active:bg-blue-800',
                  'transition-colors shadow-sm',
                  'disabled:opacity-40 disabled:cursor-not-allowed'
                )}
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
