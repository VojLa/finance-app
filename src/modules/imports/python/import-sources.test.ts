import { describe, expect, it } from "vitest"

import { IMPORT_SOURCE_OPTIONS } from "./import-sources"

describe("Raiffeisenbank import account eligibility", () => {
  it("offers every supported cash and liability account type", () => {
    expect(
      IMPORT_SOURCE_OPTIONS.find((source) => source.value === "raiffeisenbank")?.accepts
    ).toEqual(["bank", "savings", "credit_card"])
  })
})
