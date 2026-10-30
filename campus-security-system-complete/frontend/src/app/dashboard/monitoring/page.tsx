'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { CameraFeed } from '@/components/camera-feed'
import { Eye, Camera, Maximize2, X, RefreshCw } from 'lucide-react'

interface CameraData {
  id: string
  name: string
  location: string
  status: string
  camera_type: string
  stream_url: string
  settings: { resolution: string; fps: number }
  stream_active: boolean
}

export default function MonitoringPage() {
  const [cameras, setCameras] = useState<CameraData[]>([])
  const [loading, setLoading] = useState(true)
  const [layout, setLayout] = useState<'2x2' | '3x3' | '4x4'>('2x2')
  const [selectedCamera, setSelectedCamera] = useState<CameraData | null>(null)

  const fetchCameras = async () => {
    try {
      setLoading(true)
      const res = await api.get('/cameras')
      const data = res.data.items || []
      setCameras(data)
    } catch (err) {
      console.error('Failed to load cameras')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCameras()
  }, [])

  const onlineCameras = cameras.filter(c => c.status === 'online')
  const gridCols = layout === '2x2' ? 'grid-cols-1 sm:grid-cols-2' : layout === '3x3' ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4'

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Eye className="h-6 w-6 text-blue-500" /> Live Monitoring
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            {onlineCameras.length} of {cameras.length} cameras online
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchCameras}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button variant={layout === '2x2' ? 'default' : 'outline'} size="sm" onClick={() => setLayout('2x2')}>2x2</Button>
          <Button variant={layout === '3x3' ? 'default' : 'outline'} size="sm" onClick={() => setLayout('3x3')}>3x3</Button>
          <Button variant={layout === '4x4' ? 'default' : 'outline'} size="sm" onClick={() => setLayout('4x4')}>4x4</Button>
        </div>
      </div>

      {selectedCamera && (
        <Card className="border-blue-300 dark:border-blue-700">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                <Camera className="h-4 w-4 text-blue-500" />
                {selectedCamera.name} — {selectedCamera.location}
              </h3>
              <Button variant="outline" size="sm" onClick={() => setSelectedCamera(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
            <CameraFeed
              cameraName={selectedCamera.name}
              location={selectedCamera.location}
              streamUrl={selectedCamera.stream_url}
              resolution={selectedCamera.settings?.resolution}
              cameraType={selectedCamera.camera_type}
              isActive={selectedCamera.status === 'online'}
              className="aspect-video rounded-lg"
            />
          </CardContent>
        </Card>
      )}

      <div className={`grid ${gridCols} gap-3`}>
        {onlineCameras.map(camera => (
          <div
            key={camera.id}
            className="relative aspect-video rounded-lg overflow-hidden cursor-pointer group hover:ring-2 hover:ring-blue-500 transition-all"
            onClick={() => setSelectedCamera(camera)}
          >
            <CameraFeed
              cameraName={camera.name}
              location={camera.location}
              streamUrl={camera.stream_url}
              resolution={camera.settings?.resolution}
              cameraType={camera.camera_type}
              isActive={true}
              className="absolute inset-0"
            />
            <div className="absolute top-2 left-2 z-20">
              <Badge variant="success" className="text-[10px]">LIVE</Badge>
            </div>
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity z-20">
              <div className="bg-black/50 rounded p-1">
                <Maximize2 className="h-3.5 w-3.5 text-white" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {onlineCameras.length === 0 && (
        <div className="text-center py-12">
          <Camera className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">No cameras online</h3>
          <p className="text-gray-500 dark:text-gray-400">Add cameras and ensure they are online to see live feeds.</p>
        </div>
      )}
    </div>
  )
}
