import { describe, expect, it } from "vitest"

import { defaultLiabilityEffectiveAt, toNaiveUtcLiabilityTimestamp } from "./liability-balance-time"

describe("manual liability timestamp boundary", () => {
  it("round-trips the local input through the canonical naive UTC transport", () => {
    const now = new Date("2026-08-19T20:55:46.789Z")
    const localInput = defaultLiabilityEffectiveAt(now)
    const naiveUtc = toNaiveUtcLiabilityTimestamp(localInput)

    expect(new Date(`${naiveUtc}Z`).getTime()).toBe(new Date("2026-08-19T20:55:46.000Z").getTime())
  })

  it.each(["", "2026-08-19", "19.08.2026 22:55", "2026-13-40T99:99"])(
    "rejects a non-canonical local input: %s",
    (value) => {
      expect(() => toNaiveUtcLiabilityTimestamp(value)).toThrow(TypeError)
    }
  )
})
