/**
 * 会话令牌持久化：桌面壳把 refresh token 落到应用数据目录，
 * webview 清缓存 / 重装应用后仍能免激活码恢复登录（docs/19 补充）。
 * 非 Tauri 环境（Web）为 no-op，登录态仍由 http.ts 的 localStorage 承载。
 */

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

/** 读取桌面端持久化的 refresh token；非 Tauri/失败/空 返回 null */
export async function loadPersistedRefreshToken(): Promise<string | null> {
  const tauri = tauriInternals();
  if (!tauri) return null;
  try {
    const result = await tauri.invoke("session_token_read");
    if (typeof result === "string" && result.length > 0) return result;
  } catch {
    // command 未注册/权限不足等：静默降级 localStorage
  }
  return null;
}

/** 持久化（token 非空）或清除（token 为 null）桌面端 refresh token；非 Tauri 为 no-op */
export async function persistRefreshToken(token: string | null): Promise<void> {
  const tauri = tauriInternals();
  if (!tauri) return;
  try {
    if (token) await tauri.invoke("session_token_write", { token });
    else await tauri.invoke("session_token_clear");
  } catch {
    // 静默降级：本次未能持久化，仍有 localStorage 兜底
  }
}
