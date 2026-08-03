/** 会话令牌持久化分支契约：非 Tauri 为 no-op；Tauri 壳读/写/清应用数据目录；失败静默降级（docs/19 补充） */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SESSION_STORE_MODULE =
  "../../../../packages/api-client/src/session-store";

type GlobalWithTauri = typeof globalThis & {
  __TAURI_INTERNALS__?: {
    invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
  };
};

async function loadStore() {
  const mod = await import(SESSION_STORE_MODULE);
  return mod as {
    loadPersistedRefreshToken: () => Promise<string | null>;
    persistRefreshToken: (token: string | null) => Promise<void>;
  };
}

describe("session-store", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    delete (globalThis as GlobalWithTauri).__TAURI_INTERNALS__;
  });

  it("非 Tauri 环境：读返回 null、写为 no-op", async () => {
    const { loadPersistedRefreshToken, persistRefreshToken } =
      await loadStore();
    await expect(loadPersistedRefreshToken()).resolves.toBeNull();
    await expect(persistRefreshToken("rt-1")).resolves.toBeUndefined();
  });

  it("Tauri 壳：读到非空字符串即恢复令牌", async () => {
    const invoke = vi.fn().mockResolvedValue("rt-persisted");
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = { invoke };
    const { loadPersistedRefreshToken } = await loadStore();

    await expect(loadPersistedRefreshToken()).resolves.toBe("rt-persisted");
    expect(invoke).toHaveBeenCalledWith("session_token_read");
  });

  it("Tauri 壳：读到空串视为无会话，返回 null", async () => {
    const invoke = vi.fn().mockResolvedValue("");
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = { invoke };
    const { loadPersistedRefreshToken } = await loadStore();

    await expect(loadPersistedRefreshToken()).resolves.toBeNull();
  });

  it("Tauri 壳：command 未注册/失败时静默降级 null", async () => {
    const invoke = vi
      .fn()
      .mockRejectedValue(new Error("command not registered"));
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = { invoke };
    const { loadPersistedRefreshToken } = await loadStore();

    await expect(loadPersistedRefreshToken()).resolves.toBeNull();
  });

  it("Tauri 壳：写非空令牌走 session_token_write，清空走 session_token_clear", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = { invoke };
    const { persistRefreshToken } = await loadStore();

    await persistRefreshToken("rt-2");
    expect(invoke).toHaveBeenCalledWith("session_token_write", {
      token: "rt-2",
    });

    await persistRefreshToken(null);
    expect(invoke).toHaveBeenCalledWith("session_token_clear");
  });
});
