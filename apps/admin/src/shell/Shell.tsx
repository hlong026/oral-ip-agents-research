import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearAdminToken } from "../lib/adminHttp";

const navItems = [
  { to: "/", label: "总览" },
  { to: "/plans", label: "套餐 SKU" },
  { to: "/prices", label: "积分价格" },
  { to: "/activation", label: "激活码批次" },
  { to: "/providers", label: "Provider 配置" },
  { to: "/users", label: "用户管理" },
  { to: "/cost-audit", label: "成本与审计" },
];

export default function Shell() {
  const navigate = useNavigate();

  return (
    <div className="flex h-full">
      <aside className="flex w-64 flex-col border-r border-stroke bg-bg-1/80 px-4 py-5">
        <div className="mb-8">
          <p className="text-xs text-text-3">ORAL IP AGENTS</p>
          <h1 className="mt-1 text-lg font-semibold">管理控制台</h1>
        </div>
        <nav className="space-y-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `block rounded-xl px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-white/10 text-white"
                    : "text-text-2 hover:bg-white/5 hover:text-text-1"
                }`
              }
            >
              {item.label}
            </NavLink>
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
