/**
 * 设备指纹：`{设备段}.{featureHash 前 16 位}`，用于激活码登录的设备绑定（防拷贝）。
 * - Tauri 桌面壳：设备段为硬件机器码 `hw-{哈希}`（machine_code command，清缓存/重装不变）
 * - 浏览器：设备段为 localStorage UUID（软指纹兜底）
 * 特征只取稳定项（平台/语言/时区/CPU 核数），不掺 UA 版本号、屏幕、canvas 等
 * 易变特征，避免浏览器例行升级/换显示器触发误锁；服务端另对 featureHash 段容忍漂移。
 */
const DEVICE_ID_KEY = "oral_device_id";

/** Tauri 2 运行时内部注入的 invoke 通道（局部声明，不引 @tauri-apps/api 依赖） */
interface TauriInternals {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
}

function tauriInternals(): TauriInternals | null {
  const candidate = (globalThis as Record<string, unknown>).__TAURI_INTERNALS__;
  if (candidate && typeof (candidate as TauriInternals).invoke === "function") {
    return candidate as TauriInternals;
  }
  return null;
}

/** 桌面壳取硬件机器码设备段；非 Tauri/失败/超时(1s) 返回 null 降级 */
async function hardwareDeviceKey(): Promise<string | null> {
  const tauri = tauriInternals();
  if (!tauri) return null;
  try {
    const result = await Promise.race([
      tauri.invoke("machine_code"),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 1000)),
    ]);
    if (typeof result === "string" && result.startsWith("hw-")) return result;
  } catch {
    // command 未注册/权限不足等：静默降级软指纹
  }
  return null;
}

function deviceUuid(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  localStorage.setItem(DEVICE_ID_KEY, created);
  return created;
}

async function sha256Hex(input: string): Promise<string> {
  if (crypto.subtle) {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(input),
    );
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }
  // 非安全上下文降级：FNV-1a（仅开发环境兜底）
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0").repeat(4);
}

let cached: string | null = null;

/** 计算（并缓存）当前设备指纹 */
export async function deviceFingerprint(): Promise<string> {
  if (cached) return cached;
  const features = [
    navigator.platform ?? "",
    navigator.language,
    Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
    String(navigator.hardwareConcurrency ?? 0),
  ].join("|");
  const featureHash = await sha256Hex(features);
  const deviceKey = (await hardwareDeviceKey()) ?? deviceUuid();
  cached = `${deviceKey}.${featureHash.slice(0, 16)}`;
  return cached;
}
