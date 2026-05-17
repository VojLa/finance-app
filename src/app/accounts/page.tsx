"use client"

import { useEffect, useState } from "react"
import { ACCOUNT_TYPES, ACCOUNT_TYPE_LABELS } from "@/lib/constants"

type Account = {
  id: string
  name: string
  type: string
  currency: string
  color: string | null
}

type EditForm = { name: string; type: string; currency: string }

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState("")
  const [type, setType] = useState("broker")
  const [currency, setCurrency] = useState("EUR")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({ name: "", type: "", currency: "" })
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState("")

  async function load() {
    const res = await fetch("/api/accounts")
    if (res.ok) setAccounts(await res.json())
  }

  useEffect(() => { load() }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError("")
    const res = await fetch("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, type, currency }),
    })
    setLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setError(d.error)
    } else {
      setName("")
      setType("broker")
      setCurrency("EUR")
      setShowForm(false)
      load()
    }
  }

  function startEdit(acc: Account) {
    setEditingId(acc.id)
    setEditForm({ name: acc.name, type: acc.type, currency: acc.currency })
    setEditError("")
  }

  function cancelEdit() {
    setEditingId(null)
    setEditError("")
  }

  async function handleEdit(e: React.FormEvent, id: string) {
    e.preventDefault()
    setEditLoading(true)
    setEditError("")
    const res = await fetch(`/api/accounts?id=${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editForm),
    })
    setEditLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setEditError(d.error)
    } else {
      setEditingId(null)
      load()
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Smazat účet? Smažou se i všechny transakce a holdings.")) return
    await fetch(`/api/accounts?id=${id}`, { method: "DELETE" })
    load()
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Účty</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + Přidat účet
        </button>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-medium mb-4">Nový účet</h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Název</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                required
                placeholder="Trading 212"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Typ</label>
              <select
                value={type}
                onChange={e => setType(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {ACCOUNT_TYPES.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Měna</label>
              <select
                value={currency}
                onChange={e => setCurrency(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="EUR">EUR</option>
                <option value="CZK">CZK</option>
                <option value="USD">USD</option>
              </select>
            </div>
            {error && <p className="col-span-3 text-sm text-red-600">{error}</p>}
            <div className="col-span-3 flex gap-3">
              <button
                type="submit"
                disabled={loading}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? "Ukládám..." : "Vytvořit"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Zrušit
              </button>
            </div>
          </form>
        </div>
      )}

      {accounts.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-gray-400">
          Žádné účty. Přidej první účet výše.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {accounts.map(acc => (
            <div key={acc.id} className="bg-white rounded-xl border border-gray-200 p-5">
              {editingId === acc.id ? (
                <form onSubmit={e => handleEdit(e, acc.id)} className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Název</label>
                    <input
                      value={editForm.name}
                      onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                      required
                      className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Typ</label>
                    <select
                      value={editForm.type}
                      onChange={e => setEditForm(f => ({ ...f, type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {ACCOUNT_TYPES.map(t => (
                        <option key={t.value} value={t.value}>{t.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Měna</label>
                    <select
                      value={editForm.currency}
                      onChange={e => setEditForm(f => ({ ...f, currency: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="EUR">EUR</option>
                      <option value="CZK">CZK</option>
                      <option value="USD">USD</option>
                    </select>
                  </div>
                  {editError && <p className="text-xs text-red-600">{editError}</p>}
                  <div className="flex gap-2 pt-1">
                    <button
                      type="submit"
                      disabled={editLoading}
                      className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
                    >
                      {editLoading ? "Ukládám..." : "Uložit"}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-100"
                    >
                      Zrušit
                    </button>
                  </div>
                </form>
              ) : (
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-gray-900">{acc.name}</p>
                    <p className="text-sm text-gray-500 mt-0.5">
                      {ACCOUNT_TYPE_LABELS[acc.type] ?? acc.type} · {acc.currency}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => startEdit(acc)}
                      className="text-gray-300 hover:text-blue-500 p-1 rounded transition-colors"
                      title="Upravit"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => handleDelete(acc.id)}
                      className="text-gray-300 hover:text-red-500 p-1 rounded transition-colors text-lg leading-none"
                      title="Smazat"
                    >
                      ×
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
