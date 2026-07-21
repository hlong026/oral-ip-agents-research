import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PublishAccountsPage from "../pages/PublishAccountsPage";

const apiMocks = vi.hoisted(() => ({
  accounts: vi.fn(),
  listenerStatus: vi.fn(),
  qrcodePoll: vi.fn(),
  qrcodeStart: vi.fn(),
}));

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    imApi: { ...actual.imApi, listenerStatus: apiMocks.listenerStatus },
    publishApi: {
      ...actual.publishApi,
      accounts: apiMocks.accounts,
      qrcodePoll: apiMocks.qrcodePoll,
      qrcodeStart: apiMocks.qrcodeStart,
    },
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PublishAccountsPage />
    </QueryClientProvider>,
  );
}

describe("账号扫码绑定闭环", () => {
  beforeEach(() => {
    apiMocks.accounts.mockReset();
    apiMocks.listenerStatus.mockReset();
    apiMocks.qrcodePoll.mockReset();
    apiMocks.qrcodeStart.mockReset();
    apiMocks.listenerStatus.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("点击平台后展示二维码，扫码成功后自动刷新到已登录账号", async () => {
    const account = {
      id: "account-xhs-1",
      platform: "xiaohongshu" as const,
      platformName: "小红书",
      nickname: "测试小红书账号",
      status: "active" as const,
      createdAt: "2026-07-21T00:00:00Z",
    };
    apiMocks.accounts.mockResolvedValueOnce([]).mockResolvedValue([account]);
    let resolveQrcodeStart: (value: {
      ticket: string;
      qrcodeUrl: string;
    }) => void;
    apiMocks.qrcodeStart.mockReturnValue(
      new Promise((resolve) => {
        resolveQrcodeStart = resolve;
      }),
    );
    let inFlightPolls = 0;
    let maxInFlightPolls = 0;
    apiMocks.qrcodePoll.mockImplementation(async () => {
      inFlightPolls += 1;
      maxInFlightPolls = Math.max(maxInFlightPolls, inFlightPolls);
      await new Promise((resolve) => setTimeout(resolve, 2_500));
      inFlightPolls -= 1;
      return { status: "success", account };
    });

    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /小红书/ }));

    expect(
      screen.getByRole("dialog", { name: "添加小红书账号" }),
    ).toBeInTheDocument();
    expect(screen.getByText("正在生成二维码…")).toBeInTheDocument();

    await act(async () => {
      resolveQrcodeStart!({
        ticket: "ticket-xhs-1",
        qrcodeUrl: "data:image/png;base64,dGVzdA==",
      });
    });

    expect(
      await screen.findByRole("img", { name: "授权二维码" }),
    ).toHaveAttribute("src", "data:image/png;base64,dGVzdA==");
    expect(
      await screen.findByText("测试小红书账号", {}, { timeout: 7_000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("已登录账号（1）")).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "授权二维码" }),
    ).not.toBeInTheDocument();
    expect(apiMocks.qrcodeStart).toHaveBeenCalledWith("xiaohongshu");
    expect(apiMocks.qrcodePoll).toHaveBeenCalledWith(
      "ticket-xhs-1",
      "xiaohongshu",
    );
    expect(apiMocks.qrcodePoll).toHaveBeenCalledTimes(1);
    expect(maxInFlightPolls).toBe(1);
    expect(apiMocks.accounts).toHaveBeenCalledTimes(2);
  }, 10_000);
});
