"use client"

import { useCallback, useEffect, useState } from "react"
import { ACCOUNT_TYPES, ACCOUNT_TYPE_LABELS } from "@/lib/constants"
import { fmt, fmtCzk } from "@/lib/format"
import type { AccountCash } from "@/types"

type Account = {
  id: string
  name: string
  type: string
  currency: string
  color: string | null
  isShared?: boolean
  shareRole?: string
}

type EditForm = { name: string; type: string; currency: string }

interface AccountMemberShare {
  id: string
  role: string
  sharedWith: { id: string; email: string; name: string | null }
}

function AccountBalance({
  cash,
  accountCurrency,
}: {
  cash: AccountCash | undefined
  accountCurrency: string
}) {
  if (!cash || cash.balances.length === 0) {
    return <p className="text-sm text-gray-400 mt-2">Žádné transakce</p>
  }

  const primary = cash.balances.find((b) => b.currency === accountCurrency) ?? cash.balances[0]
  const isNegative = primary.amount < 0

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      <p
        className={`text-lg font-semibold tabular-nums ${isNegative ? "text-red-600" : "text-gray-900"}`}
      >
        {fmt(primary.amount)} {primary.currency}
      </p>
      {primary.currency !== "CZK" && (
        <p className="text-xs text-gray-400 mt-0.5">≈ {fmtCzk(primary.amountCzk)}</p>
      )}
      {cash.balances.length > 1 && (
        <div className="mt-1 space-y-0.5">
          {cash.balances
            .filter((b) => b.currency !== primary.currency)
            .map((b) => (
              <p key={b.currency} className="text-xs text-gray-400 tabular-nums">
                {fmt(b.amount)} {b.currency}
              </p>
            ))}
        </div>
      )}
    </div>
  )
}

function ShareDialog({
  accountId,
  accountName,
  onClose,
}: {
  accountId: string
  accountName: string
  onClose: () => void
}) {
  const [shares, setShares] = useState<AccountMemberShare[]>([])
  const [email, setEmail] = useState("")
  const [role, setRole] = useState<"viewer" | "editor">("viewer")
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState("")

  const loadShares = useCallback(async () => {
    const res = await fetch(`/api/accounts/${accountId}/shares`)
    if (res.ok) setShares(await res.json())
  }, [accountId])

  useEffect(() => {
    loadShares()
  }, [loadShares])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    setAdding(true)
    setError("")
    const res = await fetch(`/api/accounts/${accountId}/shares`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    })
    setAdding(false)
    if (res.ok) {
      setEmail("")
      loadShares()
    } else {
      const data = await res.json()
      setError(data.error ?? "Nepodařilo se přidat přístup")
    }
  }

  async function handleRemove(shareId: string) {
    await fetch(`/api/accounts/${accountId}/shares/${shareId}`, { method: "DELETE" })
    loadShares()
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between p-5 border-b border-gray-100">
          <h2 className="text-base font-semibold">Sdílení — {accountName}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-5 space-y-4">
          <form onSubmit={handleAdd} className="flex gap-2">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="E-mail uživatele"
              required
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "viewer" | "editor")}
              className="border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="viewer">Prohlížeč</option>
              <option value="editor">Editor</option>
            </select>
            <button
              type="submit"
              disabled={adding}
              className="bg-blue-600 text-white px-3 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 shrink-0"
            >
              Přidat
            </button>
          </form>
          {error && <p className="text-sm text-red-600">{error}</p>}

          {shares.length > 0 ? (
            <div className="divide-y divide-gray-100">
              {shares.map((s) => (
                <div key={s.id} className="py-2.5 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{s.sharedWith.email}</p>
                    {s.sharedWith.name && (
                      <p className="text-xs text-gray-400">{s.sharedWith.name}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        s.role === "editor"
                          ? "bg-blue-50 text-blue-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {s.role === "editor" ? "Editor" : "Prohlížeč"}
                    </span>
                    <button
                      onClick={() => handleRemove(s.id)}
                      className="text-gray-300 hover:text-red-500 transition-colors text-lg leading-none"
                    >
                      ×
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400 text-center py-2">Účet zatím není sdílen</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [cashMap, setCashMap] = useState<Record<string, AccountCash>>({})
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

  const [sharingAccountId, setSharingAccountId] = useState<string | null>(null)

  async function load() {
    const [accRes, cashRes] = await Promise.all([
      fetch("/api/accounts"),
      fetch("/api/accounts/cash"),
    ])
    if (accRes.ok) setAccounts(await accRes.json())
    if (cashRes.ok) {
      const cashData = await cashRes.json()
      const map: Record<string, AccountCash> = {}
      for (const a of cashData.accounts ?? []) map[a.accountId] = a
      setCashMap(map)
    }
  }

  useEffect(() => {
    load()
  }, [])

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
      const d = await res.json().catch(() => ({}))
      setError(d.error ?? "Nepodařilo se vytvořit účet")
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
      const d = await res.json().catch(() => ({}))
      setEditError(d.error ?? "Nepodařilo se upravit účet")
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

  const sharingAccount = accounts.find((a) => a.id === sharingAccountId)

  return (
    <div>
      {sharingAccountId && sharingAccount && (
        <ShareDialog
          accountId={sharingAccountId}
          accountName={sharingAccount.name}
          onClose={() => setSharingAccountId(null)}
        />
      )}

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
                onChange={(e) => setName(e.target.value)}
                required
                placeholder="Trading 212"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Typ</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {ACCOUNT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Měna</label>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
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
          {accounts.map((acc) => (
            <div key={acc.id} className="bg-white rounded-xl border border-gray-200 p-5">
              {editingId === acc.id ? (
                <form onSubmit={(e) => handleEdit(e, acc.id)} className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Název</label>
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                      required
                      className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Typ</label>
                    <select
                      value={editForm.type}
                      onChange={(e) => setEditForm((f) => ({ ...f, type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {ACCOUNT_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Měna</label>
                    <select
                      value={editForm.currency}
                      onChange={(e) => setEditForm((f) => ({ ...f, currency: e.target.value }))}
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
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-gray-900">{acc.name}</p>
                      {acc.isShared && (
                        <span className="text-xs px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500">
                          {acc.shareRole === "editor" ? "Editor" : "Prohlížeč"}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-0.5">
                      {ACCOUNT_TYPE_LABELS[acc.type] ?? acc.type} · {acc.currency}
                    </p>
                    <AccountBalance cash={cashMap[acc.id]} accountCurrency={acc.currency} />
                  </div>
                  {!acc.isShared && (
                    <div className="flex items-center gap-1 ml-3 shrink-0">
                      <button
                        onClick={() => setSharingAccountId(acc.id)}
                        className="text-gray-300 hover:text-green-500 p-1 rounded transition-colors"
                        title="Sdílet"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          className="w-4 h-4"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
                          <path d="M15 8a3 3 0 10-2.977-2.63l-4.94 2.47a3 3 0 100 4.319l4.94 2.47a3 3 0 10.895-1.789l-4.94-2.47a3.027 3.027 0 000-.74l4.94-2.47C13.456 7.68 14.19 8 15 8z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => startEdit(acc)}
                        className="text-gray-300 hover:text-blue-500 p-1 rounded transition-colors"
                        title="Upravit"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          className="w-4 h-4"
                          viewBox="0 0 20 20"
                          fill="currentColor"
                        >
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
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
