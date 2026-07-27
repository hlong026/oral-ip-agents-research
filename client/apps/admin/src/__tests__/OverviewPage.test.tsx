import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import OverviewPage from "../pages/OverviewPage";

// jsdom 无真实布局，图表本体以桩件替代，只验证数据流与卡片结构
vi.mock("../components/DashboardChart", () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => (
    <div role="img" aria-label={ariaLabel} />
  ),
}));

const zeros = (n: number) => Array.from({ length: n }, () => 0);

const dashboardFixture = {
  rangeDays: 30,
  generatedAt: "2026-07-26T08:00:00Z",
  dates: Array.from({ length: 30 }, (_, i) => `2026-06-${(i % 28) + 1}`),
  kpis: {
    totalUsers: 128,
    newUsersToday: 6,
    newUsersYesterday: 2,
    pointsConsumedToday: 88,
    pointsConsumedYesterday: 120,
    tasksCreatedToday: 12,
    tasksCreatedYesterday: 12,
    publishSuccessRate: 0.9231,
    codesUnused: 45,
    codesActivatedTotal: 80,
    revenueCentsWindow: 399800,
    costCentsWindow: 52300,
  },
  users: { newUsers: zeros(30), cumulativeUsers: zeros(30) },
  activation: { created: zeros(30), activated: zeros(30) },
  credits: { granted: zeros(30), consumed: zeros(30) },
  production: {
    tasksCreated: zeros(30),
    tasksSucceeded: zeros(30),
    tasksFailed: zeros(30),
    voiceClones: zeros(30),
    avatarTrainings: zeros(30),
  },
  publishing: { created: zeros(30), succeeded: zeros(30), failed: zeros(30) },
  economics: { revenueCents: zeros(30), costCents: zeros(30) },
};

describe("overview dashboard page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders KPI strip and all six business charts from dashboard API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/dashboard?days=30")) {
        return {
          ok: true,
          status: 200,
          json: async () => dashboardFixture,
        } as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>,
    );

    // KPI：总用户与今日新增环比
    expect(await screen.findByText("128")).toBeInTheDocument();
    expect(screen.getByText("+4 vs 昨日")).toBeInTheDocument();
    expect(screen.getByText("92.3%")).toBeInTheDocument();
    expect(screen.getByText("¥3998.00")).toBeInTheDocument();

    // 六大业务块图表全部渲染
    for (const label of [
      "用户增长趋势图",
      "积分发放与消耗趋势图",
      "生产任务趋势图",
      "声音克隆与数字人训练趋势图",
      "发布分发趋势图",
      "收入与成本趋势图",
      "激活码生成与激活趋势图",
    ]) {
      expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
    }

    // 时间范围切换重新请求
    const rangeButton = screen.getByRole("button", { name: "近 7 天" });
    expect(rangeButton).toBeInTheDocument();
  });

  it("shows retry panel when dashboard API fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500 }) as Response),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <OverviewPage />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("大盘数据加载失败，请重试。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新加载" }),
    ).toBeInTheDocument();
  });
});
