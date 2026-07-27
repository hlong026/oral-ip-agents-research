import { pipelineApi, publishApi } from "@oral/api-client";
import type { PipelineTask } from "@oral/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PublishJobsPage from "../pages/PublishJobsPage";

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    pipelineApi: {
      ...actual.pipelineApi,
      get: vi.fn(),
    },
    publishApi: {
      ...actual.publishApi,
      accounts: vi.fn(),
      capabilities: vi.fn(),
      jobs: vi.fn(),
      createJobs: vi.fn(),
    },
  };
});

const task: PipelineTask = {
  id: "task-publish-1",
  ipId: "ip-1",
  scriptId: "script-1",
  scriptVersion: 2,
  title: "已完成的活动成片",
  mode: "auto",
  status: "done",
  steps: [],
  compute: "cloud",
  quotaCost: 8,
  artifacts: {
    final_video_url: "/media/compose/v2.mp4?exp=1&sig=test",
  },
  activeRenderVersion: 2,
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/publish/jobs?task=${task.id}`]}>
        <PublishJobsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PublishJobsPage 成片发布闭环", () => {
  beforeEach(() => {
    vi.mocked(pipelineApi.get).mockResolvedValue(task);
    vi.mocked(publishApi.accounts).mockResolvedValue([]);
    vi.mocked(publishApi.capabilities).mockResolvedValue([
      {
        platform: "douyin",
        platformName: "抖音",
        mode: "export_only",
        verificationStatus: "unverified",
        automaticEnabled: false,
        fallback: "manual_package",
        reason: "仅提供人工发布包",
      },
    ]);
    vi.mocked(publishApi.jobs).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      pageSize: 12,
    });
    vi.mocked(publishApi.createJobs).mockResolvedValue([]);
  });

  it("从任务详情进入后可直接配置并创建活动成片发布任务", async () => {
    renderPage();

    expect(await screen.findByText("为此成片创建发布任务")).toBeInTheDocument();
    expect(await screen.findByDisplayValue(task.title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /抖音/ }));
    fireEvent.click(screen.getByRole("button", { name: "创建发布任务 ×1" }));

    await waitFor(() => {
      expect(publishApi.createJobs).toHaveBeenCalledWith({
        taskId: task.id,
        platforms: ["douyin"],
        title: task.title,
        publishAt: undefined,
      });
    });
  });
});
