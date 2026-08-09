import type { NextAuthOptions } from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"

import { createPythonAuthApi } from "@/modules/auth/server/auth-api"
import { SnapshotWorkflowAdapterError } from "@/modules/python-api/server/errors"

export async function authorizeCredentials(credentials: { email?: string; password?: string }) {
  if (!credentials.email || !credentials.password) return null

  try {
    const user = await createPythonAuthApi().verifyCredentials({
      email: credentials.email,
      password: credentials.password,
    })
    return { id: user.id, email: user.email, name: user.name }
  } catch (error) {
    if (error instanceof SnapshotWorkflowAdapterError && error.status === 401) {
      return null
    }
    throw error
  }
}

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Heslo", type: "password" },
      },
      async authorize(credentials) {
        return authorizeCredentials(credentials ?? {})
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) token.id = user.id
      return token
    },
    session({ session, token }) {
      if (session.user) session.user.id = token.id as string
      return session
    },
  },
}
