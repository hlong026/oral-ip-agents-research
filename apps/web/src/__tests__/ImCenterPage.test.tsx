import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ImCenterPage from "../pages/ImCenterPage";

const apiMocks = vi.hoisted(() => ({
  accounts: vi.fn(),
  conversations: vi.fn(),
  messages: vi.fn(),
  markRead: vi.fn(),
  send: vi.fn(),
  sync: vi.fn(),
}));

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    imApi: {
      ...actual.imApi,
      conversations: apiMocks.conversations,
      messages: apiMocks.messages,
      markRead: apiMocks.markRead,
      send: apiMocks.send,
      sync: apiMocks.sync,
    },
    publishApi: { ...actual.publishApi, accounts: apiMocks.accounts },
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ImCenterPage />
    </QueryClientProvider>,
  );
}

describe("抖音私信同步与回复", () => {
  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    apiMocks.accounts.mockResolvedValue([
      {
        id: "account-1",
        platform: "douyin",
        platformName: "抖音",
        nickname: "主账号",
        status: "active",
        createdAt: "2026-07-21T00:00:00Z",
      },
    ]);
    apiMocks.conversations.mockResolvedValue({
      items: [
        {
          id: "conversation-1",
          accountId: "account-1",
          platform: "douyin",
          remoteUid: "browser:user-1",
          remoteNickname: "咨询用户",
          remoteAvatar: "",
          lastMessageAt: "2026-07-21T01:00:00Z",
          unreadCount: 0,
          status: "active",
          createdAt: "2026-07-21T01:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      pageSize: 50,
    });
    apiMocks.messages.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      pageSize: 100,
    });
    apiMocks.send.mockResolvedValue({});
    apiMocks.sync.mockResolvedValue({
      accountId: "account-1",
      imported: 2,
      conversations: 1,
    });
  });

  it("可以同步当前账号历史并向已选会话发送回复", async () => {
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /咨询用户/ }));
    await user.type(
      screen.getByRole("textbox", { name: "回复内容" }),
      "已经收到",
    );
    await user.click(screen.getByRole("button", { name: "发送回复" }));

    await waitFor(() => {
      expect(apiMocks.send).toHaveBeenCalledWith("conversation-1", "已经收到");
    });
    expect(screen.getByRole("textbox", { name: "回复内容" })).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "同步历史" }));
    await waitFor(() => {
      expect(apiMocks.sync).toHaveBeenCalledWith("account-1");
    });
    expect(await screen.findByText("已同步 2 条历史消息")).toBeInTheDocument();
  });
});
