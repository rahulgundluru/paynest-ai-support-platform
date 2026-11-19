import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is enabled in the Docker build (Linux). On Windows hosts it needs
  // symlink privileges that pnpm's layout triggers, so local builds use the default output.
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
