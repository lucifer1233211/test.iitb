'use client'

import { useState, useRef, useCallback, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, Upload, ScanFace, UserCheck, AlertTriangle, Camera, Search, Video, VideoOff, Circle, Pause, Play } from 'lucide-react'
import Link from 'next/link'

interface DetectedFace {
  bbox: { x: number; y: number; width: number; height: number }
  confidence: number
  quality_score?: number
  is_spoofing_detected?: boolean
  person_id?: string | null
  person_name?: string | null
  match_confidence?: number
  identified?: boolean
}

interface DetectResponse {
  detected_faces: DetectedFace[]
  face_count: number
  processing_time: number
  image_size?: { width: number; height: number }
  error?: string
}

interface IdentifyResponse {
  detected_faces: DetectedFace[]
  processing_time: number
  error?: string
}

type TabMode = 'upload' | 'webcam'

export default function TestFaceRecognitionPage() {
  const [tabMode, setTabMode] = useState<TabMode>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTest, setActiveTest] = useState<'detect' | 'identify' | null>(null)
  const [detectResult, setDetectResult] = useState<DetectResponse | null>(null)
  const [identifyResult, setIdentifyResult] = useState<IdentifyResponse | null>(null)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const [webcamActive, setWebcamActive] = useState(false)
  const [liveRunning, setLiveRunning] = useState(false)
  const [webcamError, setWebcamError] = useState('')
  const [fps, setFps] = useState(0)
  const [frameCount, setFrameCount] = useState(0)
  const [lastLiveResult, setLastLiveResult] = useState<DetectedFace[]>([])
  const [liveProcessingTime, setLiveProcessingTime] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const animFrameRef = useRef<number>(0)
  const liveIntervalRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const processingRef = useRef(false)
  const liveRunningRef = useRef(false)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (selected) {
      setFile(selected)
      setPreview(URL.createObjectURL(selected))
      setDetectResult(null)
      setIdentifyResult(null)
      setError('')
    }
  }

  const handleDetect = async () => {
    if (!file) { setError('Please select an image first'); return }
    setLoading(true)
    setActiveTest('detect')
    setError('')
    setDetectResult(null)
    try {
      const { api } = await import('@/lib/api/client')
      const formData = new FormData()
      formData.append('image', file)
      const res = await api.post('/face/detect', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setDetectResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Face detection failed')
    } finally {
      setLoading(false)
    }
  }

  const handleIdentify = async () => {
    if (!file) { setError('Please select an image first'); return }
    setLoading(true)
    setActiveTest('identify')
    setError('')
    setIdentifyResult(null)
    try {
      const { api } = await import('@/lib/api/client')
      const formData = new FormData()
      formData.append('image', file)
      formData.append('threshold', '0.35')
      const res = await api.post('/face/identify', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setIdentifyResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Face identification failed')
    } finally {
      setLoading(false)
    }
  }

  const isInIframe = typeof window !== 'undefined' && window.self !== window.top

  const openInNewTab = () => {
    window.open(window.location.href, '_blank')
  }

  const startWebcam = async () => {
    setWebcamError('')
    if (typeof navigator === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setWebcamError('Camera API is not available. This may be because the page is running inside an iframe. Click "Open in New Tab" below to use the webcam.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setWebcamActive(true)
    } catch (err: any) {
      if (err.name === 'NotAllowedError' || err.name === 'SecurityError') {
        setWebcamError('Camera access was blocked. If you\'re viewing this in a preview pane, click "Open in New Tab" below — camera permissions only work when the page is opened directly in your browser.')
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        setWebcamError('No camera found. Please connect a webcam and try again.')
      } else if (err.name === 'NotReadableError') {
        setWebcamError('Camera is in use by another application. Please close other apps using the camera and try again.')
      } else {
        setWebcamError(`Camera error: ${err.message}. Try opening this page in a new browser tab.`)
      }
    }
  }

  const stopWebcam = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    if (liveIntervalRef.current) {
      clearTimeout(liveIntervalRef.current)
      liveIntervalRef.current = null
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current)
    }
    liveRunningRef.current = false
    setWebcamActive(false)
    setLiveRunning(false)
    setLastLiveResult([])
    setFrameCount(0)
    setFps(0)
  }, [])

  const captureFrame = useCallback((): Blob | null => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || video.readyState < 2) return null
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const byteString = atob(dataUrl.split(',')[1])
    const ab = new ArrayBuffer(byteString.length)
    const ia = new Uint8Array(ab)
    for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i)
    return new Blob([ab], { type: 'image/jpeg' })
  }, [])

  const drawOverlay = useCallback((faces: DetectedFace[]) => {
    const video = videoRef.current
    const overlay = overlayCanvasRef.current
    if (!video || !overlay) return
    overlay.width = video.videoWidth
    overlay.height = video.videoHeight
    const ctx = overlay.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, overlay.width, overlay.height)

    faces.forEach(face => {
      const { x, y, width, height } = face.bbox
      const isIdentified = face.identified && face.person_name
      ctx.strokeStyle = isIdentified ? '#22c55e' : '#ef4444'
      ctx.lineWidth = 3
      ctx.strokeRect(x, y, width, height)

      const corners = 15
      ctx.lineWidth = 4
      ctx.beginPath()
      ctx.moveTo(x, y + corners); ctx.lineTo(x, y); ctx.lineTo(x + corners, y)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(x + width - corners, y); ctx.lineTo(x + width, y); ctx.lineTo(x + width, y + corners)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(x, y + height - corners); ctx.lineTo(x, y + height); ctx.lineTo(x + corners, y + height)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(x + width - corners, y + height); ctx.lineTo(x + width, y + height); ctx.lineTo(x + width, y + height - corners)
      ctx.stroke()

      const label = isIdentified
        ? `${face.person_name} (${((face.match_confidence || 0) * 100).toFixed(0)}%)`
        : `Unknown (${(face.confidence * 100).toFixed(0)}%)`
      ctx.font = 'bold 14px sans-serif'
      const textWidth = ctx.measureText(label).width
      ctx.fillStyle = isIdentified ? 'rgba(34,197,94,0.85)' : 'rgba(239,68,68,0.85)'
      ctx.fillRect(x, y - 24, textWidth + 12, 24)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(label, x + 6, y - 7)
    })
  }, [])

  const processLiveFrame = useCallback(async () => {
    if (processingRef.current || !liveRunningRef.current) return
    processingRef.current = true
    const startTime = performance.now()
    try {
      const blob = captureFrame()
      if (!blob) { processingRef.current = false; return }
      const { api } = await import('@/lib/api/client')
      const formData = new FormData()
      formData.append('image', blob, 'webcam_frame.jpg')
      formData.append('threshold', '0.35')
      const res = await api.post('/face/identify', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      const elapsed = performance.now() - startTime
      const faces: DetectedFace[] = res.data.detected_faces || []
      setLastLiveResult(faces)
      setLiveProcessingTime(Math.round(elapsed))
      setFrameCount(prev => prev + 1)
      setFps(Math.round(1000 / elapsed))
      drawOverlay(faces)
    } catch (err: any) {
      console.error('Live frame error:', err)
    } finally {
      processingRef.current = false
      if (liveRunningRef.current) {
        liveIntervalRef.current = setTimeout(processLiveFrame, 200)
      }
    }
  }, [captureFrame, drawOverlay])

  const startLiveRecognition = useCallback(() => {
    if (!webcamActive) return
    liveRunningRef.current = true
    setLiveRunning(true)
    setLastLiveResult([])
    setFrameCount(0)
    processLiveFrame()
  }, [webcamActive, processLiveFrame])

  const stopLiveRecognition = useCallback(() => {
    liveRunningRef.current = false
    setLiveRunning(false)
    if (liveIntervalRef.current) {
      clearTimeout(liveIntervalRef.current)
      liveIntervalRef.current = null
    }
    const overlay = overlayCanvasRef.current
    if (overlay) {
      const ctx = overlay.getContext('2d')
      ctx?.clearRect(0, 0, overlay.width, overlay.height)
    }
  }, [])

  const captureSnapshot = useCallback(async () => {
    const blob = captureFrame()
    if (!blob) return
    setLoading(true)
    setError('')
    try {
      const { api } = await import('@/lib/api/client')
      const formData = new FormData()
      formData.append('image', blob, 'webcam_snapshot.jpg')
      formData.append('threshold', '0.35')
      const res = await api.post('/face/identify', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setIdentifyResult(res.data)
      setDetectResult(null)
      setActiveTest('identify')
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Snapshot identification failed')
    } finally {
      setLoading(false)
    }
  }, [captureFrame])

  useEffect(() => {
    return () => {
      stopWebcam()
    }
  }, [stopWebcam])

  const identifiedFaces = (identifyResult?.detected_faces || []).filter(f => f.identified)
  const unidentifiedFaces = (identifyResult?.detected_faces || []).filter(f => !f.identified)
  const liveIdentified = lastLiveResult.filter(f => f.identified)
  const liveUnidentified = lastLiveResult.filter(f => !f.identified)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/dashboard/face-recognition/persons">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" /> Back
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Test Face Recognition</h1>
          <p className="text-gray-500 dark:text-gray-400">Upload a photo or use your webcam to test face detection &amp; identification</p>
        </div>
      </div>

      <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
        <button
          onClick={() => { setTabMode('upload'); stopLiveRecognition() }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tabMode === 'upload'
              ? 'border-blue-500 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
          }`}
        >
          <Upload className="h-4 w-4 inline-block mr-2" />
          Upload Image
        </button>
        <button
          onClick={() => { setTabMode('webcam') }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tabMode === 'webcam'
              ? 'border-blue-500 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
          }`}
        >
          <Video className="h-4 w-4 inline-block mr-2" />
          Live Webcam
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <div className="flex items-center gap-2 text-red-700 dark:text-red-300">
            <AlertTriangle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {tabMode === 'upload' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Camera className="h-5 w-5 text-blue-500" /> Upload Image
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div
                className="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition-colors min-h-[280px] flex items-center justify-center"
                onClick={() => fileRef.current?.click()}
              >
                {preview ? (
                  <img src={preview} alt="Preview" className="max-h-64 mx-auto rounded-lg" />
                ) : (
                  <div>
                    <Upload className="h-12 w-12 mx-auto text-gray-400 mb-4" />
                    <p className="text-gray-600 dark:text-gray-400 font-medium">Click to upload a face photo</p>
                    <p className="text-sm text-gray-400 mt-1">JPG, PNG — clear front-facing photo works best</p>
                  </div>
                )}
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
              </div>
              {file && (
                <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
                  Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
                </p>
              )}
              <div className="grid grid-cols-2 gap-3 mt-4">
                <Button onClick={handleDetect} disabled={!file || loading} className="bg-blue-600 hover:bg-blue-700 text-white">
                  {loading && activeTest === 'detect' ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2" />
                  ) : (
                    <ScanFace className="h-4 w-4 mr-2" />
                  )}
                  Detect Faces
                </Button>
                <Button onClick={handleIdentify} disabled={!file || loading} className="bg-green-600 hover:bg-green-700 text-white">
                  {loading && activeTest === 'identify' ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2" />
                  ) : (
                    <Search className="h-4 w-4 mr-2" />
                  )}
                  Identify Person
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserCheck className="h-5 w-5 text-green-500" /> Results
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!detectResult && !identifyResult && !loading && (
                <div className="text-center py-12 text-gray-400">
                  <ScanFace className="h-16 w-16 mx-auto mb-4 opacity-30" />
                  <p className="text-lg font-medium">No results yet</p>
                  <p className="text-sm mt-1">Upload a photo and click Detect or Identify</p>
                </div>
              )}
              {loading && (
                <div className="text-center py-12">
                  <div className="animate-spin rounded-full h-12 w-12 border-4 border-gray-200 border-t-blue-500 mx-auto mb-4" />
                  <p className="text-gray-600 dark:text-gray-400">
                    {activeTest === 'detect' ? 'Detecting faces...' : 'Identifying person...'}
                  </p>
                </div>
              )}
              {detectResult && !loading && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <Badge variant="success" className="text-sm px-3 py-1">Detection Complete</Badge>
                    <span className="text-xs text-gray-400">{detectResult.processing_time}ms</span>
                  </div>
                  <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
                    <p className="font-semibold text-gray-900 dark:text-white">{detectResult.face_count} face(s) detected</p>
                    {detectResult.image_size && (
                      <p className="text-xs text-gray-500 mt-1">Image: {detectResult.image_size.width} x {detectResult.image_size.height}px</p>
                    )}
                    {detectResult.detected_faces.map((face, i) => (
                      <div key={i} className="mt-3 p-3 bg-white dark:bg-gray-800 rounded-lg border">
                        <p className="text-sm font-medium text-gray-900 dark:text-white">Face #{i + 1}</p>
                        <div className="grid grid-cols-2 gap-2 mt-2 text-sm text-gray-600 dark:text-gray-400">
                          <div>Confidence: <span className="font-mono text-green-600">{(face.confidence * 100).toFixed(1)}%</span></div>
                          <div>Quality: <span className="font-mono text-blue-600">{((face.quality_score || 0) * 100).toFixed(1)}%</span></div>
                          <div>Position: ({face.bbox.x}, {face.bbox.y})</div>
                          <div>Size: {face.bbox.width} x {face.bbox.height}</div>
                        </div>
                        {face.person_name && (
                          <div className="mt-2 p-2 bg-green-50 dark:bg-green-900/20 rounded text-sm">
                            Matched: <span className="font-semibold">{face.person_name}</span>
                            {face.match_confidence !== undefined && (
                              <span className="ml-2 text-green-600">({(face.match_confidence * 100).toFixed(1)}%)</span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {identifyResult && !loading && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <Badge variant="success" className="text-sm px-3 py-1">Identification Complete</Badge>
                    <span className="text-xs text-gray-400">{identifyResult.processing_time}ms</span>
                  </div>
                  {identifiedFaces.length > 0 ? (
                    <div className="space-y-3">
                      {identifiedFaces.map((face, i) => (
                        <div key={i} className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4 border border-green-200 dark:border-green-800">
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="font-semibold text-gray-900 dark:text-white text-lg">{face.person_name}</p>
                              {face.person_id && <p className="text-xs text-gray-500 font-mono mt-1">ID: {face.person_id}</p>}
                            </div>
                            <div className="text-right">
                              <p className="text-2xl font-bold text-green-600">{((face.match_confidence || 0) * 100).toFixed(1)}%</p>
                              <p className="text-xs text-gray-500">match confidence</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-4 border border-yellow-200 dark:border-yellow-800">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="h-5 w-5 text-yellow-600" />
                        <p className="font-medium text-yellow-800 dark:text-yellow-200">
                          {(identifyResult.detected_faces || []).length > 0 ? 'Face detected but no match found' : 'No faces detected in the image'}
                        </p>
                      </div>
                      <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">
                        {(identifyResult.detected_faces || []).length > 0
                          ? 'This person is not enrolled. Enroll them first, then try again.'
                          : 'Try a clearer photo with a visible face.'}
                      </p>
                    </div>
                  )}
                  {unidentifiedFaces.length > 0 && identifiedFaces.length > 0 && (
                    <div className="text-sm text-gray-500">+ {unidentifiedFaces.length} unidentified face(s)</div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {tabMode === 'webcam' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Video className="h-5 w-5 text-blue-500" />
                    Live Webcam Feed
                  </div>
                  <div className="flex items-center gap-2">
                    {webcamActive && liveRunning && (
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <Circle className="h-3 w-3 text-red-500 fill-red-500 animate-pulse" />
                        <span>{fps} FPS</span>
                        <span>|</span>
                        <span>{liveProcessingTime}ms</span>
                        <span>|</span>
                        <span>{frameCount} frames</span>
                      </div>
                    )}
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {isInIframe && !webcamActive && (
                  <div className="p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg mb-4">
                    <div className="flex items-center gap-2 text-blue-700 dark:text-blue-300 mb-2">
                      <AlertTriangle className="h-5 w-5" />
                      <span className="font-medium">Camera requires a direct browser tab</span>
                    </div>
                    <p className="text-sm text-blue-600 dark:text-blue-400 mb-3">
                      Camera access is restricted in preview panes. Open this page directly in your browser to use the webcam.
                    </p>
                    <Button onClick={openInNewTab} className="bg-blue-600 hover:bg-blue-700 text-white">
                      <Camera className="h-4 w-4 mr-2" />
                      Open in New Browser Tab
                    </Button>
                  </div>
                )}

                {webcamError && (
                  <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg mb-4">
                    <div className="flex items-center gap-2 text-red-700 dark:text-red-300 mb-2">
                      <AlertTriangle className="h-5 w-5" />
                      <span>{webcamError}</span>
                    </div>
                    <Button onClick={openInNewTab} variant="outline" size="sm" className="mt-1">
                      <Camera className="h-4 w-4 mr-2" />
                      Open in New Tab
                    </Button>
                  </div>
                )}

                <div className="relative bg-black rounded-lg overflow-hidden" style={{ minHeight: 360 }}>
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="w-full rounded-lg"
                    style={{ display: webcamActive ? 'block' : 'none', transform: 'scaleX(-1)' }}
                  />
                  <canvas
                    ref={overlayCanvasRef}
                    className="absolute top-0 left-0 w-full h-full pointer-events-none"
                    style={{ display: webcamActive ? 'block' : 'none', transform: 'scaleX(-1)' }}
                  />
                  <canvas ref={canvasRef} className="hidden" />

                  {!webcamActive && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                      <VideoOff className="h-16 w-16 mb-4 opacity-40" />
                      <p className="text-lg font-medium">Camera is off</p>
                      <p className="text-sm mt-1 mb-4">Click below to start your webcam</p>
                      <Button onClick={startWebcam} className="bg-blue-600 hover:bg-blue-700 text-white">
                        <Camera className="h-4 w-4 mr-2" />
                        Start Camera
                      </Button>
                    </div>
                  )}
                </div>

                {webcamActive && (
                  <div className="flex gap-3 mt-4">
                    {!liveRunning ? (
                      <Button onClick={startLiveRecognition} className="bg-green-600 hover:bg-green-700 text-white flex-1">
                        <Play className="h-4 w-4 mr-2" />
                        Start Live Recognition
                      </Button>
                    ) : (
                      <Button onClick={stopLiveRecognition} className="bg-yellow-600 hover:bg-yellow-700 text-white flex-1">
                        <Pause className="h-4 w-4 mr-2" />
                        Pause Recognition
                      </Button>
                    )}
                    <Button onClick={captureSnapshot} disabled={loading} className="bg-blue-600 hover:bg-blue-700 text-white">
                      <Camera className="h-4 w-4 mr-2" />
                      Snapshot
                    </Button>
                    <Button onClick={stopWebcam} variant="outline" className="text-red-600 border-red-300 hover:bg-red-50">
                      <VideoOff className="h-4 w-4 mr-2" />
                      Stop
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ScanFace className="h-5 w-5 text-green-500" />
                  Live Results
                </CardTitle>
              </CardHeader>
              <CardContent>
                {!webcamActive && !liveRunning && lastLiveResult.length === 0 && (
                  <div className="text-center py-8 text-gray-400">
                    <ScanFace className="h-12 w-12 mx-auto mb-3 opacity-30" />
                    <p className="text-sm font-medium">Start camera and live recognition</p>
                    <p className="text-xs mt-1">Real-time face detection and identification</p>
                  </div>
                )}

                {webcamActive && liveRunning && lastLiveResult.length === 0 && (
                  <div className="text-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-4 border-gray-200 border-t-blue-500 mx-auto mb-3" />
                    <p className="text-sm text-gray-500">Scanning for faces...</p>
                  </div>
                )}

                {lastLiveResult.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs text-gray-500">
                      <span>{lastLiveResult.length} face(s)</span>
                      <span>{liveProcessingTime}ms</span>
                    </div>

                    {liveIdentified.map((face, i) => (
                      <div key={`id-${i}`} className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 border border-green-200 dark:border-green-800">
                        <div className="flex items-center justify-between">
                          <p className="font-semibold text-gray-900 dark:text-white">{face.person_name}</p>
                          <p className="text-lg font-bold text-green-600">{((face.match_confidence || 0) * 100).toFixed(0)}%</p>
                        </div>
                        <div className="flex gap-3 mt-1 text-xs text-gray-500">
                          <span>Detection: {(face.confidence * 100).toFixed(0)}%</span>
                          <span>Quality: {((face.quality_score || 0) * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                    ))}

                    {liveUnidentified.map((face, i) => (
                      <div key={`un-${i}`} className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3 border border-red-200 dark:border-red-800">
                        <div className="flex items-center justify-between">
                          <p className="font-medium text-red-800 dark:text-red-200">Unknown Person</p>
                          <p className="text-sm font-mono text-red-600">{(face.confidence * 100).toFixed(0)}%</p>
                        </div>
                        <p className="text-xs text-red-600 dark:text-red-400 mt-1">Not enrolled in the system</p>
                      </div>
                    ))}
                  </div>
                )}

                {identifyResult && !liveRunning && (
                  <div className="mt-4 pt-4 border-t">
                    <p className="text-xs font-medium text-gray-500 mb-2">Snapshot Result</p>
                    {identifiedFaces.length > 0 ? (
                      identifiedFaces.map((face, i) => (
                        <div key={i} className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 border border-green-200 dark:border-green-800 mb-2">
                          <div className="flex items-center justify-between">
                            <p className="font-semibold text-gray-900 dark:text-white">{face.person_name}</p>
                            <p className="text-lg font-bold text-green-600">{((face.match_confidence || 0) * 100).toFixed(0)}%</p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-3 border border-yellow-200 dark:border-yellow-800">
                        <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                          {(identifyResult.detected_faces || []).length > 0 ? 'No match found' : 'No faces detected'}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-4">
                <h4 className="font-medium text-gray-900 dark:text-white text-sm mb-2">How to test</h4>
                <ol className="text-xs text-gray-500 dark:text-gray-400 space-y-1.5 list-decimal list-inside">
                  <li>First <Link href="/dashboard/face-recognition/enroll" className="text-blue-500 underline">enroll your face</Link> with a clear photo</li>
                  <li>Click &quot;Start Camera&quot; and allow permissions</li>
                  <li>Click &quot;Start Live Recognition&quot;</li>
                  <li>Face the camera — green box = identified, red = unknown</li>
                  <li>Use &quot;Snapshot&quot; to capture and analyze a single frame</li>
                </ol>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      <Card>
        <CardContent className="pt-6">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-3">How to test face recognition</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
              <div className="font-medium text-blue-800 dark:text-blue-200 mb-1">1. Enroll a Person</div>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                Go to <Link href="/dashboard/face-recognition/enroll" className="underline">Enroll</Link> and upload clear photos of a person with their name.
              </p>
            </div>
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
              <div className="font-medium text-green-800 dark:text-green-200 mb-1">2. Test with Webcam</div>
              <p className="text-sm text-green-700 dark:text-green-300">
                Switch to the Live Webcam tab and start your camera for real-time recognition.
              </p>
            </div>
            <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-4">
              <div className="font-medium text-purple-800 dark:text-purple-200 mb-1">3. View Results</div>
              <p className="text-sm text-purple-700 dark:text-purple-300">
                Green boxes show identified faces with names. Red boxes show unknown persons.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
