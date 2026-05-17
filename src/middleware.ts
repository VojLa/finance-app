export { default } from "next-auth/middleware"

export const config = {
  matcher: ["/dashboard/:path*", "/portfolio/:path*", "/accounts/:path*", "/import/:path*"],
}
