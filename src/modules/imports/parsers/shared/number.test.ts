import { describe, expect, it } from "vitest"
import { parseNum, sumAbsNums } from "./number"

describe("parseNum", () => {
  it("parses common localized number formats", () => {
    expect(parseNum("1 234,56")).toBe(1234.56)
    expect(parseNum("1234.56")).toBe(1234.56)
    expect(parseNum("(123,45)")).toBe(-123.45)
  })

  it("returns null for empty or invalid values", () => {
    expect(parseNum("")).toBeNull()
    expect(parseNum(undefined)).toBeNull()
    expect(parseNum("abc")).toBeNull()
  })
})

describe("sumAbsNums", () => {
  it("sums absolute values from selected fields", () => {
    expect(sumAbsNums({ fee: "-1,20", tax: "2.30", ignored: "5" }, ["fee", "tax"])).toBe(3.5)
  })

  it("returns null when all selected fields are empty or zero", () => {
    expect(sumAbsNums({ fee: "", tax: "0" }, ["fee", "tax"])).toBeNull()
  })
})
