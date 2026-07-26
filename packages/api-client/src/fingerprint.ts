/**
 * 软设备指纹：localStorage UUID + 浏览器稳定特征哈希
 * 格式 `{uuid}.{featureHash 前 16 位}`，用于激活码登录的设备绑定（防拷贝）。
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

function canvasSignature(): string {
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 200;
    canvas.height = 40;
    const ctx = canvas.getContext("2d");
    if (!ctx) return "no-canvas";
    ctx.textBaseline = "top";
    ctx.font = "14px Arial";
    ctx.fillStyle = "#f60";
    ctx.fillRect(60, 4, 80, 20);
    ctx.fillStyle = "#069";
    ctx.fillText("oral-ip-fp", 2, 10);
    return canvas.toDataURL();
  } catch {
    return "no-canvas";
  }
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
    navigator.userAgent,
    navigator.platform ?? "",
    navigator.language,
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
    String(navigator.hardwareConcurrency ?? 0),
    canvasSignature(),
  ].join("|");
  const featureHash = await sha256Hex(features);
  cached = `${deviceUuid()}.${featureHash.slice(0, 16)}`;
  return cached;
}
