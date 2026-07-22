import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { useSession } from "@oral/stores";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  beforeEach(() => {
    useSession.setState({
      user: {
        id: "user-1",
        phone: "13900000001",
        nickname: "普通用户",
        avatarChar: "普",
        createdAt: "2026-07-22T00:00:00Z",
        role: "user",
      },
      ready: true,
    });
  });

  it("侧栏不再暴露系统设置或 Provider 配置入口", () => {
    const { container } = renderShellPart(<Sidebar />);

    expect(screen.queryByText("系统设置")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Provider|API Key|配置 API/i),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector('a[href="/settings"]'),
    ).not.toBeInTheDocument();
    expect(container.querySelector('a[href="/im"]')).not.toBeInTheDocument();
    expect(screen.queryByText("私信中心")).not.toBeInTheDocument();
    expect(screen.getByText("充值/续费").closest("a")).toHaveAttribute(
      "href",
      "/pricing",
    );
  });

  it("顶栏菜单只进入账号和套餐，不再进入系统设置", async () => {
    const { container } = renderShellPart(<Topbar />);

    screen.getByRole("button", { name: /普通用户/ }).click();

    expect(await screen.findByText("套餐与积分")).toBeInTheDocument();
    expect(screen.queryByText("系统设置")).not.toBeInTheDocument();
    expect(
      container.querySelector('a[href="/settings"]'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("平台管理控制台")).not.toBeInTheDocument();
  });

  it("管理员在自己的创作空间可进入平台管理控制台", async () => {
    useSession.setState({
      user: {
        id: "admin-1",
        phone: "13900000002",
        nickname: "本地联调管理员",
        avatarChar: "管",
        createdAt: "2026-07-22T00:00:00Z",
        role: "admin",
      },
    });

    renderShellPart(<Topbar />);

    screen.getByRole("button", { name: /本地联调管理员/ }).click();

    const adminConsoleLink = await screen.findByRole("link", {
      name: "平台管理控制台",
    });
    expect(adminConsoleLink).toBeInTheDocument();
    expect(adminConsoleLink).toHaveAttribute("href", "http://localhost:5174");
  });

  it("管理员创作空间明确标注免积分，但不暗示可访问其他用户内容", () => {
    useSession.setState({
      user: {
        id: "admin-1",
        phone: "13900000002",
        nickname: "本地联调管理员",
        avatarChar: "管",
        createdAt: "2026-07-22T00:00:00Z",
        role: "admin",
      },
    });

    renderShellPart(<Sidebar />);

    expect(screen.getByText(/管理员创作空间/)).toBeInTheDocument();
    expect(screen.getByText("创作不扣积分")).toBeInTheDocument();
    expect(screen.getByText("仅限管理员自己的内容")).toBeInTheDocument();
  });
});
