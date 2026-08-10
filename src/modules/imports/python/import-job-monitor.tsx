"use client"

import { useEffect, useRef, useState } from "react"
import { usePathname } from "next/navigation"
import { useSession } from "next-auth/react"

import { ImportClientError, requestImportJob } from "./import-client"
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

  useEffect(() => {
    const resume = () => {
      immediate.current = true
      setStoppedJobId(null)
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
          if (job.status === "completed") {
            clearPersistedImportJob(localStorage, record)
            setRecord(null)
            publishImportCompleted(job)
            return
          }
          if (job.status === "failed") {
            setStoppedJobId(job.id)
            return
          }
          setRunAfter(job.status === "retry_wait" ? job.run_after : null)
          setPollRevision((value) => value + 1)
        })
        .catch((error: unknown) => {
          if (cancelled || currentGeneration !== generation.current) return
          if (error instanceof ImportClientError && error.status === 404) {
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

  return null
}
