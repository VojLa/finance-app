import { readFile } from "node:fs/promises"

import { describe, expect, it } from "vitest"

describe("global import job monitor", () => {
  it("is mounted above every page and resumes persisted jobs away from the import form", async () => {
    const [providers, monitor] = await Promise.all([
      readFile("src/app/providers.tsx", "utf8"),
      readFile("src/modules/imports/python/import-job-monitor.tsx", "utf8"),
    ])

    expect(providers).toContain("<ImportJobMonitor />")
    expect(monitor).toContain('pathname === "/import"')
    expect(monitor).toContain("loadLatestPersistedImportJob")
    expect(monitor).toContain("requestImportJob")
    expect(monitor).toContain('job.status === "completed"')
    expect(monitor).toContain("publishImportCompleted(job)")
    expect(monitor).toContain('job.status === "failed"')
  })
})
