"use client"

import { useEffect, useRef, useState } from "react"
import { fmtCzk } from "@/lib/format"
import { requestBudget, saveBudget } from "@/modules/budgets/budget-client"
import type { Budget } from "@/modules/budgets/budget-contract"
import { requestCategories } from "@/modules/categories/category-client"
import type { Category } from "@/modules/categories/category-contract"

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
  const [error, setError] = useState<string | null>(null)
  const budgetRequestId = useRef(0)
  const [lastLoadedPeriod, setLastLoadedPeriod] = useState<string | null>(null)

  useEffect(() => {
    requestCategories()
      .then((cats) => {
        setCategories(
          cats.filter((category) => category.type === "expense" || category.type === "both")
        )
      })
      .catch(() => setError("Kategorie se nepodařilo načíst."))
  }, [])

  async function loadBudget() {
    const requestId = ++budgetRequestId.current
    setLoading(true)
    setError(null)
    try {
      const data = await requestBudget(month, year)
      if (requestId !== budgetRequestId.current) return
      setBudget(data)
      setLastLoadedPeriod(`${year}-${month}`)
      setRollover(Boolean(data?.rollover))
    } catch {
      if (requestId !== budgetRequestId.current) return
      setError("Rozpočet se nepodařilo načíst.")
    } finally {
      if (requestId === budgetRequestId.current) setLoading(false)
    }
  }

  useEffect(() => {
    loadBudget()
  }, [month, year]) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveItems(
    items: { categoryId: string; amount: string | number; currency: string }[]
  ) {
    setError(null)
    setBudget(await saveBudget({ month, year, rollover, items }))
  }

  async function addItem(e: React.FormEvent) {
    e.preventDefault()
    if (!newCatId || !newAmount) return
    setSaving(true)

    const existing =
      budget?.items.map((i) => ({
        categoryId: i.categoryId,
        amount: i.amount,
        currency: i.currency,
      })) ?? []
    const items = [
      ...existing.filter((i) => i.categoryId !== newCatId),
      { categoryId: newCatId, amount: newAmount, currency: "CZK" },
    ]

    try {
      await saveItems(items)
      setNewCatId("")
      setNewAmount("")
      setShowForm(false)
    } catch {
      setError("Rozpočet se nepodařilo uložit.")
    } finally {
      setSaving(false)
    }
  }

  async function deleteItem(categoryId: string) {
    setDeletingId(categoryId)
    const remaining =
      budget?.items
        .filter((i) => i.categoryId !== categoryId)
        .map((i) => ({ categoryId: i.categoryId, amount: i.amount, currency: i.currency })) ?? []
    try {
      await saveItems(remaining)
    } catch {
      setError("Položku rozpočtu se nepodařilo odebrat.")
    } finally {
      setDeletingId(null)
    }
  }

  const totalLimit = Number(budget?.totalLimit ?? 0)
  const totalSpent = Number(budget?.totalSpent ?? 0)
  const periodCurrent = !loading && lastLoadedPeriod === `${year}-${month}`

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

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {lastLoadedPeriod !== null && lastLoadedPeriod !== `${year}-${month}` && (
        <p role="status" className="text-sm text-amber-700">Zobrazený rozpočet je z posledního načteného měsíce ({lastLoadedPeriod}).</p>
      )}

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
              style={{ width: `${Number(budget.progressPct)}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-1.5">
            Zbyva {fmtCzk(Math.max(0, Number(budget.totalRemaining)))}
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

      {loading && budget === null ? (
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
                      {fmtCzk(Number(item.spent))} / {fmtCzk(Number(item.effectiveAmount))}
                    </span>
                    <button
                      onClick={() => deleteItem(item.categoryId)}
                      disabled={isDeleting || !periodCurrent}
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
                    style={{ width: `${Number(item.progressPct)}%` }}
                  />
                </div>
                {Number(item.rolloverAmount) !== 0 && (
                  <p className="text-xs text-gray-400 mt-1">
                    Rollover {Number(item.rolloverAmount) > 0 ? "+" : ""}
                    {fmtCzk(Number(item.rolloverAmount))}
                  </p>
                )}
                {over && (
                  <p className="text-xs text-red-500 mt-1">
                    Prekroceno o {fmtCzk(Math.abs(Number(item.remaining)))}
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
              disabled={saving || !periodCurrent}
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
          disabled={!periodCurrent}
          className="w-full border border-dashed border-gray-300 rounded-xl py-3 text-sm text-gray-400 hover:border-blue-400 hover:text-blue-500 transition-colors"
        >
          + Pridat kategorii do rozpoctu
        </button>
      )}
    </div>
  )
}
