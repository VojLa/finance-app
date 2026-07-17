import { describe, expect, it } from "vitest"
import { latestDate, parseCzechDate, parseIsoDate } from "./date"

describe("parseIsoDate", () => {
  it("parses valid ISO-like dates", () => {
    expect(parseIsoDate("2026-06-14T10:30:00.000Z")?.toISOString()).toBe("2026-06-14T10:30:00.000Z")
    expect(parseIsoDate("2026-01-01 02:03:12+00:00")?.toISOString()).toBe(
      "2026-01-01T02:03:12.000Z"
    )
  })

  it("returns null for missing or invalid dates", () => {
    expect(parseIsoDate(undefined)).toBeNull()
    expect(parseIsoDate("not-a-date")).toBeNull()
  })
})

describe("parseCzechDate", () => {
  it("parses Czech date with optional time as UTC", () => {
    expect(parseCzechDate("14. 6. 2026 12:05")?.toISOString()).toBe("2026-06-14T12:05:00.000Z")
    expect(parseCzechDate("14.6.2026")?.toISOString()).toBe("2026-06-14T00:00:00.000Z")
  })

  it("rejects malformed dates", () => {
    expect(parseCzechDate("32. 1. 2026")).toBeNull()
    expect(parseCzechDate("2026-06-14")).toBeNull()
  })
})

describe("latestDate", () => {
  it("returns the newest non-null date", () => {
    const older = new Date("2026-01-01T00:00:00.000Z")
    const newer = new Date("2026-02-01T00:00:00.000Z")

    expect(latestDate([null, older, newer, null])).toBe(newer)
  })
})
