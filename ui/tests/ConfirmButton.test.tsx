import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import ConfirmButton from '@/components/ConfirmButton'

function renderButton(onConfirm: () => void) {
  return render(
    <ConfirmButton confirmLabel="Delete?" onConfirm={onConfirm} ariaLabel="Delete audio">
      del
    </ConfirmButton>,
  )
}

describe('ConfirmButton', () => {
  it('does not fire on the first click — it arms instead', () => {
    const onConfirm = vi.fn()
    renderButton(onConfirm)

    fireEvent.click(screen.getByRole('button', { name: /delete audio/i }))

    expect(onConfirm).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Delete?' })).toBeInTheDocument()
  })

  it('fires on the second click while armed', () => {
    const onConfirm = vi.fn()
    renderButton(onConfirm)

    const btn = screen.getByRole('button')
    fireEvent.click(btn)
    fireEvent.click(btn)

    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('reverts to idle if the second click never comes', () => {
    vi.useFakeTimers()
    try {
      const onConfirm = vi.fn()
      renderButton(onConfirm)

      const btn = screen.getByRole('button')
      fireEvent.click(btn)
      expect(screen.getByRole('button', { name: 'Delete?' })).toBeInTheDocument()

      act(() => { vi.advanceTimersByTime(3100) })

      expect(screen.getByRole('button', { name: /delete audio/i })).toBeInTheDocument()
      fireEvent.click(btn) // re-arms, does not fire
      expect(onConfirm).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })
})
