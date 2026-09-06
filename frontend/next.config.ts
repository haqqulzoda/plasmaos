import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

if (process.env.NODE_ENV === 'production' && process.env.PLASMA_ENABLE_PSEUDO_LOCALE === '1') {
  throw new Error('Pseudo locale cannot be enabled in a release build');
}

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  async headers() {
    return [{source: '/:path*', headers: [
      {key: 'X-Content-Type-Options', value: 'nosniff'},
      {key: 'Referrer-Policy', value: 'same-origin'},
      {key: 'X-Frame-Options', value: 'SAMEORIGIN'},
      {key: 'Content-Security-Policy', value: "frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com"},
    ]}];
  },
  async rewrites() {
    const backendBase =
      process.env.BACKEND_INTERNAL_URL ??
      "http://backend:8000/api/v1";

    const normalized = backendBase.replace(/\/$/, "");

    return [
      {
        source: "/api/v1/:path*",
        destination: `${normalized}/:path*`,
      },
    ];
  },
};

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

export default withNextIntl(nextConfig);
