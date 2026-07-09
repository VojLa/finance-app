import { describe, expect, it } from "vitest"
import { cleanCsvValue, get, normalizeCsvHeader, normalizeText, parseCsvRows } from "./csv"

describe("CSV helpers", () => {
  it("cleans values and headers", () => {
    expect(cleanCsvValue(' " value " ')).toBe(" value ")
    expect(normalizeCsvHeader("\uFEFF Name ")).toBe("Name")
    expect(normalizeText(" Buy ")).toBe("buy")
  })

  it("parses rows with normalized headers and drops empty rows", () => {
    const rows = parseCsvRows("\uFEFFName,Amount\n Alice , 10 \n, \n")

    expect(rows).toEqual([{ Name: "Alice", Amount: "10" }])
  })

  it("gets the first non-empty value from a list of possible keys", () => {
    expect(get({ A: "", B: "value", C: "other" }, ["A", "B", "C"])).toBe("value")
    expect(get({ A: "" }, ["A"])).toBeUndefined()
  })
})
