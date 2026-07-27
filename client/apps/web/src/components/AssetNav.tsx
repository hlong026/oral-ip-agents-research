import { Bot, CircleUserRound, type LucideIcon, Music } from "lucide-react";
import { Link, useLocation } from "react-router";

// V1.1 未上架功能（模板/素材库）入口暂时隐藏，路由保留可直达；上线时恢复注释项
const ITEMS: readonly { to: string; icon: LucideIcon; label: string }[] = [
  { to: "/assets/personas", icon: CircleUserRound, label: "IP 档案" },
  { to: "/assets/voices", icon: Music, label: "声音" },
  { to: "/assets/avatars", icon: Bot, label: "数字人" },
  // { to: "/assets/templates", icon: Sparkles, label: "模板" }, // V1.1 上架时恢复
  // { to: "/assets/materials", icon: LayoutGrid, label: "素材库" }, // V1.1 上架时恢复
] as const;

/** 资产二级导航（当前 V1.0：IP 档案/声音/数字人 三页；模板/素材库为 V1.1 能力，入口隐藏） */
export default function AssetNav() {
  const { pathname } = useLocation();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-xs text-text-3">IP 资产</span>
      {ITEMS.map((it) => {
        const on = pathname.startsWith(it.to);
        return (
          <Link
            key={it.to}
            to={it.to}
            className={`chip flex items-center gap-1 px-3 py-1 ${on ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            <it.icon className="h-3.5 w-3.5" /> {it.label}
          </Link>
        );
      })}
    </div>
  );
}
