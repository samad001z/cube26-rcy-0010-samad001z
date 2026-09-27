import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "Load demo data" reads demo-data/ at request time (copied from ../demo by the prebuild
  // step); ship those files with that route's function.
  outputFileTracingIncludes: {
    "/api/run/demo": ["./demo-data/**/*"],
  },
};

export default nextConfig;
