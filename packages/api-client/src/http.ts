/**
 * HTTP 客户端：JWT 双令牌自动刷新（F-601 / C7）
 * - accessToken 内存持有；refreshToken 持久化
 * - 401 时单飞刷新并重放原请求
 * - X-Trace-Id 请求头注入（§10.6.9 Phase 4，前后端日志贯通）
 */
import type { ApiError, AuthTokens } from "@oral/types";

const API_BASE =
  (import.meta as ImportMeta & { env?: { VITE_API_BASE?: string } }).env
    ?.VITE_API_BASE ?? "/api/v1";

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
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as AuthTokens;
    setTokens(data);
    return true;
  } catch {
    return false;
  }
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

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

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
    throw new HttpError(res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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
