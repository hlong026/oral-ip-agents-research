/**
 * HTTP 客户端：JWT 双令牌自动刷新（F-601 / C7）
 * - accessToken 内存持有；refreshToken 持久化
 * - 401 时单飞刷新并重放原请求
 * - X-Trace-Id 请求头注入（§10.6.9 Phase 4，前后端日志贯通）
 */
import type { ApiError, AuthTokens } from "@oral/types";
import { deviceFingerprint } from "./fingerprint";

type ImportMetaWithEnv = ImportMeta & { env?: { VITE_API_BASE?: string } };

export const API_BASE = (
  (import.meta as ImportMetaWithEnv).env?.VITE_API_BASE ?? "/api/v1"
).replace(/\/+$/, "");

export function buildApiUrl(path: string, base = API_BASE): string {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

// API_BASE 为绝对地址（桌面壳等跨源部署）时，后端返回的 /media/ 相对路径
// 会被错误解析到页面 origin（如 tauri.localhost），需统一换算到 API 同源
const API_ORIGIN = /^https?:\/\//.test(API_BASE) ? new URL(API_BASE).origin : "";

/** 将后端下发的 /media/ 相对路径换算为 API 同源绝对地址（同源部署时原样返回） */
export function absolutizeMediaUrl(value: string): string {
  return API_ORIGIN && value.startsWith("/media/")
    ? `${API_ORIGIN}${value}`
    : value;
}

/** 递归重写响应体里所有 /media/ 路径，覆盖嵌套产物（如 artifacts.final_video_url） */
function absolutizeMedia(data: unknown): unknown {
  if (!API_ORIGIN) return data; // 同源部署无需重写，避免无谓深拷贝
  if (typeof data === "string") return absolutizeMediaUrl(data);
  if (Array.isArray(data)) return data.map(absolutizeMedia);
  if (data && typeof data === "object") {
    return Object.fromEntries(
      Object.entries(data).map(([k, v]) => [k, absolutizeMedia(v)]),
    );
  }
  return data;
}

let accessToken: string | null = null;
let refreshToken: string | null = localStorage.getItem("oral_rt");
let refreshing: Promise<boolean> | null = null;

/** 生成短 trace_id（16 位 hex） */
function genTraceId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}

export function setTokens(tokens: AuthTokens | null) {
  accessToken = tokens?.accessToken ?? null;
  refreshToken = tokens?.refreshToken ?? null;
  if (tokens) localStorage.setItem("oral_rt", tokens.refreshToken);
  else localStorage.removeItem("oral_rt");
}

export function hasSession(): boolean {
  return Boolean(refreshToken);
}

export function getAccessToken(): string | null {
  return accessToken;
}

async function doRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  try {
    const res = await fetch(buildApiUrl("/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        refreshToken,
        deviceFingerprint: await deviceFingerprint(),
      }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as AuthTokens;
    setTokens(data);
    return true;
  } catch {
    return false;
  }
}

export async function restoreSession(): Promise<boolean> {
  if (accessToken) return true;
  if (!refreshToken) return false;
  refreshing ??= doRefresh().finally(() => (refreshing = null));
  return refreshing;
}

export class HttpError extends Error {
  constructor(
    public status: number,
    public body: ApiError,
  ) {
    super(body.message);
    this.name = "HttpError";
  }
}

async function rawFetch<T>(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (
    !headers.has("Content-Type") &&
    init.body &&
    !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  // 注入 X-Trace-Id（§10.6.9 Phase 4）
  if (!headers.has("X-Trace-Id")) {
    headers.set("X-Trace-Id", genTraceId());
  }

  const res = await fetch(buildApiUrl(path), { ...init, headers });

  if (res.status === 401 && !retried) {
    refreshing ??= doRefresh().finally(() => (refreshing = null));
    const ok = await refreshing;
    if (ok) return rawFetch<T>(path, init, true);
    setTokens(null);
    window.location.href = "/login";
    throw new HttpError(401, { code: "UNAUTHORIZED", message: "登录已过期" });
  }

  if (!res.ok) {
    let body: ApiError = {
      code: "UNKNOWN",
      message: `请求失败 (${res.status})`,
    };
    try {
      const raw = await res.json();
      // FastAPI 错误格式: {"detail": {"code": "...", "message": "..."}}
      const detail = raw?.detail;
      if (detail && typeof detail === "object" && "code" in detail) {
        body = detail as ApiError;
      } else if (typeof detail === "string") {
        body = { code: "UNKNOWN", message: detail };
      } else if (raw?.code) {
        body = raw as ApiError;
      }
    } catch {
      /* ignore */
    }
    // 套餐到期：已登录跳账户页兑换新码续期，未登录跳登录页提示
    if (res.status === 403 && body.code === "PLAN_EXPIRED") {
      const target = refreshToken
        ? "/account?reason=plan_expired"
        : "/login?reason=plan_expired";
      if (window.location.pathname !== target.split("?")[0]) {
        window.location.href = target;
      }
    }
    throw new HttpError(res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return absolutizeMedia(await res.json()) as T;
}

export const http = {
  get: <T>(path: string) => rawFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    rawFetch<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    }),
  put: <T>(path: string, body?: unknown) =>
    rawFetch<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    rawFetch<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => rawFetch<T>(path, { method: "DELETE" }),
};
