import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PublishAccountsPage from "../pages/PublishAccountsPage";

const apiMocks = vi.hoisted(() => ({
  accounts: vi.fn(),
  capabilities: vi.fn(),
  qrcodePoll: vi.fn(),
  qrcodeStart: vi.fn(),
}));

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    publishApi: {
      ...actual.publishApi,
      accounts: apiMocks.accounts,
      capabilities: apiMocks.capabilities,
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
    apiMocks.capabilities.mockReset();
    apiMocks.qrcodePoll.mockReset();
    apiMocks.qrcodeStart.mockReset();
    apiMocks.accounts.mockResolvedValue([]);
    apiMocks.capabilities.mockResolvedValue([
      {
        platform: "xiaohongshu",
        platformName: "小红书",
        automaticEnabled: true,
        reason: "已通过测试",
      },
    ]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("立即显示启动弹层，并且慢轮询不会重叠", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let resolveStart!: (value: { ticket: string; qrcodeUrl: string }) => void;
    let resolvePoll!: (value: { status: "expired"; message: string }) => void;
    apiMocks.qrcodeStart.mockReturnValue(
      new Promise((resolve) => {
        resolveStart = resolve;
      }),
    );
    apiMocks.qrcodePoll.mockReturnValue(
      new Promise((resolve) => {
        resolvePoll = resolve;
      }),
    );

    renderPage();
    await user.click(await screen.findByRole("button", { name: /小红书/ }));

    expect(
      screen.getByRole("dialog", { name: "添加小红书账号" }),
    ).toBeInTheDocument();
    expect(screen.getByText("正在生成二维码…")).toBeInTheDocument();

    await act(async () => {
      resolveStart({
        ticket: "ticket-xhs-1",
        qrcodeUrl: "data:image/png;base64,dGVzdA==",
      });
    });
    expect(screen.getByRole("img", { name: "授权二维码" })).toHaveAttribute(
      "src",
      "data:image/png;base64,dGVzdA==",
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });

    expect(apiMocks.qrcodePoll).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    expect(apiMocks.qrcodePoll).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolvePoll({ status: "expired", message: "平台拒绝登录" });
    });
    await waitFor(() =>
      expect(screen.getByText("平台拒绝登录")).toBeInTheDocument(),
    );
  });

  it("关闭启动弹层后忽略迟到的二维码响应", async () => {
    const user = userEvent.setup();
    let resolveStart!: (value: { ticket: string; qrcodeUrl: string }) => void;
    apiMocks.qrcodeStart.mockReturnValue(
      new Promise((resolve) => {
        resolveStart = resolve;
      }),
    );

    renderPage();
    await user.click(await screen.findByRole("button", { name: /小红书/ }));
    await user.click(screen.getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => {
      resolveStart({
        ticket: "late-ticket",
        qrcodeUrl: "data:image/png;base64,bGF0ZQ==",
      });
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("未通过真实验收的平台仍保持禁用", async () => {
    apiMocks.capabilities.mockResolvedValue([
      {
        platform: "xiaohongshu",
        platformName: "小红书",
        automaticEnabled: false,
        reason: "尚未完成真实账号验收",
      },
    ]);

    renderPage();

    expect(
      await screen.findByRole("button", { name: /小红书/ }),
    ).toBeDisabled();
    expect(apiMocks.qrcodeStart).not.toHaveBeenCalled();
  });
});
