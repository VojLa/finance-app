"use client"

import Link from "next/link"
import { useMemo } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { fmt, fmtCzk } from "@/lib/format"

import type { OperationalDashboardData } from "./operational-dashboard-contract"

const PIE_COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777"]

function compactCzk(value: number) {
  const absolute = Math.abs(value)
  if (absolute >= 1_000_000) return `${fmt(value / 1_000_000, 1)} mil.`
  if (absolute >= 100_000) return `${fmt(value / 1_000, 0)} tis.`
  return fmt(value, 0)
}

function OperationalEmptyState({ href, label }: { href: string; label: string }) {
  return (
    <div className="flex h-48 items-center justify-center text-center text-sm text-gray-400">
      <Link href={href} className="text-blue-600 hover:underline">
        {label}
      </Link>
    </div>
  )
}

function WidgetMoreLink({ href }: { href: string }) {
  return (
    <div className="mt-5 flex justify-end border-t border-gray-100 pt-4">
      <Link href={href} className="text-sm font-medium text-blue-600 hover:underline">
        Zobrazit více
      </Link>
    </div>
  )
}

type Props = {
  data: OperationalDashboardData
}

export function OperationalDashboardSections({ data }: Props) {
  const budgetItems = data.budget?.items.slice(0, 5) ?? []
  const netIsPositive = data.currentMonth.net >= 0
  const pieData = useMemo(
    () =>
      data.expenseByCategory.map((item, index) => ({
        ...item,
        fill: item.color ?? PIE_COLORS[index % PIE_COLORS.length],
      })),
    [data.expenseByCategory]
  )

  return (
    <section aria-labelledby="operational-heading" className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="operational-heading" className="text-lg font-medium">
            Přehled za tento měsíc
          </h2>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl bg-blue-600 p-5 text-white shadow-sm">
          <p className="text-sm font-medium text-blue-100">Cash flow</p>
          <p
            className={`mt-2 text-2xl font-semibold tabular-nums ${
              netIsPositive ? "text-white" : "text-red-100"
            }`}
          >
            {fmtCzk(data.currentMonth.net)}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <p className="text-sm text-gray-500">Příjmy</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-green-600">
            {fmtCzk(data.currentMonth.income)}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <p className="text-sm text-gray-500">Výdaje</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-red-600">
            {fmtCzk(data.currentMonth.expenses)}
          </p>
        </div>
      </div>
      <WidgetMoreLink href="/transactions" />

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-medium">Příjmy vs výdaje</h3>
            <span className="text-xs text-gray-400">6 měsíců</span>
          </div>
          <ResponsiveContainer width="100%" height={270}>
            <BarChart
              data={[...data.monthlyTrends]}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            >
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
          <WidgetMoreLink href="/transactions" />
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-medium">Výdaje podle kategorií</h3>
            <span className="text-xs text-gray-400">Tento měsíc</span>
          </div>
          {pieData.length === 0 ? (
            <OperationalEmptyState href="/transactions" label="Přidat první transakci" />
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
                    <Label
                      value={fmtCzk(data.currentMonth.expenses)}
                      position="center"
                      className="fill-slate-900 text-sm font-semibold"
                    />
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
          <WidgetMoreLink href="/transactions" />
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-medium">Zbývá z rozpočtu</h3>
            {data.budget && (
              <span
                className={
                  data.budget.remainingCzk < 0
                    ? "text-sm font-medium text-red-600"
                    : "text-sm font-medium text-green-600"
                }
              >
                {fmtCzk(data.budget.remainingCzk)}
              </span>
            )}
          </div>
          {!data.budget ? (
            <OperationalEmptyState href="/budget" label="Nastavit rozpočet" />
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
                    className={`h-2.5 rounded-full ${
                      data.budget.spentCzk > data.budget.limitCzk ? "bg-red-500" : "bg-blue-500"
                    }`}
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
                        className={`h-2 rounded-full ${
                          item.isOver
                            ? "bg-red-500"
                            : item.progressPct > 80
                              ? "bg-amber-400"
                              : "bg-green-500"
                        }`}
                        style={{ width: `${item.progressPct}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <WidgetMoreLink href="/budget" />
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-medium">Cash-flow trend</h3>
            <span className="text-xs text-gray-400">Čistý tok</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart
              data={[...data.monthlyTrends]}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="operationalNetFlow" x1="0" x2="0" y1="0" y2="1">
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
                fill="url(#operationalNetFlow)"
              />
            </AreaChart>
          </ResponsiveContainer>
          <WidgetMoreLink href="/transactions" />
        </section>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-medium">Poslední záznamy</h3>
          <span className="text-xs text-gray-400">Nejnovější</span>
        </div>
        {data.recentTransactions.length === 0 ? (
          <OperationalEmptyState href="/transactions" label="Přidat transakci" />
        ) : (
          <div className="divide-y divide-gray-100">
            {data.recentTransactions.map((transaction) => {
              const isIncome = transaction.type === "income"
              return (
                <Link
                  key={transaction.id}
                  href="/transactions"
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {transaction.counterparty || transaction.description || "Bez popisu"}
                    </p>
                    <p className="truncate text-xs text-gray-400">
                      {new Date(transaction.date).toLocaleDateString("cs-CZ")} ·{" "}
                      {transaction.accountName}
                      {transaction.categoryName
                        ? ` · ${transaction.categoryIcon ?? ""} ${transaction.categoryName}`
                        : ""}
                    </p>
                  </div>
                  <p
                    className={`text-sm font-semibold tabular-nums ${
                      isIncome ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {isIncome ? "+" : "-"}
                    {fmtCzk(transaction.amountCzk)}
                  </p>
                </Link>
              )
            })}
          </div>
        )}
        <WidgetMoreLink href="/transactions" />
      </section>
    </section>
  )
}
