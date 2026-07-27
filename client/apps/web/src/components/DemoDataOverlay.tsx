import { Info } from "lucide-react";
import type { ReactNode } from "react";

/**
 * V1.1 占位页演示数据包装层：
 * - 顶部强警示提示条（统一文案：以下全部为演示数据，非您的真实数据）
 * - 页面内容叠加半透明"演示数据"平铺水印（pointer-events 穿透，不影响交互），
 *   防止截图/直达访问时被误判为真实数据
 */
export default function DemoDataOverlay({
  note,
  children,
}: {
  note: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-5">
      <div
        role="alert"
        className="flex items-center justify-between rounded-card border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
      >
        <span className="flex items-center gap-1.5">
          <Info className="h-4 w-4 shrink-0" />
          以下全部为演示数据，非您的真实数据。{note}
        </span>
        <span className="chip shrink-0 border-warning/40 text-warning">
          V1.1 上线
        </span>
      </div>
      <div className="relative">
        {children}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-10 overflow-hidden opacity-[0.07]"
          style={{
            backgroundImage: `url("data:image/svg+xml;utf8,${encodeURIComponent(
              `<svg xmlns='http://www.w3.org/2000/svg' width='260' height='180'><text x='20' y='100' font-size='28' font-family='sans-serif' fill='white' transform='rotate(-24 130 90)'>演示数据</text></svg>`,
            )}")`,
            backgroundRepeat: "repeat",
          }}
        />
      </div>
    </div>
  );
}
