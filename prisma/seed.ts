import { PrismaClient } from "@prisma/client"
import bcrypt from "bcryptjs"

const prisma = new PrismaClient()

// ─── Default categories ───────────────────────────────────────────────────────

const CATEGORIES = [
  // Výdaje
  {
    name: "Jídlo & Restaurace",
    icon: "🍽️",
    color: "#ef4444",
    type: "expense" as const,
    keywords: [],
  },
  {
    name: "Doprava",
    icon: "🚗",
    color: "#3b82f6",
    type: "expense" as const,
    keywords: ["DPMB", "DPP", "Regiojet", "FlixBus", "Shell", "OMV", "MOL"],
  },
  {
    name: "Bydlení",
    icon: "🏠",
    color: "#8b5cf6",
    type: "expense" as const,
    keywords: ["Nájemné", "Energie", "Vodné", "Internet"],
  },
  {
    name: "Zdraví",
    icon: "💊",
    color: "#10b981",
    type: "expense" as const,
    keywords: ["Lékárna", "Dr.", "Nemocnice"],
  },
  {
    name: "Zábava",
    icon: "🎮",
    color: "#ec4899",
    type: "expense" as const,
    keywords: ["Netflix", "Spotify", "Steam", "Cinema"],
  },
  {
    name: "Oblečení",
    icon: "👕",
    color: "#f59e0b",
    type: "expense" as const,
    keywords: ["Zara", "H&M", "Reserved", "Vans"],
  },
  {
    name: "Elektronika",
    icon: "💻",
    color: "#6366f1",
    type: "expense" as const,
    keywords: ["Alza", "CZC", "Datart", "Apple"],
  },
  {
    name: "Vzdělání",
    icon: "📚",
    color: "#0891b2",
    type: "expense" as const,
    keywords: ["Udemy", "Coursera"],
  },
  {
    name: "Investice",
    icon: "📈",
    color: "#16a34a",
    type: "expense" as const,
    keywords: ["Trading 212", "Anycoin"],
  },
  {
    name: "Potraviny",
    icon: "🛒",
    color: "#f97316",
    type: "expense" as const,
    keywords: ["Albert", "Tesco", "Lidl", "Kaufland", "Billa", "Penny"],
  },
  { name: "Ostatní výdaje", icon: "💸", color: "#64748b", type: "expense" as const, keywords: [] },
  // Příjmy
  { name: "Výplata", icon: "💼", color: "#22c55e", type: "income" as const, keywords: [] },
  { name: "Freelance", icon: "🖥️", color: "#16a34a", type: "income" as const, keywords: [] },
  {
    name: "Dividendy",
    icon: "🏦",
    color: "#15803d",
    type: "income" as const,
    keywords: ["Dividenda"],
  },
  { name: "Ostatní příjmy", icon: "💰", color: "#4ade80", type: "income" as const, keywords: [] },
]

async function seedCategories() {
  console.log("Seeding default categories...")

  for (const cat of CATEGORIES) {
    const { keywords, ...data } = cat

    const category = await prisma.category.upsert({
      where: { id: `default-${cat.name}` },
      update: {},
      create: { id: `default-${cat.name}`, ...data, isDefault: true },
    })

    for (const keyword of keywords) {
      await prisma.categoryRule.upsert({
        where: { id: `rule-${cat.name}-${keyword}` },
        update: {},
        create: {
          id: `rule-${cat.name}-${keyword}`,
          value: keyword,
          field: "counterparty",
          operator: "contains",
          priority: 0,
          categoryId: category.id,
        },
      })
    }
  }

  console.log(`Seeded ${CATEGORIES.length} categories.`)
}

// ─── Dev mock data ────────────────────────────────────────────────────────────

const DEV_USER_EMAIL = "dev@financeapp.local"

async function seedDevData() {
  if (process.env.NODE_ENV === "production") {
    console.log("Skipping dev mock data in production.")
    return
  }

  const existing = await prisma.user.findUnique({ where: { email: DEV_USER_EMAIL } })
  if (existing) {
    console.log("Dev user already exists — skipping mock data.")
    return
  }

  console.log("Seeding dev mock data...")

  const passwordHash = await bcrypt.hash("password123", 10)
  const user = await prisma.user.create({
    data: {
      email: DEV_USER_EMAIL,
      name: "Dev User",
      passwordHash,
      baseCurrency: "CZK",
    },
  })

  // Accounts
  const bankAccount = await prisma.account.create({
    data: {
      name: "Raiffeisenbank",
      type: "bank",
      currency: "CZK",
      color: "#f59e0b",
      userId: user.id,
    },
  })

  const brokerAccount = await prisma.account.create({
    data: {
      name: "Trading 212",
      type: "broker",
      currency: "EUR",
      color: "#3b82f6",
      userId: user.id,
    },
  })

  const cryptoAccount = await prisma.account.create({
    data: {
      name: "Anycoin",
      type: "exchange",
      currency: "EUR",
      color: "#f97316",
      userId: user.id,
    },
  })

  // Mock bank transactions (last 3 months)
  const now = new Date()
  const months = [-2, -1, 0]

  for (const monthOffset of months) {
    const m = new Date(now.getFullYear(), now.getMonth() + monthOffset, 1)

    // Salary
    await prisma.transaction.create({
      data: {
        date: new Date(m.getFullYear(), m.getMonth(), 10),
        amount: 65000,
        currency: "CZK",
        type: "income",
        classification: "real_income",
        description: "Výplata",
        counterparty: "Zaměstnavatel s.r.o.",
        accountId: bankAccount.id,
        categoryId: `default-Výplata`,
      },
    })

    // Rent
    await prisma.transaction.create({
      data: {
        date: new Date(m.getFullYear(), m.getMonth(), 1),
        amount: 18000,
        currency: "CZK",
        type: "expense",
        classification: "real_expense",
        description: "Nájemné",
        counterparty: "Pronajímatel",
        accountId: bankAccount.id,
        categoryId: `default-Bydlení`,
      },
    })

    // Groceries
    const groceryDays = [3, 10, 17, 24]
    for (const day of groceryDays) {
      await prisma.transaction.create({
        data: {
          date: new Date(m.getFullYear(), m.getMonth(), day),
          amount: Math.round(800 + Math.random() * 400),
          currency: "CZK",
          type: "expense",
          classification: "real_expense",
          description: "Potraviny",
          counterparty: ["Albert", "Lidl", "Tesco", "Kaufland"][day % 4],
          accountId: bankAccount.id,
          categoryId: `default-Potraviny`,
        },
      })
    }

    // Spotify
    await prisma.transaction.create({
      data: {
        date: new Date(m.getFullYear(), m.getMonth(), 15),
        amount: 199,
        currency: "CZK",
        type: "expense",
        classification: "real_expense",
        description: "Spotify Premium",
        counterparty: "Spotify",
        accountId: bankAccount.id,
        categoryId: `default-Zábava`,
      },
    })

    // Transport
    await prisma.transaction.create({
      data: {
        date: new Date(m.getFullYear(), m.getMonth(), 5),
        amount: 550,
        currency: "CZK",
        type: "expense",
        classification: "real_expense",
        description: "MHD měsíční jízdenka",
        counterparty: "DPMB",
        accountId: bankAccount.id,
        categoryId: `default-Doprava`,
      },
    })

    // Broker deposit (investment transfer)
    await prisma.transaction.create({
      data: {
        date: new Date(m.getFullYear(), m.getMonth(), 12),
        amount: 5000,
        currency: "CZK",
        type: "expense",
        classification: "investment_transfer",
        description: "Vklad Trading 212",
        counterparty: "Trading 212",
        accountId: bankAccount.id,
        categoryId: `default-Investice`,
      },
    })
  }

  // Mock assets
  const vwce = await prisma.asset.upsert({
    where: { symbol: "VWCE" },
    update: {},
    create: {
      symbol: "VWCE",
      name: "Vanguard FTSE All-World ETF",
      assetType: "etf",
      currency: "EUR",
    },
  })

  const btc = await prisma.asset.upsert({
    where: { symbol: "BTC" },
    update: {},
    create: {
      symbol: "BTC",
      name: "Bitcoin",
      assetType: "crypto",
      currency: "EUR",
    },
  })

  const eth = await prisma.asset.upsert({
    where: { symbol: "ETH" },
    update: {},
    create: {
      symbol: "ETH",
      name: "Ethereum",
      assetType: "crypto",
      currency: "EUR",
    },
  })

  // Mock investment transactions
  const investDates = [
    new Date(now.getFullYear(), now.getMonth() - 2, 15),
    new Date(now.getFullYear(), now.getMonth() - 1, 15),
    new Date(now.getFullYear(), now.getMonth(), 12),
  ]

  for (const date of investDates) {
    await prisma.investmentTransaction.create({
      data: {
        date,
        type: "buy",
        assetId: vwce.id,
        symbol: "VWCE",
        name: "Vanguard FTSE All-World ETF",
        assetType: "etf",
        quantity: 1.5,
        pricePerUnit: 118.5,
        priceCurrency: "EUR",
        totalAmount: 177.75,
        totalCurrency: "EUR",
        fee: 0.15,
        feeCurrency: "EUR",
        accountId: brokerAccount.id,
      },
    })
  }

  await prisma.investmentTransaction.create({
    data: {
      date: new Date(now.getFullYear(), now.getMonth() - 1, 20),
      type: "buy",
      assetId: btc.id,
      symbol: "BTC",
      name: "Bitcoin",
      assetType: "crypto",
      quantity: 0.01,
      pricePerUnit: 55000,
      priceCurrency: "EUR",
      totalAmount: 550,
      totalCurrency: "EUR",
      accountId: cryptoAccount.id,
    },
  })

  await prisma.investmentTransaction.create({
    data: {
      date: new Date(now.getFullYear(), now.getMonth() - 2, 8),
      type: "buy",
      assetId: eth.id,
      symbol: "ETH",
      name: "Ethereum",
      assetType: "crypto",
      quantity: 0.5,
      pricePerUnit: 2200,
      priceCurrency: "EUR",
      totalAmount: 1100,
      totalCurrency: "EUR",
      accountId: cryptoAccount.id,
    },
  })

  // Mock holdings
  await prisma.holding.upsert({
    where: { symbol_accountId: { symbol: "VWCE", accountId: brokerAccount.id } },
    update: {},
    create: {
      symbol: "VWCE",
      name: "Vanguard FTSE All-World ETF",
      assetType: "etf",
      quantity: 4.5,
      avgBuyPrice: 118.5,
      currency: "EUR",
      assetId: vwce.id,
      accountId: brokerAccount.id,
    },
  })

  await prisma.holding.upsert({
    where: { symbol_accountId: { symbol: "BTC", accountId: cryptoAccount.id } },
    update: {},
    create: {
      symbol: "BTC",
      name: "Bitcoin",
      assetType: "crypto",
      quantity: 0.01,
      avgBuyPrice: 55000,
      currency: "EUR",
      assetId: btc.id,
      accountId: cryptoAccount.id,
    },
  })

  await prisma.holding.upsert({
    where: { symbol_accountId: { symbol: "ETH", accountId: cryptoAccount.id } },
    update: {},
    create: {
      symbol: "ETH",
      name: "Ethereum",
      assetType: "crypto",
      quantity: 0.5,
      avgBuyPrice: 2200,
      currency: "EUR",
      assetId: eth.id,
      accountId: cryptoAccount.id,
    },
  })

  // Mock budget for current month
  const budget = await prisma.budget.upsert({
    where: {
      month_year_userId: {
        month: now.getMonth() + 1,
        year: now.getFullYear(),
        userId: user.id,
      },
    },
    update: {},
    create: {
      month: now.getMonth() + 1,
      year: now.getFullYear(),
      userId: user.id,
      currency: "CZK",
    },
  })

  const budgetCategories = [
    { id: `default-Potraviny`, amount: 4000 },
    { id: `default-Bydlení`, amount: 18500 },
    { id: `default-Doprava`, amount: 1500 },
    { id: `default-Zábava`, amount: 1000 },
    { id: `default-Jídlo & Restaurace`, amount: 2000 },
  ]

  for (const { id: categoryId, amount } of budgetCategories) {
    await prisma.budgetItem.upsert({
      where: { id: `${budget.id}-${categoryId}` },
      update: {},
      create: {
        id: `${budget.id}-${categoryId}`,
        amount,
        budgetId: budget.id,
        categoryId,
        currency: "CZK",
      },
    })
  }

  console.log(`Dev mock data seeded:`)
  console.log(`  User: ${DEV_USER_EMAIL} / password123`)
  console.log(`  Accounts: ${bankAccount.name}, ${brokerAccount.name}, ${cryptoAccount.name}`)
  console.log(`  Assets: VWCE, BTC, ETH`)
  console.log(`  Budget: ${now.getMonth() + 1}/${now.getFullYear()}`)
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  await seedCategories()
  await seedDevData()
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect())
