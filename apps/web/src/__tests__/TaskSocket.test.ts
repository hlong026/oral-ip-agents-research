import { TaskSocket } from "@oral/api-client";
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
});
