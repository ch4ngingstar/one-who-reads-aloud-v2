'use client'
import { useEffect, useRef, useCallback } from 'react'
import type { SSEEvent } from '@/lib/types'

type Handler = (event: SSEEvent) => void

export function useSSE(enabled: boolean, onEvent: Handler) {
  const esRef    = useRef<EventSource | null>(null)
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
    }
    // Connect directly to the FastAPI backend — Next.js rewrites buffer SSE which breaks streaming
    const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
    const es = new EventSource(`${backendUrl}/api/events`)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent
        handlerRef.current(data)
      } catch {
        // ignore malformed events
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      // Auto-reconnect after 3s if still enabled
      setTimeout(() => { if (esRef.current === null) connect() }, 3000)
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      esRef.current?.close()
      esRef.current = null
      return
    }
    connect()
    return () => {
      esRef.current?.close()
      esRef.current = null
    }
  }, [enabled, connect])
}
