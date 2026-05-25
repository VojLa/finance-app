"use client"

import { useEffect, useRef, useState } from "react"
import Papa from "papaparse"

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

type RawCsvPreview = {
  headers: string[]
  rows: Record<string, string>[]
}

type ImportResult = {
  imported: number
  skipped: number
  duplicates?: number
  parsed?: number
  rowsTotal?: number
  duplicateFile?: boolean
}

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

const TYPE_LABEL: Record<string, string> = {
  income: "Příjem",
  expense: "Výdaj",
  transfer: "Převod",
}

const TYPE_COLOR: Record<string, string> = {
  income: "text-green-600",
  expense: "text-red-600",
  transfer: "text-gray-600",
}

function DropZone({
  onFile,
  file,
}: {
  onFile: (f: File) => void | Promise<void>
  file: File | null
}) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
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
        accept=".csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onFile(f)
          e.target.value = ""
        }}
      />
      {file ? (
        <div className="space-y-1">
          <p className="text-sm font-medium text-gray-800">{file.name}</p>
          <p className="text-xs text-gray-400">
            {(file.size / 1024).toFixed(1)} KB · klikni nebo přetáhni jiný soubor
          </p>
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
  const [file, setFile] = useState<File | null>(null)

  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState("")
  const [rawPreview, setRawPreview] = useState<RawCsvPreview | null>(null)
  const [rawPreviewError, setRawPreviewError] = useState("")

  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [importError, setImportError] = useState("")

  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then(setAccounts)
  }, [])

  useEffect(() => {
    const previewUrl = source.previewEndpoint
    if (!file || !accountId || !previewUrl) {
      setPreview(null)
      return
    }

    let cancelled = false
    setPreviewLoading(true)
    setPreviewError("")
    setPreview(null)

    const fd = new FormData()
    fd.append("file", file)
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
  }, [file, accountId, source.previewEndpoint])

  const filteredAccounts = accounts.filter((a) => source.accepts.includes(a.type))

  function handleSourceChange(s: (typeof SOURCES)[0]) {
    setSource(s)
    setAccountId("")
    setFile(null)
    setPreview(null)
    setPreviewError("")
    setRawPreview(null)
    setRawPreviewError("")
    setResult(null)
    setImportError("")
  }

  async function handleFile(f: File) {
    setFile(f)
    setRawPreview(null)
    setRawPreviewError("")
    setResult(null)
    setImportError("")

    try {
      const text = await f.text()
      const parsed = Papa.parse<Record<string, string>>(text, {
        header: true,
        skipEmptyLines: true,
      })

      const headers = parsed.meta.fields ?? []
      const rows = parsed.data.filter((row) =>
        headers.some((header) => (row[header] ?? "").trim() !== "")
      )

      setRawPreview({ headers, rows })
    } catch {
      setRawPreviewError("CSV soubor se nepodarilo precist.")
    }
  }

  function handleReset() {
    setFile(null)
    setPreview(null)
    setPreviewError("")
    setRawPreview(null)
    setRawPreviewError("")
    setResult(null)
    setImportError("")
  }

  async function handleImport() {
    if (!file || !accountId) return
    setImporting(true)
    setImportError("")

    const fd = new FormData()
    fd.append("file", file)
    fd.append("accountId", accountId)

    try {
      const res = await fetch(source.endpoint, { method: "POST", body: fd })
      const data = (await res.json()) as ImportResult & { error?: string }
      if (!res.ok) {
        setImportError(data.error ?? `Import selhal (status ${res.status}).`)
      } else {
        setResult({
          imported: data.imported ?? 0,
          skipped: data.skipped ?? 0,
          duplicates: data.duplicates,
          parsed: data.parsed,
          rowsTotal: data.rowsTotal,
          duplicateFile: data.duplicateFile,
        })
        setFile(null)
        setPreview(null)
      }
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import selhal.")
    } finally {
      setImporting(false)
    }
  }

  const canImport = !!file && !!accountId && !previewLoading && !importing

  return (
    <div className="max-w-2xl">
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
            <DropZone onFile={handleFile} file={file} />
          </div>
        )}

        {previewLoading && <p className="text-sm text-gray-400">Načítám náhled...</p>}

        {rawPreviewError && <p className="text-sm text-red-600">{rawPreviewError}</p>}

        {rawPreview && rawPreview.headers.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="font-medium text-gray-800">
                Prectene CSV radky: {rawPreview.rows.length}
              </span>
              <span className="text-xs text-gray-400">Hlavicka se do poctu nepocita</span>
            </div>

            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="max-h-96 overflow-auto">
                <table className="min-w-full text-xs">
                  <thead className="bg-gray-50 sticky top-0 border-b border-gray-200">
                    <tr>
                      <th className="px-3 py-2 text-left text-gray-500 font-medium">#</th>
                      {rawPreview.headers.map((header) => (
                        <th
                          key={header}
                          className="px-3 py-2 text-left text-gray-500 font-medium whitespace-nowrap"
                        >
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {rawPreview.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        <td className="px-3 py-1.5 text-gray-400 tabular-nums">{rowIndex + 1}</td>
                        {rawPreview.headers.map((header) => (
                          <td key={header} className="px-3 py-1.5 text-gray-600 whitespace-nowrap">
                            {row[header] || "-"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

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

            {preview.rows.length > 0 && (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="max-h-72 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 sticky top-0 border-b border-gray-200">
                      <tr>
                        <th className="px-3 py-2 text-left text-gray-500 font-medium">Datum</th>
                        <th className="px-3 py-2 text-left text-gray-500 font-medium">Typ</th>
                        <th className="px-3 py-2 text-right text-gray-500 font-medium">Částka</th>
                        <th className="px-3 py-2 text-left text-gray-500 font-medium">
                          Protistrana
                        </th>
                        <th className="px-3 py-2 text-left text-gray-500 font-medium">Popis</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {preview.rows.map((row, i) => (
                        <tr key={i} className={row.isDuplicate ? "opacity-35" : ""}>
                          <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">
                            {new Date(row.date).toLocaleDateString("cs-CZ")}
                          </td>
                          <td
                            className={`px-3 py-1.5 whitespace-nowrap ${TYPE_COLOR[row.type] ?? "text-gray-600"}`}
                          >
                            {TYPE_LABEL[row.type] ?? row.type}
                          </td>
                          <td
                            className={`px-3 py-1.5 text-right whitespace-nowrap font-medium tabular-nums ${TYPE_COLOR[row.type] ?? "text-gray-600"}`}
                          >
                            {row.type === "income" ? "+" : row.type === "expense" ? "−" : ""}
                            {row.amount.toLocaleString("cs-CZ")} {row.currency}
                          </td>
                          <td className="px-3 py-1.5 text-gray-600 max-w-[8rem] truncate">
                            {row.counterparty || "—"}
                          </td>
                          <td className="px-3 py-1.5 text-gray-400 max-w-[12rem] truncate">
                            {row.description || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {importError && <p className="text-sm text-red-600">{importError}</p>}

        {result && (
          <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-800">
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
            <p className="mt-1 text-green-700">
              Detekovano CSV radku: <strong>{result.rowsTotal ?? result.parsed ?? 0}</strong>
              {result.parsed !== undefined && result.rowsTotal !== undefined && (
                <>
                  , normalizovanych transakci: <strong>{result.parsed}</strong>
                </>
              )}
            </p>
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
                ? "Importuji..."
                : preview
                  ? `Importovat ${preview.counts.new} transakcí`
                  : "Importovat"}
            </button>
            {file && (
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
