/** "~2h 5m left" / "~4m left" — ETA from seconds; empty when unknowable. */
export function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `~${h}h ${m}m left`
  if (m > 0) return `~${m}m left`
  return '~1m left'
}

/** "21.4 MB" — chapter file sizes in the queue sub-line. */
export function formatMB(bytes: number | null): string {
  if (bytes == null) return ''
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}

/** Splits the backend's "[failed_stage:X] detail" error format. */
export function parseChapterError(
  msg: string | null,
): { stage: string | null; detail: string } {
  if (!msg) return { stage: null, detail: 'Unknown error' }
  const m = /^\[failed_stage:(\w+)\]\s*/.exec(msg)
  return m ? { stage: m[1], detail: msg.slice(m[0].length) } : { stage: null, detail: msg }
}
