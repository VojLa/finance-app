export type OperationalBudgetItem = Readonly<{
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
}>

export type OperationalBudget = Readonly<{
  id: string
  month: number
  year: number
  limitCzk: number
  spentCzk: number
  remainingCzk: number
  progressPct: number
  items: readonly OperationalBudgetItem[]
}>

export type OperationalExpenseCategory = Readonly<{
  categoryId: string | null
  name: string
  icon: string | null
  color: string | null
  amountCzk: number
}>

export type OperationalMonthlyTrend = Readonly<{
  month: string
  label: string
  incomeCzk: number
  expenseCzk: number
  netCzk: number
}>

export type OperationalRecentTransaction = Readonly<{
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
}>

export type OperationalDashboardData = Readonly<{
  currentMonth: Readonly<{
    income: number
    expenses: number
    net: number
  }>
  budget: OperationalBudget | null
  expenseByCategory: readonly OperationalExpenseCategory[]
  monthlyTrends: readonly OperationalMonthlyTrend[]
  recentTransactions: readonly OperationalRecentTransaction[]
}>
