import { pipelineApi, publishApi } from "@oral/api-client";
import type {
  PipelineTask,
  PublicationRevision,
  PublishAccount,
} from "@oral/types";
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
      publicationRevisions: vi.fn(),
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

const finalized: PublicationRevision = {
  id: "pub-final-1",
  taskId: task.id,
  revision: 2,
  status: "finalized",
  baseRenderVersionId: "render-v1",
  renderVersionId: "render-v2",
  draftRevision: 5,
  lastError: "",
  finalizedAt: "2026-07-27T00:10:00Z",
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:10:00Z",
  content: {
    schemaVersion: 1,
    title: "定稿标题",
    topics: ["AI", "增长"],
    subtitles: {
      enabled: true,
      source: "asr_aligned",
      segments: [],
      style: {
        fontFamily: "PingFang SC",
        fontSize: 44,
        color: "#FFFFFF",
        stroke: 2,
        xPercent: 50,
        yPercent: 82,
      },
    },
    cover: { selectedFrameMs: 2000, template: "center-band" },
  },
};

const accounts: PublishAccount[] = [
  {
    id: "douyin-a",
    platform: "douyin",
    platformName: "抖音",
    nickname: "主账号",
    status: "active",
    createdAt: "2026-07-27T00:00:00Z",
  },
  {
    id: "douyin-b",
    platform: "douyin",
    platformName: "抖音",
    nickname: "副账号",
    status: "active",
    createdAt: "2026-07-27T00:00:00Z",
  },
  {
    id: "xhs-a",
    platform: "xiaohongshu",
    platformName: "小红书",
    nickname: "小红书账号",
    status: "active",
    createdAt: "2026-07-27T00:00:00Z",
  },
];

function renderPage(
  url = `/publish/jobs?task=${task.id}&revision=${finalized.id}`,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <PublishJobsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PublishJobsPage revision publish", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(pipelineApi.get).mockResolvedValue(task);
    vi.mocked(pipelineApi.publicationRevisions).mockResolvedValue([finalized]);
    vi.mocked(publishApi.accounts).mockResolvedValue(accounts);
    vi.mocked(publishApi.capabilities).mockResolvedValue([
      {
        platform: "douyin",
        platformName: "抖音",
        mode: "automatic",
        verificationStatus: "verified",
        automaticEnabled: true,
        fallback: "manual_package",
        reason: "",
      },
      {
        platform: "xiaohongshu",
        platformName: "小红书",
        mode: "automatic",
        verificationStatus: "verified",
        automaticEnabled: true,
        fallback: "manual_package",
        reason: "",
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

  it("只传 finalized revision、平台和账号创建发布任务", async () => {
    renderPage();

    expect(await screen.findByText("定稿标题")).toBeInTheDocument();
    expect(screen.getByText("#AI")).toBeInTheDocument();
    expect(screen.queryByLabelText("视频标题")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /抖音/ }));
    fireEvent.change(screen.getByLabelText("选择抖音账号"), {
      target: { value: "douyin-b" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建发布任务 ×1" }));

    await waitFor(() => {
      expect(publishApi.createJobs).toHaveBeenCalledWith({
        publicationRevisionId: finalized.id,
        platforms: ["douyin"],
        accountIds: { douyin: "douyin-b" },
        publishAt: undefined,
      });
    });
  });

  it("没有 finalized revision 时阻止发布并引导返回剪辑页", async () => {
    vi.mocked(pipelineApi.publicationRevisions).mockResolvedValue([
      { ...finalized, id: "pub-draft-1", status: "draft", finalizedAt: null },
    ]);

    renderPage(`/publish/jobs?task=${task.id}`);

    expect(
      await screen.findByText("当前内容尚未定稿，暂不能创建发布任务。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回剪辑页" })).toHaveAttribute(
      "href",
      `/editor?task=${task.id}`,
    );
    expect(publishApi.createJobs).not.toHaveBeenCalled();
  });

  it("未验收平台无需账号也能创建人工发布包", async () => {
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
    renderPage();

    await screen.findByText("定稿标题");
    fireEvent.click(screen.getByRole("button", { name: /抖音/ }));
    expect(
      screen.getByText("抖音：生成完整人工发布包，无需选择账号"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建发布任务 ×1" }));

    await waitFor(() => {
      expect(publishApi.createJobs).toHaveBeenCalledWith({
        publicationRevisionId: finalized.id,
        platforms: ["douyin"],
        accountIds: {},
        publishAt: undefined,
      });
    });
  });
});
