import { Link, useLocation } from "react-router-dom";

// V1.1 未上架功能（模板/素材库）入口暂时隐藏，路由保留可直达；上线时恢复注释项
const ITEMS = [
  { to: "/assets/personas", icon: "◉", label: "IP 档案" },
  { to: "/assets/avatars", icon: "♟", label: "数字人" },
  { to: "/assets/voices", icon: "♪", label: "声音" },
  // { to: "/assets/templates", icon: "✦", label: "模板" }, // V1.1 上架时恢复
  // { to: "/assets/materials", icon: "▦", label: "素材库" }, // V1.1 上架时恢复
] as const;

/** 资产二级导航（当前 V1.0：IP 档案/数字人/声音 三页；模板/素材库为 V1.1 能力，入口隐藏） */
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
            className={`chip px-3 py-1 ${on ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}
          >
            {it.icon} {it.label}
          </Link>
        );
      })}
    </div>
  );
}
