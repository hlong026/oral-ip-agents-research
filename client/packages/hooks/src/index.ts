/**
 * 通用 hooks
 */
import { useEffect, useRef, useState } from "react";

/** 轮询（WS 断线兜底）：enabled 为 true 时每 intervalMs 触发 fn */
export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!enabled) return;
    const t = setInterval(() => void saved.current(), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, enabled]);
}

/** 防抖值 */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return v;
}

/** 相对时间（任务动态流） */
export function useRelativeTime(iso: string): string {
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((x) => x + 1), 30_000);
    return () => clearInterval(t);
  }, []);
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

/** 识别分享链接平台（Hero 输入框平台识别） */
export function detectPlatform(
  url: string,
): "douyin" | "kuaishou" | "xiaohongshu" | "shipinhao" | null {
  if (!url) return null;
  const u = url.toLowerCase();
  if (u.includes("douyin.com") || u.includes("iesdouyin")) return "douyin";
  if (u.includes("kuaishou.com") || u.includes("gifshow")) return "kuaishou";
  if (u.includes("xiaohongshu.com") || u.includes("xhslink"))
    return "xiaohongshu";
  if (u.includes("channels.weixin") || u.includes("weixin")) return "shipinhao";
  return null;
}
