import { defineConfig } from "@playwright/test";

const e2eDatabase = `sqlite+aiosqlite:////tmp/oral-ip-e2e-${process.pid}.db`;
const e2eStorage = `/tmp/oral-ip-e2e-storage-${process.pid}`;
const reuseApiServer = process.env.E2E_REUSE_API_SERVER === "1";

/**
 * Playwright 走查（§8：13 个流程页 flow-bar 高亮 + 7 步向导）
 * 前置：后端运行在 8000（vite 代理 /api、/media、/ws）
 */
export default defineConfig({
  testDir: "./e2e",
  testIgnore: reuseApiServer ? [] : ["**/container-proxy.spec.ts"],
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    ...(!reuseApiServer
      ? [
          {
            command:
              `exec env APP_ENV=test DATABASE_URL=${e2eDatabase} ` +
              `LOCAL_STORAGE_DIR=${e2eStorage} STORAGE_DRIVER=local REDIS_URL=redis://127.0.0.1:1/9 ` +
              "DEEPSEEK_API_KEY= DOUYIDOU_APP_ID= DASHSCOPE_API_KEY= FEIYING_API_KEY= " +
              "IM_ENABLED=false PUBLISH_VERIFIED_PLATFORMS= " +
              "BOOTSTRAP_ADMIN_PHONE=18800000000 BOOTSTRAP_ADMIN_PASSWORD=E2eAdmin@12345 " +
              "uv run --directory server uvicorn app.main:app --host 127.0.0.1 --port 8000",
            url: "http://127.0.0.1:8000/healthz",
            reuseExistingServer: false,
            timeout: 120_000,
          },
        ]
      : []),
    {
      command: "pnpm --filter @oral/web dev --host 127.0.0.1",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: reuseApiServer,
      timeout: 120_000,
    },
  ],
});
