/**
 * 抖音官方网页 WebView 入口 —— 私信发送侧方案 E。
 *
 * 桌面壳：通过 Tauri 命令拉起独立 WebView 窗口加载抖音官方页，
 *         用户在其中手动登录并回复（本应用不注入任何自动化脚本）。
 * 纯 Web：降级为新标签页打开抖音（无法嵌入，但至少可用）。
 */

interface TauriInternals {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
}

interface GlobalWithTauri {
  __TAURI_INTERNALS__?: TauriInternals;
}

function tauriInternals(): TauriInternals | undefined {
  return (globalThis as GlobalWithTauri).__TAURI_INTERNALS__;
}

/** 是否运行在 Tauri 桌面壳内（决定能否嵌入 WebView） */
export function isDesktopShell(): boolean {
  return !!tauriInternals();
}

const DOUYIN_URL = "https://www.douyin.com/";

/**
 * 打开抖音官方消息页。
 * - 桌面壳：拉起嵌入 WebView 窗口（cookie 持久化，重开免登录）
 * - 纯 Web：新标签页打开
 */
export async function openDouyinIM(accountId?: string): Promise<void> {
  const tauri = tauriInternals();
  if (tauri) {
    await tauri.invoke("open_douyin_im", { accountId: accountId ?? "" });
    return;
  }
  window.open(DOUYIN_URL, "_blank", "noopener,noreferrer");
}
