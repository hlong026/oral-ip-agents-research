import { defineConfig } from "@playwright/test";

/**
 * Playwright 走查（§8：13 个流程页 flow-bar 高亮 + 7 步向导）
 * 前置：后端运行在 8000（vite 代理 /api、/media、/ws）
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: "pnpm --filter @oral/web dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
