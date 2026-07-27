#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { isIP } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONFIG_PATH = resolve(ROOT, "apps/desktop/src-tauri/tauri.conf.json");
const RESERVED_HOST_SUFFIXES = [
  ".example",
  ".internal",
  ".invalid",
  ".lan",
  ".local",
  ".localhost",
  ".test",
];

function isPublicDnsHostname(hostname) {
  const normalized = hostname
    .trim()
    .toLowerCase()
    .replace(/^\[|\]$/g, "")
    .replace(/\.$/, "");
  if (!normalized || isIP(normalized) !== 0) return false;
  if (
    normalized === "localhost" ||
    RESERVED_HOST_SUFFIXES.some((suffix) => normalized.endsWith(suffix))
  ) {
    return false;
  }
  return /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(
    normalized,
  );
}

export function validateDesktopApiBase(rawValue) {
  const value = String(rawValue ?? "")
    .trim()
    .replace(/\/+$/, "");
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("VITE_API_BASE 必须是绝对 HTTPS 地址");
  }
  if (parsed.protocol !== "https:" || !parsed.hostname) {
    throw new Error("VITE_API_BASE 必须是绝对 HTTPS 地址");
  }
  if (!isPublicDnsHostname(parsed.hostname)) {
    throw new Error("VITE_API_BASE 必须使用公网正式域名");
  }
  if (parsed.username || parsed.password) {
    throw new Error("VITE_API_BASE 禁止内嵌凭据");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("VITE_API_BASE 禁止查询参数和片段");
  }
  if (parsed.pathname.replace(/\/+$/, "") !== "/api/v1") {
    throw new Error("VITE_API_BASE 必须以 /api/v1 结尾");
  }
  return `${parsed.origin}/api/v1`;
}

export function validateDesktopConfig(config) {
  if (config?.build?.frontendDist !== "../../web/dist") {
    throw new Error("桌面 frontendDist 必须指向 ../../web/dist");
  }
  const mainWindow = config?.app?.windows?.find(
    (window) => window?.label === "main",
  );
  if (!mainWindow || mainWindow.useHttpsScheme !== true) {
    throw new Error(
      "桌面主窗口必须固定 label=main 并启用 Windows HTTPS Origin",
    );
  }
  const csp = config?.app?.security?.csp;
  if (
    typeof csp !== "object" ||
    csp === null ||
    Array.isArray(csp) ||
    Object.keys(csp).length === 0
  ) {
    throw new Error("桌面发布必须使用显式 CSP 指令");
  }
  const capabilities = config?.app?.security?.capabilities;
  if (
    !Array.isArray(capabilities) ||
    capabilities.length !== 1 ||
    capabilities[0] !== "default"
  ) {
    throw new Error("桌面发布 capability 必须固定为 default");
  }
  if (
    csp["script-src"] !== "'self'" ||
    String(csp["default-src"] ?? "").includes("*") ||
    String(csp["script-src"]).includes("unsafe-")
  ) {
    throw new Error("桌面发布 CSP 的 script-src 必须严格限制为 'self'");
  }
  if (config?.bundle?.active !== true) {
    throw new Error("桌面发布必须启用 bundle");
  }
  if (config?.bundle?.macOS?.signingIdentity === "-") {
    throw new Error("正式配置不得固化 macOS 临时签名");
  }
}

export function validateDistributionEnvironment(
  environment = process.env,
  platform = process.platform,
) {
  if (platform === "darwin") {
    const identity = String(environment.APPLE_SIGNING_IDENTITY ?? "").trim();
    if (!identity || identity === "-") {
      throw new Error(
        "macOS 分发必须配置正式 APPLE_SIGNING_IDENTITY，禁止临时签名",
      );
    }
    if (!identity.startsWith("Developer ID Application: ")) {
      throw new Error(
        "macOS 直接分发必须使用 Developer ID Application 签名身份",
      );
    }
    const hasApiCredentials = [
      "APPLE_API_ISSUER",
      "APPLE_API_KEY",
      "APPLE_API_KEY_PATH",
    ].every((name) => String(environment[name] ?? "").trim());
    const hasAppleIdCredentials = [
      "APPLE_ID",
      "APPLE_PASSWORD",
      "APPLE_TEAM_ID",
    ].every((name) => String(environment[name] ?? "").trim());
    if (!hasApiCredentials && !hasAppleIdCredentials) {
      throw new Error(
        "macOS 分发缺少完整公证凭据：配置 App Store Connect API 或 Apple ID 三件套",
      );
    }
    return;
  }
  if (platform === "win32") {
    throw new Error(
      "Windows 分发必须在受控 Windows CI 中完成证书导入、签名和安装验收",
    );
  }
  throw new Error("桌面安装包分发检查不支持在当前平台执行");
}

export function checkDesktopRelease({
  apiBase = process.env.VITE_API_BASE,
  configPath = CONFIG_PATH,
} = {}) {
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  validateDesktopConfig(config);
  const normalizedApiBase = validateDesktopApiBase(apiBase);
  if (process.argv.includes("--distribution")) {
    validateDistributionEnvironment();
  }
  return { configPath, apiBase: normalizedApiBase };
}

if (
  process.argv[1] &&
  pathToFileURL(resolve(process.argv[1])).href === import.meta.url
) {
  try {
    const result = checkDesktopRelease();
    console.log(
      `桌面发布前置检查通过：config=${result.configPath} api=${result.apiBase}`,
    );
  } catch (error) {
    console.error(
      error instanceof Error ? error.message : "桌面发布前置检查失败",
    );
    process.exitCode = 1;
  }
}
