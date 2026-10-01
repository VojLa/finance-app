import { describe, expect, it } from "vitest"

import {
  formatSnapshotDecimal,
  formatSnapshotPercentage,
  formatSnapshotQuantity,
  formatSnapshotTimestamp,
  snapshotPercentageTone,
} from "./snapshot-page-format"

describe("snapshot decimal presentation", () => {
  it("rounds exact decimal strings to two display places without Number conversion", () => {
    expect(formatSnapshotDecimal("123456.789012")).toBe("123 456,79")
    expect(formatSnapshotDecimal("-50.005000")).toBe("-50,01")
    expect(formatSnapshotDecimal("999.999000")).toBe("1 000,00")
    expect(formatSnapshotDecimal("0")).toBe("0,00")
  })

  it("formats allocation and profit percentages to one decimal and colors the displayed sign", () => {
    expect(formatSnapshotPercentage("56.6499")).toBe("56,6")
    expect(formatSnapshotPercentage("56.6500")).toBe("56,7")
    expect(formatSnapshotPercentage("-12.3499")).toBe("-12,3")
    expect(snapshotPercentageTone("0.0499")).toBe("neutral")
    expect(snapshotPercentageTone("0.0500")).toBe("positive")
    expect(snapshotPercentageTone("-0.0500")).toBe("negative")
    expect(snapshotPercentageTone(undefined)).toBe("unavailable")
  })

  it("keeps small asset quantities visible with adaptive decimal precision", () => {
    expect(formatSnapshotQuantity("12.3456789000")).toBe("12,35")
    expect(formatSnapshotQuantity("0.1234567890")).toBe("0,123")
    expect(formatSnapshotQuantity("0.0123456789")).toBe("0,0123")
    expect(formatSnapshotQuantity("0.0012345678")).toBe("0,0012")
    expect(formatSnapshotQuantity("0.0001234567")).toBe("0,00012")
    expect(formatSnapshotQuantity("0.0000001200")).toBe("0,00000012")
    expect(formatSnapshotQuantity("0.0000000001")).toBe("0,0000000001")
  })

  it("interprets timezone-less snapshot timestamps as UTC", () => {
    const timestamp = "2036-01-01T12:00:00.000"
    expect(formatSnapshotTimestamp(timestamp)).toBe(
      new Date(`${timestamp}Z`).toLocaleString("cs-CZ", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    )
  })
})
