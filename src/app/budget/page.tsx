"use client"

import { useEffect, useState } from "react"
import { fmtCzk } from "@/lib/format"

type Category = { id: string; name: string; icon: string | null; color: string | null }
type BudgetItem = {
  id: string
  amount: number
  rolloverAmount: number
  effectiveAmount: number
  spent: number
  remaining: number
  progressPct: number
  isApproaching: boolean
  isOver: boolean
  currency: string
  categoryId: string
  category: Category
}
type Budget = {
  id: string
  month: number
  year: number
  rollover: boolean
  totalLimit: number
  totalSpent: number
  totalRemaining: number
  progressPct: number
  isOver: boolean
  alerts: { id: string; type: string; categoryName: string }[]
  items: BudgetItem[]
}

const MONTHS = [
  "Leden",
  "Unor",
  "Brezen",
  "Duben",
  "Kveten",
  "Cerven",
  "Cervenec",
  "Srpen",
  "Zari",
  "Rijen",
  "Listopad",
  "Prosinec",
]

function pct(spent: number, limit: number) {
  if (limit === 0) return 0
  return Math.min(100, (spent / limit) * 100)
}

export default function BudgetPage() {
  const now = new Date()
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [year, setYear] = useState(now.getFullYear())
  const [budget, setBudget] = useState<Budget | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [newCatId, setNewCatId] = useState("")
  const [newAmount, setNewAmount] = useState("")
  const [rollover, setRollover] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    fetch("/api/categories")
      .then((r) => r.json())
      .then((cats) => {
        setCategories(
          cats.filter((c: { type: string }) => c.type === "expense" || c.type === "both")
        )
      })
  }, [])

  async function loadBudget() {
    setLoading(true)
    const res = await fetch(`/api/budget?month=${month}&year=${year}`)
    const data = res.ok ? await res.json() : null
    setBudget(data)
    setRollover(Boolean(data?.rollover))
    setLoading(false)
  }

  useEffect(() => {
    loadBudget()
  }, [month, year]) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveItems(items: { categoryId: string; amount: number }[]) {
    const res = await fetch("/api/budget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month, year, rollover, items }),
    })
    setBudget(res.ok ? await res.json() : null)
  }

  async function addItem(e: React.FormEvent) {
    e.preventDefault()
    if (!newCatId || !newAmount) return
    setSaving(true)

    const existing =
      budget?.items.map((i) => ({ categoryId: i.categoryId, amount: i.amount })) ?? []
    const items = [
      ...existing.filter((i) => i.categoryId !== newCatId),
      { categoryId: newCatId, amount: parseFloat(newAmount) },
    ]

    await saveItems(items)
    setNewCatId("")
    setNewAmount("")
    setShowForm(false)
    setSaving(false)
  }

  async function deleteItem(categoryId: string) {
    setDeletingId(categoryId)
    const remaining =
      budget?.items
        .filter((i) => i.categoryId !== categoryId)
        .map((i) => ({ categoryId: i.categoryId, amount: i.amount })) ?? []
    await saveItems(remaining)
    setDeletingId(null)
  }

  const totalLimit = budget?.totalLimit ?? 0
  const totalSpent = budget?.totalSpent ?? 0

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Rozpocty</h1>
        <div className="flex gap-2">
          <select
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {MONTHS.map((m, i) => (
              <option key={i} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {[year - 1, year, year + 1].map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </div>

      {budget && budget.items.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-gray-500">Celkem utraceno</span>
            <span
              className={totalSpent > totalLimit ? "text-red-600 font-semibold" : "font-semibold"}
            >
              {fmtCzk(totalSpent)} / {fmtCzk(totalLimit)}
            </span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2.5">
            <div
              className={`h-2.5 rounded-full transition-all ${budget.isOver ? "bg-red-500" : "bg-blue-500"}`}
              style={{ width: `${pct(totalSpent, totalLimit)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-1.5">
            Zbyva {fmtCzk(Math.max(0, budget.totalRemaining))}
          </p>
          {budget.alerts.length > 0 && (
            <div className="mt-4 space-y-2">
              {budget.alerts.map((alert) => (
                <div
                  key={alert.id}
                  className={`rounded-lg px-3 py-2 text-xs ${
                    alert.type === "exceeded"
                      ? "bg-red-50 text-red-700"
                      : "bg-amber-50 text-amber-700"
                  }`}
                >
                  {alert.type === "exceeded"
                    ? `${alert.categoryName}: limit je prekroceny`
                    : `${alert.categoryName}: blizi se limitu`}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 py-8 text-center">Nacitam...</div>
      ) : (
        <div className="space-y-3">
          {(budget?.items ?? []).map((item) => {
            const over = item.isOver
            const isDeleting = deletingId === item.categoryId
            return (
              <div key={item.id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span>{item.category.icon}</span>
                    <span className="font-medium text-sm">{item.category.name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-sm font-mono ${over ? "text-red-600 font-semibold" : "text-gray-700"}`}
                    >
                      {fmtCzk(item.spent)} / {fmtCzk(item.effectiveAmount)}
                    </span>
                    <button
                      onClick={() => deleteItem(item.categoryId)}
                      disabled={isDeleting}
                      title="Odebrat z rozpoctu"
                      className="text-gray-300 hover:text-red-500 transition-colors text-lg leading-none disabled:opacity-40"
                    >
                      {isDeleting ? "..." : "x"}
                    </button>
                  </div>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all ${
                      over ? "bg-red-500" : item.isApproaching ? "bg-amber-400" : "bg-green-500"
                    }`}
                    style={{ width: `${item.progressPct}%` }}
                  />
                </div>
                {item.rolloverAmount !== 0 && (
                  <p className="text-xs text-gray-400 mt-1">
                    Rollover {item.rolloverAmount > 0 ? "+" : ""}
                    {fmtCzk(item.rolloverAmount)}
                  </p>
                )}
                {over && (
                  <p className="text-xs text-red-500 mt-1">
                    Prekroceno o {fmtCzk(item.spent - item.effectiveAmount)}
                  </p>
                )}
              </div>
            )
          })}

          {budget?.items.length === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400 text-sm">
              Zadne polozky rozpoctu. Pridej prvni kategorii nize.
            </div>
          )}
        </div>
      )}

      {showForm ? (
        <form
          onSubmit={addItem}
          className="bg-white rounded-xl border border-gray-200 p-5 space-y-3"
        >
          <h3 className="font-medium text-sm">Pridat kategorii do rozpoctu</h3>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={rollover}
              onChange={(event) => setRollover(event.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Prenest zustatek z predchoziho mesice
          </label>
          <div className="flex gap-3">
            <select
              value={newCatId}
              onChange={(e) => setNewCatId(e.target.value)}
              required
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Vyber kategorii</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.icon} {c.name}
                </option>
              ))}
            </select>
            <input
              type="number"
              placeholder="Limit (Kc)"
              value={newAmount}
              onChange={(e) => setNewAmount(e.target.value)}
              required
              min="1"
              className="w-36 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Ukladam..." : "Pridat"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="px-4 py-2 text-sm text-gray-500 hover:bg-gray-100 rounded-lg"
            >
              Zrusit
            </button>
          </div>
        </form>
      ) : (
        <button
          onClick={() => setShowForm(true)}
          className="w-full border border-dashed border-gray-300 rounded-xl py-3 text-sm text-gray-400 hover:border-blue-400 hover:text-blue-500 transition-colors"
        >
          + Pridat kategorii do rozpoctu
        </button>
      )}
    </div>
  )
}
