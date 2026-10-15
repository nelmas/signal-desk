import path from "node:path";
import type { NextConfig } from "next";

// Locally, share the backend's .env in the repo root (existing variables win). On Vercel,
// variables come from the project settings and there is no such file.
try {
  process.loadEnvFile(path.resolve(process.cwd(), "..", ".env"));
} catch {
  // no shared .env: fine
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Private app: never indexed, never framed, no referrer to outlets.
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
};

export default nextConfig;
