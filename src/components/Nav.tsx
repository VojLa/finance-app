"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { signOut, useSession } from "next-auth/react"

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/accounts", label: "Účty" },
  { href: "/import", label: "Import" },
]

export function Nav() {
  const pathname = usePathname()
  const { data: session } = useSession()

  if (!session) return null

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <span className="font-semibold text-gray-900">Finance</span>
        <div className="flex gap-1">
          {links.map(link => (
            <Link
              key={link.href}
              href={link.href}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                pathname.startsWith(link.href)
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:text-gray-900 hover:bg-gray-50"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-500">{session.user.email}</span>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="text-sm text-gray-500 hover:text-gray-900"
        >
          Odhlásit
        </button>
      </div>
    </nav>
  )
}
