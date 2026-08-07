"use client"

import { useEffect, useRef, useState } from "react"

import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import { AccountClientError, requestAccounts } from "@/modules/accounts/account-client"
import type { AccountPageModel } from "@/modules/accounts/account-contract"
import { toAccountPageModel } from "@/modules/accounts/account-contract"
import {
  recoverableBatchIds,
  requiresImportFinalizationRecovery,
  withImportFinalization,
  type ImportSummary,
} from "@/modules/imports/python/import-contract"
import {
  ImportClientError,
  requestImport,
  requestImportFinalization,
} from "@/modules/imports/python/import-client"
import { IMPORT_SOURCE_OPTIONS } from "@/modules/imports/python/import-sources"

type AccountLoadState =
  | { status: "loading" }
  | { status: "ready"; accounts: readonly AccountPageModel[] }
  | { status: "error"; message: string }

type ImportPageState =
  | { status: "idle" }
  | { status: "uploading"; completed: number; total: number }
  | { status: "recovering"; result: ImportSummary }
  | { status: "completed"; result: ImportSummary }
  | { status: "error"; message: string; partial?: ImportSummary }

type ToastState = {
  kind: "success" | "error"
  title: string
  message: string
} | null

function DropZone({ onFiles, files }: { onFiles: (files: File[]) => void; files: File[] }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function acceptFiles(selected: FileList | File[]) {
    const csvFiles = Array.from(selected).filter((file) => file.name.toLowerCase().endsWith(".csv"))
    onFiles(csvFiles)
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        acceptFiles(event.dataTransfer.files)
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
        dragging
          ? "border-blue-400 bg-blue-50"
          : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => {
          acceptFiles(event.target.files ?? [])
          event.target.value = ""
        }}
      />
      {files.length > 0 ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-800">Vybráno souborů: {files.length}</p>
          {files.map((file) => (
            <p
              key={`${file.name}-${file.size}-${file.lastModified}`}
              className="text-xs text-gray-500"
            >
              {file.name} ({Math.ceil(file.size / 1024)} KB)
            </p>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-2xl text-gray-300">↑</p>
          <p className="text-sm font-medium text-gray-600">Přetáhni CSV soubory sem</p>
          <p className="text-xs text-gray-400">nebo klikni pro výběr</p>
        </div>
      )}
    </div>
  )
}

function ImportResult({
  result,
  onRetry,
  retrying = false,
}: {
  result: ImportSummary
  onRetry?: () => void
  retrying?: boolean
}) {
  const recoveryRequired = requiresImportFinalizationRecovery(result)
  return (
    <div className="space-y-3">
      {recoveryRequired && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <p>Data byla zaúčtována, ale aktualizaci portfolia se nepodařilo dokončit.</p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              disabled={retrying}
              className="mt-2 rounded-lg bg-amber-800 px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              {retrying ? "Dokončuji aktualizaci…" : "Zkusit dokončit aktualizaci"}
            </button>
          )}
        </div>
      )}
      <div
        className={`rounded-lg border px-4 py-3 text-sm ${
          result.failedFiles > 0
            ? "border-amber-200 bg-amber-50 text-amber-900"
            : "border-green-200 bg-green-50 text-green-900"
        }`}
      >
        <p>
          Importováno: <strong>{result.rowsImported}</strong>, přeskočeno:{" "}
          <strong>{result.rowsSkipped}</strong>, k revizi: <strong>{result.rowsNeedsReview}</strong>
          , chybné: <strong>{result.rowsFailed}</strong>.
        </p>
        {result.duplicateFiles > 0 && (
          <p className="mt-1">Duplicitní soubory: {result.duplicateFiles}.</p>
        )}
      </div>
      <div className="space-y-2">
        {result.files.map((file, index) => (
          <div
            key={`${file.filename}-${file.status}-${index}`}
            className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-gray-800">{file.filename}</span>
              <span className="text-xs text-gray-500">{file.status}</span>
            </div>
            <p className="mt-1 text-xs text-gray-600">
              Řádky: {file.rowsTotal}; importováno: {file.rowsImported}; přeskočeno:{" "}
              {file.rowsSkipped}; revize: {file.rowsNeedsReview}; chyby: {file.rowsFailed}.
            </p>
            {"error" in file && <p className="mt-1 text-xs text-red-700">{file.error.message}</p>}
            {file.status === "failed" && file.batchId && (
              <p className="mt-1 text-xs text-gray-500">
                Batch {file.batchId}; poslední úspěšná fáze: {file.lastSuccessfulStage ?? "žádná"}.
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ImportPage() {
  const initialAccountLoadStarted = useRef(false)
  const [accountLoadState, setAccountLoadState] = useState<AccountLoadState>({
    status: "loading",
  })
  const [source, setSource] = useState<(typeof IMPORT_SOURCE_OPTIONS)[number]>(
    IMPORT_SOURCE_OPTIONS[0]
  )
  const [accountId, setAccountId] = useState("")
  const [files, setFiles] = useState<File[]>([])
  const [pageState, setPageState] = useState<ImportPageState>({ status: "idle" })
  const [toast, setToast] = useState<ToastState>(null)

  useEffect(() => {
    if (initialAccountLoadStarted.current) return
    initialAccountLoadStarted.current = true
    void requestAccounts()
      .then((accounts) => {
        setAccountLoadState({
          status: "ready",
          accounts: accounts.map(toAccountPageModel),
        })
      })
      .catch((error: unknown) => {
        setAccountId("")
        setAccountLoadState({
          status: "error",
          message:
            error instanceof AccountClientError ? error.message : "Účty se nepodařilo načíst.",
        })
      })
  }, [])

  const filteredAccounts =
    accountLoadState.status === "ready"
      ? accountLoadState.accounts.filter((account) => source.accepts.includes(account.type))
      : []

  function resetResult() {
    setPageState({ status: "idle" })
    setToast(null)
  }

  function handleSourceChange(nextSource: (typeof IMPORT_SOURCE_OPTIONS)[number]) {
    setSource(nextSource)
    setAccountId("")
    setFiles([])
    resetResult()
  }

  function handleReset() {
    setFiles([])
    resetResult()
  }

  async function handleImport() {
    if (
      accountLoadState.status !== "ready" ||
      accountId.length === 0 ||
      files.length === 0 ||
      pageState.status === "uploading" ||
      pageState.status === "recovering"
    ) {
      return
    }
    setPageState({ status: "uploading", completed: 0, total: files.length })
    setToast(null)
    try {
      const result = await requestImport(accountId, source.value, files)
      setPageState({ status: "completed", result })
      setFiles([])
      if (requiresImportFinalizationRecovery(result)) {
        setToast({
          kind: "error",
          title: "Aktualizace portfolia není dokončena",
          message: "Import je zaúčtovaný a lze bezpečně zopakovat pouze jeho dokončení.",
        })
      } else {
        setToast({
          kind: "success",
          title: "Import dokončen",
          message: `Dokončeno ${result.completedFiles} souborů.`,
        })
      }
    } catch (error) {
      const safeError =
        error instanceof ImportClientError
          ? error
          : new ImportClientError(502, "python_api_unavailable", "Import API není dostupné.")
      setPageState({
        status: "error",
        message: safeError.message,
        ...(safeError.partial ? { partial: safeError.partial } : {}),
      })
      setToast({
        kind: "error",
        title: "Import nebyl dokončen",
        message: safeError.message,
      })
    }
  }

  async function handleFinalizationRetry(result: ImportSummary) {
    const batchIds = recoverableBatchIds(result)
    if (accountId.length === 0 || batchIds.length === 0 || pageState.status === "recovering") {
      return
    }
    setPageState({ status: "recovering", result })
    setToast(null)
    try {
      const finalized = await requestImportFinalization(accountId, batchIds)
      const recovered = withImportFinalization(result, finalized.snapshotRefreshStatus)
      setPageState({ status: "completed", result: recovered })
      if (requiresImportFinalizationRecovery(recovered)) {
        setToast({
          kind: "error",
          title: "Aktualizace portfolia není dokončena",
          message: "Zaúčtovaná data zůstávají bezpečně dostupná pro další pokus.",
        })
      } else {
        setToast({
          kind: "success",
          title: "Aktualizace portfolia dokončena",
          message: "Zaúčtovaná data byla úspěšně promítnuta do portfolia.",
        })
      }
    } catch (error) {
      const safeError =
        error instanceof ImportClientError
          ? error
          : new ImportClientError(502, "python_api_unavailable", "Import API není dostupné.")
      setPageState({
        status: "error",
        message: safeError.message,
        partial: withImportFinalization(result, "not_run"),
      })
      setToast({
        kind: "error",
        title: "Aktualizaci portfolia se nepodařilo dokončit",
        message: safeError.message,
      })
    }
  }

  const isBusy = pageState.status === "uploading" || pageState.status === "recovering"
  const canImport =
    accountLoadState.status === "ready" && accountId.length > 0 && files.length > 0 && !isBusy

  return (
    <div className="max-w-2xl">
      {toast && (
        <div
          className={`fixed right-6 top-6 z-50 w-80 rounded-lg border px-4 py-3 text-sm shadow-lg ${
            toast.kind === "success"
              ? "border-green-200 bg-green-50 text-green-900"
              : "border-red-200 bg-red-50 text-red-900"
          }`}
        >
          <p className="font-semibold">{toast.title}</p>
          <p className="mt-1 text-xs">{toast.message}</p>
        </div>
      )}

      <h1 className="mb-6 text-2xl font-semibold">Import CSV</h1>
      <div className="space-y-5 rounded-xl border border-gray-200 bg-white p-6">
        <div>
          <label className="mb-2 block text-sm font-medium text-gray-700">Zdroj</label>
          <div className="flex flex-wrap gap-2">
            {IMPORT_SOURCE_OPTIONS.map((candidate) => (
              <button
                key={candidate.value}
                type="button"
                onClick={() => handleSourceChange(candidate)}
                disabled={isBusy}
                className={`rounded-lg border px-4 py-2 text-sm font-medium ${
                  source.value === candidate.value
                    ? "border-blue-600 bg-blue-600 text-white"
                    : "border-gray-300 text-gray-700"
                }`}
              >
                {candidate.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Účet</label>
          {accountLoadState.status === "loading" ? (
            <p className="text-sm text-gray-500">Načítám účty…</p>
          ) : accountLoadState.status === "error" ? (
            <p className="text-sm text-red-600">{accountLoadState.message}</p>
          ) : filteredAccounts.length === 0 ? (
            <p className="text-sm text-amber-700">
              Žádný kompatibilní účet (
              {source.accepts.map((type) => ACCOUNT_TYPE_LABELS[type]).join(", ")}).
            </p>
          ) : (
            <select
              value={accountId}
              disabled={isBusy}
              onChange={(event) => {
                setAccountId(event.target.value)
                resetResult()
              }}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">Vyber účet</option>
              {filteredAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {accountLoadState.status === "ready" && filteredAccounts.length > 0 && (
          <DropZone
            files={files}
            onFiles={(nextFiles) => {
              setFiles(nextFiles)
              resetResult()
            }}
          />
        )}

        {pageState.status === "uploading" && (
          <p className="text-sm text-blue-700">
            Zpracovávám {pageState.total} souborů přes Python API…
          </p>
        )}
        {pageState.status === "recovering" && (
          <p className="text-sm text-blue-700">Dokončuji aktualizaci portfolia přes Python API…</p>
        )}
        {pageState.status === "error" && (
          <div className="space-y-3">
            <p className="text-sm text-red-700">{pageState.message}</p>
            {pageState.partial && (
              <ImportResult
                result={pageState.partial}
                onRetry={() => handleFinalizationRetry(pageState.partial!)}
              />
            )}
          </div>
        )}
        {pageState.status === "recovering" && (
          <ImportResult
            result={pageState.result}
            onRetry={() => handleFinalizationRetry(pageState.result)}
            retrying
          />
        )}
        {pageState.status === "completed" && (
          <ImportResult
            result={pageState.result}
            onRetry={() => handleFinalizationRetry(pageState.result)}
          />
        )}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleImport}
            disabled={!canImport}
            className="flex-1 rounded-lg bg-blue-600 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {isBusy
              ? pageState.status === "recovering"
                ? "Dokončuji…"
                : "Importuji…"
              : files.length > 1
                ? `Importovat ${files.length} souborů`
                : "Importovat"}
          </button>
          {(files.length > 0 ||
            pageState.status === "completed" ||
            pageState.status === "error") && (
            <button
              type="button"
              onClick={handleReset}
              disabled={isBusy}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      <div className="mt-6 space-y-1 text-xs text-gray-400">
        <p>Raiffeisenbank: Internetbanking → Pohyby / Karty → Export CSV</p>
        <p>Trading 212: History → Export CSV</p>
        <p>Anycoin: Účet → Přehled transakcí → Export</p>
      </div>
    </div>
  )
}
