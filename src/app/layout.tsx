import type { Metadata } from "next"
import "./globals.css"
import { Providers } from "./providers"
import { Nav } from "@/components/Nav"

export const metadata: Metadata = {
  title: "Finance App",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="cs">
      <body className="bg-gray-50 min-h-screen">
        <Providers>
          <Nav />
          <main className="max-w-7xl mx-auto px-6 py-8">{children}</main>
        </Providers>
      </body>
    </html>
  )
}
