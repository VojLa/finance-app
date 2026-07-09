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

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  await seedCategories()
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect())
