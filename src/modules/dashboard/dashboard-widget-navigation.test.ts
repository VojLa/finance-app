import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

const widgetFiles = {
  "SnapshotSummaryCards.tsx": { actions: 1, actionPattern: /Zobrazit více/g },
  "SnapshotAccountCards.tsx": { actions: 1, actionPattern: /Zobrazit více/g },
  "SnapshotAssetAllocationChart.tsx": { actions: 1, actionPattern: /Zobrazit více/g },
  "SnapshotTopPositions.tsx": { actions: 1, actionPattern: /Zobrazit více/g },
  "OperationalDashboardSections.tsx": { actions: 6, actionPattern: /<WidgetMoreLink href=/g },
}

describe("dashboard widget navigation", () => {
  it("gives every dashboard widget a consistent detail action", async () => {
    const contents = await Promise.all(
      Object.keys(widgetFiles).map(async (file) => [
        file,
        await readFile(path.join(process.cwd(), "src/modules/dashboard", file), "utf8"),
      ])
    )

    for (const [file, content] of contents) {
      expect(content).toContain("Zobrazit více")
      const expected = widgetFiles[file as keyof typeof widgetFiles]
      expect(content.match(expected.actionPattern)).toHaveLength(expected.actions)
    }
  })
})
