/**
 * Web 端 PlatformBridge 实现（MVP 主端）
 * 算力策略：云端为主，localAvailable 恒为 false（本地引擎 V1.5+ 开放）
 */
import type { ComputeStatus, PlatformBridge } from "./index";

export class WebPlatformBridge implements PlatformBridge {
  readonly kind = "web" as const;

  async getComputeStatus(): Promise<ComputeStatus> {
    return {
      localAvailable: false,
      activeChannel: "cloud",
      localAgent: null,
    };
  }

  async openExternal(url: string): Promise<void> {
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async pickFile(accept: string): Promise<File | null> {
    return new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = accept;
      input.onchange = () => resolve(input.files?.[0] ?? null);
      // 用户取消时回收
      input.oncancel = () => resolve(null);
      input.click();
    });
  }
}

export const webBridge = new WebPlatformBridge();
