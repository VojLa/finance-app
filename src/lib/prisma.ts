import { PrismaClient, Prisma } from "@prisma/client"

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

export const prisma = globalForPrisma.prisma ?? new PrismaClient()

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma
}

export function toNum(d: Prisma.Decimal | number | null | undefined): number {
  if (d == null) return 0
  if (typeof d === "number") return d
  return d.toNumber()
}

// Rekurzivně převede všechny Prisma.Decimal hodnoty na number — použij před NextResponse.json()
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function serializePrisma<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj, (_, v) => (v instanceof Prisma.Decimal ? v.toNumber() : v)))
}
