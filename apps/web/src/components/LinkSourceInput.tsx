import { detectPlatform } from "@oral/hooks";
import { PLATFORM_NAMES } from "@oral/types";
import { useRef } from "react";

import PlatformIcon from "./PlatformIcon";

/** 上传 SVG（内层左侧图标按钮） */
function UploadSvg({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M12 16V4" />
      <path d="m6 10 6-6 6 6" />
      <path d="M4 20h16" />
    </svg>
  );
}

interface LinkSourceInputProps {
  value: string;
  onChange: (v: string) => void;
  /** 选中本地文件（视频/音频）时回调，父级负责解析 */
  onUpload: (file: File) => void;
  uploading?: boolean;
  placeholder?: string;
  /** input 额外类名（默认 h-14 text-base） */
  inputClassName?: string;
  onEnter?: () => void;
}

/**
 * 链接/选题来源输入框（Hero / 一键成片 / 文案工坊新建面板共用）：
 * 内层左侧上传图标按钮（本地文件降级解析），右侧平台自动识别 chip。
 */
export default function LinkSourceInput({
  value,
  onChange,
  onUpload,
  uploading = false,
  placeholder = "粘贴抖音 / 小红书视频链接或视频ID…",
  inputClassName = "h-14 text-base",
  onEnter,
}: LinkSourceInputProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const platform = detectPlatform(value);

  return (
    <div className="relative">
      {/* 右上角 API Key 申请跳转 */}
      <div className="absolute -top-5 right-0">
        <a
          href="https://www.douyidou.cc"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-0.5 text-[10px] text-text-3 transition-colors hover:text-brand-to"
        >
          获取解析 API Key
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-2.5 w-2.5">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
        </a>
      </div>
      {/* 内层上传图标按钮 */}
      <button
        type="button"
        title="上传本地视频/音频，提取文案"
        aria-label="上传本地文件提取文案"
        disabled={uploading}
        onClick={() => fileRef.current?.click()}
        className="absolute left-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-white/10 hover:text-brand-to disabled:opacity-50"
      >
        {uploading ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-to/40 border-t-brand-to" />
        ) : (
          <UploadSvg className="h-5 w-5" />
        )}
      </button>
      <input
        className={`input pl-12 ${platform ? "pr-36" : "pr-4"} ${inputClassName}`}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
      />
      {platform && (
        <span className="chip absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-1.5 border-brand-to/40 text-brand-to">
          <PlatformIcon platform={platform} size={14} /> 已识别 · {PLATFORM_NAMES[platform]}
        </span>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="video/*,audio/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onUpload(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
