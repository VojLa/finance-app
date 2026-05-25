import { prisma } from "@/lib/prisma"

/**
 * Returns all account IDs the user can access (owned + shared).
 * minRole "editor" excludes viewer-only shares.
 */
export async function getAccessibleAccountIds(
  userId: string,
  minRole: "viewer" | "editor" = "viewer"
): Promise<string[]> {
  const [ownAccounts, sharedAccounts] = await Promise.all([
    prisma.account.findMany({ where: { userId }, select: { id: true } }),
    prisma.accountShare.findMany({
      where: {
        sharedWithId: userId,
        ...(minRole === "editor" ? { role: "editor" } : {}),
      },
      select: { accountId: true },
    }),
  ])
  return [...ownAccounts.map((a) => a.id), ...sharedAccounts.map((s) => s.accountId)]
}

/**
 * Returns true if the user owns the account or has a share with at least the given role.
 */
export async function assertAccountAccess(
  accountId: string,
  userId: string,
  minRole: "viewer" | "editor" = "viewer"
): Promise<boolean> {
  const ownAccount = await prisma.account.findFirst({
    where: { id: accountId, userId },
    select: { id: true },
  })
  if (ownAccount) return true

  const share = await prisma.accountShare.findFirst({
    where: {
      accountId,
      sharedWithId: userId,
      ...(minRole === "editor" ? { role: "editor" } : {}),
    },
    select: { id: true },
  })
  return share !== null
}
