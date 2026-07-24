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
  | {
      kind: "content_job_updated";
      jobId: string;
      userId?: string;
      status: string;
      progress: number;
      stage: string;
    }
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

export class TaskSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retries = 0;
  private closedByUser = false;
  private url: string;
  private token: string;

  constructor(token: string) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.url = `${proto}://${location.host}/ws/tasks`;
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
      if (this.closedByUser) this.ws?.close();
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
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.close();
  }
}
