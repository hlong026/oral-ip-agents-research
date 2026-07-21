import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ImSafetyPage from "../pages/ImSafetyPage";

describe("IM safety page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the gray allowlist and 24-hour rollout metrics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/im/kill-switch")) {
          return jsonResponse({ stopped: true, canceledMessages: 0 });
        }
        if (url.includes("/im/gray/accounts")) {
          return jsonResponse([
            {
              accountId: "account-1",
              userId: "user-1",
              nickname: "灰度测试账号",
              approvedBy: "admin-1",
              addedAt: "2026-07-21T00:00:00Z",
            },
          ]);
        }
        if (url.includes("/im/monitoring")) {
          return jsonResponse({
            hours: 24,
            windowStart: "2026-07-20T00:00:00Z",
            windowEnd: "2026-07-21T00:00:00Z",
            grayAccounts: 1,
            listenerAccounts: 1,
            listeningAccounts: 1,
            connectionAttempts: 2,
            connectionSuccessRate: 100,
            dropoutRate: 0,
            sendSuccessRate: 100,
            sendSuccess: 3,
            sendFailure: 0,
            quotaRejected: 0,
            moderationBlocked: 0,
            credentialExpired: 0,
            ownershipRejected: 0,
            riskControlIncidents: 0,
          });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ImSafetyPage />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "24 小时灰度监控" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("灰度测试账号")).toBeInTheDocument();
    expect(screen.getByText("1/1")).toBeInTheDocument();
    expect(screen.getAllByText("100%")).toHaveLength(2);
  });
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}
