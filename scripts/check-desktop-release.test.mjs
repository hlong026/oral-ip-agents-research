import assert from "node:assert/strict";
import { test } from "node:test";

import {
  validateDesktopApiBase,
  validateDesktopConfig,
  validateDistributionEnvironment,
} from "./check-desktop-release.mjs";

const VALID_CONFIG = {
  build: {
    frontendDist: "../../web/dist",
  },
  app: {
    windows: [
      {
        label: "main",
        useHttpsScheme: true,
      },
    ],
    security: {
      capabilities: ["default"],
      csp: {
        "default-src": "'self' customprotocol: asset:",
        "connect-src": "'self' ipc: http://ipc.localhost https: wss:",
        "script-src": "'self'",
      },
    },
  },
  bundle: {
    active: true,
    macOS: {},
  },
};

test("桌面发布 API 必须是无凭据、无查询参数的 HTTPS /api/v1 地址", () => {
  assert.equal(
    validateDesktopApiBase("https://api.oral.company/api/v1"),
    "https://api.oral.company/api/v1",
  );
  assert.throws(() => validateDesktopApiBase("/api/v1"), /绝对 HTTPS/);
  assert.throws(
    () => validateDesktopApiBase("http://api.oral.company/api/v1"),
    /绝对 HTTPS/,
  );
  assert.throws(
    () => validateDesktopApiBase("https://user:pass@api.oral.company/api/v1"),
    /凭据/,
  );
  assert.throws(
    () => validateDesktopApiBase("https://api.oral.company/api/v2"),
    /api\/v1/,
  );
  for (const privateApiBase of [
    "https://localhost/api/v1",
    "https://127.0.0.1/api/v1",
    "https://[::1]/api/v1",
    "https://10.0.0.8/api/v1",
    "https://api.internal/api/v1",
    "https://api.example/api/v1",
    "https://oral-api/api/v1",
  ]) {
    assert.throws(() => validateDesktopApiBase(privateApiBase), /公网正式域名/);
  }
});

test("桌面发布配置必须启用 CSP、固定主窗口和 Windows HTTPS Origin", () => {
  assert.doesNotThrow(() => validateDesktopConfig(VALID_CONFIG));
  assert.throws(
    () =>
      validateDesktopConfig({
        ...VALID_CONFIG,
        app: {
          ...VALID_CONFIG.app,
          security: { csp: null },
        },
      }),
    /CSP/,
  );
  assert.throws(
    () =>
      validateDesktopConfig({
        ...VALID_CONFIG,
        bundle: {
          ...VALID_CONFIG.bundle,
          macOS: { signingIdentity: "-" },
        },
      }),
    /临时签名/,
  );
  assert.throws(
    () =>
      validateDesktopConfig({
        ...VALID_CONFIG,
        app: {
          ...VALID_CONFIG.app,
          security: {
            capabilities: ["default", "shell:default"],
            csp: VALID_CONFIG.app.security.csp,
          },
        },
      }),
    /capability/,
  );
  assert.throws(
    () =>
      validateDesktopConfig({
        ...VALID_CONFIG,
        app: {
          ...VALID_CONFIG.app,
          security: {
            capabilities: ["default"],
            csp: {
              ...VALID_CONFIG.app.security.csp,
              "script-src": "'self' 'unsafe-eval'",
            },
          },
        },
      }),
    /script-src/,
  );
});

test("macOS 分发必须同时具备正式签名身份和一组公证凭据", () => {
  assert.throws(
    () => validateDistributionEnvironment({}, "darwin"),
    /APPLE_SIGNING_IDENTITY/,
  );
  assert.throws(
    () =>
      validateDistributionEnvironment(
        { APPLE_SIGNING_IDENTITY: "Developer ID Application: Oral" },
        "darwin",
      ),
    /公证凭据/,
  );
  assert.throws(
    () =>
      validateDistributionEnvironment(
        {
          APPLE_SIGNING_IDENTITY: "Oral",
          APPLE_API_ISSUER: "issuer",
          APPLE_API_KEY: "key",
          APPLE_API_KEY_PATH: "/secure/AuthKey.p8",
        },
        "darwin",
      ),
    /Developer ID Application/,
  );
  assert.doesNotThrow(() =>
    validateDistributionEnvironment(
      {
        APPLE_SIGNING_IDENTITY: "Developer ID Application: Oral",
        APPLE_API_ISSUER: "issuer",
        APPLE_API_KEY: "key",
        APPLE_API_KEY_PATH: "/secure/AuthKey.p8",
      },
      "darwin",
    ),
  );
  assert.throws(
    () => validateDistributionEnvironment({}, "linux"),
    /不支持在当前平台/,
  );
});
