'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { AlertTriangle, Bell, CheckCircle, Clock, RefreshCw, Search, Radio } from 'lucide-react'

interface Alert {
  id: string
  type: string
  severity: string
  title: string
  message: string
  location: string
  camera_id: string | null
  camera_name: string | null
  person_id: string | null
  person_name: string | null
  status: string
  timestamp: string
  acknowledged_by: string | null
  resolved_at: string | null
}

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }

export default function AlertsPage() {
  const [alerts, setAlerts]             = useState<Alert[]>([])
  const [loading, setLoading]           = useState(true)
  const [error, setError]               = useState('')
  const [search, setSearch]             = useState('')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [statusFilter, setStatusFilter]     = useState('all')
  const [newAlertIds, setNewAlertIds]   = useState<Set<string>>(new Set())
  const [liveActive, setLiveActive]     = useState(false)

  // Tracks every alert id we have ever received so we can detect genuinely new ones
  const knownIdsRef      = useRef<Set<string>>(new Set())
  const pollIntervalRef  = useRef<ReturnType<typeof setInterval> | null>(null)
  // AbortController for the in-flight fetch — lets us cancel on unmount / rapid calls
  const abortCtrlRef     = useRef<AbortController | null>(null)

  // ── Fetch alerts ──────────────────────────────────────────────────────────

  const fetchAlerts = useCallback(async (silent = false) => {
    // Cancel any previous in-flight request
    if (abortCtrlRef.current) {
      abortCtrlRef.current.abort()
    }
    const ctrl = new AbortController()
    abortCtrlRef.current = ctrl

    try {
      if (!silent) setLoading(true)

      const res = await api.get('/alerts', {
        params: { size: 100 },
        // 10 s is plenty; stream-stop operations take < 5 s server-side
        timeout: 10_000,
        signal: ctrl.signal,
      })

      const incoming: Alert[] = res.data?.items ?? []

      // Detect brand-new alerts since the last fetch
      const freshIds = new Set<string>()
      incoming.forEach(a => {
        if (!knownIdsRef.current.has(a.id)) {
          freshIds.add(a.id)
        }
        knownIdsRef.current.add(a.id)
      })

      if (freshIds.size > 0) {
        setNewAlertIds(prev => new Set([...prev, ...freshIds]))
        setTimeout(() => {
          setNewAlertIds(prev => {
            const next = new Set(prev)
            freshIds.forEach(id => next.delete(id))
            return next
          })
        }, 8_000)
      }

      // Sort: active first → by severity → newest first
      incoming.sort((a, b) => {
        if (a.status === 'active' && b.status !== 'active') return -1
        if (b.status === 'active' && a.status !== 'active') return 1
        const sd = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
        if (sd !== 0) return sd
        return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      })

      setAlerts(incoming)
      setError('')
    } catch (err: any) {
      // AbortError = we intentionally cancelled the request (unmount / new call).
      // Never surface this as a user-visible error.
      if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return

      if (!silent) {
        setError(err?.response?.data?.detail || 'Failed to load alerts')
      }
      // In live/silent mode swallow the error — network blips shouldn't kill polling
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    fetchAlerts()
    // Cancel the in-flight request if the component unmounts
    return () => {
      abortCtrlRef.current?.abort()
    }
  }, [fetchAlerts])

  // ── Live polling toggle ───────────────────────────────────────────────────

  useEffect(() => {
    if (liveActive) {
      pollIntervalRef.current = setInterval(() => fetchAlerts(true), 5_000)
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
    // Clean up both the interval AND the in-flight request on unmount
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
    }
  }, [liveActive, fetchAlerts])

  // ── Acknowledge / Resolve ─────────────────────────────────────────────────

  const handleAcknowledge = async (alertId: string) => {
    try {
      await api.patch(`/alerts/${alertId}`, { status: 'acknowledged' })
      setAlerts(prev =>
        prev.map(a => a.id === alertId ? { ...a, status: 'acknowledged' } : a)
      )
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to acknowledge alert')
    }
  }

  const handleResolve = async (alertId: string) => {
    try {
      await api.patch(`/alerts/${alertId}`, { status: 'resolved' })
      setAlerts(prev =>
        prev.map(a => a.id === alertId ? { ...a, status: 'resolved' } : a)
      )
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to resolve alert')
    }
  }

  // ── Filters ───────────────────────────────────────────────────────────────

  const filtered = alerts.filter(a => {
    const q = search.toLowerCase()
    const matchSearch =
      (a.title       || '').toLowerCase().includes(q) ||
      (a.location    || '').toLowerCase().includes(q) ||
      (a.message     || '').toLowerCase().includes(q) ||
      (a.person_name || '').toLowerCase().includes(q) ||
      (a.camera_name || '').toLowerCase().includes(q)
    const matchSeverity = severityFilter === 'all' || a.severity === severityFilter
    const matchStatus   = statusFilter   === 'all' || a.status   === statusFilter
    return matchSearch && matchSeverity && matchStatus
  })

  const activeCount = alerts.filter(a => a.status === 'active').length

  // ── Helpers ───────────────────────────────────────────────────────────────

  const severityBadgeVariant = (severity: string) => {
    switch (severity) {
      case 'critical': case 'high': return 'destructive'
      case 'medium':               return 'warning'
      default:                     return 'success'
    }
  }

  const severityIcon = (severity: string) => {
    switch (severity) {
      case 'critical': case 'high':
        return <AlertTriangle className="h-5 w-5 text-red-500 shrink-0" />
      case 'medium':
        return <Bell className="h-5 w-5 text-yellow-500 shrink-0" />
      default:
        return <Bell className="h-5 w-5 text-blue-500 shrink-0" />
    }
  }

  const alertTypeLabel = (type: string) => {
    switch (type) {
      case 'unknown_person':       return '🔴 Unknown Person'
      case 'low_confidence_match': return '🟡 Low-Confidence Match'
      case 'face_recognized':      return '🟢 Person Identified'
      case 'unauthorized_access':  return '🔴 Unauthorized Access'
      case 'camera_offline':       return '⚫ Camera Offline'
      default:                     return type?.replace(/_/g, ' ') || 'Alert'
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
            Alerts
            {activeCount > 0 && (
              <Badge variant="destructive" className="text-sm px-2 py-0.5">
                {activeCount} active
              </Badge>
            )}
          </h1>
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            Real-time security alerts from RTSP streams and system events
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Live mode toggle */}
          <Button
            variant={liveActive ? 'default' : 'outline'}
            size="sm"
            onClick={() => setLiveActive(v => !v)}
            className={liveActive ? 'bg-green-600 hover:bg-green-700 text-white' : ''}
          >
            <Radio className={`h-4 w-4 mr-2 ${liveActive ? 'animate-pulse' : ''}`} />
            {liveActive ? 'Live' : 'Go Live'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => fetchAlerts()}>
            <RefreshCw className="h-4 w-4 mr-2" /> Refresh
          </Button>
        </div>
      </div>

      {/* ── Filters ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search by title, location, person, camera…"
            className="w-full pl-10 pr-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white text-sm"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="px-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white text-sm"
          value={severityFilter}
          onChange={e => setSeverityFilter(e.target.value)}
        >
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select
          className="px-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white text-sm"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="active">Active</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>
      </div>

      {/* ── Error banner ─────────────────────────────────────────────────── */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-4 text-red-500 hover:text-red-700 font-bold">✕</button>
        </div>
      )}

      {/* ── Alert list ───────────────────────────────────────────────────── */}
      <div className="space-y-3">
        {filtered.map(alert => (
          <Card
            key={alert.id}
            className={[
              'transition-all duration-300',
              alert.severity === 'critical' ? 'border-red-400 dark:border-red-700'    : '',
              alert.severity === 'high'     ? 'border-orange-300 dark:border-orange-800' : '',
              // Pulse ring for brand-new alerts arriving via live polling
              newAlertIds.has(alert.id)
                ? 'ring-2 ring-yellow-400 dark:ring-yellow-500 animate-pulse'
                : '',
            ].filter(Boolean).join(' ')}
          >
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                {/* Left: icon + text */}
                <div className="flex items-start gap-3 min-w-0">
                  {severityIcon(alert.severity)}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-medium text-gray-900 dark:text-white">{alert.title}</h3>
                      <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                        {alertTypeLabel(alert.type)}
                      </span>
                    </div>
                    {alert.message && (
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{alert.message}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 dark:text-gray-400 flex-wrap">
                      {alert.person_name && (
                        <span>👤 {alert.person_name}</span>
                      )}
                      {alert.location && (
                        <span>📍 {alert.location}</span>
                      )}
                      {alert.camera_name && (
                        <span>📷 {alert.camera_name}</span>
                      )}
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {alert.timestamp
                          ? new Date(alert.timestamp).toLocaleString()
                          : 'N/A'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Right: badges + action buttons */}
                <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
                  <Badge variant={severityBadgeVariant(alert.severity) as any}>
                    {alert.severity}
                  </Badge>
                  <Badge
                    variant={
                      alert.status === 'active'
                        ? 'destructive'
                        : alert.status === 'acknowledged'
                        ? 'warning'
                        : 'success'
                    }
                  >
                    {alert.status}
                  </Badge>
                  {alert.status === 'active' && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleAcknowledge(alert.id)}
                    >
                      <CheckCircle className="h-3 w-3 mr-1" /> Ack
                    </Button>
                  )}
                  {alert.status === 'acknowledged' && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleResolve(alert.id)}
                    >
                      <CheckCircle className="h-3 w-3 mr-1" /> Resolve
                    </Button>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Empty state ──────────────────────────────────────────────────── */}
      {filtered.length === 0 && !loading && (
        <div className="text-center py-12">
          <Bell className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">No alerts found</h3>
          <p className="text-gray-500 dark:text-gray-400">
            {search || severityFilter !== 'all' || statusFilter !== 'all'
              ? 'No alerts match your filters.'
              : liveActive
              ? 'Watching for new alerts…'
              : 'No alerts yet. Enable Live mode to watch in real time.'}
          </p>
        </div>
      )}
    </div>
  )
}
