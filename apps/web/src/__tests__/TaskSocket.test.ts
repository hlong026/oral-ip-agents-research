import { afterEach, describe, expect, it, vi } from "vitest";

describe("TaskSocket 鉴权", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("通过 WebSocket 子协议发送令牌，避免 JWT 出现在访问日志 URL", async () => {
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
    const { TaskSocket } = await import("@oral/api-client");

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("ws://localhost:3000/ws/tasks");
    expect(opened.url).not.toContain("secret.jwt.token");
    expect(opened.protocols).toEqual(["access-token", "secret.jwt.token"]);
  });

  it("支持显式远程 WebSocket 地址，避免生产桌面包误连页面 host", async () => {
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
    vi.stubEnv("VITE_WS_BASE", "wss://api.example.com/ws");
    const { TaskSocket } = await import("@oral/api-client");

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("wss://api.example.com/ws/tasks");
    expect(opened.protocols).toEqual(["access-token", "secret.jwt.token"]);
  });

  it("未显式配置 WebSocket 时可从远程 API 地址推导", async () => {
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
    vi.stubEnv("VITE_API_BASE", "https://api.example.com/api/v1");
    const { TaskSocket } = await import("@oral/api-client");

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("wss://api.example.com/ws/tasks");
    expect(opened.protocols).toEqual(["access-token", "secret.jwt.token"]);
  });

  it("完整 WebSocket 地址不会重复追加任务路径", async () => {
    const opened: { url?: string } = {};
    class FakeWebSocket {
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
    vi.stubEnv("VITE_WS_BASE", "wss://api.example.com/ws/tasks");
    const { TaskSocket } = await import("@oral/api-client");

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("wss://api.example.com/ws/tasks");
  });

  it("HTTP API 地址会推导为 ws 协议", async () => {
    const opened: { url?: string } = {};
    class FakeWebSocket {
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
    vi.stubEnv("VITE_API_BASE", "http://api.example.com/api/v1");
    const { TaskSocket } = await import("@oral/api-client");

    new TaskSocket("secret.jwt.token").connect();

    expect(opened.url).toBe("ws://api.example.com/ws/tasks");
  });
});
