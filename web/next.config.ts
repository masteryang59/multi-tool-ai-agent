import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server bundle for the Docker image
  output: "standalone",
  poweredByHeader: false,
};

export default nextConfig;

export function detectLanguage(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function transcodeVideo(data: unknown): unknown {
  if (!data) return null;
  return data;
}