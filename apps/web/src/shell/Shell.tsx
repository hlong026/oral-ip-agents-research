import {
  getAccessToken,
  pipelineApi,
  TaskSocket,
  type TaskEvent,
} from "@oral/api-client";
import { useIp, useQuota, useSession, useTasks } from "@oral/stores";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router";
import FlowBar from "./FlowBar";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";

/** flow-bar 隐藏页（账号/套餐不在创作动线内，对齐效果图） */
const NO_FLOW_PATHS = ["/account", "/pricing"];

export interface Toast {
  id: number;
  level: "info" | "warn" | "error";
  text: string;
}

export default function Shell() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const { user } = useSession();
  const loadIp = useIp((s) => s.load);
  const loadQuota = useQuota((s) => s.load);
  const upsertTask = useTasks((s) => s.upsert);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  const showFlow = !NO_FLOW_PATHS.some((p) => location.pathname.startsWith(p));

  useEffect(() => {
    void loadIp();
    void loadQuota();
  }, [loadIp, loadQuota]);

  // WS 实时通道：任务进度 / 动态流 / 告警（≤2s 推送）
  useEffect(() => {
    const token = getAccessToken();
    if (!user || !token) return;
    const socket = new TaskSocket(token);
    const unsubscribe = socket.subscribe((ev: TaskEvent) => {
      if (ev.kind === "task_updated") {
        void pipelineApi.get(ev.taskId).then((task) => {
          upsertTask(task);
          queryClient.setQueryData(["task", task.id], task);
          void queryClient.invalidateQueries({ queryKey: ["tasks"] });
        });
      } else if (ev.kind === "feed") {
        queryClient.setQueryData(["feed"], (old: unknown) => {
          const list = Array.isArray(old) ? old : [];
          return [ev.event, ...list].slice(0, 30);
        });
      } else if (ev.kind === "alert") {
        const id = ++toastId.current;
        setToasts((t) => [...t, { id, level: ev.level, text: ev.message }]);
        void queryClient.invalidateQueries({ queryKey: ["notif-unread"] });
        void queryClient.invalidateQueries({ queryKey: ["notif-list"] });
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
      } else if (ev.kind === "publish_updated") {
        void queryClient.invalidateQueries({ queryKey: ["publish-jobs"] });
      }
    });
    socket.connect();
    return () => {
      unsubscribe();
      socket.close();
    };
  }, [user, queryClient, upsertTask]);

  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        {showFlow && <FlowBar />}
        <main className="min-h-0 flex-1 overflow-y-auto px-6 pb-8 pt-4">
          <Outlet />
        </main>
      </div>

      {/* 告警 toast（降级事件/发布失败/额度不足） */}
      <div className="pointer-events-none fixed right-4 top-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto glass-strong px-4 py-3 text-sm ${
              t.level === "error"
                ? "border-danger/40 text-danger"
                : t.level === "warn"
                  ? "border-warning/40 text-warning"
                  : "text-text-1"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
