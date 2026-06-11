'use client'
import { useEffect, useRef } from 'react'
import type { SSEEvent } from '@/lib/types'

type Handler = (event: SSEEvent) => void

const RECONNECT_DELAY_MS = 3000

export function useSSE(
  enabled: boolean,
  onEvent: Handler,
  onConnection?: (connected: boolean) => void,
) {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent
  const connRef = useRef(onConnection)
  connRef.current = onConnection

  useEffect(() => {
    if (!enabled) return

    let es: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let disposed = false

    function connect() {
      if (disposed) return
      // Connect directly to the FastAPI backend — Next.js rewrites buffer SSE
      // which breaks streaming.
      const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      es = new EventSource(`${backendUrl}/api/events`)

      es.onopen = () => { connRef.current?.(true) }

      es.onmessage = (e) => {
        try {
          handlerRef.current(JSON.parse(e.data) as SSEEvent)
        } catch {
          // ignore malformed events
        }
      }

      es.onerror = () => {
        connRef.current?.(false)
        es?.close()
        es = null
        if (!disposed) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }

    connect()

    return () => {
      disposed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      es?.close()
      es = null
    }
  }, [enabled])
}
