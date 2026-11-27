'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  audiobookFileUrl, getAudiobookExport, startAudiobookExport, type AudiobookJob,
} from '@/lib/api'

const POLL_MS = 3000

/** One-click .m4b of every finished chapter, so audiobook apps get chapters, resume and speed. */
export default function AudiobookExport({ projectId, finished }: { projectId: number; finished: number }) {
  const [job, setJob] = useState<AudiobookJob | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setJob(await getAudiobookExport(projectId))
      setProblem(null)
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e))
    }
  }, [projectId])

  useEffect(() => { setJob(null); void refresh() }, [refresh])

  // A full volume takes minutes to encode; poll only while it runs.
  useEffect(() => {
    if (job?.state !== 'running') return
    const timer = setInterval(() => { void refresh() }, POLL_MS)
    return () => clearInterval(timer)
  }, [job?.state, refresh])

  const start = async () => {
    try {
      setJob(await startAudiobookExport(projectId))
      setProblem(null)
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e))
    }
  }

  const running = job?.state === 'running'
  const message = job?.state === 'error' ? job.error : problem
  return (
    <div className="flex items-center gap-3 text-[11px] min-w-0">
      <button
        className="btn-filter"
        onClick={start}
        disabled={running || finished === 0}
        title="Package every finished chapter into one .m4b audiobook with chapter markers"
      >
        {running ? 'Exporting audiobook…' : 'Export audiobook (.m4b)'}
      </button>
      {job?.state === 'done' && (
        <a className="underline text-spell-g5 truncate" href={audiobookFileUrl(projectId)} download>
          Download ({job.chapters} chapters, {job.hours} h
          {job.missing ? `, ${job.missing} unfinished left out` : ''})
        </a>
      )}
      {message && <span role="alert" className="text-blood-text truncate">{message}</span>}
    </div>
  )
}
