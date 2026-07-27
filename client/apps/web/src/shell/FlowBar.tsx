import { Check } from "lucide-react";
import { useMemo } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

/** flow-bar 全局七步动线（与一键成片向导七步对齐：创作流程页显示，账号/套餐页不显示） */
const FLOW_STEPS = [
  { key: "link", label: "链接选题", to: "/create?step=link" },
  { key: "script", label: "文案二创", to: "/scripts" },
  { key: "voice", label: "配音", to: "/assets/voices" },
  { key: "avatar", label: "数字人", to: "/assets/avatars" },
  { key: "compose", label: "视频合成", to: "/create?step=compose" },
  { key: "edit", label: "视频剪辑", to: "/create?step=edit" },
  { key: "publish", label: "发布", to: "/publish/jobs" },
] as const;

/** 路由 → 当前步映射 */
function useActiveStep(): string | null {
  const { pathname } = useLocation();
  const [params] = useSearchParams();

  return useMemo(() => {
    if (pathname === "/create") {
      const step = params.get("step") ?? "link";
      if (step === "link" || step === "topic") return "link";
      if (step === "script") return "script";
      if (step === "voice") return "voice";
      if (step === "avatar") return "avatar";
      if (step === "compose") return "compose";
      if (step === "edit") return "edit";
      if (step === "publish") return "publish";
      return "link";
    }
    if (pathname.startsWith("/scripts")) return "script";
    if (pathname.startsWith("/assets/voices")) return "voice";
    if (pathname.startsWith("/assets/avatars")) return "avatar";
    if (pathname.startsWith("/tasks")) return "compose";
    if (pathname.startsWith("/editor")) return "edit";
    if (pathname.startsWith("/publish")) return "publish";
    return null;
  }, [pathname, params]);
}

export default function FlowBar() {
  const active = useActiveStep();
  const activeIdx = FLOW_STEPS.findIndex((s) => s.key === active);

  return (
    <div
      data-testid="flow-bar"
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-stroke px-6 py-2.5"
    >
      {FLOW_STEPS.map((step, i) => {
        const done = activeIdx > i;
        const current = step.key === active;
        return (
          <div key={step.key} className="flex shrink-0 items-center gap-1">
            <Link
              to={step.to}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors ${
                current
                  ? "bg-brand-grad font-medium text-white shadow-cta"
                  : done
                    ? "text-success"
                    : "text-text-3 hover:text-text-2"
              }`}
            >
              <span
                className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${
                  current
                    ? "bg-white/20"
                    : done
                      ? "bg-success/20"
                      : "bg-white/5"
                }`}
              >
                {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
              </span>
              {step.label}
            </Link>
            {i < FLOW_STEPS.length - 1 && (
              <span
                className={`mx-0.5 h-px w-6 ${done ? "bg-success/50" : "bg-stroke"}`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
