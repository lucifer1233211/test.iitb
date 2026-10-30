'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/auth-context'
import { useNotifications } from '@/contexts/notification-context'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { api } from '@/lib/api/client'
import {
  Activity,
  Camera,
  Users,
  UserPlus,
  AlertTriangle,
  Eye,
  Shield,
  TrendingUp,
  Clock,
  MapPin,
  Zap,
} from 'lucide-react'
import { formatNumber, formatRelativeTime } from '@/lib/utils'

export default function DashboardPage() {
  const { user } = useAuth()
  const { connected: isSSEConnected } = useNotifications()
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(true)
  const [systemStatus, setSystemStatus] = useState<any>(null)
  const [recentAlerts, setRecentAlerts] = useState<any[]>([])
  const [recentDetections, setRecentDetections] = useState<any[]>([])

  useEffect(() => {
    const controller = new AbortController();
    let isMounted = true;

    const fetchData = async () => {
      try {
        const requestConfig = { signal: controller.signal };

        const [statusRes, alertsRes, detectionsRes] = await Promise.allSettled([
          api.get('/system/status', requestConfig),
          api.get('/alerts?size=3&sort_by=timestamp&sort_order=desc', requestConfig),
          api.get('/detections?size=3&sort_by=timestamp&sort_order=desc', requestConfig),
        ]);

        if (!isMounted) return;

        // Process System Status Promise
        if (statusRes.status === 'fulfilled') {
          setSystemStatus(statusRes.value.data);
        } else {
          const error = statusRes.reason;
          if (error?.name !== 'CanceledError' && error?.message !== 'canceled' && error?.code !== 'ERR_CANCELED') {
            console.error('Status fetch failed:', error);
          }
        }

        // Process Recent Alerts Promise
        if (alertsRes.status === 'fulfilled') {
          setRecentAlerts(alertsRes.value.data.items || []);
        } else {
          const error = alertsRes.reason;
          if (error?.name !== 'CanceledError' && error?.message !== 'canceled' && error?.code !== 'ERR_CANCELED') {
            console.error('Alerts fetch failed:', error);
          }
        }

        // Process Recent Detections Promise
        if (detectionsRes.status === 'fulfilled') {
          setRecentDetections(detectionsRes.value.data.items || []);
        } else {
          const error = detectionsRes.reason;
          if (error?.name !== 'CanceledError' && error?.message !== 'canceled' && error?.code !== 'ERR_CANCELED') {
            console.error('Detections fetch failed:', error);
          }
        }

      } catch (err: any) {
        if (err.name !== 'CanceledError' && err.message !== 'canceled' && err.code !== 'ERR_CANCELED') {
          console.error('Failed to fetch dashboard data', err);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);
  
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'operational':
      case 'healthy':
        return 'text-green-600 dark:text-green-400'
      case 'warning':
        return 'text-yellow-600 dark:text-yellow-400'
      case 'error':
        return 'text-red-600 dark:text-red-400'
      default:
        return 'text-gray-600 dark:text-gray-400'
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'low':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
      case 'medium':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
      case 'high':
        return 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200'
      case 'critical':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200'
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  const activeCameras = systemStatus?.active_cameras ?? 0
  const totalCameras = systemStatus?.total_cameras ?? 0
  const uptime = systemStatus?.uptime ?? 0
  const cpuUsage = systemStatus?.cpu_usage ?? 0
  const memoryUsage = systemStatus?.memory_usage ?? 0
  const status = systemStatus?.status ?? 'unknown'
  const activeDetections = systemStatus?.active_detections ?? 0

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-security-600 to-security-700 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">
              Welcome back, {user?.full_name?.split(' ')[0]}!
            </h1>
            <p className="text-security-100 mt-1">
              IIT Bombay Security Dashboard - {new Date().toLocaleDateString()}
            </p>
          </div>
          <div className="flex items-center space-x-2">
            <div className={`flex items-center space-x-1 ${isSSEConnected ? 'text-green-200' : 'text-red-200'}`}>
              <div className={`w-2 h-2 rounded-full ${isSSEConnected ? 'bg-green-400' : 'bg-red-400'}`} />
              <span className="text-sm font-medium">
                {isSSEConnected ? 'Live Feed Connected' : 'Live Feed Disconnected'}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">System Status</CardTitle>
            <Shield className={`h-4 w-4 ${getStatusColor(status)}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold capitalize">{status}</div>
            <p className="text-xs text-muted-foreground">
              Uptime: {uptime}s
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Cameras</CardTitle>
            <Camera className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {activeCameras}/{totalCameras}
            </div>
            <p className="text-xs text-muted-foreground">
              {totalCameras > 0 ? Math.round((activeCameras / totalCameras) * 100) : 0}% online
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Detections</CardTitle>
            <Eye className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatNumber(activeDetections)}</div>
            <p className="text-xs text-muted-foreground">
              Face recognition events
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Alerts</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{systemStatus?.alerts_count?.active ?? 0}</div>
            <p className="text-xs text-muted-foreground">
              {systemStatus?.alerts_count?.resolved ?? 0} resolved
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
            <TrendingUp className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{cpuUsage.toFixed(1)}%</div>
            <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
              <div
                className="bg-green-600 h-2 rounded-full"
                style={{ width: `${Math.min(cpuUsage, 100)}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Server processor load
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Memory Usage</CardTitle>
            <Clock className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{memoryUsage.toFixed(1)}%</div>
            <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
              <div
                className="bg-blue-600 h-2 rounded-full"
                style={{ width: `${Math.min(memoryUsage, 100)}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Server memory utilization
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Camera Health</CardTitle>
            <Activity className="h-4 w-4 text-orange-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {totalCameras > 0 ? Math.round((activeCameras / totalCameras) * 100) : 0}%
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
              <div
                className="bg-orange-600 h-2 rounded-full"
                style={{ width: `${totalCameras > 0 ? (activeCameras / totalCameras) * 100 : 0}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {activeCameras} of {totalCameras} cameras active
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <AlertTriangle className="h-5 w-5" />
              <span>Recent Alerts</span>
            </CardTitle>
            <CardDescription>
              Latest security alerts and notifications
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {recentAlerts.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">No recent alerts</p>
              )}
              {recentAlerts.map((alert) => (
                <div key={alert.id} className="flex items-start space-x-3">
                  <div className="flex-shrink-0">
                    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${getSeverityColor(alert.severity)}`}>
                      {(alert.severity || '').toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {alert.message || alert.title}
                    </p>
                    <div className="flex items-center space-x-2 text-xs text-gray-500 dark:text-gray-400">
                      <MapPin className="h-3 w-3" />
                      <span>{alert.location || 'Unknown'}</span>
                      <span>•</span>
                      <span>{alert.timestamp ? formatRelativeTime(alert.timestamp) : ''}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <Button variant="outline" className="w-full" onClick={() => router.push('/dashboard/alerts')}>
                View All Alerts
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <Users className="h-5 w-5" />
              <span>Recent Detections</span>
            </CardTitle>
            <CardDescription>
              Latest face recognition detections
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {recentDetections.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">No recent detections</p>
              )}
              {recentDetections.map((detection) => (
                <div key={detection.id} className="flex items-start space-x-3">
                  <div className="flex-shrink-0">
                    <div className="h-8 w-8 rounded-full bg-security-600 flex items-center justify-center">
                      <span className="text-xs font-medium text-white">
                        {(detection.person_name || detection.personName || '?').charAt(0)}
                      </span>
                    </div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">
                      {detection.person_name || detection.personName || 'Unknown'}
                    </p>
                    <div className="flex items-center space-x-2 text-xs text-gray-500 dark:text-gray-400">
                      <MapPin className="h-3 w-3" />
                      <span>{detection.camera_name || detection.location || 'Unknown'}</span>
                      <span>•</span>
                      <span>{(detection.confidence * 100 || 0).toFixed(1)}% confidence</span>
                      <span>•</span>
                      <span>{detection.timestamp ? formatRelativeTime(detection.timestamp) : ''}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <Button variant="outline" className="w-full" onClick={() => router.push('/dashboard/face-recognition/detections')}>
                View All Detections
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <Zap className="h-5 w-5" />
            <span>Quick Actions</span>
          </CardTitle>
          <CardDescription>
            Common tasks and shortcuts
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Button variant="outline" className="h-20 flex flex-col space-y-2" onClick={() => router.push('/dashboard/face-recognition/enroll')}>
              <UserPlus className="h-6 w-6" />
              <span className="text-sm">Enroll Person</span>
            </Button>
            <Button variant="outline" className="h-20 flex flex-col space-y-2" onClick={() => router.push('/dashboard/cameras/add')}>
              <Camera className="h-6 w-6" />
              <span className="text-sm">Add Camera</span>
            </Button>
            <Button variant="outline" className="h-20 flex flex-col space-y-2" onClick={() => router.push('/dashboard/monitoring')}>
              <Eye className="h-6 w-6" />
              <span className="text-sm">Live Monitor</span>
            </Button>
            <Button variant="outline" className="h-20 flex flex-col space-y-2" onClick={() => router.push('/dashboard/reports')}>
              <Activity className="h-6 w-6" />
              <span className="text-sm">View Reports</span>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
