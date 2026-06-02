import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backendBase =
      process.env.BACKEND_INTERNAL_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      "http://localhost:8000/api/v1";

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
