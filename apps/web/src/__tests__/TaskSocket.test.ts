import { buildApiUrl, TaskSocket } from "@oral/api-client";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("TaskSocket 鉴权", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("通过 WebSocket 子协议发送令牌，避免 JWT 出现在访问日志 URL", () => {
    const opened: { url?: string; protocols?: string[] } = {};
    class FakeWebSocket {
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;

      constructor(url: string, protocols?: string[]) {
        opened.url = url;
        opened.protocols = protocols;
      }

      close() {}
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("ws://localhost:3000/ws/tasks");
    expect(opened.url).not.toContain("secret.jwt.token");
    expect(opened.protocols).toEqual(["access-token", "secret.jwt.token"]);
  });

  it("桌面构建使用远程 HTTPS API 时连接同源 WSS，而不是 Tauri 自身协议", () => {
    const opened: { url?: string } = {};
    class FakeWebSocket {
      static readonly OPEN = 1;

      readyState = FakeWebSocket.OPEN;
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;

      constructor(url: string) {
        opened.url = url;
      }

      close() {}
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    new TaskSocket(
      "secret.jwt.token",
      "https://api.oral.company/api/v1",
    ).connect();

    expect(opened.url).toBe("wss://api.oral.company/ws/tasks");
    expect(
      buildApiUrl(
        "/billing/usage?export=csv",
        "https://api.oral.company/api/v1/",
      ),
    ).toBe("https://api.oral.company/api/v1/billing/usage?export=csv");
  });

  it("连接建立前关闭时等待握手完成，避免浏览器记录连接中断告警", () => {
    let socket: FakeWebSocket | undefined;
    class FakeWebSocket {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;

      readyState = FakeWebSocket.CONNECTING;
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      close = vi.fn();

      constructor() {
        socket = this;
      }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const taskSocket = new TaskSocket("secret.jwt.token");
    taskSocket.connect();
    taskSocket.close();

    expect(socket?.close).not.toHaveBeenCalled();

    socket!.readyState = FakeWebSocket.OPEN;
    socket!.onopen?.();

    expect(socket?.close).toHaveBeenCalledOnce();
  });
});
