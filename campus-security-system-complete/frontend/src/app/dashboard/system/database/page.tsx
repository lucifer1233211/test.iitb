'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { Database, Server, HardDrive, RefreshCw, Activity } from 'lucide-react'

export default function DatabasePage() {
  const [status, setStatus] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const fetchStatus = async () => {
    try {
      setLoading(true)
      const res = await api.get('/system/status')
      setStatus(res.data)
    } catch (err) {
      console.error('Failed to load database status')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchStatus() }, [])

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  const dbStats = [
    { label: 'System Status', value: status?.status || 'operational', badge: true, variant: 'success' },
    { label: 'Total Cameras', value: status?.total_cameras || 0 },
    { label: 'Active Cameras', value: status?.active_cameras || 0 },
    { label: 'Total Detections', value: status?.active_detections || 0 },
    { label: 'Active Alerts', value: status?.alerts_count?.active || 0 },
    { label: 'Resolved Alerts', value: status?.alerts_count?.resolved || 0 },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Database className="h-6 w-6 text-blue-500" /> Database
          </h1>
          <p className="text-gray-500 dark:text-gray-400">Database status and statistics</p>
        </div>
        <Button variant="outline" onClick={fetchStatus}>
          <RefreshCw className="h-4 w-4 mr-2" /> Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {dbStats.map((stat, i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500 dark:text-gray-400">{stat.label}</span>
                {stat.badge ? (
                  <Badge variant={stat.variant as any}>{stat.value}</Badge>
                ) : (
                  <span className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value}</span>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-green-500" /> Database Information
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2 border-b dark:border-gray-700">
              <span className="text-gray-600 dark:text-gray-400">Engine</span>
              <span className="text-gray-900 dark:text-white font-medium">PostgreSQL</span>
            </div>
            <div className="flex items-center justify-between py-2 border-b dark:border-gray-700">
              <span className="text-gray-600 dark:text-gray-400">Host</span>
              <span className="text-gray-900 dark:text-white font-medium font-mono text-sm">localhost</span>
            </div>
            <div className="flex items-center justify-between py-2 border-b dark:border-gray-700">
              <span className="text-gray-600 dark:text-gray-400">Face Embeddings Storage</span>
              <span className="text-gray-900 dark:text-white font-medium">JSON File (models/embeddings/)</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-gray-600 dark:text-gray-400">System Status</span>
              <Badge variant="success">Operational</Badge>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
