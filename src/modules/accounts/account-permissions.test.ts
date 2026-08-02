import { describe, expect, it } from "vitest"

import {
  accountRoleLabel,
  canArchiveAccount,
  canEditAccount,
  isSharedAccount,
} from "./account-permissions"

describe("account page role permissions", () => {
  it.each([
    ["owner", true, true, "Vlastník"],
    ["admin", true, true, "Administrátor"],
    ["editor", true, false, "Editor"],
    ["viewer", false, false, "Prohlížející"],
  ] as const)("%s has the exact edit/archive controls", (role, edit, archive, label) => {
    expect(canEditAccount(role)).toBe(edit)
    expect(canArchiveAccount(role)).toBe(archive)
    expect(accountRoleLabel(role)).toBe(label)
  })

  it.each([
    ["owner", false],
    ["joint_owner", true],
    ["manager", true],
    ["beneficiary", true],
    ["collaborator", true],
  ] as const)("relation %s has exact shared status", (relation, shared) => {
    expect(isSharedAccount(relation)).toBe(shared)
  })
})
