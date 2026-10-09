import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // lucide-react + recharts are optimized by default; @xyflow/react is not.
  experimental: {
    optimizePackageImports: ["@xyflow/react"],
  },
  poweredByHeader: false,
};

export default nextConfig;
