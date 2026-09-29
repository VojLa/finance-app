"use client"

import { useEffect, useRef, useState } from "react"
import { usePathname } from "next/navigation"
import { useSession } from "next-auth/react"

import { ImportClientError, requestImportJob } from "./import-client"
import type { PythonImportJob } from "./import-contract"
import {
  IMPORT_COMPLETED_EVENT,
  publishImportCompleted,
  subscribeImportJobBroadcasts,
} from "./import-job-events"
import {
  beginImportPoll,
  clearPersistedImportJob,
  finishImportPoll,
  importPollDelayMs,
  loadLatestPersistedImportJob,
  resolveImportPollFailure,
  resolveImportPollJob,
  type PersistedImportJob,
} from "./import-job-state"

/** Keeps accepted imports observable after navigation away from the import page. */
export function ImportJobMonitor() {
  const pathname = usePathname()
  const { data: session } = useSession()
  const userId = session?.user?.id ?? ""
  const gate = useRef({ inFlight: false, pending: false })
  const immediate = useRef(true)
  const generation = useRef(0)
  const [record, setRecord] = useState<PersistedImportJob | null>(null)
  const [runAfter, setRunAfter] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [resumeRevision, setResumeRevision] = useState(0)
  const [pollRevision, setPollRevision] = useState(0)
  const [visible, setVisible] = useState(true)
  const [stoppedJobId, setStoppedJobId] = useState<string | null>(null)
  const [failedJob, setFailedJob] = useState<PythonImportJob | null>(null)

  useEffect(() => {
    const resume = () => {
      immediate.current = true
      setStoppedJobId(null)
      setFailedJob(null)
      setResumeRevision((value) => value + 1)
    }
    const unsubscribe = subscribeImportJobBroadcasts((message) => {
      if (message.type === "completed") {
        window.dispatchEvent(new Event(IMPORT_COMPLETED_EVENT))
      }
      resume()
    })
    window.addEventListener("storage", resume)
    return () => {
      unsubscribe()
      window.removeEventListener("storage", resume)
    }
  }, [])

  useEffect(() => {
    const onVisibility = () => {
      const nextVisible = document.visibilityState === "visible"
      setVisible(nextVisible)
      if (nextVisible) {
        immediate.current = true
        setPollRevision((value) => value + 1)
      }
    }
    document.addEventListener("visibilitychange", onVisibility)
    onVisibility()
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [])

  useEffect(() => {
    if (!userId || pathname === "/import") {
      setRecord(null)
      return
    }
    setRunAfter(null)
    setFailures(0)
    setStoppedJobId(null)
    setFailedJob(null)
    setRecord(loadLatestPersistedImportJob(localStorage, userId))
  }, [pathname, resumeRevision, userId])

  useEffect(() => {
    if (pathname === "/import" || !visible || record === null || stoppedJobId === record.jobId) {
      return
    }
    let cancelled = false
    const currentGeneration = ++generation.current
    const delay = importPollDelayMs(failures, runAfter, Date.now(), immediate.current)
    immediate.current = false
    const timer = window.setTimeout(() => {
      if (!beginImportPoll(gate.current)) return
      void requestImportJob(record.accountId, record.jobId)
        .then((job) => {
          if (cancelled || currentGeneration !== generation.current) return
          setFailures(0)
          const decision = resolveImportPollJob(job)
          if (decision.kind === "completed") {
            clearPersistedImportJob(localStorage, record)
            setRecord(null)
            setFailedJob(null)
            publishImportCompleted(job)
            return
          }
          if (decision.kind === "failed") {
            setStoppedJobId(job.id)
            setFailedJob(job)
            return
          }
          setRunAfter(decision.runAfter)
          setPollRevision((value) => value + 1)
        })
        .catch((error: unknown) => {
          if (cancelled || currentGeneration !== generation.current) return
          const status = error instanceof ImportClientError ? error.status : null
          if (resolveImportPollFailure(status) === "discard") {
            clearPersistedImportJob(localStorage, record)
            setRecord(null)
            return
          }
          setFailures((value) => Math.min(value + 1, 100))
        })
        .finally(() => {
          if (finishImportPoll(gate.current)) {
            immediate.current = true
            setPollRevision((value) => value + 1)
          }
        })
    }, delay)
    return () => {
      cancelled = true
      generation.current += 1
      window.clearTimeout(timer)
    }
  }, [failures, pathname, pollRevision, record, runAfter, stoppedJobId, visible])

  if (pathname === "/import" || failedJob === null) return null
  return (
    <div
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded border border-red-300 bg-red-50 p-3 text-sm text-red-950 shadow-lg"
      role="alert"
    >
      <p>Import na pozadí selhal: {failedJob.error?.message ?? "Neznámá chyba."}</p>
      <p className="mt-1 text-xs">
        Fáze {failedJob.progress.phase}, pokus {failedJob.attempt_count} z {failedJob.max_attempts}.
      </p>
      <a className="mt-2 inline-block underline" href="/import">
        Zobrazit detail a bezpečně opakovat
      </a>
    </div>
  )
}
