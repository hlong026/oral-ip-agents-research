/**
 * 全局状态（Zustand）：会话 / 当前 IP / 算力额度 / 任务缓存
 * 任务实时数据经 TaskSocket 推送写入 taskStore，页面订阅即可。
 */
import { create } from "zustand";
import type { Persona, PipelineTask, Quota, User } from "@oral/types";
import {
  authApi,
  billingApi,
  personaApi,
  restoreSession,
  setTokens,
} from "@oral/api-client";

// ---------- 会话 ----------
interface SessionState {
  user: User | null;
  ready: boolean;
  login: (phone: string, password: string) => Promise<void>;
  logout: () => void;
  bootstrap: () => Promise<void>;
}

export const useSession = create<SessionState>((set) => ({
  user: null,
  ready: false,
  async login(phone, password) {
    const tokens = await authApi.login(phone, password);
    setTokens(tokens);
    const user = await authApi.me();
    set({ user });
  },
  logout() {
    setTokens(null);
    set({ user: null });
    window.location.href = "/login";
  },
  async bootstrap() {
    try {
      if (!(await restoreSession())) {
        set({ user: null, ready: true });
        return;
      }
      const user = await authApi.me();
      set({ user, ready: true });
    } catch {
      set({ user: null, ready: true });
    }
  },
}));

// ---------- 当前 IP（全局作用于所有页面） ----------
interface IpState {
  personas: Persona[];
  current: Persona | null;
  load: () => Promise<void>;
  switch: (id: string) => Promise<void>;
}

export const useIp = create<IpState>((set, get) => ({
  personas: [],
  current: null,
  async load() {
    const list = await personaApi.list();
    const current = list.find((p) => p.isActive) ?? list[0] ?? null;
    set({ personas: list, current });
  },
  async switch(id) {
    await personaApi.activate(id);
    const { personas } = get();
    set({
      current: personas.find((p) => p.id === id) ?? null,
      personas: personas.map((p) => ({ ...p, isActive: p.id === id })),
    });
  },
}));

// ---------- 算力额度（侧栏常驻卡） ----------
interface QuotaState {
  quota: Quota | null;
  load: () => Promise<void>;
}

export const useQuota = create<QuotaState>((set) => ({
  quota: null,
  async load() {
    const quota = await billingApi.quota();
    set({ quota });
  },
}));

// ---------- 任务缓存（WS 推送写入） ----------
interface TaskState {
  tasks: Record<string, PipelineTask>;
  upsert: (task: PipelineTask) => void;
}

export const useTasks = create<TaskState>((set) => ({
  tasks: {},
  upsert: (task) => set((s) => ({ tasks: { ...s.tasks, [task.id]: task } })),
}));
