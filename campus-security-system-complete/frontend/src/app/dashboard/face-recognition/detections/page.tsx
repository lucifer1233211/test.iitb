'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { Eye, Clock, Camera, RefreshCw, Search, User } from 'lucide-react'

interface Detection {
  id: string
  camera_id: string | null
  camera_name: string
  person_name: string | null
  person_id: string | null
  confidence: number
  timestamp: string
  location: string
  status: string
  alert_level: string
}

export default function DetectionsPage() {
  const [detections, setDetections] = useState<Detection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const fetchDetections = async () => {
    try {
      setLoading(true)
      const res = await api.get('/detections')
      setDetections(res.data.items || [])
    } catch (err: any) {
      setError(err.detail || 'Failed to load detections')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchDetections() }, [])

  const filtered = detections.filter(d =>
    (d.person_name || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.camera_name || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.location || '').toLowerCase().includes(search.toLowerCase())
  )

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Detection History</h1>
          <p className="text-gray-500 dark:text-gray-400">Face detection events from all cameras</p>
        </div>
        <Button variant="outline" onClick={fetchDetections}>
          <RefreshCw className="h-4 w-4 mr-2" /> Refresh
        </Button>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
        <input type="text" placeholder="Search detections..."
          className="w-full pl-10 pr-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
          value={search} onChange={e => setSearch(e.target.value)} />
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Person</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Camera</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Location</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Confidence</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Time</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
            {filtered.map(det => (
              <tr key={det.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="flex items-center gap-2">
                    <User className="h-4 w-4 text-gray-400" />
                    <span className="text-sm text-gray-900 dark:text-white">
                      {det.person_name || det.person_id || 'Unknown'}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  <div className="flex items-center gap-1">
                    <Camera className="h-3 w-3" /> {det.camera_name || `Camera ${det.camera_id}`}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">{det.location}</td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <Badge variant={det.confidence > 0.8 ? 'success' : det.confidence > 0.5 ? 'warning' : 'destructive'}>
                    {(det.confidence * 100).toFixed(1)}%
                  </Badge>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" /> {new Date(det.timestamp).toLocaleString()}
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <Badge variant={det.status === 'identified' ? 'success' : 'secondary'}>{det.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && !loading && (
        <div className="text-center py-12">
          <Eye className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">No detections found</h3>
          <p className="text-gray-500 dark:text-gray-400">Detection events will appear here as they occur.</p>
        </div>
      )}
    </div>
  )
}
