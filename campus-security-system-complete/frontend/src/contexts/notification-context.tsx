'use client'

/**
 * notification-context.tsx
 *
 * Connects to the backend SSE endpoint (/api/v1/notifications/stream) and
 * fans out push notifications to every component that calls useNotifications().
 *
 * Notification types handled:
 *   new_alert          → red/orange toast + browser notification
 *   alert_updated      → grey toast
 *   camera_added       → green toast
 *   camera_deleted     → yellow toast
 *   person_enrolled    → blue toast
 *   person_deleted     → yellow toast
 *   stream_started     → green toast
 *   stream_stopped     → grey toast
 *   connected          → silent (internal only)
 *
 * Usage:
 *   1. Wrap your app with <NotificationProvider> (inside AuthProvider so token is available).
 *   2. Call useNotifications() in any component.
 *   3. Call useNotificationToast() anywhere to imperatively push a toast.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { X, AlertTriangle, CheckCircle, Info } from 'lucide-react'
import { useAuth } from './auth-context'

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type NotificationEventType =
  | 'new_alert'
  | 'alert_updated'
  | 'camera_added'
  | 'camera_deleted'
  | 'person_enrolled'
  | 'person_deleted'
  | 'stream_started'
  | 'stream_stopped'
  | 'person_reidentified'
  | 'connected'

export interface NotificationEvent {
  event: NotificationEventType
  data: Record<string, any>
  ts: string
}

export type ToastVariant = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: string
  variant: ToastVariant
  title: string
  message?: string
  duration?: number   // ms, default 6000
  /** Internal: timestamp the toast was added */
  createdAt: number
}

interface NotificationContextValue {
  /** All SSE events received since mount (newest first, max 100) */
  events: NotificationEvent[]
  /** Whether the SSE connection is currently open */
  connected: boolean
  /** Number of events not yet marked as read */
  unreadCount: number
  /** Imperatively push a toast (e.g. for API action feedback) */
  addToast: (toast: Omit<Toast, 'id' | 'createdAt'>) => void
  /** Back-compat alias used by socket-context */
  addNotification: (toast: Omit<Toast, 'id' | 'createdAt'>) => void
  /** Dismiss a specific toast by id */
  dismissToast: (id: string) => void
  /** Clear all stored events */
  clearEvents: () => void
  /** Mark a single notification as read (by event data id or timestamp) */
  markAsRead: (id: string) => void
  /** Mark every notification as read */
  markAllAsRead: () => void
  /** Remove a notification from the event list */
  removeEvent: (id: string) => void
  /** Whether a notification has been marked as read */
  isRead: (id: string) => boolean
}

// ─────────────────────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────────────────────

const NotificationContext = createContext<NotificationContextValue>({
  events: [],
  connected: false,
  unreadCount: 0,
  addToast: () => {},
  addNotification: () => {},
  dismissToast: () => {},
  clearEvents: () => {},
  markAsRead: () => {},
  markAllAsRead: () => {},
  removeEvent: () => {},
  isRead: () => false,
})

// ─────────────────────────────────────────────────────────────────────────────
// Toast icon helpers
// ─────────────────────────────────────────────────────────────────────────────

function toastIcon(variant: ToastVariant) {
  const cls = 'h-5 w-5 shrink-0'
  switch (variant) {
    case 'error':   return <AlertTriangle className={`${cls} text-red-500`} />
    case 'warning': return <AlertTriangle className={`${cls} text-yellow-500`} />
    case 'success': return <CheckCircle   className={`${cls} text-green-500`} />
    default:        return <Info          className={`${cls} text-blue-500`} />
  }
}

function variantBg(variant: ToastVariant) {
  switch (variant) {
    case 'error':   return 'border-red-300    bg-red-50    dark:bg-red-950    dark:border-red-700'
    case 'warning': return 'border-yellow-300 bg-yellow-50 dark:bg-yellow-950 dark:border-yellow-700'
    case 'success': return 'border-green-300  bg-green-50  dark:bg-green-950  dark:border-green-700'
    default:        return 'border-blue-300   bg-blue-50   dark:bg-blue-950   dark:border-blue-700'
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Single Toast card
// ─────────────────────────────────────────────────────────────────────────────

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const [visible, setVisible] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    // Tiny delay so the enter animation fires
    const t = setTimeout(() => setVisible(true), 20)
    return () => clearTimeout(t)
  }, [])

  const dismiss = useCallback(() => {
    setLeaving(true)
    setTimeout(() => onDismiss(toast.id), 300)
  }, [onDismiss, toast.id])

  useEffect(() => {
    const duration = toast.duration ?? 6000
    const t = setTimeout(dismiss, duration)
    return () => clearTimeout(t)
  }, [dismiss, toast.duration])

  return (
    <div
      role="alert"
      aria-live="polite"
      className={[
        'flex items-start gap-3 w-80 rounded-xl border p-4 shadow-lg',
        'transition-all duration-300',
        variantBg(toast.variant),
        visible && !leaving
          ? 'opacity-100 translate-x-0'
          : 'opacity-0 translate-x-10',
      ].join(' ')}
    >
      {toastIcon(toast.variant)}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">
          {toast.title}
        </p>
        {toast.message && (
          <p className="text-xs text-gray-600 dark:text-gray-300 mt-0.5 line-clamp-2">
            {toast.message}
          </p>
        )}
      </div>
      <button
        onClick={dismiss}
        aria-label="Dismiss notification"
        className="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Toast container (fixed bottom-right)
// ─────────────────────────────────────────────────────────────────────────────

function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: string) => void
}) {
  if (toasts.length === 0) return null

  return (
    <div
      aria-label="Notifications"
      className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-3 pointer-events-none"
    >
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <ToastCard toast={t} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Map SSE event → toast config
// ─────────────────────────────────────────────────────────────────────────────

function eventToToast(event: NotificationEvent): Omit<Toast, 'id' | 'createdAt'> | null {
  const d = event.data

  switch (event.event) {
    case 'new_alert':
      return {
        variant: d.severity === 'critical' || d.severity === 'high' ? 'error' : 'warning',
        title: d.title || 'New Alert',
        message: [d.person_name && `👤 ${d.person_name}`, d.location && `📍 ${d.location}`]
          .filter(Boolean)
          .join('  ') || d.description,
        duration: d.severity === 'critical' ? 12000 : 8000,
      }

    case 'alert_updated':
      return {
        variant: 'info',
        title: `Alert ${d.new_status === 'resolved' ? 'Resolved' : 'Acknowledged'}`,
        message: `"${d.title}" → ${d.new_status} by ${d.updated_by}`,
        duration: 4000,
      }

    case 'camera_added':
      return {
        variant: 'success',
        title: '📷 Camera Added',
        message: `${d.name}${d.location ? ` at ${d.location}` : ''} — by ${d.added_by}`,
        duration: 5000,
      }

    case 'camera_deleted':
      return {
        variant: 'warning',
        title: '🗑️ Camera Removed',
        message: `${d.name}${d.location ? ` (${d.location})` : ''} — by ${d.deleted_by}`,
        duration: 5000,
      }

    case 'person_enrolled':
      return {
        variant: 'success',
        title: '👤 Person Enrolled',
        message: d.bulk
          ? `${d.person_name} enrolled by ${d.enrolled_by}`
          : `${d.person_name}${d.department ? ` · ${d.department}` : ''} — by ${d.enrolled_by}`,
        duration: 5000,
      }

    case 'person_deleted':
      return {
        variant: 'warning',
        title: '🗑️ Person Removed',
        message: `${d.person_name} removed by ${d.deleted_by}`,
        duration: 5000,
      }

    case 'stream_started':
      return {
        variant: 'success',
        title: '🎥 Stream Started',
        message: `${d.camera_name || d.stream_id}${d.location ? ` · ${d.location}` : ''}`,
        duration: 4000,
      }

    case 'stream_stopped':
      return {
        variant: 'info',
        title: '⏹ Stream Stopped',
        message: `${d.stream_id} — ${d.frames_read ?? 0} frames · ${d.detections_count ?? 0} detections`,
        duration: 4000,
      }

    case 'person_reidentified':
      return {
        variant: 'info',
        title: 'Person Re-identified',
        message: d.message || `${d.person_name || 'Person'} moved from ${d.source_camera_name} to ${d.camera_name}.`,
        duration: 9000,
      }

    case 'connected':
      // Silent — don't show a toast for internal connection acknowledgement
      return null

    default:
      return null
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────────────────────

const MAX_EVENTS  = 100
const MAX_TOASTS  = 6      // Never show more than 6 toasts at once

function eventId(event: NotificationEvent): string {
  return event.data?.id ?? event.ts
}

function buildNotificationStreamUrl(token: string): string {
  const apiUrl = (process.env.NEXT_PUBLIC_API_URL || '/api/v1').replace(/\/$/, '')

  if (apiUrl.startsWith('http')) {
    const base = apiUrl.replace(/\/api\/v1$/, '')
    return `${base}/api/v1/notifications/stream?token=${encodeURIComponent(token)}`
  }

  // Same-origin route handler proxies the backend SSE stream reliably
  return `/api/v1/notifications/stream?token=${encodeURIComponent(token)}`
}

function normalizeIncomingEvent(raw: Record<string, unknown>): NotificationEvent {
  if (raw.event && typeof raw.event === 'string') {
    const data =
      raw.data && typeof raw.data === 'object'
        ? (raw.data as Record<string, unknown>)
        : { ...raw, event: undefined, ts: undefined, data: undefined }

    return {
      event: raw.event as NotificationEventType,
      data: data as Record<string, any>,
      ts: typeof raw.ts === 'string' ? raw.ts : new Date().toISOString(),
    }
  }

  return {
    event: 'connected',
    data: raw as Record<string, any>,
    ts: new Date().toISOString(),
  }
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [events,    setEvents]    = useState<NotificationEvent[]>([])
  const [toasts,    setToasts]    = useState<Toast[]>([])
  const [connected, setConnected] = useState(false)
  const [readIds,   setReadIds]   = useState<Set<string>>(new Set())

  const esRef          = useRef<EventSource | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCount     = useRef(0)
  const MAX_RETRIES    = 10
  const unmounted      = useRef(false)

  // ── Toast helpers ──────────────────────────────────────────────────────────

  const addToast = useCallback((toast: Omit<Toast, 'id' | 'createdAt'>) => {
    const entry: Toast = {
      ...toast,
      id: crypto.randomUUID(),
      createdAt: Date.now(),
    }
    setToasts(prev => [entry, ...prev].slice(0, MAX_TOASTS))
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const clearEvents = useCallback(() => {
    setEvents([])
    setReadIds(new Set())
  }, [])

  const markAsRead = useCallback((id: string) => {
    setReadIds(prev => new Set([...prev, id]))
  }, [])

  const markAllAsRead = useCallback(() => {
    setReadIds(prev => {
      const next = new Set(prev)
      events.forEach(e => next.add(eventId(e)))
      return next
    })
  }, [events])

  const removeEvent = useCallback((id: string) => {
    setEvents(prev => prev.filter(e => eventId(e) !== id))
    setReadIds(prev => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }, [])

  const isRead = useCallback((id: string) => readIds.has(id), [readIds])

  const unreadCount = useMemo(
    () => events.filter(e => !readIds.has(eventId(e))).length,
    [events, readIds],
  )

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
    esRef.current?.close()
    esRef.current = null
    setConnected(false)
  }, [])

  // ── SSE connection ─────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (unmounted.current || !isAuthenticated) return

    disconnect()

    const token =
      typeof window !== 'undefined'
        ? localStorage.getItem('access_token') ?? sessionStorage.getItem('access_token')
        : null

    if (!token) return

    const es = new EventSource(buildNotificationStreamUrl(token))
    esRef.current = es

    es.onopen = () => {
      if (unmounted.current) return
      setConnected(true)
      retryCount.current = 0
    }

    es.onmessage = (e) => {
      if (unmounted.current) return
      try {
        const notification = normalizeIncomingEvent(JSON.parse(e.data))

        if (notification.event === 'connected') {
          setConnected(true)
          return
        }

        setEvents(prev => [notification, ...prev].slice(0, MAX_EVENTS))

        const toastConfig = eventToToast(notification)
        if (toastConfig) {
          addToast(toastConfig)

          if (
            notification.event === 'new_alert' &&
            (notification.data.severity === 'critical' || notification.data.severity === 'high') &&
            typeof Notification !== 'undefined' &&
            Notification.permission === 'granted'
          ) {
            new Notification(toastConfig.title, {
              body: toastConfig.message,
              icon: '/favicon.ico',
              tag: notification.data.id ?? 'alert',
            })
          }
        }
      } catch {
        // Malformed SSE payload — ignore
      }
    }

    es.onerror = () => {
      if (unmounted.current) return
      es.close()
      setConnected(false)
      esRef.current = null

      retryCount.current += 1
      if (retryCount.current > MAX_RETRIES) return

      const delay = Math.min(2 ** retryCount.current * 1000, 30_000)
      reconnectTimer.current = setTimeout(connect, delay)
    }
  }, [addToast, disconnect, isAuthenticated])

  useEffect(() => {
    unmounted.current = false

    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }

    if (isAuthenticated) {
      retryCount.current = 0
      connect()
    } else {
      disconnect()
    }

    return () => {
      unmounted.current = true
      disconnect()
    }
  }, [connect, disconnect, isAuthenticated])

  const contextValue: NotificationContextValue = {
    events,
    connected,
    unreadCount,
    addToast,
    addNotification: addToast,
    dismissToast,
    clearEvents,
    markAsRead,
    markAllAsRead,
    removeEvent,
    isRead,
  }

  return (
    <NotificationContext.Provider value={contextValue}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </NotificationContext.Provider>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Hooks
// ─────────────────────────────────────────────────────────────────────────────

/** Access the full notification context */
export function useNotifications() {
  return useContext(NotificationContext)
}

/**
 * Convenience hook — just returns addToast so you can push a toast from
 * any component without caring about the rest of the context.
 *
 *   const toast = useNotificationToast()
 *   toast({ variant: 'success', title: 'Saved!' })
 */
export function useNotificationToast() {
  return useContext(NotificationContext).addToast
}
