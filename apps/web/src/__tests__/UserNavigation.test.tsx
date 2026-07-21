import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Sidebar from "../shell/Sidebar";
import Topbar from "../shell/Topbar";

vi.mock("@oral/api-client", () => ({
  pipelineApi: {
    list: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 1 }),
  },
  publishApi: {
    jobs: vi
      .fn()
      .mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 1 }),
  },
  notifyApi: {
    unreadCount: vi.fn().mockResolvedValue({ count: 0 }),
    list: vi.fn().mockResolvedValue([]),
    markAllRead: vi.fn(),
    markRead: vi.fn(),
  },
}));

function renderShellPart(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("用户端导航", () => {
  it("侧栏不再暴露系统设置或 Provider 配置入口", () => {
    const { container } = renderShellPart(<Sidebar />);

    expect(screen.queryByText("系统设置")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Provider|API Key|配置 API/i),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector('a[href="/settings"]'),
    ).not.toBeInTheDocument();
    expect(screen.getByText("充值/续费").closest("a")).toHaveAttribute(
      "href",
      "/pricing",
    );
  });

  it("顶栏菜单只进入账号和套餐，不再进入系统设置", async () => {
    const { container } = renderShellPart(<Topbar />);

    screen.getByRole("button", { name: /U|账号/ }).click();

    expect(await screen.findByText("套餐与积分")).toBeInTheDocument();
    expect(screen.queryByText("系统设置")).not.toBeInTheDocument();
    expect(
      container.querySelector('a[href="/settings"]'),
    ).not.toBeInTheDocument();
  });
});
