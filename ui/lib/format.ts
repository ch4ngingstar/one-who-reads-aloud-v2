type ChapterLike = { chapter_index: number; title: string; chapter_number?: number | null;
  display_title?: string | null; kind?: string | null }

/** The book's chapter number ("1994"); "Intro" for the synopsis; position for unnumbered books. */
export function chapterNumberLabel(chapter: ChapterLike): string {
  if (chapter.kind === 'front') return 'Intro'
  return String(chapter.chapter_number ?? chapter.chapter_index + 1)
}

/** The chapter's name without the "Chapter 1994:" prefix (the number is shown beside it). */
export function chapterName(chapter: ChapterLike): string {
  const display = chapter.display_title || chapter.title
  return display.replace(/^chapter\s+\d+\s*[:.\-–—]?\s*/i, '') || display
}

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
