import { pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type { PipelineRenderVersion, PipelineTask } from "@oral/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { confirmMeteredOperation } from "../lib/meteredOperation";
import EditorPage from "../pages/EditorPage";

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    pipelineApi: {
      ...actual.pipelineApi,
      list: vi.fn(),
      get: vi.fn(),
      renderVersions: vi.fn(),
      recompose: vi.fn(),
      cancelRender: vi.fn(),
      retryStep: vi.fn(),
    },
  };
});

vi.mock("../lib/meteredOperation", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../lib/meteredOperation")>();
  return {
    ...actual,
    confirmMeteredOperation: vi.fn(),
  };
});

const task: PipelineTask = {
  id: "task-editor-1",
  ipId: "ip-1",
  scriptId: "script-1",
  scriptVersion: 2,
  title: "编辑器回归任务",
  mode: "auto",
  status: "done",
  steps: [
    {
      step: "compose",
      status: "done",
      progress: 100,
      artifacts: { final_video_key: "compose/v1.mp4" },
    },
  ],
  compute: "cloud",
  quotaCost: 3,
  artifacts: {
    final_video_url: "/media/compose/v1.mp4?exp=1&sig=test",
    script: "这是用于编辑器测试的口播文案。",
  },
  activeRenderVersion: 1,
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

const activeRender: PipelineRenderVersion = {
  id: "render-v1",
  taskId: task.id,
  version: 1,
  baseVersion: 0,
  status: "done",
  config: {
    subtitleStyle: {
      fontSize: 52,
      color: "#FDE047",
      position: "top",
      stroke: 4,
    },
    bgmMode: "off",
    bgmVolume: 0,
    coverTemplate: "center-band",
  },
  videoUrl: "/media/compose/v1.mp4?exp=1&sig=test",
  coverUrl: "/media/compose/v1.jpg?exp=1&sig=test",
  quality: { passed: true },
  error: "",
  isActive: true,
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

const failedRender: PipelineRenderVersion = {
  ...activeRender,
  id: "render-v2-failed",
  version: 2,
  baseVersion: 1,
  status: "failed",
  config: {
    ...activeRender.config,
    subtitleStyle: {
      ...activeRender.config.subtitleStyle,
      fontSize: 56,
    },
  },
  videoUrl: null,
  coverUrl: null,
  quality: {},
  error: "重新合成失败，请稍后重试",
  isActive: false,
  updatedAt: "2026-07-27T00:01:00Z",
};

function renderEditor() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/editor?task=${task.id}`]}>
        <EditorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EditorPage 原子重合成", () => {
  beforeEach(() => {
    vi.mocked(pipelineApi.list).mockResolvedValue({
      items: [task],
      total: 1,
      page: 1,
      pageSize: 20,
    });
    vi.mocked(pipelineApi.get).mockResolvedValue(task);
    vi.mocked(pipelineApi.renderVersions).mockResolvedValue([activeRender]);
    vi.mocked(pipelineApi.recompose).mockResolvedValue({
      ...activeRender,
      id: "render-v2",
      version: 2,
      baseVersion: 1,
      status: "pending",
      isActive: false,
    });
    vi.mocked(confirmMeteredOperation).mockResolvedValue("quote-hd-export");
    useTasks.setState({ tasks: {} });
  });

  it("恢复活动版本配置，并用单次报价调用版本化重合成接口", async () => {
    renderEditor();

    expect(await screen.findByText("字号（52px）")).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("slider")[0]!, {
      target: { value: "56" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并重新合成" }));

    await waitFor(() => {
      expect(confirmMeteredOperation).toHaveBeenCalledWith(
        "hd_export",
        "重新合成成片",
        { assets: 1 },
      );
      expect(pipelineApi.recompose).toHaveBeenCalledWith(
        task.id,
        expect.objectContaining({
          quoteId: "quote-hd-export",
          baseVersion: 1,
          idempotencyKey: expect.any(String),
          config: expect.objectContaining({
            subtitleStyle: expect.objectContaining({ fontSize: 56 }),
            bgmMode: "off",
            bgmVolume: 0,
            coverTemplate: "center-band",
          }),
        }),
      );
    });
    expect(pipelineApi.retryStep).not.toHaveBeenCalled();
  });

  it("展示失败版本并保留失败配置供重新报价重试", async () => {
    vi.mocked(pipelineApi.renderVersions).mockResolvedValue([
      failedRender,
      activeRender,
    ]);

    renderEditor();

    expect(
      await screen.findByText("重新合成失败，请稍后重试"),
    ).toBeInTheDocument();
    expect(screen.getByText("字号（56px）")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "保存并重新合成" }),
    ).toBeEnabled();
  });
});
