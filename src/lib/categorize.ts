import { prisma } from "./prisma"

export async function autoCategorize(accountId: string) {
  const [rules, uncategorized] = await Promise.all([
    prisma.categoryRule.findMany({
      include: { category: true },
      orderBy: { priority: "desc" },
    }),
    prisma.transaction.findMany({
      where: { accountId, categoryId: null },
    }),
  ])

  const updates: { id: string; categoryId: string }[] = []

  for (const tx of uncategorized) {
    for (const rule of rules) {
      const haystack =
        rule.field === "counterparty"
          ? (tx.counterparty ?? "").toLowerCase()
          : (tx.description ?? "").toLowerCase()

      if (haystack.includes(rule.keyword.toLowerCase())) {
        const catType = rule.category.type
        if (catType === "both" || catType === tx.type) {
          updates.push({ id: tx.id, categoryId: rule.categoryId })
          break
        }
      }
    }
  }

  if (updates.length > 0) {
    await prisma.$transaction(
      updates.map(u =>
        prisma.transaction.update({ where: { id: u.id }, data: { categoryId: u.categoryId } })
      )
    )
  }
}
