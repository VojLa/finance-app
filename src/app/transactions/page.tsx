"use client"

import { useEffect, useState, useCallback } from "react"
import Link from "next/link"
import { fmt } from "@/lib/format"

type Category = {
  id: string
  name: string
  icon: string | null
  color: string | null
  type: string
}
type Account = { id: string; name: string; type: string; currency: string }
type Transaction = {
  id: string
  date: string
  amount: number
  currency: string
  type: string
  description: string | null
  counterparty: string | null
  note: string | null
  accountId: string
  categoryId: string | null
  category: Category | null
  account: { name: string; currency: string }
}

type TxForm = {
  date: string
  amount: string
  currency: string
  type: string
  accountId: string
  description: string
  counterparty: string
  note: string
  categoryId: string
}

const TODAY = new Date().toISOString().slice(0, 10)

function emptyForm(defaultAccountId = ""): TxForm {
  return {
    date: TODAY,
    amount: "",
    currency: "CZK",
    type: "expense",
    accountId: defaultAccountId,
    description: "",
    counterparty: "",
    note: "",
    categoryId: "",
  }
}

function txToForm(tx: Transaction): TxForm {
  return {
    date: tx.date.slice(0, 10),
    amount: String(tx.amount),
    currency: tx.currency,
    type: tx.type,
    accountId: tx.accountId,
    description: tx.description ?? "",
    counterparty: tx.counterparty ?? "",
    note: tx.note ?? "",
    categoryId: tx.categoryId ?? "",
  }
}

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
const TYPE_SIGN: Record<string, string> = { income: "+", expense: "−", transfer: "" }

// ─── TxFormFields ─────────────────────────────────────────────────────────────

function TxFormFields({
  form,
  accounts,
  categories,
  onChange,
  hideAccount,
}: {
  form: TxForm
  accounts: Account[]
  categories: Category[]
  onChange: (f: TxForm) => void
  hideAccount?: boolean
}) {
  function set(k: keyof TxForm) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      onChange({ ...form, [k]: e.target.value })
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Datum *</label>
          <input
            type="date"
            value={form.date}
            onChange={set("date")}
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Typ *</label>
          <select
            value={form.type}
            onChange={set("type")}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="expense">Výdaj</option>
            <option value="income">Příjem</option>
            <option value="transfer">Převod</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Částka *</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={form.amount}
            onChange={set("amount")}
            required
            placeholder="0.00"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Měna *</label>
          <select
            value={form.currency}
            onChange={set("currency")}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="CZK">CZK</option>
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
          </select>
        </div>
      </div>
      {!hideAccount && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Účet *</label>
          <select
            value={form.accountId}
            onChange={set("accountId")}
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— vyberte účet —</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </select>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Protistrana</label>
        <input
          type="text"
          value={form.counterparty}
          onChange={set("counterparty")}
          placeholder="Název protistrany"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Popis</label>
        <input
          type="text"
          value={form.description}
          onChange={set("description")}
          placeholder="Popis transakce"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Kategorie</label>
        <select
          value={form.categoryId}
          onChange={set("categoryId")}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">— bez kategorie —</option>
          {categories
            .filter((c) => c.type === "both" || c.type === form.type)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
        </select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Poznámka</label>
        <textarea
          value={form.note}
          onChange={set("note")}
          rows={2}
          placeholder="Nepovinná poznámka..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>
    </div>
  )
}

// ─── DetailRow ────────────────────────────────────────────────────────────────

function DetailRow({
  label,
  value,
  highlight,
}: {
  label: string
  value: string
  highlight?: string
}) {
  const cls =
    highlight === "income"
      ? "text-green-600 font-semibold"
      : highlight === "expense"
        ? "text-red-600 font-semibold"
        : "text-gray-900"
  return (
    <div className="flex items-start gap-4 py-2 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-500 w-28 shrink-0">{label}</span>
      <span className={`text-sm ${cls}`}>{value}</span>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [page, setPage] = useState(1)
  const [filterType, setFilterType] = useState("")
  const [filterCategory, setFilterCategory] = useState("")
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [loading, setLoading] = useState(true)

  // Create
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState<TxForm>(emptyForm())
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState("")

  // Detail + edit
  const [detailTx, setDetailTx] = useState<Transaction | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [editForm, setEditForm] = useState<TxForm>(emptyForm())
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState("")

  useEffect(() => {
    fetch("/api/categories")
      .then((r) => r.json())
      .then(setCategories)
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((data: Account[]) => {
        setAccounts(data)
        if (data.length > 0) setCreateForm((f) => ({ ...f, accountId: data[0].id }))
      })
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams({ page: String(page) })
    if (filterType) params.set("type", filterType)
    if (filterCategory) params.set("categoryId", filterCategory)
    if (search) params.set("q", search)

    const res = await fetch(`/api/transactions?${params}`)
    const data = await res.json()
    setTransactions(data.transactions ?? [])
    setTotal(data.total ?? 0)
    setPages(data.pages ?? 1)
    setLoading(false)
  }, [page, filterType, filterCategory, search])

  useEffect(() => {
    load()
  }, [load])

  async function assignCategory(txId: string, categoryId: string) {
    await fetch("/api/transactions", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: txId, categoryId: categoryId || null }),
    })
    load()
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreateLoading(true)
    setCreateError("")
    const res = await fetch("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: createForm.date,
        amount: parseFloat(createForm.amount),
        currency: createForm.currency,
        type: createForm.type,
        accountId: createForm.accountId,
        description: createForm.description || null,
        counterparty: createForm.counterparty || null,
        note: createForm.note || null,
        categoryId: createForm.categoryId || null,
      }),
    })
    setCreateLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setCreateError(d.error)
    } else {
      setShowCreate(false)
      setCreateForm((f) => ({ ...emptyForm(), accountId: f.accountId }))
      load()
    }
  }

  function openDetail(tx: Transaction) {
    setDetailTx(tx)
    setEditMode(false)
    setEditForm(txToForm(tx))
    setEditError("")
  }

  function closeDetail() {
    setDetailTx(null)
    setEditMode(false)
    setEditError("")
  }

  async function handleEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!detailTx) return
    setEditLoading(true)
    setEditError("")
    const res = await fetch("/api/transactions", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: detailTx.id,
        date: editForm.date,
        amount: parseFloat(editForm.amount),
        currency: editForm.currency,
        type: editForm.type,
        description: editForm.description || null,
        counterparty: editForm.counterparty || null,
        note: editForm.note || null,
        categoryId: editForm.categoryId || null,
      }),
    })
    setEditLoading(false)
    if (!res.ok) {
      const d = await res.json()
      setEditError(d.error)
    } else {
      closeDetail()
      load()
    }
  }

  async function handleDelete(txId: string) {
    if (!confirm("Smazat transakci?")) return
    await fetch(`/api/transactions?id=${txId}`, { method: "DELETE" })
    closeDetail()
    load()
  }

  return (
    <>
      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center overflow-y-auto p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg my-8 p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold">Nová transakce</h2>
              <button
                onClick={() => setShowCreate(false)}
                className="text-gray-400 hover:text-gray-700 text-2xl leading-none"
              >
                ×
              </button>
            </div>
            <form onSubmit={handleCreate}>
              <TxFormFields
                form={createForm}
                accounts={accounts}
                categories={categories}
                onChange={setCreateForm}
              />
              {createError && <p className="mt-3 text-sm text-red-600">{createError}</p>}
              <div className="flex gap-3 mt-5">
                <button
                  type="submit"
                  disabled={createLoading}
                  className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                >
                  {createLoading ? "Ukládám..." : "Vytvořit"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100"
                >
                  Zrušit
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Detail / Edit modal */}
      {detailTx && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center overflow-y-auto p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg my-8 p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold">
                {editMode ? "Upravit transakci" : "Detail transakce"}
              </h2>
              <button
                onClick={closeDetail}
                className="text-gray-400 hover:text-gray-700 text-2xl leading-none"
              >
                ×
              </button>
            </div>

            {editMode ? (
              <form onSubmit={handleEdit}>
                <TxFormFields
                  form={editForm}
                  accounts={accounts}
                  categories={categories}
                  onChange={setEditForm}
                  hideAccount
                />
                {editError && <p className="mt-3 text-sm text-red-600">{editError}</p>}
                <div className="flex gap-3 mt-5">
                  <button
                    type="submit"
                    disabled={editLoading}
                    className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                  >
                    {editLoading ? "Ukládám..." : "Uložit"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditMode(false)}
                    className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100"
                  >
                    Zrušit
                  </button>
                </div>
              </form>
            ) : (
              <div>
                <DetailRow
                  label="Datum"
                  value={new Date(detailTx.date).toLocaleDateString("cs-CZ")}
                />
                <DetailRow label="Typ" value={TYPE_LABEL[detailTx.type] ?? detailTx.type} />
                <DetailRow
                  label="Částka"
                  value={`${TYPE_SIGN[detailTx.type]}${fmt(detailTx.amount)} ${detailTx.currency}`}
                  highlight={detailTx.type}
                />
                <DetailRow label="Účet" value={detailTx.account.name} />
                {detailTx.counterparty && (
                  <DetailRow label="Protistrana" value={detailTx.counterparty} />
                )}
                {detailTx.description && <DetailRow label="Popis" value={detailTx.description} />}
                {detailTx.category && (
                  <DetailRow
                    label="Kategorie"
                    value={`${detailTx.category.icon ?? ""} ${detailTx.category.name}`}
                  />
                )}
                {detailTx.note && <DetailRow label="Poznámka" value={detailTx.note} />}
                <div className="flex gap-3 pt-4 mt-2">
                  <button
                    onClick={() => setEditMode(true)}
                    className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
                  >
                    Upravit
                  </button>
                  <button
                    onClick={() => handleDelete(detailTx.id)}
                    className="px-4 py-2 rounded-lg text-sm font-medium text-red-600 hover:bg-red-50"
                  >
                    Smazat
                  </button>
                  <button
                    onClick={closeDetail}
                    className="ml-auto px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100"
                  >
                    Zavřít
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Page */}
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Transakce</h1>
          <div className="flex items-center gap-4">
            <Link href="/categories" className="text-sm text-gray-500 hover:text-gray-700">
              Kategorie →
            </Link>
            <span className="text-sm text-gray-400">{total} celkem</span>
            <button
              onClick={() => {
                setCreateForm((f) => ({ ...emptyForm(), accountId: f.accountId }))
                setShowCreate(true)
              }}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
            >
              + Přidat
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-3">
          <input
            placeholder="Hledat..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setSearch(searchInput)
                setPage(1)
              }
            }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          />
          <select
            value={filterType}
            onChange={(e) => {
              setFilterType(e.target.value)
              setPage(1)
            }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Všechny typy</option>
            <option value="income">Příjmy</option>
            <option value="expense">Výdaje</option>
            <option value="transfer">Převody</option>
          </select>
          <select
            value={filterCategory}
            onChange={(e) => {
              setFilterCategory(e.target.value)
              setPage(1)
            }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Všechny kategorie</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
          {(filterType || filterCategory || search) && (
            <button
              onClick={() => {
                setFilterType("")
                setFilterCategory("")
                setSearch("")
                setSearchInput("")
                setPage(1)
              }}
              className="text-sm text-gray-400 hover:text-gray-700"
            >
              Zrušit filtry ×
            </button>
          )}
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="py-12 text-center text-gray-400">Načítám...</div>
          ) : transactions.length === 0 ? (
            <div className="py-12 text-center text-gray-400">
              Žádné transakce.{" "}
              <a href="/import" className="text-blue-600 hover:underline">
                Importovat CSV →
              </a>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr className="text-gray-500 text-left">
                  <th className="px-4 py-3 font-medium">Datum</th>
                  <th className="px-4 py-3 font-medium">Popis / Protistrana</th>
                  <th className="px-4 py-3 font-medium">Účet</th>
                  <th className="px-4 py-3 font-medium">Kategorie</th>
                  <th className="px-4 py-3 font-medium text-right">Částka</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {transactions.map((tx) => (
                  <tr
                    key={tx.id}
                    className="hover:bg-gray-50 transition-colors cursor-pointer"
                    onClick={() => openDetail(tx)}
                  >
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                      {new Date(tx.date).toLocaleDateString("cs-CZ")}
                    </td>
                    <td className="px-4 py-3 max-w-xs">
                      <p className="font-medium truncate">
                        {tx.counterparty || tx.description || "—"}
                      </p>
                      {tx.counterparty && tx.description && (
                        <p className="text-xs text-gray-400 truncate">{tx.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{tx.account.name}</td>
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <select
                        value={tx.categoryId ?? ""}
                        onChange={(e) => assignCategory(tx.id, e.target.value)}
                        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 max-w-[160px]"
                      >
                        <option value="">— bez kategorie</option>
                        {categories
                          .filter((c) => c.type === "both" || c.type === tx.type)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.icon} {c.name}
                            </option>
                          ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-right font-mono whitespace-nowrap">
                      <span className={TYPE_COLOR[tx.type] ?? "text-gray-600"}>
                        {TYPE_SIGN[tx.type]}
                        {fmt(tx.amount)} {tx.currency}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {pages > 1 && (
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              ← Předchozí
            </button>
            <span className="text-sm text-gray-500">
              {page} / {pages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Další →
            </button>
          </div>
        )}
      </div>
    </>
  )
}
