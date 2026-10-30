'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, Radio, Play, Square, Plus, Trash2, AlertTriangle, Eye, RefreshCw } from 'lucide-react'
import Link from 'next/link'

interface ActiveStream {
  stream_id: string
  rtsp_url: string
  started_at: string
  frames_read: number
  detections_count: number
  object_detections_count: number
  active_faces: number
  active_objects: number
}

export default function RTSPStreamsPage() {
  const [rtspUrl, setRtspUrl] = useState('')
  const [streamId, setStreamId] = useState('')
  const [frameInterval, setFrameInterval] = useState(5)
  const [detectionMode, setDetectionMode] = useState<'face' | 'object' | 'both'>('both')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeStreams, setActiveStreams] = useState<ActiveStream[]>([])
  const [viewingStream, setViewingStream] = useState<string | null>(null)
  const [currentFrame, setCurrentFrame] = useState<string | null>(null)
  const [fps, setFps] = useState(0)
  const [streamStats, setStreamStats] = useState<any>(null)
  const pollingRef = useRef<boolean>(false)
  const frameCountRef = useRef(0)
  const fpsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchActiveStreams = async () => {
    try {
      const { api } = await import('@/lib/api/client')
      const res = await api.get('/video/rtsp/active')
      setActiveStreams(res.data.streams || [])
    } catch {
    }
  }

  useEffect(() => {
    fetchActiveStreams()
    const interval = setInterval(fetchActiveStreams, 5000)
    return () => clearInterval(interval)
  }, [])

  const pollFrames = useCallback(async (sid: string) => {
    pollingRef.current = true
    frameCountRef.current = 0

    fpsIntervalRef.current = setInterval(() => {
      setFps(frameCountRef.current)
      frameCountRef.current = 0
    }, 1000)

    while (pollingRef.current) {
      try {
        const { api } = await import('@/lib/api/client')
        const res = await api.get(`/video/rtsp/${sid}/snapshot`)
        if (!pollingRef.current) break
        setCurrentFrame(res.data.image)
        setStreamStats({
          frames_read: res.data.frames_read,
          detections_count: res.data.detections_count,
          active_faces: res.data.active_faces,
          objects: res.data.objects || [],
        })
        frameCountRef.current++
      } catch (err: any) {
        if (!pollingRef.current) break
        if (err?.response?.status === 504) {
          await new Promise(r => setTimeout(r, 200))
          continue
        }
        if (err?.response?.status === 404) {
          pollingRef.current = false
          setViewingStream(null)
          setCurrentFrame(null)
          break
        }
        await new Promise(r => setTimeout(r, 500))
      }
      await new Promise(r => setTimeout(r, 50))
    }
  }, [])

  const stopPolling = useCallback(() => {
    pollingRef.current = false
    if (fpsIntervalRef.current) {
      clearInterval(fpsIntervalRef.current)
      fpsIntervalRef.current = null
    }
    setFps(0)
    setCurrentFrame(null)
    setStreamStats(null)
  }, [])

  useEffect(() => {
    if (viewingStream) {
      pollFrames(viewingStream)
    } else {
      stopPolling()
    }
    return () => stopPolling()
  }, [viewingStream, pollFrames, stopPolling])

  const handleStartStream = async () => {
    if (!rtspUrl) { setError('Please enter an RTSP URL'); return }
    setLoading(true)
    setError('')
    try {
      const { api } = await import('@/lib/api/client')
      const res = await api.post('/video/rtsp/start', {
        rtsp_url: rtspUrl,
        stream_id: streamId || undefined,
        frame_interval: frameInterval,
        detection_mode: detectionMode,
      })
      setRtspUrl('')
      setStreamId('')
      await fetchActiveStreams()
      setViewingStream(res.data.stream_id)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to start RTSP stream')
    } finally {
      setLoading(false)
    }
  }

  const handleStopStream = async (sid: string) => {
    // 1. CLEAR LOGIC IMMEDIATELY: Stop polling fo r snapshots and clear the stream container
    if (viewingStream === sid) {
      stopPolling();       // 🔥 Stop the snapshot requests instantly!
      setViewingStream(null);
    }
  
    try {
      const { api } = await import('@/lib/api/client');
      
      // 2. Fire and forget with a low timeout. We don't care if it takes 30s to clean up resources, 
      // we want the UI to move on.
      await api.post(`/video/rtsp/${sid}/stop`, {}, { timeout: 2000 });
    } catch (err: any) {
      console.warn("Stop request timed out or was abgebrochen, cleaning up UI anyway.");
    } finally {
      // 3. Re-sync active streams cleanly
      try {
        await fetchActiveStreams();
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleChangeMode = async (mode: string) => {
    if (!viewingStream) return
    try {
      const { api } = await import('@/lib/api/client')
      await api.post(`/video/rtsp/${viewingStream}/mode`, { mode })
    } catch (e) {
      console.error('[RTSP] mode change failed', e)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/dashboard/video-analysis">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">RTSP Stream Analysis</h1>
          <p className="text-muted-foreground">
            Connect to live RTSP camera feeds for real-time face detection and identification
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plus className="h-5 w-5" />
                Connect RTSP Stream
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium">RTSP URL</label>
                <input
                  type="text"
                  value={rtspUrl}
                  onChange={(e) => setRtspUrl(e.target.value)}
                  placeholder="rtsp://camera-ip:554/stream"
                  className="w-full border rounded-md p-2 text-sm bg-background mt-1"
                />
              </div>

              <div>
                <label className="text-sm font-medium">Stream ID (optional)</label>
                <input
                  type="text"
                  value={streamId}
                  onChange={(e) => setStreamId(e.target.value)}
                  placeholder="main-gate-cam"
                  className="w-full border rounded-md p-2 text-sm bg-background mt-1"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  A friendly name for this stream
                </p>
              </div>

              <div>
                <label className="text-sm font-medium">Frame Interval</label>
                <select
                  value={frameInterval}
                  onChange={(e) => setFrameInterval(Number(e.target.value))}
                  className="w-full border rounded-md p-2 text-sm bg-background mt-1"
                >
                  <option value={3}>Every 3rd frame (high accuracy)</option>
                  <option value={5}>Every 5th frame (recommended)</option>
                  <option value={10}>Every 10th frame (low CPU)</option>
                  <option value={15}>Every 15th frame (minimal)</option>
                </select>
              </div>

              <div>
                <label className="text-sm font-medium">Detection Mode</label>
                <select
                  value={detectionMode}
                  onChange={(e) => setDetectionMode(e.target.value as any)}
                  className="w-full border rounded-md p-2 text-sm bg-background mt-1"
                >
                  <option value="face">Face Recognition Only</option>
                  <option value="object">Object Detection Only</option>
                  <option value="both">Face + Object (Both)</option>
                </select>
              </div>

              <Button
                onClick={handleStartStream}
                disabled={!rtspUrl || loading}
                className="w-full"
              >
                {loading ? (
                  <>
                    <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Start Stream
                  </>
                )}
              </Button>

              {error && (
                <div className="bg-destructive/10 text-destructive text-sm rounded-md p-3 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  {error}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <Radio className="h-5 w-5" />
                  Active Streams
                </span>
                <Button variant="ghost" size="sm" onClick={fetchActiveStreams}>
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {activeStreams.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No active streams
                </p>
              ) : (
                <div className="space-y-3">
                  {activeStreams.map(stream => (
                    <div
                      key={stream.stream_id}
                      className="p-3 border rounded-lg space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                          <span className="font-medium text-sm truncate max-w-[150px]">
                            {stream.stream_id}
                          </span>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setViewingStream(stream.stream_id)}
                            className="h-7 w-7 p-0"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleStopStream(stream.stream_id)}
                            className="h-7 w-7 p-0 text-destructive"
                          >
                            <Square className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      <div className="grid grid-cols-4 gap-2 text-xs">
                        <div>
                          <p className="text-muted-foreground">Frames</p>
                          <p className="font-medium">{stream.frames_read}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Detections</p>
                          <p className="font-medium">{stream.detections_count}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Faces</p>
                          <p className="font-medium">{stream.active_faces}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Objects</p>
                          <p className="font-medium">{stream.active_objects}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Common RTSP URLs</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="text-xs space-y-1.5 text-muted-foreground">
                <p><span className="font-medium text-foreground">Hikvision:</span> rtsp://user:pass@ip:554/Streaming/Channels/101</p>
                <p><span className="font-medium text-foreground">Dahua:</span> rtsp://user:pass@ip:554/cam/realmonitor?channel=1</p>
                <p><span className="font-medium text-foreground">Generic:</span> rtsp://ip:554/stream</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          {viewingStream ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                    Live Stream: {viewingStream}
                  </span>
                  <div className="flex items-center gap-3">
                    <select
                      value={detectionMode}
                      onChange={(e) => {
                        setDetectionMode(e.target.value as any)
                        handleChangeMode(e.target.value)
                      }}
                      className="text-xs border rounded-md px-2 py-1 bg-background"
                    >
                      <option value="face">Face</option>
                      <option value="object">Object</option>
                      <option value="both">Both</option>
                    </select>
                    <Badge variant="outline" className="font-mono text-xs">
                      {fps} FPS
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleStopStream(viewingStream)}
                    >
                      <Square className="h-4 w-4 mr-2" />
                      Stop
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="bg-black rounded-lg overflow-hidden aspect-video relative">
                  {currentFrame ? (
                    <img
                      src={currentFrame}
                      alt="Live RTSP stream with face detection"
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <div className="text-center text-white/60">
                        <div className="h-8 w-8 border-2 border-white/40 border-t-white rounded-full animate-spin mx-auto mb-3" />
                        <p className="text-sm">Waiting for frames...</p>
                      </div>
                    </div>
                  )}
                </div>
                {streamStats && (
                  <div className="grid grid-cols-4 gap-4 mt-3">
                    <div className="text-center p-2 bg-muted/50 rounded">
                      <p className="text-xs text-muted-foreground">Total Frames</p>
                      <p className="font-bold text-sm">{streamStats.frames_read}</p>
                    </div>
                    <div className="text-center p-2 bg-muted/50 rounded">
                      <p className="text-xs text-muted-foreground">Total Detections</p>
                      <p className="font-bold text-sm">{streamStats.detections_count}</p>
                    </div>
                    <div className="text-center p-2 bg-muted/50 rounded">
                      <p className="text-xs text-muted-foreground">Active Faces</p>
                      <p className="font-bold text-sm text-green-600">{streamStats.active_faces}</p>
                    </div>
                    <div className="text-center p-2 bg-muted/50 rounded">
                      <p className="text-xs text-muted-foreground">Objects Detected</p>
                      <p className="font-bold text-sm text-orange-600">{(streamStats.objects || []).length}</p>
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground mt-2">
                  Server-side face and object detection with bounding boxes and labels overlaid on the RTSP stream
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-16 text-center">
                <Radio className="h-16 w-16 mx-auto text-muted-foreground/30 mb-4" />
                <h3 className="text-lg font-medium mb-2">Connect an RTSP Stream</h3>
                <p className="text-sm text-muted-foreground max-w-md mx-auto mb-6">
                  Enter the RTSP URL of a campus CCTV camera to start real-time face detection
                  and identification. The server processes the stream and sends annotated frames
                  with bounding boxes and identity labels.
                </p>
                <div className="bg-muted/50 rounded-lg p-4 max-w-lg mx-auto">
                  <h4 className="font-medium text-sm mb-2">How it works:</h4>
                  <ol className="text-xs text-muted-foreground text-left space-y-1.5">
                    <li>1. Backend connects to the RTSP camera feed via OpenCV + FFmpeg</li>
                    <li>2. Frames are extracted and processed through the face detection pipeline</li>
                    <li>3. Detected faces are matched against enrolled persons using embedding similarity</li>
                    <li>4. Annotated frames (with bounding boxes and labels) are polled by the browser</li>
                  </ol>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
