'use client'
import { useEffect } from 'react'

export type ToastTone = 'gold' | 'crimson' | 'chrome'

export interface Toast {
  id:   number
  tone: ToastTone
  /** Message body — rendered inside Spell brackets: [ message ]. */
  message: string
}

const AUTO_DISMISS_MS = 6000

const TONE_CLASS: Record<ToastTone, string> = {
  gold:    'spell-toast--gold',
  crimson: 'spell-toast--crimson',
  chrome:  'spell-toast--chrome',
}

const TONE_SIGIL: Record<ToastTone, string> = {
  gold:    '!',
  crimson: '✗',
  chrome:  '✓',
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(toast.id), AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [toast.id, onDismiss])

  return (
    <div className={`spell-toast ${TONE_CLASS[toast.tone]} animate-toast-in`} role="status">
      <span className="opacity-60 select-none flex-shrink-0">{TONE_SIGIL[toast.tone]}</span>
      <span className="min-w-0 break-words">
        <span className="spell-bracket">[&thinsp;</span>
        {toast.message}
        <span className="spell-bracket">&thinsp;]</span>
      </span>
      <button
        className="opacity-40 hover:opacity-90 transition-opacity flex-shrink-0 ml-1"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
      >✕</button>
    </div>
  )
}

/**
 * Nightmare-Spell-style notification stack, top-right.
 * The Spell speaks in square brackets — so do we.
 */
export default function Toasts({ toasts, onDismiss }: {
  toasts: Toast[]; onDismiss: (id: number) => void
}) {
  if (!toasts.length) return null
  return (
    <div className="fixed top-16 right-4 z-50 flex flex-col gap-2 items-end" aria-live="polite">
      {toasts.map(t => <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />)}
    </div>
  )
}
