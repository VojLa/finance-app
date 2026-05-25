export { default } from "next-auth/middleware"

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/portfolio/:path*",
    "/accounts/:path*",
    "/import/:path*",
    "/transactions/:path*",
    "/budgets/:path*",
    "/categories/:path*",
    "/settings/:path*",
  ],
}
