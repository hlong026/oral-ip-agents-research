import { pipelineApi } from "@oral/api-client";
import { useTasks } from "@oral/stores";
import type { PipelineTask, PublicationRevision } from "@oral/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
      publicationDraft: vi.fn(),
      savePublicationDraft: vi.fn(),
      metadataSuggestions: vi.fn(),
      coverCandidates: vi.fn(),
      coverPreview: vi.fn(),
      finalizePublication: vi.fn(),
      publicationRevisions: vi.fn(),
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
    script: "第一句。第二句。",
    duration: 30,
  },
  activeRenderVersion: 1,
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

const draft: PublicationRevision = {
  id: "pub-draft-1",
  taskId: task.id,
  revision: 1,
  status: "draft",
  baseRenderVersionId: "render-v1",
  renderVersionId: null,
  draftRevision: 3,
  lastError: "",
  content: {
    schemaVersion: 1,
    title: "原始标题",
    topics: ["旧标签"],
    subtitles: {
      enabled: true,
      source: "asr_aligned",
      segments: [
        { id: "s1", startMs: 0, endMs: 1200, text: "第一句" },
        { id: "s2", startMs: 1200, endMs: 2400, text: "第二句" },
      ],
      style: {
        fontFamily: "PingFang SC",
        fontSize: 44,
        color: "#FFFFFF",
        stroke: 2,
        xPercent: 50,
        yPercent: 82,
      },
    },
    cover: { selectedFrameMs: 0, template: "bold-bottom" },
  },
  createdAt: "2026-07-27T00:00:00Z",
  updatedAt: "2026-07-27T00:00:00Z",
};

/** jsdom 不会真的播放，直接改 currentTime 再派发 timeupdate 模拟播放进度 */
function seekTo(video: HTMLElement, seconds: number) {
  Object.defineProperty(video, "currentTime", {
    value: seconds,
    writable: true,
    configurable: true,
  });
  fireEvent.timeUpdate(video);
}

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

describe("EditorPage publication draft", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(pipelineApi.list).mockResolvedValue({
      items: [task],
      total: 1,
      page: 1,
      pageSize: 20,
    });
    vi.mocked(pipelineApi.get).mockResolvedValue(task);
    vi.mocked(pipelineApi.renderVersions).mockResolvedValue([]);
    vi.mocked(pipelineApi.publicationDraft).mockResolvedValue(draft);
    vi.mocked(pipelineApi.savePublicationDraft).mockImplementation(
      async (_id, input) => ({
        ...draft,
        content: input.content,
        draftRevision: input.draftRevision + 1,
      }),
    );
    vi.mocked(pipelineApi.metadataSuggestions).mockResolvedValue({
      titles: ["爆款标题 A", "爆款标题 B", "爆款标题 C"],
      tags: ["AI", "口播", "成交", "增长", "案例", "私域"],
      groups: [
        { title: "爆款标题 A", tags: ["AI", "口播"], coverText: "【爆点】A" },
        { title: "爆款标题 B", tags: ["成交", "增长"], coverText: "【爆点】B" },
        { title: "爆款标题 C", tags: ["案例", "私域"], coverText: "" },
      ],
    });
    vi.mocked(pipelineApi.coverCandidates).mockResolvedValue([
      { timestampMs: 1500, imageUrl: "/covers/1.jpg" },
      { timestampMs: 6900, imageUrl: "/covers/2.jpg" },
      { timestampMs: 12300, imageUrl: "/covers/3.jpg" },
      { timestampMs: 17700, imageUrl: "/covers/4.jpg" },
      { timestampMs: 23100, imageUrl: "/covers/5.jpg" },
      { timestampMs: 28500, imageUrl: "/covers/6.jpg" },
    ]);
    vi.mocked(pipelineApi.coverPreview).mockResolvedValue({
      imageUrl: "/covers/preview.jpg",
    });
    vi.mocked(pipelineApi.finalizePublication).mockResolvedValue({
      ...draft,
      status: "finalized",
      id: "pub-final-1",
      renderVersionId: "render-v2",
    });
    vi.mocked(pipelineApi.publicationRevisions).mockResolvedValue([]);
    vi.mocked(confirmMeteredOperation).mockResolvedValue("quote-finalize");
    useTasks.setState({ tasks: {} });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("编辑字幕、字体和拖动坐标后用 CAS 自动保存", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    const subtitle = await screen.findByDisplayValue("第二句");
    await user.clear(subtitle);
    await user.type(subtitle, "第二句已校对");
    await user.selectOptions(
      screen.getByLabelText("字幕字体"),
      "Source Han Sans SC",
    );

    const overlay = screen.getByTestId("subtitle-overlay");
    Object.defineProperty(overlay.parentElement, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 200, height: 400 }),
    });
    fireEvent.pointerDown(overlay, { clientX: 100, clientY: 328 });
    window.dispatchEvent(
      new MouseEvent("pointermove", {
        clientX: 80,
        clientY: 240,
        bubbles: true,
      }),
    );
    window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));

    await vi.advanceTimersByTimeAsync(750);

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({
            subtitles: expect.objectContaining({
              segments: expect.arrayContaining([
                expect.objectContaining({
                  id: "s2",
                  text: expect.stringContaining("第二句已校对"),
                }),
              ]),
              style: expect.objectContaining({
                fontFamily: "Source Han Sans SC",
                xPercent: 40,
                yPercent: 60,
              }),
            }),
          }),
        }),
      );
    });
  });

  it("AI 生成后自动填充第 1 组，可切换其他组，封面候选可选择并保存", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    await user.click(
      await screen.findByRole("button", { name: "AI生成标题和标签" }),
    );
    // 生成后自动采用第 1 组：标题+标签+封面文字直接填充
    expect(await screen.findByLabelText("标题")).toHaveValue("爆款标题 A");
    await user.click(
      await screen.findByRole("button", { name: "采用第 2 组" }),
    );
    await user.click(screen.getByRole("button", { name: /选择 17\.7s 封面/ }));

    await vi.advanceTimersByTimeAsync(750);

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({
            title: "爆款标题 B",
            topics: ["成交", "增长"],
            cover: expect.objectContaining({
              selectedFrameMs: 17700,
              text: "【爆点】B",
            }),
          }),
        }),
      );
    });
  });

  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });

    expect(timeline).toHaveValue("20000");
    expect(screen.getByText(/当前选中 20\.0s/)).toBeInTheDocument();
  });

  it("保存草稿按钮立即提交当前编辑内容", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    const title = await screen.findByLabelText("标题");
    await user.clear(title);
    await user.type(title, "立即保存的标题");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({ title: "立即保存的标题" }),
        }),
      );
    });
  });

  it("合成前先保存草稿、报价并调用 finalize", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    await user.clear(await screen.findByLabelText("标题"));
    await user.type(screen.getByLabelText("标题"), "准备定稿的标题");
    await user.click(screen.getByRole("button", { name: "合成最终视频" }));

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenCalled();
      expect(confirmMeteredOperation).toHaveBeenCalledWith(
        "hd_export",
        "合成最终视频",
        { assets: 1 },
      );
      expect(pipelineApi.finalizePublication).toHaveBeenCalledWith(
        task.id,
        expect.objectContaining({
          quoteId: "quote-finalize",
          draftRevision: 4,
          idempotencyKey: expect.any(String),
        }),
      );
    });
    expect(await screen.findByText("带内容去发布 →")).toHaveAttribute(
      "href",
      `/publish/jobs?task=${task.id}&revision=pub-final-1`,
    );
  });

  it("保存请求期间继续编辑时不会被旧响应覆盖", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let resolveFirst: ((value: PublicationRevision) => void) | undefined;
    let saveCount = 0;
    vi.mocked(pipelineApi.savePublicationDraft).mockImplementation(
      async (_id, input) => {
        saveCount += 1;
        if (saveCount === 1) {
          return await new Promise<PublicationRevision>((resolve) => {
            resolveFirst = resolve;
          });
        }
        return {
          ...draft,
          content: input.content,
          draftRevision: input.draftRevision + 1,
        };
      },
    );
    renderEditor();

    const title = await screen.findByLabelText("标题");
    await user.clear(title);
    await user.type(title, "第一次编辑");
    await vi.advanceTimersByTimeAsync(700);
    await waitFor(() =>
      expect(pipelineApi.savePublicationDraft).toHaveBeenCalledTimes(1),
    );

    await user.clear(title);
    await user.type(title, "第二次编辑");
    await vi.advanceTimersByTimeAsync(700);
    resolveFirst?.({
      ...draft,
      content: {
        ...draft.content,
        title: "第一次编辑",
      },
      draftRevision: 4,
    });

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenCalledTimes(2);
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          draftRevision: 4,
          content: expect.objectContaining({ title: "第二次编辑" }),
        }),
      );
    });
    expect(screen.getByLabelText("标题")).toHaveValue("第二次编辑");
  });

  it("overlay 字幕严格跟随 [startMs, endMs)，句间停顿留空", async () => {
    vi.mocked(pipelineApi.publicationDraft).mockResolvedValue({
      ...draft,
      content: {
        ...draft.content,
        subtitles: {
          ...draft.content.subtitles,
          // 两段之间留 500ms 真实停顿：成片在停顿处不显示字幕，预览必须一致
          segments: [
            { id: "s1", startMs: 0, endMs: 1000, text: "第一句" },
            { id: "s2", startMs: 1500, endMs: 2500, text: "第二句" },
          ],
        },
      },
    });
    renderEditor();

    const overlay = await screen.findByTestId("subtitle-overlay");
    const video = screen.getByLabelText("剪辑成片预览");

    expect(overlay).toHaveTextContent("第一句");

    seekTo(video, 1.2);
    await waitFor(() => expect(overlay.textContent).toBe(""));

    seekTo(video, 1.6);
    await waitFor(() => expect(overlay).toHaveTextContent("第二句"));

    seekTo(video, 3);
    await waitFor(() => expect(overlay.textContent).toBe(""));
  });

  it("成片已烧录字幕时 overlay 只标位置，不再叠第二层文字", async () => {
    vi.mocked(pipelineApi.publicationRevisions).mockResolvedValue([
      {
        ...draft,
        id: "pub-final-9",
        status: "finalized",
        renderVersionId: "render-v2",
      },
    ]);
    renderEditor();

    const overlay = await screen.findByTestId("subtitle-overlay");
    await waitFor(() => expect(overlay).toHaveAttribute("data-burned", "true"));
    expect(overlay).toHaveTextContent("字幕位置");
    expect(overlay).not.toHaveTextContent("第一句");
  });
});
