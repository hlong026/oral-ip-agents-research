import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8000";
const websocketTarget = proxyTarget.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: proxyTarget, changeOrigin: true },
      "/media": { target: proxyTarget, changeOrigin: true },
      "/ws": { target: websocketTarget, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
