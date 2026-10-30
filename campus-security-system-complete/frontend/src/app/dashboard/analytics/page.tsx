'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api/client'
import { useNotifications } from '@/contexts/notification-context'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Camera,
  RefreshCw,
  TrendingUp,
  Users,
  Scan,
} from 'lucide-react'

type AnalyticsMetric = {
  total_detections: number
  all_time_detections?: number
  total_face_detections?: number
  total_object_detections?: number
  unique_object_classes?: number
  unique_persons: number
  identification_accuracy: number
  false_positive_rate: number
  system_uptime: number
  camera_uptime: number
  active_cameras?: number
  total_cameras?: number
  active_alerts?: number
}

type HourlyActivity = {
  hour: number
  count: number
}

type TopLocation = {
  location: string
  count: number
}

type TopObjectClass = {
  label: string
  count: number
}

type AnalyticsData = {
  period: string
  start_date: string
  end_date: string
  last_updated?: string
  metrics: AnalyticsMetric
  peak_hours: HourlyActivity[]
  object_peak_hours?: HourlyActivity[]
  top_locations: TopLocation[]
  top_object_classes?: TopObjectClass[]
  trends?: {
    detections_over_time: Array<{ date: string; count: number; identified: number }>
    identifications_over_time: Array<{ date: string; count: number; identified: number }>
    object_detections_over_time?: Array<{ date: string; count: number }>
    camera_status_over_time: Array<any>
  }
}

const periodOptions = [
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' },
]

function formatPercent(value: number | undefined, digits = 1) {
  return `${Number(value || 0).toFixed(digits)}%`
}

function formatTime(value?: string) {
  if (!value) return 'Never'
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [period, setPeriod] = useState('7d')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const { events, connected } = useNotifications()

  const fetchAnalytics = useCallback(async (showSpinner = false) => {
    try {
      if (showSpinner) setRefreshing(true)
      setError('')
      const res = await api.get<AnalyticsData>('/analytics', { params: { period } })
      setData(res.data)
    } catch (err: any) {
      setError(err.detail || 'Failed to load analytics')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [period])

  useEffect(() => {
    setLoading(true)
    fetchAnalytics()
  }, [fetchAnalytics])

  useEffect(() => {
    const timer = window.setInterval(() => fetchAnalytics(), 30000)
    return () => window.clearInterval(timer)
  }, [fetchAnalytics])

  useEffect(() => {
    const latest = events[0]
    if (!latest) return

    const liveAnalyticsEvents = new Set([
      'detection_created',
      'new_alert',
      'alert_updated',
      'camera_added',
      'camera_deleted',
      'stream_started',
      'stream_stopped',
    ])

    if (!liveAnalyticsEvents.has(latest.event)) return

    const timer = window.setTimeout(() => fetchAnalytics(), 250)
    return () => window.clearTimeout(timer)
  }, [events, fetchAnalytics])

  const metrics = data?.metrics
  const stats = useMemo(() => [
    {
      label: 'Total Detections',
      value: metrics?.total_detections ?? 0,
      icon: Activity,
      color: 'text-blue-500',
      bg: 'bg-blue-500/10',
    },
    {
      label: 'Face Detections',
      value: metrics?.total_face_detections ?? 0,
      icon: Users,
      color: 'text-emerald-500',
      bg: 'bg-emerald-500/10',
    },
    {
      label: 'Object Detections',
      value: metrics?.total_object_detections ?? 0,
      icon: Scan,
      color: 'text-orange-500',
      bg: 'bg-orange-500/10',
    },
    {
      label: 'Unique Object Classes',
      value: metrics?.unique_object_classes ?? 0,
      icon: BarChart3,
      color: 'text-pink-500',
      bg: 'bg-pink-500/10',
    },
    {
      label: 'Identification Accuracy',
      value: formatPercent(metrics?.identification_accuracy),
      icon: TrendingUp,
      color: 'text-indigo-500',
      bg: 'bg-indigo-500/10',
    },
    {
      label: 'False Positive Rate',
      value: formatPercent(metrics?.false_positive_rate, 2),
      icon: AlertTriangle,
      color: 'text-yellow-500',
      bg: 'bg-yellow-500/10',
    },
    {
      label: 'System Uptime',
      value: formatPercent(metrics?.system_uptime, 2),
      icon: Camera,
      color: 'text-purple-500',
      bg: 'bg-purple-500/10',
    },
    {
      label: 'Camera Uptime',
      value: formatPercent(metrics?.camera_uptime),
      icon: BarChart3,
      color: 'text-orange-500',
      bg: 'bg-orange-500/10',
    },
  ], [metrics])

  const peakHours = data?.peak_hours || []
  const objectPeakHours = data?.object_peak_hours || []
  const topLocations = data?.top_locations || []
  const topObjectClasses = data?.top_object_classes || []
  const maxHourlyCount = Math.max(...peakHours.map(item => item.count), 1)
  const maxObjectHourlyCount = Math.max(...objectPeakHours.map(item => item.count), 1)
  const maxLocationCount = Math.max(...topLocations.map(item => item.count), 1)
  const maxObjectClassCount = Math.max(...topObjectClasses.map(item => item.count), 1)

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900 dark:text-white">
            <BarChart3 className="h-6 w-6 text-blue-500" /> Analytics
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            Real-time system performance and detection metrics
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
            Last updated {formatTime(data?.last_updated || data?.end_date)}
            <span className={connected ? 'ml-3 text-emerald-500' : 'ml-3 text-yellow-500'}>
              {connected ? 'Live updates connected' : 'Polling for updates'}
            </span>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-gray-200 bg-white p-1 dark:border-gray-700 dark:bg-gray-900">
            {periodOptions.map(option => (
              <button
                key={option.value}
                type="button"
                onClick={() => setPeriod(option.value)}
                className={[
                  'h-8 min-w-12 rounded-md px-3 text-sm font-medium transition-colors',
                  period === option.value
                    ? 'bg-blue-500 text-white'
                    : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800',
                ].join(' ')}
              >
                {option.label}
              </button>
            ))}
          </div>
          <Button variant="outline" onClick={() => fetchAnalytics(true)} disabled={refreshing}>
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label}>
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className={`rounded-lg p-3 ${stat.bg}`}>
                  <stat.icon className={`h-6 w-6 ${stat.color}`} />
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-gray-500 dark:text-gray-400">{stat.label}</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Hourly Detection Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-56 items-end gap-1">
            {peakHours.map((item) => (
              <div key={item.hour} className="flex h-full flex-1 flex-col items-center justify-end gap-2">
                <div className="flex h-44 w-full items-end">
                  <div
                    className="w-full rounded-t bg-blue-500 transition-all"
                    title={`${item.hour}:00 - ${item.count} detections`}
                    style={{ height: item.count ? `${Math.max((item.count / maxHourlyCount) * 100, 4)}%` : '2px' }}
                  />
                </div>
                {item.hour % 4 === 0 && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">{item.hour}h</span>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {objectPeakHours.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Hourly Object Detection Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex h-56 items-end gap-1">
              {objectPeakHours.map((item) => (
                <div key={item.hour} className="flex h-full flex-1 flex-col items-center justify-end gap-2">
                  <div className="flex h-44 w-full items-end">
                    <div
                      className="w-full rounded-t bg-orange-500 transition-all"
                      title={`${item.hour}:00 - ${item.count} object detections`}
                      style={{ height: item.count ? `${Math.max((item.count / maxObjectHourlyCount) * 100, 4)}%` : '2px' }}
                    />
                  </div>
                  {item.hour % 4 === 0 && (
                    <span className="text-xs text-gray-500 dark:text-gray-400">{item.hour}h</span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Top Locations</CardTitle>
          </CardHeader>
          <CardContent>
            {topLocations.length > 0 ? (
              <div className="space-y-3">
                {topLocations.map((loc) => (
                  <div key={loc.location} className="grid grid-cols-[minmax(0,1fr)_180px] items-center gap-4">
                    <span className="truncate text-sm text-gray-700 dark:text-gray-300">{loc.location}</span>
                    <div className="flex items-center gap-3">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                        <div
                          className="h-full rounded-full bg-blue-500"
                          style={{ width: `${(loc.count / maxLocationCount) * 100}%` }}
                        />
                      </div>
                      <span className="w-12 text-right text-sm font-medium text-gray-900 dark:text-white">
                        {loc.count}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
                No detection locations recorded for this period.
              </div>
            )}
          </CardContent>
        </Card>

        {topObjectClasses.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Top Object Classes</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {topObjectClasses.map((item) => (
                  <div key={item.label} className="grid grid-cols-[minmax(0,1fr)_180px] items-center gap-4">
                    <span className="truncate text-sm text-gray-700 dark:text-gray-300 capitalize">{item.label}</span>
                    <div className="flex items-center gap-3">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                        <div
                          className="h-full rounded-full bg-orange-500"
                          style={{ width: `${(item.count / maxObjectClassCount) * 100}%` }}
                        />
                      </div>
                      <span className="w-12 text-right text-sm font-medium text-gray-900 dark:text-white">
                        {item.count}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
