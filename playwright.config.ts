import { defineConfig } from "@playwright/test";

const e2eDatabase = `sqlite+aiosqlite:////tmp/oral-ip-e2e-${process.pid}.db`;
const e2eStorage = `/tmp/oral-ip-e2e-storage-${process.pid}`;
const e2eApiPort = Number(process.env.E2E_API_PORT ?? 28_080);
const e2eWebPort = Number(process.env.E2E_WEB_PORT ?? 25_173);
const e2eApiOrigin = `http://127.0.0.1:${e2eApiPort}`;
const e2eWebOrigin = `http://127.0.0.1:${e2eWebPort}`;
process.env.E2E_API_BASE ??= `${e2eApiOrigin}/api`;

/**
 * Playwright 走查：核心流程页、V1.1 预览隔离与 7 步向导
 * 默认使用隔离端口 28080/25173；可通过 E2E_API_PORT/E2E_WEB_PORT 覆盖。
 */
export default defineConfig({
  testDir: "./tools/e2e",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: e2eWebOrigin,
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command:
        `exec env APP_ENV=test DATABASE_URL=${e2eDatabase} LOCAL_STORAGE_DIR=${e2eStorage} ` +
        "BOOTSTRAP_ADMIN_PHONE=18800000000 BOOTSTRAP_ADMIN_PASSWORD=E2eAdmin@12345 " +
        `uv run --directory server uvicorn app.main:app --host 127.0.0.1 --port ${e2eApiPort}`,
      url: `${e2eApiOrigin}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        `VITE_PROXY_TARGET=${e2eApiOrigin} pnpm --filter @oral/web dev ` +
        `--host 127.0.0.1 --port ${e2eWebPort}`,
      url: e2eWebOrigin,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
