/**
 * 软设备指纹：localStorage UUID + 浏览器稳定特征哈希
 * 格式 `{uuid}.{featureHash 前 16 位}`，用于激活码登录的设备绑定（防拷贝）。
 * 特征只取稳定项（平台/语言/时区/CPU 核数），不掺 UA 版本号、屏幕、canvas 等
 * 易变特征，避免浏览器例行升级/换显示器触发误锁；服务端另对 featureHash 段容忍漂移。
 * Tauri 端后续可在同一通道替换为硬件机器码，服务端无需改动。
 */
const DEVICE_ID_KEY = "oral_device_id";

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
  cached = `${deviceUuid()}.${featureHash.slice(0, 16)}`;
  return cached;
}
