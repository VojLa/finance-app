"use client"

import { useSession, signOut } from "next-auth/react"

export default function SettingsPage() {
  const { data: session } = useSession()

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Nastavení</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-medium text-gray-900">Profil</h2>
        <div>
          <p className="text-sm text-gray-500">E-mail</p>
          <p className="text-sm font-medium text-gray-900 mt-0.5">{session?.user?.email}</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
        <h2 className="text-base font-medium text-gray-900">Účet</h2>
        <p className="text-sm text-gray-400">Další nastavení budou přidána v budoucnu.</p>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="px-4 py-2 rounded-lg text-sm font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors"
        >
          Odhlásit se
        </button>
      </div>
    </div>
  )
}
