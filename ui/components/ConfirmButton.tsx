'use client'
import { useEffect, useRef, useState } from 'react'

interface Props {
  /** Idle-state content (icon or label). */
  children: React.ReactNode
  /** Short prompt shown in the armed state, e.g. "Delete?". */
  confirmLabel: string
  onConfirm: () => void | Promise<void>
  className?:        string
  confirmClassName?: string
  disabled?: boolean
  title?:    string
  /** Accessible name for the idle state. */
  ariaLabel: string
  /** ms before an armed button reverts to idle. */
  revertMs?: number
}

/**
 * Two-step inline confirm — replaces native confirm() dialogs.
 * First click arms the button (shows confirmLabel), second click within
 * revertMs fires onConfirm; otherwise it quietly reverts.
 */
export default function ConfirmButton({
  children, confirmLabel, onConfirm,
  className = 'btn', confirmClassName = 'btn-danger',
  disabled, title, ariaLabel, revertMs = 3000,
}: Props) {
  const [armed, setArmed] = useState(false)
  const [busy,  setBusy]  = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  async function handleClick() {
    if (busy) return
    if (!armed) {
      setArmed(true)
      timer.current = setTimeout(() => setArmed(false), revertMs)
      return
    }
    if (timer.current) clearTimeout(timer.current)
    setArmed(false); setBusy(true)
    try { await onConfirm() }
    finally { setBusy(false) }
  }

  return (
    <button
      className={armed ? confirmClassName : className}
      onClick={handleClick}
      disabled={disabled || busy}
      title={armed ? confirmLabel : title}
      aria-label={armed ? confirmLabel : ariaLabel}
    >
      {busy ? '…' : armed ? confirmLabel : children}
    </button>
  )
}
