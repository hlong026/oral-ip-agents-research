import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TasksPage from "../pages/TasksPage";

describe("admin tasks page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows global task ownership, root cause, trace and controlled actions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/tasks?")) {
          return jsonResponse({
            items: [
              {
                id: "task-failed",
                userId: "user-1",
                userNickname: "演示用户",
                title: "口播成片",
                status: "failed",
                step: "voice",
                provider: "hifly",
                failureClass: "network",
                errorSummary: "provider timeout",
                traceId: "trace-001",
                quotaCost: 8,
                createdAt: "2026-07-30T00:00:00Z",
                updatedAt: "2026-07-30T00:01:00Z",
              },
              {
                id: "task-running",
                userId: "user-2",
                userNickname: "运行用户",
                title: "数字人成片",
                status: "running",
                step: "avatar",
                provider: "hifly",
                failureClass: "none",
                errorSummary: "",
                traceId: "trace-002",
                quotaCost: 20,
                createdAt: "2026-07-30T00:00:00Z",
                updatedAt: "2026-07-30T00:01:00Z",
              },
            ],
            total: 2,
            page: 1,
            pageSize: 20,
          });
        }
        if (url.includes("/operations/health")) {
          return jsonResponse({
            hours: 24,
            generatedAt: "2026-07-30T00:00:00Z",
            providerScanTruncated: false,
            providers: [
              {
                provider: "hifly",
                attempts: 2,
                successes: 1,
                failures: 1,
                failureRate: 50,
                quotaFailures: 1,
                quotaAlert: true,
                lastSuccessAt: "2026-07-30T00:00:00Z",
              },
            ],
            publishing: {
              succeeded: 9,
              failed: 1,
              manualFallback: 2,
              recovered: 1,
              failureClasses: { network: 1 },
              successRate: 90,
              manualFallbackRate: 16.67,
            },
            billing: {
              reserved: 2,
              settled: 8,
              released: 1,
              unknownOutcomes: 1,
            },
          });
        }
        if (url.includes("/tasks/task-failed/retry-quote")) {
          return jsonResponse({
            required: true,
            quote: {
              quoteId: "retry-quote-1",
              estimatedPoints: 12,
              availablePoints: 80,
            },
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
        <TasksPage />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "全局任务运维" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/演示用户/)).toBeInTheDocument();
    expect(screen.getAllByText(/网络异常/)).toHaveLength(2);
    expect(screen.getByText("trace-001")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText(/网络异常 1/)).toBeInTheDocument();
    expect(screen.getByText(/配额告警 1/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "受控重试" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "受控取消" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "受控重试" }));
    expect(
      await screen.findByText(/本次重试需重新冻结 12 点，用户当前可用 80 点/),
    ).toBeInTheDocument();
  });
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ "X-Trace-Id": "request-trace" }),
    json: async () => body,
  } as Response;
}
