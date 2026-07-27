/**
 * PlatformBridge — 端能力桥（06 文档 §9.3 关键设计 1）
 *
 * UI 只依赖该接口，不感知端差异。
 * 「本地备用」算力策略的全部预留点就在本接口：
 *  - MVP：所有端仅云端通道（localAvailable=false）
 *  - V1.5+：本地引擎接入后 getComputeStatus() 返回 localAvailable:true
 */

import type { ComputeChannel } from "@oral/types";

export interface ComputeStatus {
  /** 本地引擎是否可用（V1.5+ 可选下载组件） */
  localAvailable: boolean;
  /** 当前生效通道（MVP 恒为 cloud） */
  activeChannel: ComputeChannel;
  /** 本地 Agent 信息（未接入为 null） */
  localAgent?: {
    version: string;
    gpuModel?: string;
    vramMb?: number;
    caps: string[];
    load: number;
  } | null;
}

export interface PlatformBridge {
  /** 端标识 */
  readonly kind: "web" | "desktop" | "mobile";

  /** 算力通道状态 */
  getComputeStatus(): Promise<ComputeStatus>;

  /** 打开外部链接（桌面端走系统浏览器） */
  openExternal(url: string): Promise<void>;

  /** 选择本地文件（素材上传） */
  pickFile(accept: string): Promise<File | null>;

  /** 下载本地引擎组件（V1.5+；MVP 抛 UnsupportedError） */
  downloadLocalEngine?(): Promise<void>;
}

export class UnsupportedError extends Error {
  constructor(feature: string) {
    super(`当前端不支持该能力: ${feature}`);
    this.name = "UnsupportedError";
  }
}
