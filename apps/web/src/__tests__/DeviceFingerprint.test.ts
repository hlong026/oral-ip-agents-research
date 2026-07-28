/** 设备指纹分支契约：无 Tauri 走 localStorage 软指纹；Tauri 壳走硬件码；失败降级（docs/19 §4.2） */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const FINGERPRINT_MODULE = "../../../../packages/api-client/src/fingerprint";

type GlobalWithTauri = typeof globalThis & {
  __TAURI_INTERNALS__?: { invoke: (cmd: string) => Promise<unknown> };
};

async function loadFingerprint() {
  const mod = await import(FINGERPRINT_MODULE);
  return mod.deviceFingerprint as () => Promise<string>;
}

describe("deviceFingerprint", () => {
  beforeEach(() => {
    vi.resetModules(); // 清除模块级 cached
    localStorage.clear();
    delete (globalThis as GlobalWithTauri).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    delete (globalThis as GlobalWithTauri).__TAURI_INTERNALS__;
  });

  it("无 Tauri 环境：设备段为 localStorage UUID 且跨次稳定（现有行为回归）", async () => {
    const deviceFingerprint = await loadFingerprint();
    const first = await deviceFingerprint();
    const [key, featureHash] = first.split(".");
    expect(key).toBe(localStorage.getItem("oral_device_id"));
    expect(featureHash).toHaveLength(16);

    vi.resetModules();
    const again = await (await loadFingerprint())();
    expect(again).toBe(first); // uuid 持久化，重载模块仍同一设备
  });

  it("Tauri 壳：machine_code 返回 hw- 码时设备段为硬件机器码", async () => {
    const invoke = vi.fn().mockResolvedValue("hw-0123456789abcdef0123456789abcdef");
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = { invoke };
    const deviceFingerprint = await loadFingerprint();

    const fingerprint = await deviceFingerprint();
    expect(invoke).toHaveBeenCalledWith("machine_code");
    expect(fingerprint.startsWith("hw-0123456789abcdef0123456789abcdef.")).toBe(true);
  });

  it("Tauri invoke 失败：静默降级 localStorage 软指纹", async () => {
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = {
      invoke: vi.fn().mockRejectedValue(new Error("command not registered")),
    };
    const deviceFingerprint = await loadFingerprint();

    const fingerprint = await deviceFingerprint();
    expect(fingerprint.startsWith("hw-")).toBe(false);
    expect(fingerprint.split(".")[0]).toBe(localStorage.getItem("oral_device_id"));
  });

  it("Tauri 返回非 hw- 前缀等异常值：同样降级软指纹", async () => {
    (globalThis as GlobalWithTauri).__TAURI_INTERNALS__ = {
      invoke: vi.fn().mockResolvedValue("unexpected-value"),
    };
    const deviceFingerprint = await loadFingerprint();

    const fingerprint = await deviceFingerprint();
    expect(fingerprint.split(".")[0]).toBe(localStorage.getItem("oral_device_id"));
  });
});
