/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverComponentsExternalPackages: ["yahoo-finance2"],
  },
}

module.exports = nextConfig
