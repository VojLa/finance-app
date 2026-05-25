import { Prisma } from "@prisma/client"

export type DecimalInput = Prisma.Decimal | number | string

export function toDecimal(value: DecimalInput): Prisma.Decimal {
  return new Prisma.Decimal(value)
}

export function decimalToNumber(value: Prisma.Decimal | number | null | undefined): number {
  if (value == null) return 0
  if (typeof value === "number") return value
  return value.toNumber()
}
