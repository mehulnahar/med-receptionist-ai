import { useState, useEffect, useCallback, useRef } from 'react'
import { format, parseISO } from 'date-fns'
import {
  Plus,
  ArrowLeft,
  Upload,
  CloudUpload,
  Play,
  Sparkles,
  Send,
  RefreshCw,
  AlertCircle,
  Check,
  X,
  FileAudio,
  Clock,
  Globe,
  BarChart3,
  MessageSquareText,
  Shield,
  Lightbulb,
  Loader2,
} from 'lucide-react'
import clsx from 'clsx'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACCEPTED_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.webm', '.flac']
const ACCEPTED_MIME = 'audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/ogg,audio/webm,audio/flac'

const SESSION_STATUS_CONFIG = {
  pending: {
    label: 'Pending',
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    ring: 'ring-gray-500/20',
    dot: 'bg-gray-400',
  },
  uploading: {
    label: 'Uploading',
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    ring: 'ring-blue-600/20',
    dot: 'bg-blue-500',
  },
  transcribing: {
    label: 'Transcribing',
    bg: 'bg-yellow-50',
    text: 'text-yellow-700',
    ring: 'ring-yellow-600/20',
    dot: 'bg-yellow-500',
  },
  analyzing: {
    label: 'Analyzing',
    bg: 'bg-purple-50',
    text: 'text-purple-700',
    ring: 'ring-purple-600/20',
    dot: 'bg-purple-500',
  },
  processing: {
    label: 'Processing',
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    ring: 'ring-blue-600/20',
    dot: 'bg-blue-500',
  },
  completed: {
    label: 'Completed',
    bg: 'bg-green-50',
    text: 'text-green-700',
    ring: 'ring-green-600/20',
    dot: 'bg-green-500',
  },
  failed: {
    label: 'Failed',
    bg: 'bg-red-50',
    text: 'text-red-700',
    ring: 'ring-red-600/20',
    dot: 'bg-red-500',
  },
}

const RECORDING_STATUS_CONFIG = {
  uploaded: {
    label: 'Uploaded',
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    ring: 'ring-gray-500/20',
    dot: 'bg-gray-400',
  },
  transcribing: {
    label: 'Transcribing',
    bg: 'bg-yellow-50',
    text: 'text-yellow-700',
    ring: 'ring-yellow-600/20',
    dot: 'bg-yellow-500',
  },
  transcribed: {
    label: 'Transcribed',
    bg: 'bg-blue-50',
    text: 'text-blue-700',
    ring: 'ring-blue-600/20',
    dot: 'bg-blue-500',
  },
  analyzing: {
    label: 'Analyzing',
    bg: 'bg-purple-50',
    text: 'text-purple-700',
    ring: 'ring-purple-600/20',
    dot: 'bg-purple-500',
  },
  completed: {
    label: 'Completed',
    bg: 'bg-green-50',
    text: 'text-green-700',
    ring: 'ring-green-600/20',
    dot: 'bg-green-500',
  },
  failed: {
    label: 'Failed',
    bg: 'bg-red-50',
    text: 'text-red-700',
    ring: 'ring-red-600/20',
    dot: 'bg-red-500',
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format bytes into human-readable file size. */
function formatFileSize(bytes) {
  if (bytes == null || bytes <= 0) return '--'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Format seconds into mm:ss. */
function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '--'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

/** Check if a file has an accepted audio extension. */
function isAcceptedFile(file) {
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  return ACCEPTED_EXTENSIONS.includes(ext)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status, configMap }) {
  const config = configMap[status] || configMap.pending || {
    label: status || 'Unknown',
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    ring: 'ring-gray-500/20',
    dot: 'bg-gray-400',
  }
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

function Toast({ toast, onDismiss }) {
  if (!toast) return null
  return (
    <div
      className={clsx(
        'flex items-center gap-2.5 rounded-xl px-5 py-3 text-sm font-medium shadow-sm border',
        toast.type === 'success'
          ? 'bg-green-50 border-green-200 text-green-700'
          : 'bg-red-50 border-red-200 text-red-700'
      )}
    >
      {toast.type === 'success' ? (
        <Check className="w-4 h-4 flex-shrink-0" />
      ) : (
        <AlertCircle className="w-4 h-4 flex-shrink-0" />
      )}
      {toast.message}
      <button
        onClick={onDismiss}
        className="ml-auto p-1 rounded hover:bg-black/5 transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

/** Simple horizontal bar for visualization. */
function HorizontalBar({ label, value, maxValue, color }) {
  const pct = maxValue > 0 ? Math.round((value / maxValue) * 100) : 0
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-700 font-medium truncate mr-2">{label}</span>
        <span className="text-gray-500 text-xs whitespace-nowrap">{value} ({pct}%)</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-2">
        <div
          className={clsx('h-2 rounded-full transition-all duration-500', color)}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session List View
// ---------------------------------------------------------------------------

function SessionListView({ sessions, loading, onSelect, onCreate, onRefresh, refreshing }) {
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  async function handleCreate() {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await onCreate(newName.trim())
      setNewName('')
      setShowCreateModal(false)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
            Call Training
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Upload call recordings to analyze patterns and improve the AI receptionist
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
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
            <RefreshCw className={clsx('w-4 h-4', refreshing && 'animate-spin')} />
            <span className="hidden sm:inline">{refreshing ? 'Refreshing...' : 'Refresh'}</span>
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className={clsx(
              'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
              'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
              'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
              'transition-colors shadow-sm hover:shadow-md'
            )}
          >
            <Plus className="w-4 h-4" />
            New Session
          </button>
        </div>
      </div>

      {/* Session cards */}
      {loading ? (
        <LoadingSpinner fullPage={false} message="Loading sessions..." size="md" />
      ) : sessions.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
          <EmptyState
            icon={FileAudio}
            title="No training sessions"
            description="Create your first training session to start analyzing call recordings and improving the AI receptionist."
            actionLabel="Create Session"
            onAction={() => setShowCreateModal(true)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sessions.map((session) => {
            const recordingCount = session.total_recordings || session.recording_count || session.recordings?.length || 0
            const processedCount = session.processed_count || 0
            const progressPct = recordingCount > 0
              ? Math.round((processedCount / recordingCount) * 100)
              : 0

            return (
              <button
                key={session.id}
                onClick={() => onSelect(session.id)}
                className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 text-left hover:border-primary-300 hover:shadow-md transition-all duration-200 group"
              >
                <div className="flex items-start justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-900 group-hover:text-primary-700 transition-colors truncate mr-2">
                    {session.name}
                  </h3>
                  <StatusBadge status={session.status} configMap={SESSION_STATUS_CONFIG} />
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <FileAudio className="w-3.5 h-3.5" />
                      {recordingCount} recording{recordingCount !== 1 ? 's' : ''}
                    </span>
                    {session.created_at && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        {format(parseISO(session.created_at), 'MMM d, yyyy')}
                      </span>
                    )}
                  </div>

                  {recordingCount > 0 && (
                    <div>
                      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                        <span>Progress</span>
                        <span>{processedCount}/{recordingCount}</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-1.5">
                        <div
                          className="h-1.5 rounded-full bg-primary-500 transition-all duration-500"
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* Create session modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setShowCreateModal(false)}
            aria-hidden="true"
          />
          <div className="relative bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-lg font-semibold text-gray-900">New Training Session</h2>
              <button
                onClick={() => setShowCreateModal(false)}
                className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Session Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  placeholder="e.g., January 2026 Call Review"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors"
                  autoFocus
                />
              </div>
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2.5 rounded-lg text-sm font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 active:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={creating || !newName.trim()}
                  className={clsx(
                    'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white',
                    'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                    'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                    'transition-colors shadow-sm',
                    'disabled:opacity-60 disabled:cursor-not-allowed'
                  )}
                >
                  {creating ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      Create Session
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session Detail View
// ---------------------------------------------------------------------------

function SessionDetailView({ sessionId, onBack, showToast }) {
  const [session, setSession] = useState(null)
  const [recordings, setRecordings] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Upload state
  const [stagedFiles, setStagedFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  // Action state
  const [processing, setProcessing] = useState(false)
  const [generatingPrompt, setGeneratingPrompt] = useState(false)
  const [applyingPrompt, setApplyingPrompt] = useState(false)
  const [editedPrompt, setEditedPrompt] = useState('')

  // Auto-refresh ref
  const pollRef = useRef(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  // ---- Fetch session detail ----
  const fetchSession = useCallback(async () => {
    try {
      const res = await api.get(`/training/sessions/${sessionId}`)
      if (!mountedRef.current) return
      setSession(res.data)
      if (res.data.generated_prompt && !editedPrompt) {
        setEditedPrompt(res.data.generated_prompt)
      }
    } catch (err) {
      if (!mountedRef.current) return
      if (err.response?.status !== 401) {
        setError(err.response?.data?.detail || 'Failed to load session details.')
      }
    }
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Fetch recordings ----
  const fetchRecordings = useCallback(async () => {
    try {
      const res = await api.get(`/training/sessions/${sessionId}/recordings`)
      if (!mountedRef.current) return
      setRecordings(res.data.recordings || [])
    } catch (err) {
      if (!mountedRef.current) return
      if (err.response?.status !== 401) {
        console.error('Failed to load recordings:', err)
      }
    }
  }, [sessionId])

  // Initial load
  useEffect(() => {
    async function load() {
      setLoading(true)
      await Promise.all([fetchSession(), fetchRecordings()])
      if (mountedRef.current) setLoading(false)
    }
    load()
  }, [fetchSession, fetchRecordings])

  // Auto-refresh every 5s when any recording is in a processing state
  useEffect(() => {
    const hasProcessing = recordings.some(
      (r) => r.status === 'transcribing' || r.status === 'analyzing' || r.status === 'uploaded'
    )
    const sessionProcessing = session?.status === 'processing' || session?.status === 'transcribing' || session?.status === 'analyzing'

    if (hasProcessing || sessionProcessing) {
      pollRef.current = setInterval(() => {
        fetchSession()
        fetchRecordings()
      }, 5000)
    } else if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [recordings, session?.status, fetchSession, fetchRecordings])

  // ---- Drag and Drop handlers ----
  function handleDragOver(e) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }

  function handleDragLeave(e) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }

  function handleDrop(e) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files).filter(isAcceptedFile)
    if (files.length > 0) {
      setStagedFiles((prev) => [...prev, ...files])
    }
  }

  function handleFileSelect(e) {
    const files = Array.from(e.target.files).filter(isAcceptedFile)
    if (files.length > 0) {
      setStagedFiles((prev) => [...prev, ...files])
    }
    // Reset so the same file can be re-selected
    e.target.value = ''
  }

  function removeStagedFile(index) {
    setStagedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  // ---- Upload files ----
  async function handleUpload() {
    if (stagedFiles.length === 0) return
    setUploading(true)
    setUploadProgress(0)

    try {
      const formData = new FormData()
      stagedFiles.forEach((f) => formData.append('files', f))

      await api.post(`/training/sessions/${sessionId}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (e.total) {
            setUploadProgress(Math.round((e.loaded / e.total) * 100))
          }
        },
      })

      setStagedFiles([])
      showToast('success', 'Files uploaded successfully.')
      await Promise.all([fetchSession(), fetchRecordings()])
    } catch (err) {
      showToast('error', err.response?.data?.detail || 'Upload failed. Please try again.')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  // ---- Start processing ----
  async function handleStartAnalysis() {
    setProcessing(true)
    try {
      await api.post(`/training/sessions/${sessionId}/process`)
      showToast('success', 'Analysis started. Recordings are being processed.')
      await Promise.all([fetchSession(), fetchRecordings()])
    } catch (err) {
      showToast('error', err.response?.data?.detail || 'Failed to start analysis.')
    } finally {
      setProcessing(false)
    }
  }

  // ---- Generate prompt ----
  async function handleGeneratePrompt() {
    setGeneratingPrompt(true)
    try {
      const res = await api.post(`/training/sessions/${sessionId}/generate-prompt`)
      showToast('success', 'Prompt generated successfully.')
      setEditedPrompt(res.data.generated_prompt || '')
      await fetchSession()
    } catch (err) {
      showToast('error', err.response?.data?.detail || 'Failed to generate prompt.')
    } finally {
      setGeneratingPrompt(false)
    }
  }

  // ---- Apply prompt ----
  async function handleApplyPrompt() {
    setApplyingPrompt(true)
    try {
      await api.post(`/training/sessions/${sessionId}/apply-prompt`, {
        push_to_vapi: true,
        prompt_override: editedPrompt,
      })
      showToast('success', 'Prompt applied and pushed to Vapi.')
      await fetchSession()
    } catch (err) {
      showToast('error', err.response?.data?.detail || 'Failed to apply prompt.')
    } finally {
      setApplyingPrompt(false)
    }
  }

  // ---- Derived state ----
  const completedRecordings = recordings.filter((r) => r.status === 'completed')
  const transcribedRecordings = recordings.filter(
    (r) => r.status === 'transcribed' || r.status === 'completed'
  )
  const canStartAnalysis = transcribedRecordings.length > 0 &&
    session?.status !== 'processing' &&
    session?.status !== 'analyzing' &&
    session?.status !== 'completed'
  const canGeneratePrompt = session?.status === 'completed' || completedRecordings.length > 0
  const insights = session?.aggregated_insights

  if (loading) {
    return <LoadingSpinner fullPage={false} message="Loading session..." size="md" />
  }

  if (error) {
    return (
      <div className="space-y-6">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to sessions
        </button>
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-4 text-sm shadow-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-medium">Failed to load session</p>
            <p className="mt-0.5 text-red-600">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to sessions
      </button>

      {/* Session header */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold text-gray-900 tracking-tight">
                {session?.name || 'Training Session'}
              </h1>
              <StatusBadge status={session?.status} configMap={SESSION_STATUS_CONFIG} />
            </div>
            <p className="text-sm text-gray-500">
              {recordings.length} recording{recordings.length !== 1 ? 's' : ''}
              {completedRecordings.length > 0 && (
                <span> &middot; {completedRecordings.length} processed</span>
              )}
              {session?.created_at && (
                <span> &middot; Created {format(parseISO(session.created_at), 'MMM d, yyyy')}</span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {canStartAnalysis && (
              <button
                onClick={handleStartAnalysis}
                disabled={processing}
                className={clsx(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
                  'text-white bg-purple-600 hover:bg-purple-700 active:bg-purple-800',
                  'focus:outline-none focus:ring-2 focus:ring-purple-500/40 focus:ring-offset-2',
                  'transition-colors shadow-sm',
                  'disabled:opacity-60 disabled:cursor-not-allowed'
                )}
              >
                {processing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Starting...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Start Analysis
                  </>
                )}
              </button>
            )}
            {canGeneratePrompt && (
              <button
                onClick={handleGeneratePrompt}
                disabled={generatingPrompt}
                className={clsx(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
                  'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                  'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                  'transition-colors shadow-sm',
                  'disabled:opacity-60 disabled:cursor-not-allowed'
                )}
              >
                {generatingPrompt ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Generate Prompt
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Upload section */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Upload Recordings</h2>

        {/* Drop zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            'relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200',
            dragOver
              ? 'border-primary-400 bg-primary-50/50'
              : 'border-gray-300 bg-gray-50/50 hover:border-primary-300 hover:bg-primary-50/30'
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_MIME}
            onChange={handleFileSelect}
            className="hidden"
          />
          <CloudUpload className={clsx(
            'w-10 h-10 mx-auto mb-3',
            dragOver ? 'text-primary-500' : 'text-gray-400'
          )} />
          <p className="text-sm font-medium text-gray-700">
            Drag and drop audio files here, or click to browse
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Supports MP3, WAV, M4A, OGG, WebM, FLAC
          </p>
        </div>

        {/* Staged files list */}
        {stagedFiles.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-sm font-medium text-gray-700">
              {stagedFiles.length} file{stagedFiles.length !== 1 ? 's' : ''} selected
            </p>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {stagedFiles.map((file, idx) => (
                <div
                  key={`${file.name}-${idx}`}
                  className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileAudio className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span className="text-sm text-gray-700 truncate">{file.name}</span>
                    <span className="text-xs text-gray-400 flex-shrink-0">
                      {formatFileSize(file.size)}
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      removeStagedFile(idx)
                    }}
                    className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors flex-shrink-0"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>

            {/* Upload progress */}
            {uploading && (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>Uploading...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className="h-2 rounded-full bg-primary-500 transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}

            <button
              onClick={handleUpload}
              disabled={uploading}
              className={clsx(
                'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold',
                'text-white bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                'transition-colors shadow-sm',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {uploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  Upload Files
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* Recordings table */}
      {recordings.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Recordings</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {recordings.length} recording{recordings.length !== 1 ? 's' : ''}
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead>
                <tr className="bg-gray-50/80">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Filename
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Language
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Duration
                  </th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3">
                    Analysis
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {recordings.map((rec) => (
                  <tr key={rec.id} className="hover:bg-gray-50/80 transition-colors">
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <FileAudio className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <span className="text-sm font-medium text-gray-900 truncate max-w-[200px]">
                          {rec.filename || rec.original_filename || 'Unknown'}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <StatusBadge status={rec.status} configMap={RECORDING_STATUS_CONFIG} />
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {rec.language || rec.detected_language || '--'}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {formatDuration(rec.duration_seconds || rec.duration)}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-sm text-gray-600 line-clamp-1 max-w-[300px]">
                        {rec.analysis_summary || rec.summary || '--'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Insights panel */}
      {insights && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-5">Aggregated Insights</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">

            {/* Intent Distribution */}
            {insights.intent_distribution && Object.keys(insights.intent_distribution).length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-primary-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Intent Distribution</h3>
                </div>
                <div className="space-y-2">
                  {(() => {
                    const entries = Object.entries(insights.intent_distribution)
                    const maxVal = Math.max(...entries.map(([, v]) => v))
                    const colors = [
                      'bg-primary-500', 'bg-purple-500', 'bg-green-500',
                      'bg-amber-500', 'bg-red-500', 'bg-teal-500',
                    ]
                    return entries.map(([label, value], i) => (
                      <HorizontalBar
                        key={label}
                        label={label}
                        value={value}
                        maxValue={entries.reduce((s, [, v]) => s + v, 0)}
                        color={colors[i % colors.length]}
                      />
                    ))
                  })()}
                </div>
              </div>
            )}

            {/* Language Distribution */}
            {insights.language_distribution && Object.keys(insights.language_distribution).length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Globe className="w-4 h-4 text-blue-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Language Distribution</h3>
                </div>
                <div className="space-y-2">
                  {(() => {
                    const entries = Object.entries(insights.language_distribution)
                    const colors = ['bg-blue-500', 'bg-green-500', 'bg-amber-500', 'bg-red-500']
                    return entries.map(([label, value], i) => (
                      <HorizontalBar
                        key={label}
                        label={label}
                        value={value}
                        maxValue={entries.reduce((s, [, v]) => s + v, 0)}
                        color={colors[i % colors.length]}
                      />
                    ))
                  })()}
                </div>
              </div>
            )}

            {/* Common Phrases */}
            {insights.common_phrases && insights.common_phrases.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <MessageSquareText className="w-4 h-4 text-green-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Common Phrases</h3>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {insights.common_phrases.slice(0, 15).map((phrase, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 ring-1 ring-inset ring-gray-300"
                    >
                      {typeof phrase === 'string' ? phrase : phrase.phrase || phrase.text}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Insurance Carriers */}
            {insights.insurance_carriers && insights.insurance_carriers.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-amber-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Insurance Carriers</h3>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {insights.insurance_carriers.map((carrier, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/20"
                    >
                      {typeof carrier === 'string' ? carrier : carrier.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Recommendations */}
            {insights.recommendations && insights.recommendations.length > 0 && (
              <div className="space-y-3 md:col-span-2 lg:col-span-2">
                <div className="flex items-center gap-2">
                  <Lightbulb className="w-4 h-4 text-purple-500" />
                  <h3 className="text-sm font-semibold text-gray-900">Recommendations</h3>
                </div>
                <ul className="space-y-2">
                  {insights.recommendations.map((rec, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-sm text-gray-700"
                    >
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-xs font-semibold mt-0.5">
                        {i + 1}
                      </span>
                      <span>{typeof rec === 'string' ? rec : rec.text || rec.description}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Generated Prompt panel */}
      {(session?.generated_prompt || editedPrompt) && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-5">Generated Prompt</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Current prompt */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">
                Current Prompt
              </label>
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 max-h-80 overflow-y-auto">
                <pre className="text-sm text-gray-700 whitespace-pre-wrap font-sans leading-relaxed">
                  {session?.current_prompt || 'No current prompt configured.'}
                </pre>
              </div>
            </div>

            {/* Editable generated prompt */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">
                Generated Prompt (editable)
              </label>
              <textarea
                value={editedPrompt}
                onChange={(e) => setEditedPrompt(e.target.value)}
                rows={12}
                className="w-full px-4 py-3 rounded-lg border border-gray-300 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500 transition-colors resize-y font-sans leading-relaxed"
              />
            </div>
          </div>

          {/* Apply button */}
          <div className="mt-5 flex items-center justify-end">
            <button
              onClick={handleApplyPrompt}
              disabled={applyingPrompt || !editedPrompt.trim()}
              className={clsx(
                'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold text-white',
                'bg-primary-600 hover:bg-primary-700 active:bg-primary-800',
                'focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:ring-offset-2',
                'transition-colors shadow-sm',
                'disabled:opacity-60 disabled:cursor-not-allowed'
              )}
            >
              {applyingPrompt ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Applying...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  Apply &amp; Push to Vapi
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Training Component
// ---------------------------------------------------------------------------

export default function Training() {
  useAuth() // ensure user is authenticated
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => { mountedRef.current = false }
  }, [])

  // ---- View state ----
  const [view, setView] = useState('list')
  const [selectedSession, setSelectedSession] = useState(null)

  // ---- Data state ----
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // ---- Toast state ----
  const [toast, setToast] = useState(null)

  function showToast(type, message) {
    setToast({ type, message })
  }

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 5000)
      return () => clearTimeout(timer)
    }
  }, [toast])

  // ---- Fetch sessions ----
  const fetchSessions = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const res = await api.get('/training/sessions')
      if (!mountedRef.current) return
      setSessions(res.data.sessions || [])
    } catch (err) {
      if (!mountedRef.current) return
      if (err.response?.status !== 401) {
        showToast('error', err.response?.data?.detail || 'Failed to load training sessions.')
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // ---- Create session ----
  async function handleCreate(name) {
    try {
      const res = await api.post('/training/sessions', { name })
      showToast('success', 'Training session created.')
      await fetchSessions(true)
      // Auto-navigate to new session
      if (res.data?.id) {
        setSelectedSession(res.data.id)
        setView('detail')
      }
    } catch (err) {
      showToast('error', err.response?.data?.detail || 'Failed to create session.')
      throw err
    }
  }

  // ---- Select session ----
  function handleSelectSession(id) {
    setSelectedSession(id)
    setView('detail')
  }

  // ---- Back to list ----
  function handleBack() {
    setView('list')
    setSelectedSession(null)
    fetchSessions(true)
  }

  return (
    <div className="space-y-6">
      {/* Toast */}
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      {/* View router */}
      {view === 'list' ? (
        <SessionListView
          sessions={sessions}
          loading={loading}
          onSelect={handleSelectSession}
          onCreate={handleCreate}
          onRefresh={() => fetchSessions(true)}
          refreshing={refreshing}
        />
      ) : (
        <SessionDetailView
          sessionId={selectedSession}
          onBack={handleBack}
          showToast={showToast}
        />
      )}
    </div>
  )
}
