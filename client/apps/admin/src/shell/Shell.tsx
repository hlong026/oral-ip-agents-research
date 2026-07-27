import {
  Calculator,
  Coins,
  LayoutDashboard,
  type LucideIcon,
  Package,
  ServerCog,
  ShieldCheck,
  Ticket,
  Users,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { clearAdminToken } from "@oral/admin-api-client";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const navGroups: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "运营看板",
    items: [{ to: "/", label: "总览", icon: LayoutDashboard }],
  },
  {
    title: "商业化",
    items: [
      { to: "/plans", label: "套餐 SKU", icon: Package },
      { to: "/prices", label: "积分价格", icon: Coins },
      { to: "/activation", label: "激活码批次", icon: Ticket },
      { to: "/cost-audit", label: "成本与审计", icon: Calculator },
    ],
  },
  {
    title: "用户与安全",
    items: [
      { to: "/users", label: "用户管理", icon: Users },
      { to: "/im-safety", label: "私信安全", icon: ShieldCheck },
    ],
  },
  {
    title: "系统配置",
    items: [{ to: "/providers", label: "服务商配置", icon: ServerCog }],
  },
];

export default function Shell() {
  const navigate = useNavigate();

  return (
    <div className="flex h-full">
      <aside className="flex w-64 flex-col border-r border-stroke bg-bg-1/80 px-4 py-5">
        <div className="mb-8">
          <p className="text-xs text-text-3">口播智能体</p>
          <h1 className="mt-1 text-lg font-semibold">管理控制台</h1>
        </div>
        <nav className="space-y-5 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group.title}>
              <p className="mb-1.5 px-3 text-[10px] uppercase tracking-[0.18em] text-text-3">
                {group.title}
              </p>
              <div className="space-y-1">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition ${
                        isActive
                          ? "bg-white/10 text-white"
                          : "text-text-2 hover:bg-white/5 hover:text-text-1"
                      }`
                    }
                  >
                    <item.icon size={15} strokeWidth={1.75} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <button
          className="btn-ghost mt-auto"
          onClick={() => {
            clearAdminToken();
            navigate("/login", { replace: true });
          }}
        >
          退出登录
        </button>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto px-6 py-5">
        <Outlet />
      </main>
    </div>
  );
}
