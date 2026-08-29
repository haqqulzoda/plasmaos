import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
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

export default nextConfig;
