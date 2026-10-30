'use client'

import { useEffect, useRef, useState } from 'react'

interface CameraFeedProps {
  cameraName: string
  location: string
  streamUrl?: string
  resolution?: string
  cameraType?: string
  isActive?: boolean
  className?: string
  showOverlay?: boolean
  detectionMode?: 'face' | 'object' | 'both'
  onModeChange?: (mode: 'face' | 'object' | 'both') => void
  showModeToggle?: boolean
}

interface FaceDetection {
  bbox?: { x: number; y: number; width: number; height: number }
  bounding_box?: { x: number; y: number; width: number; height: number }
  x?: number; y?: number; width?: number; height?: number
  name?: string
  person_name?: string
  person_id?: string
  confidence?: number
  identified?: boolean
}

interface ObjectDetection {
  bbox?: { x: number; y: number; width: number; height: number }
  x?: number; y?: number; width?: number; height?: number
  label?: string
  confidence?: number
}

function FaceOverlay({ faces, imgWidth, imgHeight }: { faces: FaceDetection[]; imgWidth: number; imgHeight: number }) {
  if (!faces || faces.length === 0) return null
  return (
    <svg
      style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 20, pointerEvents: 'none' }}
      viewBox={`0 0 ${imgWidth} ${imgHeight}`}
      preserveAspectRatio="none"
    >
      {faces.map((face, i) => {
        const bb = face.bbox || face.bounding_box || {
          x: face.x || 0, y: face.y || 0,
          width: face.width || 0, height: face.height || 0
        }
        if (!bb.width || !bb.height) return null
        const identified = face.identified === true || !!face.person_name
        const name = identified ? (face.person_name || 'Identified') : 'Unknown'
        const color = identified ? '#22c55e' : '#ef4444'
        const labelText = name 
        const labelW = Math.min(labelText.length * 8 + 16, 280)
        const labelY = Math.max(0, bb.y - 26)
        return (
          <g key={i}>
            <rect
              x={bb.x} y={bb.y} width={bb.width} height={bb.height}
              fill="none"
              stroke={color}
              strokeWidth={Math.max(2, imgWidth / 640)}
              strokeDasharray={identified ? undefined : '10,5'}
            />
            {identified && (() => {
              const cs = Math.min(bb.width, bb.height) * 0.15
              const sw = Math.max(3, imgWidth / 480)
              return (
                <>
                  <path d={`M${bb.x},${bb.y + cs} L${bb.x},${bb.y} L${bb.x + cs},${bb.y}`} fill="none" stroke="#22c55e" strokeWidth={sw} />
                  <path d={`M${bb.x + bb.width - cs},${bb.y} L${bb.x + bb.width},${bb.y} L${bb.x + bb.width},${bb.y + cs}`} fill="none" stroke="#22c55e" strokeWidth={sw} />
                  <path d={`M${bb.x},${bb.y + bb.height - cs} L${bb.x},${bb.y + bb.height} L${bb.x + cs},${bb.y + bb.height}`} fill="none" stroke="#22c55e" strokeWidth={sw} />
                  <path d={`M${bb.x + bb.width - cs},${bb.y + bb.height} L${bb.x + bb.width},${bb.y + bb.height} L${bb.x + bb.width},${bb.y + bb.height - cs}`} fill="none" stroke="#22c55e" strokeWidth={sw} />
                </>
              )
            })()}
            <rect
              x={bb.x} y={labelY}
              width={labelW} height={24}
              fill={color} fillOpacity="0.88" rx="3"
            />
            <text
              x={bb.x + 8} y={labelY + 16}
              fill="white"
              fontSize={Math.max(12, imgWidth / 120)}
              fontFamily="monospace"
              fontWeight="bold"
            >
              {labelText}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function ObjectOverlay({ objects, imgWidth, imgHeight }: { objects: ObjectDetection[]; imgWidth: number; imgHeight: number }) {
  if (!objects || objects.length === 0) return null
  return (
    <svg
      style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 20, pointerEvents: 'none' }}
      viewBox={`0 0 ${imgWidth} ${imgHeight}`}
      preserveAspectRatio="none"
    >
      {objects.map((obj, i) => {
        const bb = obj.bbox || {
          x: obj.x || 0, y: obj.y || 0,
          width: obj.width || 0, height: obj.height || 0
        }
        if (!bb.width || !bb.height) return null
        const label = obj.label || 'object'
        const conf = obj.confidence ? ` ${(obj.confidence * 100).toFixed(0)}%` : ''
        const labelText = `${label}${conf}`
        const labelW = Math.min(labelText.length * 8 + 16, 280)
        const labelY = Math.max(0, bb.y - 26)
        return (
          <g key={i}>
            <rect
              x={bb.x} y={bb.y} width={bb.width} height={bb.height}
              fill="none"
              stroke="#f97316"
              strokeWidth={Math.max(2, imgWidth / 640)}
            />
            <rect
              x={bb.x} y={labelY}
              width={labelW} height={24}
              fill="#f97316" fillOpacity="0.88" rx="3"
            />
            <text
              x={bb.x + 8} y={labelY + 16}
              fill="white"
              fontSize={Math.max(12, imgWidth / 120)}
              fontFamily="monospace"
              fontWeight="bold"
            >
              {labelText}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function getStreamType(url: string): 'video' | 'hls' | 'mjpeg' | 'iframe' | 'image' | 'unknown' {
  const lower = url.toLowerCase()
  if (lower.endsWith('.m3u8')) return 'hls'
  if (lower.endsWith('.mjpg') || lower.endsWith('.mjpeg') || lower.includes('mjpg') || lower.includes('mjpeg')) return 'mjpeg'
  if (lower.endsWith('.mp4') || lower.endsWith('.webm') || lower.endsWith('.ogg')) return 'video'
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.png') || lower.endsWith('.gif')) return 'image'
  if (lower.startsWith('http://') || lower.startsWith('https://')) return 'iframe'
  return 'unknown'
}

function RtspStreamFeed({ cameraName, location, resolution, cameraType, streamUrl, className, showOverlay, detectionMode = 'both', onModeChange, showModeToggle = false }: CameraFeedProps & { streamUrl: string }) {
  const [currentFrame, setCurrentFrame] = useState<string | null>(null)
  const [streamId, setStreamId] = useState<string | null>(null)
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting')
  const [errorMsg, setErrorMsg] = useState('')
  const [currentTime, setCurrentTime] = useState('')
  const [faces, setFaces] = useState<FaceDetection[]>([])
  const [objects, setObjects] = useState<ObjectDetection[]>([])
  const [localMode, setLocalMode] = useState(detectionMode)
  const pollingRef = useRef(false)
  const mountedRef = useRef(true)
  const latestFrameRef = useRef<string | null>(null)

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-US', { hour12: false }))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const streamUrlRef = useRef(streamUrl)
  streamUrlRef.current = streamUrl

  useEffect(() => {
    setLocalMode(detectionMode)
  }, [detectionMode])

  const handleModeChange = async (mode: 'face' | 'object' | 'both') => {
    setLocalMode(mode)
    onModeChange?.(mode)
    if (!streamId || !mountedRef.current) return
    try {
      const { api } = await import('@/lib/api/client')
      await api.post(`/video/rtsp/${streamId}/mode`, { mode })
    } catch (e) {
      console.error('[CameraFeed] mode change failed', e)
    }
  }

  useEffect(() => {
    mountedRef.current = true
    pollingRef.current = false

    const startAndPoll = async () => {
      const { api } = await import('@/lib/api/client')
      const url = streamUrlRef.current
      const camId = url.replace(/[^a-zA-Z0-9]/g, '-').slice(-40)
      const sid = `cam-${camId}`
      let started = false

      try {
        const res = await api.post('/video/rtsp/start', {
          rtsp_url: url,
          stream_id: sid,
          frame_interval: 10,
          detection_mode: localMode,
        })
        started = true
        if (!mountedRef.current) return
        setStreamId(res.data.stream_id || sid)
      } catch (err: any) {
        const detail = err?.detail || err?.response?.data?.detail || err?.message || ''
        if (detail.toLowerCase().includes('already active') || detail.toLowerCase().includes('already_active')) {
          started = true
        } else {
          if (!mountedRef.current) return
          setStatus('error')
          setErrorMsg(detail || 'Failed to start stream')
          return
        }
      }

      if (!started || !mountedRef.current) return
      setStreamId(sid)
      setStatus('live')
      pollingRef.current = true

      let consecutiveErrors = 0
      while (pollingRef.current && mountedRef.current) {
        try {
          const snap = await api.get(`/video/rtsp/${sid}/snapshot`)
          if (!mountedRef.current) break
          const d = snap.data
          const raw: string =
            d?.image || d?.frame || d?.data || d?.jpeg || d?.base64 ||
            (typeof d === 'string' ? d : '')
          if (!raw) {
            console.warn('[CameraFeed] snapshot keys:', Object.keys(d || {}), d)
          } else {
            const frame = raw.startsWith('data:') ? raw : `data:image/jpeg;base64,${raw}`
            setCurrentFrame(frame)

            // Store latest frame for face detection interval
            latestFrameRef.current = frame
          }
          // Use faces and objects from snapshot response (backend now runs identify_face + rfdetr per frame)
          if (d?.faces && Array.isArray(d.faces)) {
            setFaces(d.faces)
          }
          if (d?.objects && Array.isArray(d.objects)) {
            setObjects(d.objects)
          }
          consecutiveErrors = 0
        } catch (err: any) {
          if (!mountedRef.current) break
          const httpStatus = err?.response?.status || err?.status || err?.status_code
          // 504/503 = no frame ready yet, keep polling
          if (httpStatus === 504 || httpStatus === 503) {
            await new Promise(r => setTimeout(r, 300))
            continue
          }
          // 404 = stream gone
          if (httpStatus === 404) {
            setStatus('error')
            setErrorMsg('Stream ended')
            break
          }
          consecutiveErrors++
          if (consecutiveErrors > 30) {
            setStatus('error')
            setErrorMsg('Stream unavailable')
            break
          }
        }
        await new Promise(r => setTimeout(r, 100))
      }
    }

    startAndPoll()

    return () => {
      mountedRef.current = false
      pollingRef.current = false
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const overlay = showOverlay && (
    <>
      <div className="absolute top-0 left-0 right-0 p-2 flex items-center justify-between z-10 pointer-events-none">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${status === 'live' ? 'bg-red-500 animate-pulse' : status === 'connecting' ? 'bg-yellow-500 animate-pulse' : 'bg-gray-500'}`} />
          <span className={`text-[10px] font-mono uppercase tracking-wider ${status === 'live' ? 'text-red-400' : status === 'connecting' ? 'text-yellow-400' : 'text-gray-400'}`}>
            {status === 'live' ? 'LIVE' : status === 'connecting' ? 'CONNECTING' : 'ERROR'}
          </span>
        </div>
        <span className="text-[10px] font-mono text-green-400">{currentTime}</span>
      </div>
      <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/70 to-transparent z-10 pointer-events-none">
        <p className="text-[11px] font-mono text-white/90 truncate">{cameraName}</p>
        <p className="text-[9px] font-mono text-white/60 truncate">{location} | {resolution || '1080p'} | {(cameraType || 'fixed').toUpperCase()}</p>
      </div>
    </>
  )

  const [imgDims, setImgDims] = useState({ w: 1920, h: 1080 })
  const imgDimsRef = useRef({ w: 1920, h: 1080 })

  // Face identification — runs every 2s using latest frame
  useEffect(() => {
    const run = async () => {
      // Faces now come directly from the snapshot response (d.faces)
      // This is just a fallback for cases where snapshot doesn't include faces
      const frame = latestFrameRef.current
      if (!frame || !mountedRef.current) return
    }

        const interval = setInterval(run, 2000)
    return () => clearInterval(interval)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={`relative bg-black overflow-hidden w-full h-full ${className}`}>
      {currentFrame ? (
        <>
          <img
            src={currentFrame}
            alt={cameraName}
            className="w-full h-full object-cover"
            style={{ display: "block", minHeight: 0 }}
            onLoad={e => {
              const el = e.currentTarget
              if (el.naturalWidth > 0) {
                setImgDims({ w: el.naturalWidth, h: el.naturalHeight })
                imgDimsRef.current = { w: el.naturalWidth, h: el.naturalHeight }
              }
            }}
          />
          <FaceOverlay
            faces={faces}
            imgWidth={imgDims.w}
            imgHeight={imgDims.h}
          />
          <ObjectOverlay
            objects={objects}
            imgWidth={imgDims.w}
            imgHeight={imgDims.h}
          />
        </>
      ) : status === 'connecting' ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-gray-400">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-600 border-t-green-400 mx-auto mb-2" />
            <p className="text-xs">Connecting to RTSP...</p>
            <p className="text-[9px] font-mono text-gray-500 mt-1 break-all max-w-[200px] mx-auto">{streamUrl}</p>
          </div>
        </div>
      ) : status === 'error' ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-gray-400">
            <p className="text-sm text-red-400">Connection Failed</p>
            <p className="text-[9px] text-gray-500 mt-1">{errorMsg}</p>
          </div>
        </div>
      ) : null}
      {overlay}
      {showModeToggle && status === 'live' && (
        <div className="absolute top-10 right-2 z-30 flex items-center gap-0.5 bg-black/70 rounded-lg p-0.5 backdrop-blur-sm">
          {(['face', 'object', 'both'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => handleModeChange(mode)}
              className={`px-2 py-1 text-[9px] font-mono uppercase rounded-md transition-colors ${
                localMode === mode
                  ? 'bg-white text-black'
                  : 'text-white/70 hover:text-white hover:bg-white/10'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function CameraFeed({
  cameraName,
  location,
  streamUrl,
  resolution = '1920x1080',
  cameraType = 'fixed',
  isActive = true,
  className = '',
  showOverlay = true,
  detectionMode = 'both',
  onModeChange,
  showModeToggle = false,
}: CameraFeedProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>(0)
  const [currentTime, setCurrentTime] = useState('')
  const [streamError, setStreamError] = useState(false)
  const [streamLoaded, setStreamLoaded] = useState(false)

  const isRtsp = !!streamUrl && streamUrl.startsWith('rtsp://')
  const hasRealStream = !!streamUrl && streamUrl.trim() !== '' && !isRtsp && !streamError
  const streamType = hasRealStream ? getStreamType(streamUrl) : 'unknown'

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-US', { hour12: false }))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setStreamError(false)
    setStreamLoaded(false)
  }, [streamUrl])

  useEffect(() => {
    if (hasRealStream && streamType !== 'unknown') return
    if (isRtsp) return

    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const drawFrame = () => {
      const w = canvas.width
      const h = canvas.height

      ctx.fillStyle = '#0a0a0a'
      ctx.fillRect(0, 0, w, h)

      const time = Date.now() / 1000
      for (let y = 0; y < h; y += 4) {
        for (let x = 0; x < w; x += 4) {
          const noise = Math.sin(x * 0.01 + time) * Math.cos(y * 0.01 + time * 0.7) * 0.5 + 0.5
          const variation = Math.random() * 0.15
          const brightness = Math.floor((noise + variation) * 35 + 15)
          ctx.fillStyle = `rgb(${brightness}, ${brightness + 2}, ${brightness})`
          ctx.fillRect(x, y, 4, 4)
        }
      }

      const shapes = [
        { x: w * 0.15, y: h * 0.6, bw: w * 0.12, bh: h * 0.35 },
        { x: w * 0.45, y: h * 0.55, bw: w * 0.15, bh: h * 0.4 },
        { x: w * 0.75, y: h * 0.5, bw: w * 0.18, bh: h * 0.45 },
      ]

      shapes.forEach((s) => {
        ctx.fillStyle = 'rgba(30, 35, 40, 0.7)'
        ctx.fillRect(s.x - s.bw / 2, s.y - s.bh, s.bw, s.bh)
        ctx.fillStyle = 'rgba(60, 70, 80, 0.5)'
        ctx.fillRect(s.x - s.bw / 2, s.y - s.bh, s.bw, s.bh * 0.15)
        const windowRows = 4
        const windowCols = 3
        for (let r = 0; r < windowRows; r++) {
          for (let c = 0; c < windowCols; c++) {
            const wx = s.x - s.bw / 2 + (c + 0.5) * (s.bw / (windowCols + 0.5))
            const wy = s.y - s.bh + (r + 1.5) * (s.bh / (windowRows + 2))
            const lit = Math.sin(wx * 0.1 + time * 0.3 + r) > -0.2
            ctx.fillStyle = lit ? 'rgba(180, 170, 100, 0.6)' : 'rgba(20, 25, 30, 0.8)'
            ctx.fillRect(wx - 3, wy - 4, 7, 8)
          }
        }
      })

      ctx.fillStyle = 'rgba(25, 30, 20, 0.6)'
      ctx.fillRect(0, h * 0.85, w, h * 0.15)
      ctx.fillStyle = 'rgba(35, 50, 30, 0.4)'
      for (let x = 0; x < w; x += 8) {
        const grassH = Math.sin(x * 0.05 + time * 2) * 3 + h * 0.12
        ctx.fillRect(x, h - grassH, 6, grassH)
      }

      ctx.fillStyle = 'rgba(15, 15, 20, 0.9)'
      ctx.fillRect(0, 0, w, h * 0.12)
      for (let x = 20; x < w; x += 80) {
        const starBright = Math.sin(x * 0.3 + time) * 0.3 + 0.5
        ctx.fillStyle = `rgba(200, 200, 220, ${starBright * 0.4})`
        ctx.fillRect(x, Math.sin(x) * 10 + 15, 2, 2)
      }

      if (isActive) {
        for (let y = 0; y < h; y += 3) {
          ctx.fillStyle = `rgba(0, 0, 0, ${0.03 + Math.sin(y * 0.5 + time * 5) * 0.02})`
          ctx.fillRect(0, y, w, 1)
        }
        const scanY = ((time * 40) % h)
        ctx.fillStyle = 'rgba(100, 255, 100, 0.03)'
        ctx.fillRect(0, scanY - 2, w, 4)
      }

      animationRef.current = requestAnimationFrame(drawFrame)
    }

    const resizeCanvas = () => {
      const rect = canvas.getBoundingClientRect()
      canvas.width = rect.width * (window.devicePixelRatio > 1 ? 1.5 : 1)
      canvas.height = rect.height * (window.devicePixelRatio > 1 ? 1.5 : 1)
    }

    resizeCanvas()
    drawFrame()

    const observer = new ResizeObserver(resizeCanvas)
    observer.observe(canvas)

    return () => {
      cancelAnimationFrame(animationRef.current)
      observer.disconnect()
    }
  }, [isActive, hasRealStream, streamType, isRtsp])

  if (!isActive) {
    return (
      <div className={`relative bg-gray-900 flex items-center justify-center ${className}`}>
        <div className="text-center text-gray-500">
          <div className="text-4xl mb-2">&#x23FB;</div>
          <p className="text-sm">Camera Offline</p>
        </div>
      </div>
    )
  }

  if (isRtsp) {
    return (
      <RtspStreamFeed
        cameraName={cameraName}
        location={location}
        streamUrl={streamUrl!}
        resolution={resolution}
        cameraType={cameraType}
        isActive={isActive}
        className={className}
        showOverlay={showOverlay}
        detectionMode={detectionMode}
        onModeChange={onModeChange}
        showModeToggle={showModeToggle}
      />
    )
  }

  const overlay = showOverlay && (
    <>
      <div className="absolute top-0 left-0 right-0 p-2 flex items-center justify-between z-10 pointer-events-none">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-[10px] font-mono text-red-400 uppercase tracking-wider">REC</span>
        </div>
        <span className="text-[10px] font-mono text-green-400">{currentTime}</span>
      </div>
      <div className="absolute bottom-0 left-0 right-0 p-2 bg-gradient-to-t from-black/70 to-transparent z-10 pointer-events-none">
        <p className="text-[11px] font-mono text-white/90 truncate">{cameraName}</p>
        <p className="text-[9px] font-mono text-white/60 truncate">{location} | {resolution} | {cameraType.toUpperCase()}</p>
      </div>
    </>
  )

  if (hasRealStream && streamType === 'video') {
    return (
      <div className={`relative bg-black overflow-hidden ${className}`}>
        <video
          src={streamUrl}
          autoPlay
          muted
          loop
          playsInline
          className="absolute inset-0 w-full h-full object-cover"
          onError={() => setStreamError(true)}
          onLoadedData={() => setStreamLoaded(true)}
        />
        {!streamLoaded && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <div className="text-center text-gray-400">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-600 border-t-blue-400 mx-auto mb-2" />
              <p className="text-xs">Loading stream...</p>
            </div>
          </div>
        )}
        {overlay}
      </div>
    )
  }

  if (hasRealStream && (streamType === 'mjpeg' || streamType === 'image')) {
    return (
      <div className={`relative bg-black overflow-hidden ${className}`}>
        <img
          src={streamUrl}
          alt={cameraName}
          className="absolute inset-0 w-full h-full object-cover"
          onError={() => setStreamError(true)}
          onLoad={() => setStreamLoaded(true)}
        />
        {!streamLoaded && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <div className="text-center text-gray-400">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-600 border-t-blue-400 mx-auto mb-2" />
              <p className="text-xs">Loading stream...</p>
            </div>
          </div>
        )}
        {overlay}
      </div>
    )
  }

  if (hasRealStream && (streamType === 'iframe' || streamType === 'hls')) {
    return (
      <div className={`relative bg-black overflow-hidden ${className}`}>
        <iframe
          src={streamUrl}
          className="absolute inset-0 w-full h-full border-0"
          allow="autoplay; encrypted-media"
          allowFullScreen
          onError={() => setStreamError(true)}
          onLoad={() => setStreamLoaded(true)}
        />
        {!streamLoaded && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900">
            <div className="text-center text-gray-400">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-600 border-t-blue-400 mx-auto mb-2" />
              <p className="text-xs">Loading stream...</p>
            </div>
          </div>
        )}
        {overlay}
      </div>
    )
  }

  return (
    <div className={`relative bg-black overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      {overlay}
    </div>
  )
}
