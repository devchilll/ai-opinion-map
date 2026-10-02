import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Opening the dev server by LAN address (a phone, another laptop) is blocked
  // by default, and a blocked page never hydrates: the 3D canvas stays blank.
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "*.local"],
};

export default nextConfig;
