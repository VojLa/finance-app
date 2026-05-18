"use client"

import { useEffect, useState } from "react"
import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"

type Account = { id: string; name: string; type: string }
type ImportResult = { imported: number; skipped: number } | null

const SOURCES = [
  { value: "trading212",    label: "Trading 212",    endpoint: "/api/import/trading212",    accepts: ["broker"] },
  { value: "anycoin",       label: "Anycoin",         endpoint: "/api/import/anycoin",        accepts: ["exchange"] },
  { value: "raiffeisenbank", label: "Raiffeisenbank", endpoint: "/api/import/raiffeisenbank", accepts: ["bank"] },
]

export default function ImportPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [source, setSource] = useState(SOURCES[0])
  const [accountId, setAccountId] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ImportResult>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    fetch("/api/accounts").then(r => r.json()).then(setAccounts)
  }, [])

  const filteredAccounts = accounts.filter(a => source.accepts.includes(a.type))

  function handleSourceChange(s: typeof SOURCES[0]) {
    setSource(s)
    setAccountId("")
    setResult(null)
    setError("")
  }

  async function handleImport(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !accountId) return
    setLoading(true)
    setError("")
    setResult(null)

    const fd = new FormData()
    fd.append("file", file)
    fd.append("accountId", accountId)

    try {
    const res = await fetch(source.endpoint, {
      method: "POST",
      body: fd,
    })

    const text = await res.text()

    let data: any = null

    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }

    setLoading(false)

    if (!res.ok) {
      setError(
        data?.error ||
        text ||
        `Import selhal. Server vrátil status ${res.status}.`
      )
      return
    }

    if (!data) {
      setError("Import endpoint nevrátil žádná JSON data.")
      return
    }

    setResult(data)
    setFile(null)
  } catch (err) {
    setLoading(false)
    setError(err instanceof Error ? err.message : "Import selhal.")
  }
  }

  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold mb-6">Import CSV</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <form onSubmit={handleImport} className="space-y-5">
          {/* Výběr zdroje */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Zdroj</label>
            <div className="flex gap-2 flex-wrap">
              {SOURCES.map(s => (
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

          {/* Výběr účtu */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Účet</label>
            {filteredAccounts.length === 0 ? (
              <p className="text-sm text-amber-600">
                Žádný kompatibilní účet (typ:{" "}
                {source.accepts.map(t => ACCOUNT_TYPE_LABELS[t]).join(", ")}). Nejdřív přidej účet na stránce{" "}
                <a href="/accounts" className="underline">Účty</a>.
              </p>
            ) : (
              <select
                value={accountId}
                onChange={e => setAccountId(e.target.value)}
                required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Vyber účet</option>
                {filteredAccounts.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            )}
          </div>

          {/* Upload souboru */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">CSV soubor</label>
            <input
              type="file"
              accept=".csv"
              onChange={e => setFile(e.target.files?.[0] ?? null)}
              required
              className="w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          {result && (
            <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-800">
              Importováno: <strong>{result.imported}</strong> transakcí,
              přeskočeno (duplicity): <strong>{result.skipped}</strong>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || filteredAccounts.length === 0}
            className="w-full bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Importuji..." : "Importovat"}
          </button>
        </form>
      </div>

      {/* Nápověda k formátům */}
      <div className="mt-6 text-xs text-gray-400 space-y-1">
        <p><strong className="text-gray-500">Trading 212:</strong> Exportovat z app → History → Export CSV</p>
        <p><strong className="text-gray-500">Anycoin:</strong> Účet → Přehled transakcí → Export</p>
        <p><strong className="text-gray-500">Raiffeisenbank:</strong> Internetbanking → Pohyby → Export CSV (UTF-8, středník)</p>
      </div>
    </div>
  )
}
