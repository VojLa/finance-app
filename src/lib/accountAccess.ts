import { prisma } from "@/lib/prisma"

export type AccountAccessRole = "viewer" | "editor" | "admin" | "owner"

const ROLE_RANK: Record<AccountAccessRole, number> = {
  viewer: 1,
  editor: 2,
  admin: 3,
  owner: 4,
}

function allowedRoles(minRole: AccountAccessRole): AccountAccessRole[] {
  return (Object.keys(ROLE_RANK) as AccountAccessRole[]).filter(
    (role) => ROLE_RANK[role] >= ROLE_RANK[minRole]
  )
}

export async function getAccessibleAccountIds(
  userId: string,
  minRole: AccountAccessRole = "viewer"
): Promise<string[]> {
  const memberships = await prisma.accountMember.findMany({
    where: {
      userId,
      role: { in: allowedRoles(minRole) },
    },
    select: { accountId: true },
  })

  return memberships.map((membership) => membership.accountId)
}

export async function assertAccountAccess(
  accountId: string,
  userId: string,
  minRole: AccountAccessRole = "viewer"
): Promise<boolean> {
  const membership = await prisma.accountMember.findFirst({
    where: {
      accountId,
      userId,
      role: { in: allowedRoles(minRole) },
    },
    select: { id: true },
  })

  return membership !== null
}
