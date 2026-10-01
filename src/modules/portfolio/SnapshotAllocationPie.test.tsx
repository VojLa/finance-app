import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { buildSnapshotAllocationSlices } from "./snapshot-allocation-pie"

describe("SnapshotAllocationPie", () => {
  it("keeps at most five major slices and groups smaller holdings into Ostatní", () => {
    const items = [
      { key: "a", name: "AAA", allocationPct: "40.0000" },
      { key: "b", name: "BBB", allocationPct: "20.0000" },
      { key: "c", name: "CCC", allocationPct: "15.0000" },
      { key: "d", name: "DDD", allocationPct: "10.0000" },
      { key: "e", name: "EEE", allocationPct: "5.0000" },
      { key: "f", name: "FFF", allocationPct: "4.9999" },
      { key: "g", name: "GGG", allocationPct: "5.0001" },
    ] as const
    const before = JSON.stringify(items)

    const slices = buildSnapshotAllocationSlices(items)

    expect(slices.map((slice) => slice.name)).toEqual([
      "AAA",
      "BBB",
      "CCC",
      "DDD",
      "GGG",
      "Ostatní",
    ])
    expect(slices.at(-1)?.exactAllocation).toBe("9.9999")
    expect(slices.at(-1)?.members.map((item) => item.name)).toEqual(["EEE", "FFF"])
    expect(JSON.stringify(items)).toBe(before)
  })

  it("keeps the five-percent boundary as its own slice", () => {
    expect(
      buildSnapshotAllocationSlices([
        { key: "a", name: "AAA", allocationPct: "95.0000" },
        { key: "b", name: "BBB", allocationPct: "5.0000" },
      ]).map((slice) => slice.name)
    ).toEqual(["AAA", "BBB"])
  })

  it("preserves exact grouped rounding overflow for presentation-safe geometry", async () => {
    const slices = buildSnapshotAllocationSlices(
      Array.from({ length: 3_200 }, (_, index) => ({
        key: String(index),
        name: `Position ${index}`,
        allocationPct: "0.0313",
      }))
    )
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/SnapshotAllocationPie.tsx"),
      "utf8"
    )

    expect(slices).toHaveLength(1)
    expect(slices[0]?.exactAllocation).toBe("100.1600")
    expect(source).toContain("slice.members.length * 0.00005")
    expect(source).toContain("return converted > 100 ? 100 : converted")
  })

  it("fails closed for a non-canonical percentage", () => {
    expect(() =>
      buildSnapshotAllocationSlices([{ key: "a", name: "AAA", allocationPct: "5" }])
    ).toThrow(TypeError)
  })

  it("uses a native SVG pie whose sectors do not depend on responsive container sizing", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/SnapshotAllocationPie.tsx"),
      "utf8"
    )

    expect(source).toContain("<svg")
    expect(source).toContain('aria-label="Koláčový graf alokace portfolia"')
    expect(source).toContain("<path")
    expect(source).toContain("sectorPath(slice)")
    expect(source).not.toContain("strokeDasharray")
    expect(source).not.toContain("ResponsiveContainer")
  })

  it("does not label a nonempty all-zero allocation as a complete portfolio", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/SnapshotAllocationPie.tsx"),
      "utf8"
    )

    expect(source).toContain("!data.some((slice) => slice.value > 0)")
    expect(source).not.toContain("100 %")
  })
})
