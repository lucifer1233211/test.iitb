'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, Camera, Save, Radio, Info, ScanLine } from 'lucide-react'
import Link from 'next/link'

const RTSP_TEMPLATES = [
  { brand: 'Hikvision', template: 'rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/101' },
  { brand: 'Dahua', template: 'rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel=1&subtype=0' },
  { brand: 'Axis', template: 'rtsp://{user}:{pass}@{ip}:554/axis-media/media.amp' },
  { brand: 'Bosch', template: 'rtsp://{ip}:554/video?inst=1' },
  { brand: 'Uniview', template: 'rtsp://{user}:{pass}@{ip}:554/media/video1' },
  { brand: 'Generic H.264', template: 'rtsp://{user}:{pass}@{ip}:554/h264' },
  { brand: 'Generic MPEG4', template: 'rtsp://{user}:{pass}@{ip}:554/mpeg4' },
]

const IITB_LOCATIONS = [
  'Main Gate',
  'Central Library (Ground Floor)',
  'Central Library (1st Floor)',
  'KReSIT Building - Entrance',
  'KReSIT Building - Lab Wing',
  'Student Activity Centre (SAC)',
  'Hostel 10 - Main Entrance',
  'Hostel 10 - Mess Area',
  'Hostel 4 - Entrance',
  'Hostel 4 - Common Room',
  'Main Building - Front Entrance',
  'Main Building - Corridor',
  'Gymkhana Ground',
  'Lecture Hall Complex (LHC)',
  'Convocation Hall',
  'Powai Lake Side - Perimeter',
  'Boat House Area',
  'Chemical Engineering Building',
  'Electrical Engineering Building',
  'Mechanical Engineering Building',
  'VMCC (Victor Menezes Convention Centre)',
  'SOM (School of Management)',
  'IDC (Industrial Design Centre)',
  'Aerospace Engineering Building',
  'Physics Department',
  'Chemistry Department',
  'Parking Lot - Main',
  'Parking Lot - KReSIT',
  'Swimming Pool Area',
  'Hospital / Health Centre',
]

const IITB_BUILDINGS = [
  'Main Building', 'KReSIT', 'Central Library', 'SAC', 'LHC',
  'Convocation Hall', 'VMCC', 'SOM', 'IDC', 'Chemical Engg.',
  'Electrical Engg.', 'Mechanical Engg.', 'Aerospace Engg.',
  'Physics Dept.', 'Chemistry Dept.', 'Health Centre',
  'Hostel 1', 'Hostel 2', 'Hostel 3', 'Hostel 4', 'Hostel 5',
  'Hostel 6', 'Hostel 7', 'Hostel 8', 'Hostel 9', 'Hostel 10',
  'Hostel 11', 'Hostel 12', 'Hostel 13', 'Hostel 14', 'Hostel 15', 'Hostel 16',
  'Tansa House', 'QIP House',
]

const IITB_ZONES = [
  'Main Gate Area', 'Academic Zone', 'Hostel Zone (North)',
  'Hostel Zone (South)', 'Lakeside Perimeter', 'Sports Complex',
  'Administrative Block', 'Research Park', 'Staff Quarters',
]

function extractIpFromRtsp(url: string): string {
  try {
    const match = url.match(/@([\d.]+):|\/\/([\d.]+):/)
    if (match) return match[1] || match[2]
    const match2 = url.match(/\/\/([\w.]+):/)
    if (match2) return match2[1]
  } catch {}
  return ''
}

export default function AddCameraPage() {
  const router = useRouter()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [form, setForm] = useState({
    name: '',
    location: '',
    camera_type: 'fixed',
    resolution: '1080p',
    ip_address: '',
    zone: '',
    floor: '',
    building: '',
    stream_url: '',
    description: '',
    person_reidentification_enabled: true,
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    setForm(prev => {
      const updated = { ...prev, [name]: value }
      if (name === 'stream_url' && value.startsWith('rtsp://')) {
        const ip = extractIpFromRtsp(value)
        if (ip && !prev.ip_address) {
          updated.ip_address = ip
        }
      }
      return updated
    })
  }

  const applyTemplate = (template: string) => {
    const ip = form.ip_address || '{ip}'
    const url = template.replace('{ip}', ip).replace('{user}', '{user}').replace('{pass}', '{pass}')
    setForm(prev => ({ ...prev, stream_url: url }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const { api } = await import('@/lib/api/client')
      await api.post('/cameras', form)
      setSuccess(true)
      setTimeout(() => router.push('/dashboard/cameras'), 1500)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to add camera.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/dashboard/cameras">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" /> Back
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Add Camera</h1>
          <p className="text-gray-500 dark:text-gray-400">Register a new CCTV / RTSP camera to the system</p>
        </div>
      </div>

      {success && (
        <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-green-700 dark:text-green-300">
          Camera added successfully! Redirecting...
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Camera className="h-5 w-5 text-blue-500" /> Camera Details
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Camera Name *</label>
                    <input name="name" required value={form.name} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., Main Gate Camera 1" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Location *</label>
                    <input name="location" required value={form.location} onChange={handleChange}
                      list="locations-list"
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., Main Gate" />
                    <datalist id="locations-list">
                      {IITB_LOCATIONS.map(loc => <option key={loc} value={loc} />)}
                    </datalist>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Type</label>
                    <select name="camera_type" value={form.camera_type} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white">
                      <option value="fixed">Fixed</option>
                      <option value="ptz">PTZ</option>
                      <option value="dome">Dome</option>
                      <option value="bullet">Bullet</option>
                      <option value="drone">Drone</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Resolution</label>
                    <select name="resolution" value={form.resolution} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white">
                      <option value="720p">720p</option>
                      <option value="1080p">1080p</option>
                      <option value="1440p">1440p</option>
                      <option value="4K">4K</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">IP Address</label>
                    <input name="ip_address" value={form.ip_address} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., 10.162.1.182" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Zone</label>
                    <input name="zone" value={form.zone} onChange={handleChange}
                      list="zones-list"
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., Main Gate Area" />
                    <datalist id="zones-list">
                      {IITB_ZONES.map(z => <option key={z} value={z} />)}
                    </datalist>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Building</label>
                    <input name="building" value={form.building} onChange={handleChange}
                      list="buildings-list"
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., KReSIT" />
                    <datalist id="buildings-list">
                      {IITB_BUILDINGS.map(b => <option key={b} value={b} />)}
                    </datalist>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Floor</label>
                    <input name="floor" value={form.floor} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="e.g., Ground Floor" />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      <span className="flex items-center gap-1.5">
                        <Radio className="h-4 w-4 text-green-500" />
                        RTSP Stream URL
                      </span>
                    </label>
                    <input name="stream_url" value={form.stream_url} onChange={handleChange}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white font-mono text-sm"
                      placeholder="rtsp://username:password@10.162.1.182:554/h264" />
                    <p className="text-xs text-muted-foreground mt-1">
                      Enter the full RTSP URL including credentials. Used for live stream processing and video analysis.
                    </p>
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                    <textarea name="description" value={form.description} onChange={handleChange} rows={3}
                      className="w-full px-3 py-2 border rounded-lg bg-white dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-white"
                      placeholder="Additional details about this camera..." />
                  </div>
                  <label className="md:col-span-2 flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
                    <input
                      type="checkbox"
                      checked={form.person_reidentification_enabled}
                      onChange={e => setForm(prev => ({ ...prev, person_reidentification_enabled: e.target.checked }))}
                      className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>
                      <span className="flex items-center gap-2 text-sm font-medium text-blue-950 dark:text-blue-100">
                        <ScanLine className="h-4 w-4" /> Enable cross-camera person tracking
                      </span>
                      <span className="mt-1 block text-xs text-blue-800 dark:text-blue-200">
                        Match recent appearances from this camera with other enabled live cameras and send a dedicated tracking notification.
                      </span>
                    </span>
                  </label>
                </div>
                <div className="flex justify-end gap-3">
                  <Link href="/dashboard/cameras">
                    <Button variant="outline">Cancel</Button>
                  </Link>
                  <Button type="submit" disabled={saving} className="bg-blue-600 hover:bg-blue-700 text-white">
                    {saving ? <LoadingSpinner size="sm" /> : <Save className="h-4 w-4 mr-2" />}
                    {saving ? 'Saving...' : 'Add Camera'}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Radio className="h-4 w-4" />
                RTSP URL Templates
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-xs text-muted-foreground mb-3">
                Click a template to auto-fill the stream URL. Replace {'{user}'}, {'{pass}'}, and {'{ip}'} with your camera credentials.
              </p>
              {RTSP_TEMPLATES.map(t => (
                <button
                  key={t.brand}
                  type="button"
                  onClick={() => applyTemplate(t.template)}
                  className="w-full text-left p-2 rounded-md border hover:bg-muted/50 transition-colors"
                >
                  <p className="text-sm font-medium">{t.brand}</p>
                  <p className="text-xs text-muted-foreground font-mono truncate">{t.template}</p>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Info className="h-4 w-4" />
                Tips
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="text-xs text-muted-foreground space-y-2">
                <li>The IP address is auto-extracted from the RTSP URL when you enter it.</li>
                <li>Location and building fields have auto-suggestions for IITB campus locations.</li>
                <li>RTSP streams can be used for live face detection from the Video Analysis section.</li>
                <li>Cross-camera person tracking is enabled by default and starts when this camera's RTSP stream is running.</li>
                <li>When deployed on-campus, RTSP connections to cameras on the local network will work for real-time monitoring.</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function LoadingSpinner({ size }: { size: string }) {
  return <div className={`animate-spin rounded-full border-2 border-gray-300 border-t-blue-600 ${size === 'sm' ? 'h-4 w-4' : 'h-8 w-8'}`} />
}
