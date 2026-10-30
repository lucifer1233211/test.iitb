'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/ui/loading-spinner'
import { CameraFeed } from '@/components/camera-feed'
import { Camera, Plus, MapPin, RefreshCw, Search, Eye, Radio, X, Maximize2, Trash2, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

interface CameraData {
  id: string
  name: string
  location: string
  status: string
  camera_type: string
  stream_url: string
  is_active: boolean
  settings: { resolution: string; fps: number }
  stream_active: boolean
  created_at: string | null
  last_heartbeat: string | null
}

// ── Delete Confirmation Modal ──────────────────────────────────────────────────
function DeleteModal({
  camera,
  onConfirm,
  onCancel,
  deleting,
}: {
  camera: CameraData
  onConfirm: () => void
  onCancel: () => void
  deleting: boolean
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4"
      onClick={e => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-gray-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
              <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Delete Camera</h2>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5 space-y-3">
          <p className="text-gray-700 dark:text-gray-300">
            Are you sure you want to delete{' '}
            <span className="font-semibold text-gray-900 dark:text-white">{camera.name}</span>?
          </p>
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2">
            <MapPin className="h-3.5 w-3.5 shrink-0" />
            {camera.location}
          </div>
          <p className="text-sm text-red-600 dark:text-red-400">
            This action cannot be undone. All data associated with this camera will be permanently removed.
          </p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t dark:border-gray-700 flex justify-end gap-3">
          <Button variant="outline" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={deleting}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            {deleting ? (
              <span className="flex items-center gap-2">
                <div className="animate-spin rounded-full border-2 border-white/30 border-t-white h-4 w-4" />
                Deleting...
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <Trash2 className="h-4 w-4" />
                Delete Camera
              </span>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Camera View Modal ──────────────────────────────────────────────────────────
function CameraModal({ camera, onClose }: { camera: CameraData; onClose: () => void }) {
  const handleBackdrop = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const statusColor = (status: string) => {
    switch (status) {
      case 'online': return 'success'
      case 'offline': return 'destructive'
      case 'maintenance': return 'warning'
      default: return 'secondary'
    }
  }

  const [mode, setMode] = useState<'face' | 'object' | 'both'>('both')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4"
      onClick={handleBackdrop}
    >
      <div className="relative bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-3xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b dark:border-gray-700">
          <div className="flex items-center gap-3">
            <Camera className="h-5 w-5 text-blue-500 shrink-0" />
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white leading-tight">{camera.name}</h2>
              <div className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
                <MapPin className="h-3.5 w-3.5" />
                {camera.location}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={statusColor(camera.status) as any}>{camera.status}</Badge>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition-colors"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Feed */}
        <div className="bg-black" style={{ width: '100%', height: '420px' }}>
          <CameraFeed
            cameraName={camera.name}
            location={camera.location}
            streamUrl={camera.stream_url}
            resolution={camera.settings?.resolution}
            cameraType={camera.camera_type}
            isActive={camera.status === 'online'}
            showOverlay={true}
            className="w-full h-full"
            detectionMode={mode}
            onModeChange={setMode}
            showModeToggle
          />
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t dark:border-gray-700 flex flex-wrap items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
          {camera.stream_url && (
            <div className="flex items-center gap-1.5 min-w-0">
              <Radio className="h-3.5 w-3.5 text-green-500 shrink-0" />
              <span className="font-mono text-xs truncate max-w-[260px]">{camera.stream_url}</span>
            </div>
          )}
          <div className="flex items-center gap-4 ml-auto shrink-0">
            <span><span className="text-gray-400">Mode:</span> <span className="font-mono uppercase text-xs">{mode}</span></span>
            <span><span className="text-gray-400">Type:</span> {camera.camera_type}</span>
            <span><span className="text-gray-400">Res:</span> {camera.settings?.resolution}</span>
            <span><span className="text-gray-400">FPS:</span> {camera.settings?.fps}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function CamerasPage() {
  const [cameras, setCameras] = useState<CameraData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedCamera, setSelectedCamera] = useState<CameraData | null>(null)
  const [cameraToDelete, setCameraToDelete] = useState<CameraData | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const router = useRouter()

  const fetchCameras = async () => {
    try {
      setLoading(true)
      const res = await api.get('/cameras')
      setCameras(res.data.items || [])
    } catch (err: any) {
      setError(err.detail || 'Failed to load cameras')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchCameras() }, [])

  const handleDeleteConfirm = async () => {
    if (!cameraToDelete) return
    setDeleting(true)
    setDeleteError('')
    try {
      await api.delete(`/cameras/${cameraToDelete.id}`)
      setCameras(prev => prev.filter(c => c.id !== cameraToDelete.id))
      setCameraToDelete(null)
    } catch (err: any) {
      setDeleteError(err?.response?.data?.detail || err?.message || 'Failed to delete camera.')
    } finally {
      setDeleting(false)
    }
  }

  const filtered = cameras.filter(c => {
    const matchSearch = c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.location.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || c.status === statusFilter
    return matchSearch && matchStatus
  })

  const statusColor = (status: string) => {
    switch (status) {
      case 'online': return 'success'
      case 'offline': return 'destructive'
      case 'maintenance': return 'warning'
      default: return 'secondary'
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64"><LoadingSpinner size="lg" /></div>
  }

  return (
    <div className="space-y-6">
      {/* Camera View Modal */}
      {selectedCamera && (
        <CameraModal camera={selectedCamera} onClose={() => setSelectedCamera(null)} />
      )}

      {/* Delete Confirmation Modal */}
      {cameraToDelete && (
        <DeleteModal
          camera={cameraToDelete}
          onConfirm={handleDeleteConfirm}
          onCancel={() => { setCameraToDelete(null); setDeleteError('') }}
          deleting={deleting}
        />
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Cameras</h1>
          <p className="text-gray-500 dark:text-gray-400">Manage and monitor all campus cameras</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => router.push('/dashboard/monitoring')}>
            <Eye className="h-4 w-4 mr-2" /> Live View
          </Button>
          <Link href="/dashboard/cameras/add">
            <Button className="bg-blue-600 hover:bg-blue-700 text-white">
              <Plus className="h-4 w-4 mr-2" /> Add Camera
            </Button>
          </Link>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search cameras..."
            className="w-full pl-10 pr-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="px-4 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="all">All Status</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="maintenance">Maintenance</option>
        </select>
        <Button variant="outline" onClick={fetchCameras}>
          <RefreshCw className="h-4 w-4 mr-2" /> Refresh
        </Button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Inline delete error (shown below filters if modal was closed) */}
      {deleteError && !cameraToDelete && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300 flex items-center justify-between">
          <span>{deleteError}</span>
          <button onClick={() => setDeleteError('')}><X className="h-4 w-4" /></button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(camera => (
          <Card
            key={camera.id}
            className="hover:shadow-lg transition-shadow overflow-hidden group"
          >
            {/* Camera feed — clickable to open view modal */}
            <div
              className="aspect-video relative cursor-pointer"
              onClick={() => setSelectedCamera(camera)}
            >
              <CameraFeed
                cameraName={camera.name}
                location={camera.location}
                streamUrl={camera.stream_url}
                resolution={camera.settings?.resolution}
                cameraType={camera.camera_type}
                isActive={camera.status === 'online'}
                showOverlay={true}
                className="absolute inset-0"
              />
              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center z-20">
                <Maximize2 className="h-8 w-8 text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
              </div>
            </div>

            <CardContent className="pt-4">
              <div className="space-y-2 text-sm">
                {/* Name row */}
                <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <Camera className="h-4 w-4 text-blue-500 shrink-0" />
                  {camera.name}
                </h3>
                <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                  <MapPin className="h-3.5 w-3.5" />
                  {camera.location}
                </div>
                {camera.stream_url && camera.stream_url.startsWith('rtsp://') && (
                  <div className="flex items-center gap-1.5 text-xs">
                    <Radio className="h-3 w-3 text-green-500" />
                    <span className="text-green-600 dark:text-green-400 font-mono truncate max-w-[200px]">{camera.stream_url}</span>
                  </div>
                )}
                {/* Bottom row: type/res + status badge + delete */}
                <div className="flex items-center justify-between pt-1 gap-2">
                  <div className="flex items-center gap-3">
                    <span><span className="text-gray-500 dark:text-gray-400">Type:</span>{' '}<span className="text-gray-900 dark:text-white">{camera.camera_type}</span></span>
                    <span><span className="text-gray-500 dark:text-gray-400">Res:</span>{' '}<span className="text-gray-900 dark:text-white">{camera.settings?.resolution}</span></span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={statusColor(camera.status) as any}>{camera.status}</Badge>
                    <button
                      onClick={e => { e.stopPropagation(); setCameraToDelete(camera) }}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                      title="Delete camera"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {filtered.length === 0 && !loading && (
        <div className="text-center py-12">
          <Camera className="h-12 w-12 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white">No cameras found</h3>
          <p className="text-gray-500 dark:text-gray-400">Try adjusting your search or filter, or add a new camera.</p>
        </div>
      )}
    </div>
  )
} 
