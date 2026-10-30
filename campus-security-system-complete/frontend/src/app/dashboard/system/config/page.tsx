'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { Settings, Server, Database, Cpu, HardDrive, RefreshCw } from 'lucide-react'

export default function SystemConfigPage() {
  const [status, setStatus] = useState<any>(null)
  const [faceConfig, setFaceConfig] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      setLoading(true)
      const [statusRes, faceRes] = await Promise.all([
        api.get('/system/status'),
        api.get('/face/config'),
      ])
      setStatus(statusRes.data)
      setFaceConfig(faceRes.data)
    } catch (err) {
      console.error('Failed to load system config')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Settings className="h-6 w-6 text-blue-500" /> System Configuration
          </h1>
          <p className="text-gray-500 dark:text-gray-400">System settings and health status</p>
        </div>
        <Button variant="outline" onClick={fetchData}>
          <RefreshCw className="h-4 w-4 mr-2" /> Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5 text-blue-500" /> System Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">Status</span>
                <Badge variant={status?.status === 'operational' ? 'success' : 'destructive'}>
                  {status?.status || 'unknown'}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">Uptime</span>
                <span className="text-gray-900 dark:text-white font-medium">{status?.uptime || 'N/A'}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">CPU Usage</span>
                <span className="text-gray-900 dark:text-white font-medium">{status?.cpu_usage || 0}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">Memory Usage</span>
                <span className="text-gray-900 dark:text-white font-medium">{status?.memory_usage || 0}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600 dark:text-gray-400">Active Cameras</span>
                <span className="text-gray-900 dark:text-white font-medium">{status?.active_cameras || 0} / {status?.total_cameras || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-5 w-5 text-purple-500" /> Face Recognition Config
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {faceConfig && Object.entries(faceConfig).map(([key, value]: [string, any]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-gray-600 dark:text-gray-400 text-sm">{key.replace(/_/g, ' ')}</span>
                  <span className="text-gray-900 dark:text-white font-medium text-sm">
                    {typeof value === 'boolean' ? (
                      <Badge variant={value ? 'success' : 'secondary'}>{value ? 'Yes' : 'No'}</Badge>
                    ) : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
