import { describe, expect, it } from "vitest"

import { formatSnapshotDecimal } from "./snapshot-page-format"

describe("snapshot decimal presentation", () => {
  it("rounds exact decimal strings to two display places without Number conversion", () => {
    expect(formatSnapshotDecimal("123456.789012")).toBe("123 456,79")
    expect(formatSnapshotDecimal("-50.005000")).toBe("-50,01")
    expect(formatSnapshotDecimal("999.999000")).toBe("1 000,00")
    expect(formatSnapshotDecimal("0")).toBe("0,00")
  })
})
