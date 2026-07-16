"use client"

import { useEffect, useRef, useState } from "react"

import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"

type Account = { id: string; name: string; type: string }

type PreviewRow = {
  date: string
  amount: number
  currency: string
  type: string
  description: string
  counterparty: string
  isDuplicate: boolean
}

type PreviewData = {
  rows: PreviewRow[]
  counts: { new: number; duplicate: number }
}

type ParseIssue = {
  severity: "ignored" | "warning" | "error"
  code: string
  message: string
  rowNumber?: number
  raw?: Record<string, string>
  filename?: string
}

type ImportResult = {
  accepted?: boolean
  batchId?: string
  status?: string
  imported: number
  skipped: number
  duplicates?: number
  parsed?: number
  rowsTotal?: number
  duplicateFile?: boolean
  parseIssues?: ParseIssue[]
  filename?: string
  error?: string
  detail?: string
}

type ImportSummary = ImportResult & {
  files: ImportResult[]
  failed: number
}

type ImportStatusResponse = {
  batches: Array<
    ImportResult & { id: string; status: string; completedAt?: string; error?: string | null }
  >
}

type ToastState = {
  kind: "success" | "error"
  title: string
  message: string
} | null

const SOURCES = [
  {
    value: "raiffeisenbank",
    label: "Raiffeisenbank",
    endpoint: "/api/import/raiffeisenbank",
    previewEndpoint: "/api/import/raiffeisenbank/preview",
    accepts: ["bank"],
  },
  {
    value: "trading212",
    label: "Trading 212",
    endpoint: "/api/import/trading212",
    previewEndpoint: null as string | null,
    accepts: ["broker"],
  },
  {
    value: "anycoin",
    label: "Anycoin",
    endpoint: "/api/import/anycoin",
    previewEndpoint: null as string | null,
    accepts: ["exchange"],
  },
]

const ISSUE_SEVERITY_LABEL: Record<ParseIssue["severity"], string> = {
  ignored: "Ignorovano",
  warning: "Varovani",
  error: "Chyba",
}

function rawIssuePreview(raw: Record<string, string> | undefined) {
  if (!raw) return "-"
  const values = Object.entries(raw)
    .filter(([, value]) => value && value.trim() !== "")
    .slice(0, 8)
    .map(([key, value]) => `${key}: ${value}`)

  return values.length > 0 ? values.join(" | ") : "-"
}

function DropZone({
  onFiles,
  files,
}: {
  onFiles: (files: File[]) => void | Promise<void>
  files: File[]
}) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length > 0) onFiles(droppedFiles)
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer border-2 border-dashed rounded-xl p-8 text-center transition-colors select-none ${
        dragging
          ? "border-blue-400 bg-blue-50"
          : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".csv"
        className="hidden"
        onChange={(e) => {
          const selectedFiles = Array.from(e.target.files ?? [])
          if (selectedFiles.length > 0) onFiles(selectedFiles)
          e.target.value = ""
        }}
      />
      {files.length > 0 ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-800">Vybrano souboru: {files.length}</p>
          <div className="space-y-1">
            {files.slice(0, 5).map((file) => (
              <p
                key={`${file.name}-${file.size}-${file.lastModified}`}
                className="text-xs text-gray-500"
              >
                {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </p>
            ))}
            {files.length > 5 && (
              <p className="text-xs text-gray-400">+ dalsich {files.length - 5}</p>
            )}
          </div>
          <p className="text-xs text-gray-400">klikni nebo pretahni soubory pro novy vyber</p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-2xl text-gray-300">↑</p>
          <p className="text-sm font-medium text-gray-600">Přetáhni CSV soubor sem</p>
          <p className="text-xs text-gray-400">nebo klikni pro výběr souboru</p>
        </div>
      )}
    </div>
  )
}

export default function ImportPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [source, setSource] = useState(SOURCES[0])
  const [accountId, setAccountId] = useState("")
  const [files, setFiles] = useState<File[]>([])

  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState("")

  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportSummary | null>(null)
  const [importError, setImportError] = useState("")
  const [activeBatchIds, setActiveBatchIds] = useState<string[]>([])
  const [toast, setToast] = useState<ToastState>(null)
  const previewFile = files[0] ?? null

  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then(setAccounts)
  }, [])

  useEffect(() => {
    if (activeBatchIds.length === 0) return

    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`/api/import/status?ids=${activeBatchIds.join(",")}`)
        const data = (await res.json()) as ImportStatusResponse & { error?: string }
        if (cancelled) return
        if (!res.ok) throw new Error(data.error || "Nepodarilo se nacist stav importu.")

        const batches = data.batches ?? []
        const done =
          batches.length === activeBatchIds.length &&
          batches.every((batch) =>
            ["completed", "failed", "cancelled", "partially_completed"].includes(batch.status)
          )

        if (!done) return

        const summary = batches.reduce<ImportSummary>(
          (acc, batch) => ({
            ...acc,
            imported: acc.imported + (batch.imported ?? 0),
            skipped: acc.skipped + (batch.skipped ?? 0),
            duplicates: (acc.duplicates ?? 0) + (batch.duplicates ?? 0),
            parsed: (acc.parsed ?? 0) + (batch.parsed ?? 0),
            rowsTotal: (acc.rowsTotal ?? 0) + (batch.rowsTotal ?? 0),
            parseIssues: [
              ...(acc.parseIssues ?? []),
              ...((batch.parseIssues ?? []).map((issue) => ({
                ...issue,
                filename: batch.filename,
              })) as ParseIssue[]),
            ],
            failed: acc.failed + (batch.status === "failed" ? 1 : 0),
          }),
          {
            imported: 0,
            skipped: 0,
            duplicates: 0,
            parsed: 0,
            rowsTotal: 0,
            parseIssues: [],
            files: [],
            failed: 0,
          }
        )
        summary.files = batches
        setResult(summary)
        setImporting(false)
        setActiveBatchIds([])

        if (summary.failed > 0) {
          setImportError(`Nepodarilo se importovat ${summary.failed} z ${batches.length} souboru.`)
          setToast({
            kind: "error",
            title: "Import selhal",
            message: `Chybne soubory: ${summary.failed}.`,
          })
        } else {
          setFiles([])
          setPreview(null)
          setToast({
            kind: "success",
            title: "Import dokoncen",
            message: `Importovano ${summary.imported}, preskoceno ${summary.skipped}. Neprectene radky: ${summary.parseIssues?.length ?? 0}.`,
          })
        }
      } catch (error) {
        if (cancelled) return
        setImporting(false)
        setActiveBatchIds([])
        setImportError(error instanceof Error ? error.message : "Import selhal.")
        setToast({
          kind: "error",
          title: "Import selhal",
          message: error instanceof Error ? error.message : "Import selhal.",
        })
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [activeBatchIds])

  useEffect(() => {
    const previewUrl = source.previewEndpoint
    if (!previewFile || !accountId || !previewUrl) {
      setPreview(null)
      return
    }

    let cancelled = false
    setPreviewLoading(true)
    setPreviewError("")
    setPreview(null)

    const fd = new FormData()
    fd.append("file", previewFile)
    fd.append("accountId", accountId)

    fetch(previewUrl, { method: "POST", body: fd })
      .then(async (r) => {
        const data = (await r.json()) as PreviewData & { error?: string }
        if (cancelled) return
        if (!r.ok) {
          setPreviewError(data.error ?? "Náhled se nepodařilo načíst.")
        } else {
          setPreview(data)
        }
      })
      .catch(() => {
        if (!cancelled) setPreviewError("Nepodařilo se připojit k serveru.")
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [previewFile, accountId, source.previewEndpoint])

  const filteredAccounts = accounts.filter((a) => source.accepts.includes(a.type))

  function handleSourceChange(s: (typeof SOURCES)[0]) {
    setSource(s)
    setAccountId("")
    setFiles([])
    setPreview(null)
    setPreviewError("")
    setResult(null)
    setImportError("")
    setToast(null)
  }

  async function handleFiles(selectedFiles: File[]) {
    const csvFiles = selectedFiles.filter((selectedFile) =>
      selectedFile.name.toLowerCase().endsWith(".csv")
    )
    const nextFiles = csvFiles.length > 0 ? csvFiles : selectedFiles

    setFiles(nextFiles)
    setResult(null)
    setImportError("")
    setToast(null)
  }

  function handleReset() {
    setFiles([])
    setPreview(null)
    setPreviewError("")
    setResult(null)
    setImportError("")
    setActiveBatchIds([])
    setToast(null)
  }

  async function handleImport() {
    if (files.length === 0 || !accountId) return
    setImporting(true)
    setImportError("")

    try {
      const fd = new FormData()
      for (const currentFile of files) fd.append("file", currentFile)
      fd.append("accountId", accountId)

      const res = await fetch(source.endpoint, { method: "POST", body: fd })
      const data = (await res.json()) as {
        batchIds?: string[]
        files?: ImportResult[]
        error?: string
        detail?: string
      }

      if (!res.ok)
        throw new Error(data.detail ?? data.error ?? `Import selhal (status ${res.status}).`)

      const batchIds = (data.batchIds ??
        data.files?.map((file) => file.batchId).filter(Boolean) ??
        []) as string[]
      if (batchIds.length === 0) {
        const perFile = data.files ?? []
        const summary = perFile.reduce<ImportSummary>(
          (acc, item) => ({
            ...acc,
            imported: acc.imported + item.imported,
            skipped: acc.skipped + item.skipped,
            duplicates: (acc.duplicates ?? 0) + (item.duplicates ?? 0),
            parsed: (acc.parsed ?? 0) + (item.parsed ?? 0),
            rowsTotal: (acc.rowsTotal ?? 0) + (item.rowsTotal ?? 0),
            parseIssues: [...(acc.parseIssues ?? []), ...(item.parseIssues ?? [])],
            failed: acc.failed + (item.error ? 1 : 0),
          }),
          {
            imported: 0,
            skipped: 0,
            duplicates: 0,
            parsed: 0,
            rowsTotal: 0,
            parseIssues: [],
            files: [],
            failed: 0,
          }
        )
        summary.files = perFile
        setResult(summary)
        setImporting(false)
        return
      }

      setActiveBatchIds(batchIds)
      setToast({
        kind: "success",
        title: "Import prijat",
        message: `Zpracovavam ${batchIds.length} souboru na pozadi.`,
      })
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import selhal.")
      setImporting(false)
    }
  }

  const canImport = files.length > 0 && !!accountId && !previewLoading && !importing

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
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-semibold">{toast.title}</p>
              <p className="mt-1 text-xs opacity-80">{toast.message}</p>
            </div>
            <button
              type="button"
              onClick={() => setToast(null)}
              className="text-lg leading-none opacity-50 hover:opacity-80"
              aria-label="Zavrit notifikaci"
            >
              ×
            </button>
          </div>
        </div>
      )}
      <h1 className="text-2xl font-semibold mb-6">Import CSV</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Zdroj</label>
          <div className="flex gap-2 flex-wrap">
            {SOURCES.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => handleSourceChange(s)}
                className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  source.value === s.value
                    ? "bg-blue-600 text-white border-blue-600"
                    : "border-gray-300 text-gray-700 hover:bg-gray-50"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Účet</label>
          {filteredAccounts.length === 0 ? (
            <p className="text-sm text-amber-600">
              Žádný kompatibilní účet (typ:{" "}
              {source.accepts.map((t) => ACCOUNT_TYPE_LABELS[t]).join(", ")}). Nejdřív přidej účet
              na stránce{" "}
              <a href="/accounts" className="underline">
                Účty
              </a>
              .
            </p>
          ) : (
            <select
              value={accountId}
              onChange={(e) => {
                setAccountId(e.target.value)
                setPreview(null)
                setPreviewError("")
              }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Vyber účet</option>
              {filteredAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {filteredAccounts.length > 0 && !result && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">CSV soubor</label>
            <DropZone onFiles={handleFiles} files={files} />
          </div>
        )}

        {previewLoading && <p className="text-sm text-gray-400">Načítám náhled...</p>}

        {previewError && <p className="text-sm text-red-600">{previewError}</p>}

        {preview && !previewLoading && (
          <div className="space-y-3">
            <div className="flex items-center gap-4 text-sm">
              <span className="font-medium text-gray-800">
                {preview.counts.new} nových transakcí
              </span>
              {preview.counts.duplicate > 0 && (
                <span className="text-gray-400">
                  {preview.counts.duplicate} duplicit (budou přeskočeny)
                </span>
              )}
            </div>
          </div>
        )}

        {importError && <p className="text-sm text-red-600">{importError}</p>}

        {result && (
          <div
            className={`rounded-lg border px-4 py-3 text-sm ${
              result.failed > 0
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-green-200 bg-green-50 text-green-800"
            }`}
          >
            {result.duplicateFile && (
              <p className="font-medium mb-1">
                Tento soubor uz byl importovan. Nove transakce nebyly pridany.
              </p>
            )}
            <p>
              Importováno: <strong>{result.imported}</strong> transakcí
              {result.skipped > 0 && (
                <>
                  , přeskočeno (duplicity): <strong>{result.skipped}</strong>
                </>
              )}
            </p>
            {result.failed > 0 && (
              <p className="mt-1 font-medium">Chybne soubory: {result.failed}</p>
            )}
            <p className={`mt-1 ${result.failed > 0 ? "text-amber-800" : "text-green-700"}`}>
              Detekovano CSV radku: <strong>{result.rowsTotal ?? result.parsed ?? 0}</strong>
              {result.parsed !== undefined && result.rowsTotal !== undefined && (
                <>
                  , normalizovanych transakci: <strong>{result.parsed}</strong>
                </>
              )}
            </p>
          </div>
        )}

        {result && result.parseIssues && result.parseIssues.length > 0 && (
          <div className="border border-amber-200 rounded-lg overflow-hidden">
            <div className="bg-amber-50 px-4 py-3">
              <p className="text-sm font-medium text-amber-900">
                Neprectene radky: {result.parseIssues.length}
              </p>
              <p className="text-xs text-amber-700">
                Tyto radky parser ignoroval nebo je neumel bezpecne zpracovat.
              </p>
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-white sticky top-0 border-y border-amber-100">
                  <tr>
                    {result.files.length > 1 && (
                      <th className="px-3 py-2 text-left text-gray-500 font-medium">Soubor</th>
                    )}
                    <th className="px-3 py-2 text-left text-gray-500 font-medium">Radek</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium">Stav</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium">Duvod</th>
                    <th className="px-3 py-2 text-left text-gray-500 font-medium">Data</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-amber-100 bg-white">
                  {result.parseIssues.map((issue, index) => (
                    <tr key={`${issue.filename ?? "file"}-${issue.rowNumber ?? index}-${index}`}>
                      {result.files.length > 1 && (
                        <td className="px-3 py-2 text-gray-500 whitespace-nowrap">
                          {issue.filename ?? "-"}
                        </td>
                      )}
                      <td className="px-3 py-2 text-gray-500 tabular-nums whitespace-nowrap">
                        {issue.rowNumber ?? "-"}
                      </td>
                      <td className="px-3 py-2 text-gray-600 whitespace-nowrap">
                        {ISSUE_SEVERITY_LABEL[issue.severity] ?? issue.severity}
                      </td>
                      <td className="px-3 py-2 text-gray-700 min-w-[14rem]">{issue.message}</td>
                      <td className="px-3 py-2 text-gray-500 min-w-[22rem]">
                        {rawIssuePreview(issue.raw)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!result ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleImport}
              disabled={!canImport}
              className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {importing
                ? activeBatchIds.length > 0
                  ? "Zpracovavam..."
                  : "Prijimam import..."
                : files.length > 1
                  ? `Importovat ${files.length} souboru`
                  : preview
                    ? `Importovat ${preview.counts.new} transakcí`
                    : "Importovat"}
            </button>
            {files.length > 0 && (
              <button
                type="button"
                onClick={handleReset}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
              >
                Zrušit
              </button>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={handleReset}
            className="w-full border border-gray-300 text-gray-700 rounded-lg py-2 text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Importovat další soubor
          </button>
        )}
      </div>

      <div className="mt-6 text-xs text-gray-400 space-y-1">
        <p>
          <strong className="text-gray-500">Raiffeisenbank:</strong> Internetbanking → Pohyby /
          Karty → Export CSV
        </p>
        <p>
          <strong className="text-gray-500">Trading 212:</strong> History → Export CSV
        </p>
        <p>
          <strong className="text-gray-500">Anycoin:</strong> Účet → Přehled transakcí → Export
        </p>
      </div>
    </div>
  )
}
