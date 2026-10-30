import { NextRequest } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000'

/**
 * Proxies the backend SSE notification stream through Next.js so EventSource
 * can use a same-origin URL without relying on rewrite buffering behaviour.
 */
export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get('token')
  if (!token) {
    return new Response('Missing token', { status: 401 })
  }

  const backendUrl = `${BACKEND_URL}/api/v1/notifications/stream?token=${encodeURIComponent(token)}`

  try {
    const response = await fetch(backendUrl, {
      headers: { Accept: 'text/event-stream' },
    })

    if (!response.ok || !response.body) {
      return new Response(response.statusText || 'Stream unavailable', {
        status: response.status,
      })
    }

    return new Response(response.body, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    })
  } catch {
    return new Response('Failed to connect to notification stream', { status: 502 })
  }
}
