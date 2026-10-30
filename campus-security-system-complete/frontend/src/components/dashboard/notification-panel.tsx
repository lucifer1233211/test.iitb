'use client'

import { useState } from 'react'
import { useNotifications } from '@/contexts/notification-context'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { formatRelativeTime, cn } from '@/lib/utils'
import {
  X,
  Bell,
  AlertTriangle,
  CheckCircle,
  Info,
  Trash2,
  MailCheck,
} from 'lucide-react'

interface NotificationPanelProps {
  open: boolean
  onClose: () => void
}

export function NotificationPanel({ open, onClose }: NotificationPanelProps) {
  const {
    events: notifications = [],
    unreadCount,
    clearEvents: clearAllNotifications,
    markAsRead,
    removeEvent,
    isRead,
  } = useNotifications()

  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  const normalizedNotifications = notifications.map(n => {
    const id = n.data?.id ||  n.ts
    
    let type = 'info'
    if (n.event === 'new_alert') {
      type = n.data?.severity === 'critical' || n.data?.severity === 'high' ? 'error' : 'warning'
    } else if (n.event === 'person_reidentified') {
      type = 'info'
    } else if (n.event?.includes('added') || n.event?.includes('enrolled') || n.event?.includes('started')) {
      type = 'success'
    }

    return {
      id,
      type,
      title: n.data?.title || n.event?.replace('_', ' ').toUpperCase() || 'System Event',
      message: n.data?.message || n.data?.description || `Event logged at location: ${n.data?.location || 'Main Campus'}`,
      timestamp: n.ts,
      isRead: isRead(id)
    }
  })

  const filteredNotifications = normalizedNotifications.filter(notification => {
    if (filter === 'unread') {
      return !notification.isRead
    }
    return true
  })

  const getNotificationIcon = (type: string) => {
    switch (type) {
      case 'success':
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'error':
        return <AlertTriangle className="h-5 w-5 text-red-500" />
      case 'warning':
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />
      case 'info':
      default:
        return <Info className="h-5 w-5 text-blue-500" />
    }
  }

  const getNotificationBorderColor = (type: string) => {
    switch (type) {
      case 'success':
        return 'border-l-green-500'
      case 'error':
        return 'border-l-red-500'
      case 'warning':
        return 'border-l-yellow-500'
      case 'info':
      default:
        return 'border-l-blue-500'
    }
  }

  return (
    <>
      {/* Overlay */}
      {open && (
        <div 
          className="fixed inset-0 z-40 bg-black bg-opacity-50 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div className={cn(
        'fixed inset-y-0 right-0 z-50 w-96 bg-white dark:bg-gray-900 shadow-xl transform transition-transform duration-300 ease-in-out',
        open ? 'translate-x-0' : 'translate-x-full'
      )}>
        <div className="flex h-full flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center space-x-2">
              <Bell className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Notifications
              </h2>
              {unreadCount > 0 && (
                <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
                  {unreadCount}
                </span>
              )}
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-5 w-5" />
            </Button>
          </div>

          {/* Filters */}
          <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex space-x-2">
              <Button
                variant={filter === 'all' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setFilter('all')}
              >
                All
              </Button>
              <Button
                variant={filter === 'unread' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setFilter('unread')}
              >
                Unread ({unreadCount})
              </Button>
            </div>
            {notifications.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearAllNotifications}
                className="text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
              >
                <Trash2 className="h-4 w-4 mr-1" />
                Clear All
              </Button>
            )}
          </div>

          {/* Notifications List */}
          <div className="flex-1 overflow-y-auto">
            {filteredNotifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center p-6">
                <Bell className="h-12 w-12 text-gray-400 dark:text-gray-600 mb-4" />
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
                  No notifications
                </h3>
                <p className="text-gray-500 dark:text-gray-400">
                  {filter === 'unread' 
                    ? "You're all caught up! No unread notifications."
                    : "You'll see notifications here when they arrive."
                  }
                </p>
              </div>
            ) : (
              <div className="space-y-2 p-4">
                {filteredNotifications.map((notification, index) => (
                  <Card 
                    key={`${notification.id}-${index}`}
                    className={cn(
                      'border-l-4 hover:shadow-md transition-shadow cursor-pointer',
                      getNotificationBorderColor(notification.type),
                      notification.isRead && 'opacity-60'
                    )}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start space-x-3">
                        <div className="flex-shrink-0 mt-0.5">
                          {getNotificationIcon(notification.type)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <h4 className="text-sm font-medium text-gray-900 dark:text-white">
                                {notification.title}
                              </h4>
                              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                                {notification.message}
                              </p>
                              <p className="text-xs text-gray-500 dark:text-gray-500 mt-2">
                                {formatRelativeTime(notification.timestamp)}
                              </p>
                            </div>
                            <div className="flex items-center space-x-1 ml-2">
                              {!notification.isRead && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-6 w-6"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    markAsRead(notification.id)
                                  }}
                                >
                                  <MailCheck className="h-3 w-3" />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-red-500 hover:text-red-700"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  removeEvent(notification.id)
                                }}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
