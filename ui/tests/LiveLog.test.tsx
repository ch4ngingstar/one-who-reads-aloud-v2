import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import LiveLog from '@/components/LiveLog'
import type { SSEEvent } from '@/lib/types'

function makeEvent(overrides: Partial<SSEEvent> = {}): SSEEvent {
  return { type: 'chapter_start', ts: 1_700_000_000, ...overrides } as SSEEvent
}

describe('LiveLog', () => {
  it('shows event count in the toggle bar', () => {
    const events = [makeEvent(), makeEvent()]
    render(<LiveLog events={events} open={false} onToggle={() => {}} />)
    expect(screen.getByText('2 events')).toBeInTheDocument()
  })

  it('shows waiting message when open with no events', () => {
    render(<LiveLog events={[]} open={true} onToggle={() => {}} />)
    expect(screen.getByText(/waiting for pipeline/i)).toBeInTheDocument()
  })

  it('calls onToggle when the bar is clicked', () => {
    const toggle = vi.fn()
    render(<LiveLog events={[]} open={false} onToggle={toggle} />)
    fireEvent.click(screen.getByRole('button', { name: /live log/i }))
    expect(toggle).toHaveBeenCalledOnce()
  })

  it('renders pipeline_stopped event with stopped color', () => {
    const e = makeEvent({ type: 'pipeline_stopped', elapsed_s: 42, success: 3, error: 1 })
    const { container } = render(<LiveLog events={[e]} open={true} onToggle={() => {}} />)
    const line = container.querySelector('[class*="52525B"]')
    expect(line).not.toBeNull()
    expect(line?.textContent).toMatch(/stopped after 42s/)
  })

  it('collapses log body when closed', () => {
    const e = makeEvent({ type: 'chapter_start', chapter_id: 5, title: 'Secret Chapter' } as SSEEvent)
    const { container } = render(<LiveLog events={[e]} open={false} onToggle={() => {}} />)
    expect(container.querySelector('.log-scanlines')).toBeNull()
  })
})
