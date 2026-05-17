"use client"

import { useEffect, useState, useCallback } from "react"
import { fmt } from "@/lib/format"

type Category = { id: string; name: string; icon: string | null; color: string | null; type: string }
type Transaction = {
  id: string
  date: string
  amount: number
  currency: string
  type: string
  description: string | null
  counterparty: string | null
  categoryId: string | null
  category: Category | null
  account: { name: string; currency: string }
}

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [page, setPage] = useState(1)
  const [filterType, setFilterType] = useState("")
  const [filterCategory, setFilterCategory] = useState("")
  const [search, setSearch] = useState("")
  const [searchInput, setSearchInput] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch("/api/categories").then(r => r.json()).then(setCategories)
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

  useEffect(() => { load() }, [load])

  async function assignCategory(txId: string, categoryId: string) {
    await fetch("/api/transactions", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: txId, categoryId: categoryId || null }),
    })
    load()
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Transakce</h1>
        <span className="text-sm text-gray-400">{total} celkem</span>
      </div>

      <div className="flex flex-wrap gap-3">
        <input
          placeholder="Hledat..."
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { setSearch(searchInput); setPage(1) } }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
        />
        <select
          value={filterType}
          onChange={e => { setFilterType(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Všechny typy</option>
          <option value="income">Příjmy</option>
          <option value="expense">Výdaje</option>
          <option value="transfer">Převody</option>
        </select>
        <select
          value={filterCategory}
          onChange={e => { setFilterCategory(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Všechny kategorie</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
          ))}
        </select>
        {(filterType || filterCategory || search) && (
          <button
            onClick={() => { setFilterType(""); setFilterCategory(""); setSearch(""); setSearchInput(""); setPage(1) }}
            className="text-sm text-gray-400 hover:text-gray-700"
          >
            Zrušit filtry ×
          </button>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="py-12 text-center text-gray-400">Načítám...</div>
        ) : transactions.length === 0 ? (
          <div className="py-12 text-center text-gray-400">
            Žádné transakce. <a href="/import" className="text-blue-600 hover:underline">Importovat CSV →</a>
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
              {transactions.map(tx => (
                <tr key={tx.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {new Date(tx.date).toLocaleDateString("cs-CZ")}
                  </td>
                  <td className="px-4 py-3 max-w-xs">
                    <p className="font-medium truncate">{tx.counterparty || tx.description || "—"}</p>
                    {tx.counterparty && tx.description && (
                      <p className="text-xs text-gray-400 truncate">{tx.description}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{tx.account.name}</td>
                  <td className="px-4 py-3">
                    <select
                      value={tx.categoryId ?? ""}
                      onChange={e => assignCategory(tx.id, e.target.value)}
                      className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 max-w-[160px]"
                    >
                      <option value="">— bez kategorie</option>
                      {categories
                        .filter(c => c.type === "both" || c.type === tx.type)
                        .map(c => (
                          <option key={c.id} value={c.id}>{c.icon} {c.name}</option>
                        ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-right font-mono whitespace-nowrap">
                    <span className={tx.type === "income" ? "text-green-600" : tx.type === "expense" ? "text-red-600" : "text-gray-600"}>
                      {tx.type === "income" ? "+" : tx.type === "expense" ? "−" : ""}
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
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
          >
            ← Předchozí
          </button>
          <span className="text-sm text-gray-500">{page} / {pages}</span>
          <button
            onClick={() => setPage(p => Math.min(pages, p + 1))}
            disabled={page === pages}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
          >
            Další →
          </button>
        </div>
      )}
    </div>
  )
}
