"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"

import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import { AccountClientError, requestAccounts } from "@/modules/accounts/account-client"
import type { AccountPageModel } from "@/modules/accounts/account-contract"
import { toAccountPageModel } from "@/modules/accounts/account-contract"
import {
  ImportClientError,
  requestImport,
  requestImportJob,
  retryImportJob,
} from "@/modules/imports/python/import-client"
import type { PythonImportJob } from "@/modules/imports/python/import-contract"
import {
  publishImportCompleted,
  publishImportJobActive,
} from "@/modules/imports/python/import-job-events"
import {
  beginImportPoll,
  clearPersistedImportJob,
  finishImportPoll,
  importPollDelayMs,
  loadLatestPersistedImportJob,
  persistImportJob,
  type PersistedImportJob,
} from "@/modules/imports/python/import-job-state"
import { IMPORT_SOURCE_OPTIONS } from "@/modules/imports/python/import-sources"

const BACKGROUND_NOTICE_MS = 5_000

type AccountLoadState =
  | { status: "loading" }
  | { status: "ready"; accounts: readonly AccountPageModel[] }
  | { status: "error"; message: string }

type PageState =
  | { status: "idle" }
  | { status: "uploading"; backgroundNotice: boolean }
  | { status: "resuming" }
  | { status: "background"; job: PythonImportJob }
  | { status: "completed"; job: PythonImportJob }
  | { status: "failed"; job: PythonImportJob }
  | { status: "error"; message: string }

type RejectedFile = { filename: string; code: string; message: string }
type ImportSourceOption = (typeof IMPORT_SOURCE_OPTIONS)[number]

function isTerminal(job: PythonImportJob): boolean {
  return job.status === "completed" || job.status === "failed"
}

function backgroundStatus(job: PythonImportJob): string {
  if (job.status === "queued") return "čeká ve frontě"
  if (job.status === "retry_wait") return "čeká na automatický další pokus"
  return "zpracovává se"
}

function DropZone({ files, onFiles }: { files: File[]; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const accept = (selected: FileList | File[]) =>
    onFiles(Array.from(selected).filter((file) => file.name.toLocaleLowerCase().endsWith(".csv")))

  return (
    <div
      className="cursor-pointer rounded-xl border-2 border-dashed border-gray-300 p-8 text-center"
      onClick={() => input.current?.click()}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault()
        accept(event.dataTransfer.files)
      }}
    >
      <input
        ref={input}
        className="hidden"
        type="file"
        multiple
        accept=".csv,text/csv"
        onChange={(event) => {
          accept(event.target.files ?? [])
          event.target.value = ""
        }}
      />
      <p className="text-sm text-gray-600">
        {files.length ? `Vybráno souborů: ${files.length}` : "Přetáhni CSV soubory sem"}
      </p>
    </div>
  )
}

export default function ImportPage() {
  const accountLoadStarted = useRef(false)
  const pollGeneration = useRef(0)
  const pollImmediately = useRef(false)
  const pollGate = useRef({ inFlight: false, pending: false })
  const { data: session } = useSession()
  const userId = session?.user?.id ?? ""

  const [accounts, setAccounts] = useState<AccountLoadState>({ status: "loading" })
  const [source, setSource] = useState<ImportSourceOption>(IMPORT_SOURCE_OPTIONS[0])
  const [accountId, setAccountId] = useState("")
  const [files, setFiles] = useState<File[]>([])
  const [state, setState] = useState<PageState>({ status: "idle" })
  const [persistedRecord, setPersistedRecord] = useState<PersistedImportJob | null>(null)
  const [pollFailures, setPollFailures] = useState(0)
  const [pollRevision, setPollRevision] = useState(0)
  const [visible, setVisible] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [rejectedFiles, setRejectedFiles] = useState<readonly RejectedFile[]>([])

  useEffect(() => {
    if (accountLoadStarted.current) return
    accountLoadStarted.current = true
    void requestAccounts()
      .then((value) => setAccounts({ status: "ready", accounts: value.map(toAccountPageModel) }))
      .catch((error: unknown) =>
        setAccounts({
          status: "error",
          message:
            error instanceof AccountClientError ? error.message : "Účty se nepodařilo načíst.",
        })
      )
  }, [])

  useEffect(() => {
    const onVisibility = () => {
      const isVisible = document.visibilityState === "visible"
      setVisible(isVisible)
      if (isVisible) {
        pollImmediately.current = true
        setPollRevision((value) => value + 1)
      }
    }
    document.addEventListener("visibilitychange", onVisibility)
    onVisibility()
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [])

  useEffect(() => {
    if (!userId) return
    const stored = loadLatestPersistedImportJob(localStorage, userId)
    if (stored !== null) {
      setPersistedRecord(stored)
      setAccountId(stored.accountId)
      setState({ status: "resuming" })
    }
  }, [userId])

  const acceptJob = useCallback(
    (job: PythonImportJob) => {
      const record = userId ? persistImportJob(localStorage, userId, job) : null
      setPersistedRecord(record)
      setPollFailures(0)
      setActionError(null)
      if (job.status === "completed") {
        if (record !== null) clearPersistedImportJob(localStorage, record)
        setPersistedRecord(null)
        publishImportCompleted(job)
        setState({ status: "completed", job })
      } else if (job.status === "failed") {
        setState({ status: "failed", job })
      } else {
        setState({ status: "background", job })
      }
    },
    [userId]
  )

  const job = "job" in state ? state.job : null
  useEffect(() => {
    if (!visible || (job !== null && isTerminal(job))) return
    const target =
      job !== null
        ? {
            accountId: job.account_id,
            jobId: job.id,
            runAfter: job.status === "retry_wait" ? job.run_after : null,
          }
        : state.status === "resuming" && persistedRecord !== null
          ? {
              accountId: persistedRecord.accountId,
              jobId: persistedRecord.jobId,
              runAfter: null,
            }
          : null
    if (target === null) return

    let cancelled = false
    const generation = ++pollGeneration.current
    const delay = importPollDelayMs(
      pollFailures,
      target.runAfter,
      Date.now(),
      pollImmediately.current
    )
    pollImmediately.current = false
    const timer = window.setTimeout(() => {
      if (!beginImportPoll(pollGate.current)) return
      void requestImportJob(target.accountId, target.jobId)
        .then((next) => {
          if (!cancelled && generation === pollGeneration.current) acceptJob(next)
        })
        .catch((error: unknown) => {
          if (cancelled || generation !== pollGeneration.current) return
          if (error instanceof ImportClientError && error.status === 404) {
            if (persistedRecord !== null) {
              clearPersistedImportJob(localStorage, persistedRecord)
              setPersistedRecord(null)
            }
            setState({ status: "error", message: error.message })
            return
          }
          setActionError(
            error instanceof ImportClientError
              ? error.message
              : "Spojení bylo přerušeno; stav zpracování načteme znovu."
          )
          setPollFailures((value) => Math.min(value + 1, 100))
        })
        .finally(() => {
          if (finishImportPoll(pollGate.current)) {
            pollImmediately.current = true
            setPollRevision((value) => value + 1)
          }
        })
    }, delay)
    return () => {
      cancelled = true
      pollGeneration.current += 1
      window.clearTimeout(timer)
    }
  }, [acceptJob, job, persistedRecord, pollFailures, pollRevision, state.status, visible])

  const filteredAccounts =
    accounts.status === "ready"
      ? accounts.accounts.filter((account) => source.accepts.includes(account.type))
      : []
  const busy = ["uploading", "resuming", "background"].includes(state.status)

  async function submit() {
    if (!accountId || !files.length || busy) return
    setActionError(null)
    setRejectedFiles([])
    setState({ status: "uploading", backgroundNotice: false })
    const noticeTimer = window.setTimeout(() => {
      setState((current) =>
        current.status === "uploading" ? { status: "uploading", backgroundNotice: true } : current
      )
    }, BACKGROUND_NOTICE_MS)
    try {
      const acceptance = await requestImport(accountId, source.value, files)
      setRejectedFiles(acceptance.rejectedFiles)
      setFiles([])
      acceptJob(acceptance.job)
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof ImportClientError ? error.message : "Import API není dostupné.",
      })
    } finally {
      window.clearTimeout(noticeTimer)
    }
  }

  async function retry() {
    if (job?.status !== "failed") return
    setActionError(null)
    try {
      const retried = await retryImportJob(job.account_id, job.id)
      publishImportJobActive(retried)
      acceptJob(retried)
    } catch (error) {
      if (error instanceof ImportClientError && error.status === 409) {
        try {
          const current = await requestImportJob(job.account_id, job.id)
          if (!isTerminal(current)) publishImportJobActive(current)
          acceptJob(current)
          return
        } catch {
          // Keep the last failed job visible and retryable.
        }
      }
      setActionError(
        error instanceof ImportClientError ? error.message : "Opakování se nepodařilo spustit."
      )
    }
  }

  return (
    <div className="max-w-2xl space-y-5">
      <h1 className="text-2xl font-semibold">Import CSV</h1>
      <div className="space-y-5 rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex flex-wrap gap-2">
          {IMPORT_SOURCE_OPTIONS.map((candidate) => (
            <button
              key={candidate.value}
              type="button"
              disabled={busy}
              onClick={() => {
                setSource(candidate)
                setAccountId("")
                setFiles([])
                setState({ status: "idle" })
              }}
              className="rounded border px-3 py-2 text-sm disabled:opacity-50"
            >
              {candidate.label}
            </button>
          ))}
        </div>

        {accounts.status === "loading" && <p className="text-sm text-gray-500">Načítám účty…</p>}
        {accounts.status === "error" && <p className="text-sm text-red-700">{accounts.message}</p>}
        {accounts.status === "ready" && (
          <select
            value={accountId}
            disabled={busy}
            onChange={(event) => setAccountId(event.target.value)}
            className="w-full rounded border p-2"
          >
            <option value="">Vyber účet</option>
            {filteredAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name} ({ACCOUNT_TYPE_LABELS[account.type]})
              </option>
            ))}
          </select>
        )}

        <DropZone files={files} onFiles={setFiles} />

        {state.status === "uploading" && (
          <p className="text-sm text-blue-700" role="status">
            {state.backgroundNotice
              ? "Nahrání a přijetí trvá déle. Po zařazení do fronty můžeš stránku zavřít."
              : "Nahrávám soubory a čekám na bezpečné zařazení do fronty…"}
          </p>
        )}
        {state.status === "resuming" && (
          <p className="text-sm text-blue-700" role="status">
            Obnovuji stav zpracování na pozadí…
          </p>
        )}
        {state.status === "background" && (
          <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
            <p>
              Zpracování běží na pozadí: {backgroundStatus(state.job)} ({state.job.progress.phase}).
            </p>
            <p>
              Dokončeno {state.job.progress.completed_units} z {state.job.progress.total_units}{" "}
              kroků.
            </p>
            <p className="mt-1 text-xs">Stránku můžeš bezpečně zavřít.</p>
          </div>
        )}
        {state.status === "completed" && (
          <div className="rounded border border-green-200 bg-green-50 p-3 text-sm text-green-900">
            Import je dokončen. Importováno {state.job.result?.rows_imported ?? 0} řádků, přeskočeno{" "}
            {state.job.result?.rows_skipped ?? 0}.
          </div>
        )}
        {state.status === "failed" && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            <p>{state.job.error?.message ?? "Import se nepodařilo dokončit."}</p>
            <button
              type="button"
              onClick={() => void retry()}
              className="mt-2 rounded bg-red-700 px-3 py-2 text-white"
            >
              Zkusit znovu
            </button>
          </div>
        )}
        {state.status === "error" && <p className="text-sm text-red-700">{state.message}</p>}
        {actionError !== null && (
          <p className="text-sm text-amber-800" role="status">
            {actionError}
          </p>
        )}
        {rejectedFiles.length > 0 && (
          <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p>Některé soubory nebyly přijaty, ostatní se zpracují na pozadí:</p>
            <ul className="mt-1 list-disc pl-5">
              {rejectedFiles.map((file) => (
                <li key={`${file.filename}:${file.code}`}>
                  {file.filename}: {file.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          type="button"
          disabled={!accountId || !files.length || busy}
          onClick={() => void submit()}
          className="w-full rounded bg-blue-600 py-2 text-white disabled:opacity-50"
        >
          {busy ? "Zpracování běží…" : "Spustit import"}
        </button>
      </div>
    </div>
  )
}
