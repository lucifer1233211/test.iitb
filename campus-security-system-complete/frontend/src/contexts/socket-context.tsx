'use client'

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { io, Socket } from 'socket.io-client'
import { useAuth } from './auth-context'
import { useNotifications, type ToastVariant } from './notification-context'

interface SocketContextType {
  socket: Socket | null
  /** Live connection: Socket.IO when configured, otherwise SSE notification stream */
  isConnected: boolean
  connectionError: string | null
}

const SocketContext = createContext<SocketContextType | undefined>(undefined)

export function useSocket() {
  const context = useContext(SocketContext)
  if (context === undefined) {
    throw new Error('useSocket must be used within a SocketProvider')
  }
  return context
}

interface SocketProviderProps {
  children: React.ReactNode
}

function pushToast(
  addNotification: (toast: {
    variant: ToastVariant
    title: string
    message?: string
    duration?: number
  }) => void,
  variant: ToastVariant,
  title: string,
  message?: string,
  duration?: number,
) {
  addNotification({ variant, title, message, duration })
}

export function SocketProvider({ children }: SocketProviderProps) {
  const [socket, setSocket] = useState<Socket | null>(null)
  const [socketConnected, setSocketConnected] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const { isAuthenticated, user } = useAuth()
  const { addNotification, connected: sseConnected } = useNotifications()

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL
  const useSocketIo = Boolean(wsUrl)

  useEffect(() => {
    if (!isAuthenticated || !user || !useSocketIo) {
      setSocket(null)
      setSocketConnected(false)
      if (!useSocketIo) {
        setConnectionError(null)
      }
      return
    }

    const newSocket = io(wsUrl, {
      auth: {
        token: localStorage.getItem('access_token'),
        userId: user.id,
      },
      transports: ['websocket', 'polling'],
      timeout: 20000,
      reconnection: true,
      reconnectionAttempts: 3,
      reconnectionDelay: 2000,
    })

    newSocket.on('connect', () => {
      setSocketConnected(true)
      setConnectionError(null)
    })

    newSocket.on('disconnect', (reason) => {
      setSocketConnected(false)
      if (reason === 'io server disconnect') {
        newSocket.connect()
      }
    })

    newSocket.on('connect_error', (error) => {
      setConnectionError(error.message)
      setSocketConnected(false)
    })

    newSocket.on('reconnect', () => {
      setSocketConnected(true)
      setConnectionError(null)
    })

    newSocket.on('reconnect_error', (error) => {
      setConnectionError(error.message)
    })

    newSocket.on('reconnect_failed', () => {
      setConnectionError('Failed to reconnect to server')
    })

    newSocket.on('face_detected', (data) => {
      if (data.alert_level && data.alert_level !== 'low') {
        pushToast(
          addNotification,
          data.alert_level === 'critical' ? 'error' : 'warning',
          'Face Detection Alert',
          `${data.alert_level.toUpperCase()}: Face detected at ${data.camera_name}`,
          data.alert_level === 'critical' ? 0 : 5000,
        )
      }
    })

    newSocket.on('person_identified', (data) => {
      if (data.confidence < 0.8) {
        pushToast(
          addNotification,
          'warning',
          'Low Confidence Identification',
          `Person identified with ${(data.confidence * 100).toFixed(1)}% confidence at ${data.camera_name}`,
          5000,
        )
      }
    })

    newSocket.on('security_alert', (data) => {
      const variant: ToastVariant =
        data.severity === 'critical'
          ? 'error'
          : data.severity === 'high'
            ? 'warning'
            : 'info'

      pushToast(
        addNotification,
        variant,
        'Security Alert',
        data.message,
        data.severity === 'critical' ? 0 : 8000,
      )
    })

    newSocket.on('camera_status', (data) => {
      if (data.status === 'offline') {
        pushToast(
          addNotification,
          'error',
          'Camera Offline',
          `Camera ${data.camera_name} has gone offline`,
          0,
        )
      } else if (data.status === 'online' && data.was_offline) {
        pushToast(
          addNotification,
          'success',
          'Camera Online',
          `Camera ${data.camera_name} is back online`,
          5000,
        )
      }
    })

    newSocket.on('system_status', (data) => {
      if (data.status === 'error') {
        pushToast(addNotification, 'error', 'System Error', data.message, 0)
      }
    })

    newSocket.on('user_enrolled', (data) => {
      pushToast(
        addNotification,
        'success',
        'User Enrolled',
        `${data.user_name} has been successfully enrolled in the system`,
        5000,
      )
    })

    newSocket.on('unauthorized_access', (data) => {
      pushToast(
        addNotification,
        'error',
        'Unauthorized Access',
        `Unauthorized access attempt detected at ${data.location}`,
        0,
      )
    })

    setSocket(newSocket)

    return () => {
      newSocket.disconnect()
      setSocket(null)
      setSocketConnected(false)
    }
  }, [isAuthenticated, user, addNotification, useSocketIo, wsUrl])

  const value = useMemo<SocketContextType>(
    () => ({
      socket: useSocketIo ? socket : null,
      isConnected: useSocketIo ? socketConnected : sseConnected,
      connectionError: useSocketIo ? connectionError : null,
    }),
    [socket, socketConnected, connectionError, useSocketIo, sseConnected],
  )

  return (
    <SocketContext.Provider value={value}>
      {children}
    </SocketContext.Provider>
  )
}
