import { describe, it, expect } from 'vitest'
import { formatEta, formatMB, parseChapterError } from '@/lib/format'

describe('formatEta', () => {
  it('formats hours and minutes', () => {
    expect(formatEta(2 * 3600 + 5 * 60)).toBe('~2h 5m left')
  })
  it('formats minutes only', () => {
    expect(formatEta(240)).toBe('~4m left')
  })
  it('returns empty for non-positive or non-finite', () => {
    expect(formatEta(0)).toBe('')
    expect(formatEta(Number.NaN)).toBe('')
  })
})

describe('formatMB', () => {
  it('formats bytes as MB with one decimal', () => {
    expect(formatMB(22_452_000)).toBe('21.4 MB')
  })
  it('returns empty for null', () => {
    expect(formatMB(null)).toBe('')
  })
})

describe('parseChapterError', () => {
  it('extracts the failed stage prefix', () => {
    expect(parseChapterError('[failed_stage:synthesize] CUDA OOM at line 31')).toEqual({
      stage: 'synthesize',
      detail: 'CUDA OOM at line 31',
    })
  })
  it('handles messages without a stage prefix', () => {
    expect(parseChapterError('boom')).toEqual({ stage: null, detail: 'boom' })
  })
  it('handles null', () => {
    expect(parseChapterError(null)).toEqual({ stage: null, detail: 'Unknown error' })
  })
})
