/**
 * WebSocket 任务进度通道（06 文档 §6.2：WS 网关 + Redis Pub/Sub，推送延迟 ≤2s）
 * 自动重连（指数退避）。消息与后端事件总线三频道对齐：
 *   CHANNEL_TASKS → task_updated / publish_updated / provider_fallback
 *   CHANNEL_FEED  → feed
 *   CHANNEL_ALERT → alert
 */
import type { FeedEvent } from "@oral/types";

export type TaskEvent =
  | { kind: "task_updated"; taskId: string; userId?: string }
  | { kind: "publish_updated"; jobId: string; userId?: string; status: string }
  | {
      kind: "provider_fallback";
      provider_kind?: string;
      to?: string;
      taskId?: string;
      message?: string;
    }
  | { kind: "feed"; event: FeedEvent; userId?: string }
  | {
      kind: "alert";
      level: "info" | "warn" | "error";
      message: string;
      body?: string;
    }
  | { kind: "ping" };

type Listener = (ev: TaskEvent) => void;

type ClientEnv = { VITE_API_BASE?: string; VITE_WS_BASE?: string };
type ImportMetaWithEnv = ImportMeta & { env?: ClientEnv };
type RuntimeGlobal = typeof globalThis & { process?: { env?: ClientEnv } };

function appendTasksPath(base: string): string {
  const trimmed = base.trim().replace(/\/+$/, "");
  if (trimmed.endsWith("/ws/tasks")) return trimmed;
  if (trimmed.endsWith("/ws")) return `${trimmed}/tasks`;
  return `${trimmed}/ws/tasks`;
}

function toWebSocketUrl(base: string): string {
  const url = new URL(appendTasksPath(base), location.origin);
  if (url.protocol === "https:") url.protocol = "wss:";
  if (url.protocol === "http:") url.protocol = "ws:";
  return url.toString();
}

function wsUrlFromApiBase(apiBase: string): string {
  const url = new URL(apiBase, location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/tasks";
  url.search = "";
  url.hash = "";
  return url.toString();
}

function buildTaskSocketUrl(): string {
  const env = {
    ...(globalThis as RuntimeGlobal).process?.env,
    ...(import.meta as ImportMetaWithEnv).env,
  };
  const explicitWsBase = env.VITE_WS_BASE?.trim();
  if (explicitWsBase) return toWebSocketUrl(explicitWsBase);

  const apiBase = env.VITE_API_BASE?.trim();
  if (apiBase && /^https?:\/\//.test(apiBase)) {
    return wsUrlFromApiBase(apiBase);
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/tasks`;
}

export class TaskSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retries = 0;
  private closedByUser = false;
  private url: string;
  private token: string;

  constructor(token: string) {
    this.url = buildTaskSocketUrl();
    this.token = token;
  }

  connect() {
    this.closedByUser = false;
    this.open();
  }

  private open() {
    try {
      this.ws = new WebSocket(this.url, ["access-token", this.token]);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retries = 0;
    };
    this.ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data as string) as TaskEvent;
        this.listeners.forEach((fn) => fn(data));
      } catch {
        /* ignore malformed */
      }
    };
    this.ws.onclose = () => {
      if (!this.closedByUser) this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect() {
    const delay = Math.min(15000, 500 * 2 ** this.retries++);
    setTimeout(() => {
      if (!this.closedByUser) this.open();
    }, delay);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  close() {
    this.closedByUser = true;
    this.ws?.close();
  }
}
