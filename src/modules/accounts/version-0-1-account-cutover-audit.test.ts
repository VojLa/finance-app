import type { NextRequest } from "next/server"
import { getServerSession } from "next-auth"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { prisma } from "@/lib/prisma"
import { POST } from "@/app/api/accounts/route"

vi.mock("next-auth", () => ({
  getServerSession: vi.fn(),
}))

vi.mock("@/lib/auth", () => ({
  authOptions: { providers: [] },
}))

vi.mock("@/lib/accountAccess", () => ({
  assertAccountAccess: vi.fn(),
}))

vi.mock("@/lib/prisma", () => ({
  prisma: {
    user: { findUnique: vi.fn() },
    account: {
      create: vi.fn(),
      findMany: vi.fn(),
      findUnique: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
    accountMember: { findMany: vi.fn() },
    transaction: { findMany: vi.fn(), deleteMany: vi.fn() },
    transactionPair: { deleteMany: vi.fn() },
    accountSnapshot: { deleteMany: vi.fn() },
    transactionSplit: { deleteMany: vi.fn() },
    investmentEvent: { deleteMany: vi.fn() },
    holding: { deleteMany: vi.fn() },
    importBatch: { deleteMany: vi.fn() },
    $transaction: vi.fn(),
  },
}))

const getSession = vi.mocked(getServerSession)
const findUser = vi.mocked(prisma.user.findUnique)
const createAccount = vi.mocked(prisma.account.create)

beforeEach(() => {
  vi.clearAllMocks()
})

describe("version 0.1 account browser-flow acceptance", () => {
  it("proves the current authenticated account creation is owned by Prisma, not Python", async () => {
    getSession.mockResolvedValue({
      user: { id: "account-audit-user", email: "audit@example.test" },
      expires: "2038-01-01",
    })
    findUser.mockResolvedValue({ id: "account-audit-user" } as never)
    createAccount.mockResolvedValue({
      id: "account-audit-account",
      name: "Audit broker",
      type: "broker",
      currency: "EUR",
      color: null,
    } as never)
    const backendFetch = vi.spyOn(globalThis, "fetch")

    const response = await POST(
      new Request("http://next.test/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "Audit broker",
          type: "broker",
          currency: "EUR",
        }),
      }) as NextRequest
    )

    expect(response.status).toBe(201)
    expect(getSession).toHaveBeenCalledTimes(1)
    expect(findUser).toHaveBeenCalledWith({
      where: { id: "account-audit-user" },
      select: { id: true },
    })
    expect(createAccount).toHaveBeenCalledTimes(1)
    expect(createAccount).toHaveBeenCalledWith({
      data: {
        name: "Audit broker",
        type: "broker",
        currency: "EUR",
        color: null,
        members: {
          create: {
            userId: "account-audit-user",
            role: "owner",
            relationType: "owner",
            acceptedAt: expect.any(Date),
          },
        },
      },
    })
    expect(backendFetch).not.toHaveBeenCalled()
  })

  it("rejects a missing session before the Prisma write", async () => {
    getSession.mockResolvedValue(null)

    const response = await POST(
      new Request("http://next.test/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Blocked", type: "broker", currency: "EUR" }),
      }) as NextRequest
    )

    expect(response.status).toBe(401)
    expect(findUser).not.toHaveBeenCalled()
    expect(createAccount).not.toHaveBeenCalled()
  })
})
