import { notifyApi } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data: unread } = useQuery({
    queryKey: ["notif-unread"],
    queryFn: () => notifyApi.unreadCount(),
    refetchInterval: 30_000,
  });
  const { data: list } = useQuery({
    queryKey: ["notif-list"],
    queryFn: () => notifyApi.list(),
    enabled: open,
  });

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-stroke bg-white/5 text-text-2 hover:text-text-1"
      >
        🔔
        {(unread?.count ?? 0) > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {unread!.count > 99 ? "99+" : unread!.count}
          </span>
        )}
      </button>
      {open && (
        <div className="glass-strong absolute right-0 top-full z-40 mt-2 w-80 overflow-hidden">
          <div className="flex items-center justify-between border-b border-stroke px-4 py-2.5">
            <span className="text-sm font-medium">站内通知</span>
            <button
              className="text-xs text-brand-to hover:underline"
              onClick={() => void notifyApi.markAllRead()}
            >
              全部已读
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {(list ?? []).length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-text-3">
                暂无通知
              </div>
            )}
            {(list ?? []).map((n) => (
              <button
                key={n.id}
                onClick={() => void notifyApi.markRead(n.id)}
                className={`block w-full border-b border-stroke/50 px-4 py-3 text-left hover:bg-white/5 ${n.read ? "opacity-60" : ""}`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      n.level === "error"
                        ? "bg-danger"
                        : n.level === "warn"
                          ? "bg-warning"
                          : "bg-info"
                    }`}
                  />
                  <span className="flex-1 truncate text-sm">{n.title}</span>
                </div>
                {n.body && (
                  <div className="mt-1 line-clamp-2 text-xs text-text-3">
                    {n.body}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** 顶栏：搜索 + 通知 + 头像（账号唯一入口，对齐效果图） */
export default function Topbar() {
  const { user, logout } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-stroke px-6">
      <div className="relative w-80 max-w-full">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-3">
          ⌕
        </span>
        <input
          className="input h-9 pl-9"
          placeholder="搜索任务 / 文案 / 资产…"
          onKeyDown={(e) => {
            if (e.key === "Enter")
              navigate(`/tasks?q=${(e.target as HTMLInputElement).value}`);
          }}
        />
      </div>
      <div className="flex-1" />
      <NotificationBell />
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="flex items-center gap-2 rounded-xl border border-stroke bg-white/5 py-1.5 pl-1.5 pr-3 hover:border-stroke-strong"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-grad text-sm font-bold text-white">
            {user?.avatarChar || user?.nickname?.[0] || "U"}
          </span>
          <span className="max-w-24 truncate text-sm">
            {user?.nickname || "账号"}
          </span>
        </button>
        {menuOpen && (
          <div className="glass-strong absolute right-0 top-full z-40 mt-2 w-44 overflow-hidden p-1">
            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/account");
              }}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm text-text-2 hover:bg-white/5 hover:text-text-1"
            >
              账号与额度
            </button>
            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/pricing");
              }}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm text-text-2 hover:bg-white/5 hover:text-text-1"
            >
              套餐与积分
            </button>
            <button
              onClick={logout}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm text-danger hover:bg-danger/10"
            >
              退出登录
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
