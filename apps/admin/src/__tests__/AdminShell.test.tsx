import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ADMIN_TOKEN_KEY } from "../lib/adminHttp";
import App from "../App";

function renderApp(initialEntries: string[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("admin app routing", () => {
  beforeEach(() => {
    localStorage.clear();
    // 总览页会拉取大盘数据；保持挂起态即可（本用例只断言导航结构）
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
  });

  it("redirects anonymous visitors to admin login", () => {
    renderApp(["/plans"]);

    expect(
      screen.getByRole("heading", { name: "管理员登录" }),
    ).toBeInTheDocument();
  });

  it("shows protected navigation after admin token exists", () => {
    localStorage.setItem(ADMIN_TOKEN_KEY, "test-token");

    renderApp(["/"]);

    expect(screen.getByText("管理控制台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "套餐 SKU" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "用户管理" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "成本与审计" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "私信安全" })).toBeInTheDocument();
    // 侧边栏按业务域分组
    expect(screen.getByText("商业化")).toBeInTheDocument();
    expect(screen.getByText("用户与安全")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "运营总览" }),
    ).toBeInTheDocument();
  });
});
