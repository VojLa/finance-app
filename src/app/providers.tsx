"use client"

import { SessionProvider } from "next-auth/react"

import { ImportJobMonitor } from "@/modules/imports/python/import-job-monitor"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ImportJobMonitor />
      {children}
    </SessionProvider>
  )
}
