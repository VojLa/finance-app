"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { fmt, fmtCzk } from "@/lib/format"
import { ACCOUNT_TYPE_LABELS } from "@/lib/constants"

type DashboardData = {
  summary: {
    cashValueCzk: number
    portfolioValueCzk: number
    liabilitiesValueCzk: number
    netWorthCzk: number
    currentMonthIncomeCzk: number
    currentMonthExpenseCzk: number
    currentMonthNetCzk: number
  }
  accountBalances: {
    accountId: string
    accountName: string
    accountType: string
    currency: string
    color: string | null
    totalCzk: number
    balances: { currency: string; amount: number; amountCzk: number }[]
  }[]
  budget: {
    id: string
    month: number
    year: number
    limitCzk: number
    spentCzk: number
    remainingCzk: number
    progressPct: number
    items: {
      id: string
      categoryId: string
      name: string
      icon: string | null
      color: string | null
      limitCzk: number
      spentCzk: number
      remainingCzk: number
      progressPct: number
      isOver: boolean
    }[]
  } | null
  expenseByCategory: {
    categoryId: string | null
    name: string
    icon: string | null
    color: string | null
    amountCzk: number
  }[]
  monthlyTrends: {
    month: string
    label: string
    incomeCzk: number
    expenseCzk: number
    netCzk: number
  }[]
  recentTransactions: {
    id: string
    date: string
    amount: number
    amountCzk: number
    currency: string
    type: string
    description: string | null
    counterparty: string | null
    accountName: string
    categoryName: string | null
    categoryIcon: string | null
  }[]
}

const PIE_COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777"]

function compactCzk(value: number) {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${fmt(value / 1_000_000, 1)} mil.`
  if (abs >= 100_000) return `${fmt(value / 1_000, 0)} tis.`
  return fmt(value, 0)
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-8 w-48 animate-pulse rounded bg-gray-100" />
      <div className="grid gap-4 md:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-32 animate-pulse rounded-lg bg-gray-100" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="h-80 animate-pulse rounded-lg bg-gray-100" />
        <div className="h-80 animate-pulse rounded-lg bg-gray-100" />
      </div>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string
  value: string
  sub?: string
  tone?: "neutral" | "good" | "bad"
}) {
  const toneClass =
    tone === "good" ? "text-green-600" : tone === "bad" ? "text-red-600" : "text-gray-900"

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
    </section>
  )
}

function EmptyState({ href, label }: { href: string; label: string }) {
  return (
    <div className="flex h-56 items-center justify-center text-center text-sm text-gray-400">
      <Link href={href} className="text-blue-600 hover:underline">
        {label}
      </Link>
    </div>
  )
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch("/api/dashboard")
      .then((res) => res.json())
      .then((payload) => setData(payload))
      .finally(() => setLoading(false))
  }, [])

  const budgetItems = data?.budget?.items.slice(0, 5) ?? []
  const netIsPositive = (data?.summary.currentMonthNetCzk ?? 0) >= 0

  const pieData = useMemo(
    () =>
      data?.expenseByCategory.map((item, index) => ({
        ...item,
        fill: item.color ?? PIE_COLORS[index % PIE_COLORS.length],
      })) ?? [],
    [data]
  )

  if (loading || !data) return <DashboardSkeleton />

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            {new Date().toLocaleDateString("cs-CZ", {
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/transactions"
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Transakce
          </Link>
          <Link
            href="/budget"
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Rozpočet
          </Link>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <SummaryCard label="Net worth" value={fmtCzk(data.summary.netWorthCzk)} />
        <SummaryCard label="Hotovost" value={fmtCzk(data.summary.cashValueCzk)} />
        <SummaryCard label="Portfolio" value={fmtCzk(data.summary.portfolioValueCzk)} />
        <SummaryCard
          label="Měsíční cash flow"
          value={fmtCzk(data.summary.currentMonthNetCzk)}
          sub={`${fmtCzk(data.summary.currentMonthIncomeCzk)} příjmy / ${fmtCzk(data.summary.currentMonthExpenseCzk)} výdaje`}
          tone={netIsPositive ? "good" : "bad"}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Příjmy vs výdaje</h2>
            <span className="text-xs text-gray-400">6 měsíců</span>
          </div>
          <ResponsiveContainer width="100%" height={270}>
            <BarChart data={data.monthlyTrends} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 12 }} />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12 }}
                tickFormatter={compactCzk}
                width={68}
              />
              <Tooltip formatter={(value: number) => fmtCzk(value)} />
              <Bar dataKey="incomeCzk" name="Příjmy" fill="#16a34a" radius={[4, 4, 0, 0]} />
              <Bar dataKey="expenseCzk" name="Výdaje" fill="#dc2626" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Výdaje podle kategorií</h2>
            <Link href="/transactions" className="text-sm text-blue-600 hover:underline">
              Detail
            </Link>
          </div>
          {pieData.length === 0 ? (
            <EmptyState href="/transactions" label="Přidat první transakci" />
          ) : (
            <div className="grid gap-4 md:grid-cols-[1fr_0.9fr]">
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="amountCzk"
                    nameKey="name"
                    innerRadius={58}
                    outerRadius={92}
                  >
                    {pieData.map((item) => (
                      <Cell key={item.name} fill={item.fill} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => fmtCzk(value)} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2 self-center">
                {pieData.slice(0, 6).map((item) => (
                  <div key={item.name} className="flex items-center justify-between gap-3 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: item.fill }}
                      />
                      <span className="truncate">
                        {item.icon} {item.name}
                      </span>
                    </span>
                    <span className="font-medium tabular-nums">{fmtCzk(item.amountCzk)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Průběh rozpočtu</h2>
            <Link href="/budget" className="text-sm text-blue-600 hover:underline">
              Upravit
            </Link>
          </div>
          {!data.budget ? (
            <EmptyState href="/budget" label="Nastavit rozpočet" />
          ) : (
            <div className="space-y-4">
              <div>
                <div className="mb-2 flex justify-between text-sm">
                  <span className="text-gray-500">Celkem</span>
                  <span
                    className={
                      data.budget.spentCzk > data.budget.limitCzk
                        ? "font-semibold text-red-600"
                        : "font-semibold"
                    }
                  >
                    {fmtCzk(data.budget.spentCzk)} / {fmtCzk(data.budget.limitCzk)}
                  </span>
                </div>
                <div className="h-2.5 rounded-full bg-gray-100">
                  <div
                    className={`h-2.5 rounded-full ${data.budget.spentCzk > data.budget.limitCzk ? "bg-red-500" : "bg-blue-500"}`}
                    style={{ width: `${data.budget.progressPct}%` }}
                  />
                </div>
              </div>
              <div className="space-y-3">
                {budgetItems.map((item) => (
                  <div key={item.id}>
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate">
                        {item.icon} {item.name}
                      </span>
                      <span
                        className={
                          item.isOver ? "font-medium text-red-600" : "font-medium text-gray-700"
                        }
                      >
                        {fmtCzk(item.spentCzk)}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100">
                      <div
                        className={`h-2 rounded-full ${item.isOver ? "bg-red-500" : item.progressPct > 80 ? "bg-amber-400" : "bg-green-500"}`}
                        style={{ width: `${item.progressPct}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Měsíční trend</h2>
            <span className="text-xs text-gray-400">čistý tok</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data.monthlyTrends} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="netFlowGrad" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.22} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 12 }} />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12 }}
                tickFormatter={compactCzk}
                width={68}
              />
              <Tooltip formatter={(value: number) => fmtCzk(value)} />
              <Area
                type="monotone"
                dataKey="netCzk"
                name="Čistý tok"
                stroke="#2563eb"
                strokeWidth={2}
                fill="url(#netFlowGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Zůstatky</h2>
            <Link href="/accounts" className="text-sm text-blue-600 hover:underline">
              Účty
            </Link>
          </div>
          {data.accountBalances.length === 0 ? (
            <EmptyState href="/accounts" label="Přidat účet" />
          ) : (
            <div className="divide-y divide-gray-100">
              {data.accountBalances.slice(0, 7).map((account) => (
                <div key={account.accountId} className="py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: account.color ?? "#94a3b8" }}
                      />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{account.accountName}</p>
                        <p className="text-xs text-gray-400">
                          {ACCOUNT_TYPE_LABELS[account.accountType] ?? account.accountType}
                        </p>
                      </div>
                    </div>
                    <p className="text-sm font-semibold tabular-nums">{fmtCzk(account.totalCzk)}</p>
                  </div>
                  {account.balances.length > 1 && (
                    <p className="mt-1 truncate pl-4 text-xs text-gray-400">
                      {account.balances
                        .map((balance) => `${fmt(balance.amount)} ${balance.currency}`)
                        .join(" / ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-medium">Nedávné transakce</h2>
            <Link href="/transactions" className="text-sm text-blue-600 hover:underline">
              Všechny
            </Link>
          </div>
          {data.recentTransactions.length === 0 ? (
            <EmptyState href="/transactions" label="Přidat transakci" />
          ) : (
            <div className="divide-y divide-gray-100">
              {data.recentTransactions.map((tx) => {
                const isIncome = tx.type === "income"
                return (
                  <Link
                    key={tx.id}
                    href="/transactions"
                    className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {tx.counterparty || tx.description || "Bez popisu"}
                      </p>
                      <p className="truncate text-xs text-gray-400">
                        {new Date(tx.date).toLocaleDateString("cs-CZ")} · {tx.accountName}
                        {tx.categoryName ? ` · ${tx.categoryIcon ?? ""} ${tx.categoryName}` : ""}
                      </p>
                    </div>
                    <p
                      className={`text-sm font-semibold tabular-nums ${isIncome ? "text-green-600" : "text-red-600"}`}
                    >
                      {isIncome ? "+" : "-"}
                      {fmtCzk(tx.amountCzk)}
                    </p>
                  </Link>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
