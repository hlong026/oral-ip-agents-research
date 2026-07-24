import { contentApi } from "@oral/api-client";
import { useQuota } from "@oral/stores";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  confirmMeteredOperation,
  mediaDurationSeconds,
} from "../lib/meteredOperation";
import CreatePage from "../pages/CreatePage";

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    contentApi: {
      ...actual.contentApi,
      probe: vi.fn(),
      parse: vi.fn(),
      rewrite: vi.fn(),
    },
    catalogApi: {
      ...actual.catalogApi,
      modulePrices: vi.fn().mockResolvedValue({ items: [] }),
    },
  };
});

vi.mock("../lib/meteredOperation", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../lib/meteredOperation")>();
  return {
    ...actual,
    confirmMeteredOperation: vi.fn(),
    mediaDurationSeconds: vi.fn(),
  };
});

describe("CreatePage 来源模式切换", () => {
  beforeEach(() => {
    vi.mocked(contentApi.probe).mockReset();
    vi.mocked(contentApi.parse).mockReset();
    vi.mocked(contentApi.rewrite).mockReset();
    vi.mocked(confirmMeteredOperation).mockReset();
    vi.mocked(mediaDurationSeconds).mockReset();
    useQuota.setState({ quota: null, load: vi.fn() });
  });

  it("切换模式时清除已放弃的来源，避免用旧输入继续下一步", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴抖音 / 小红书视频链接或视频ID…"),
      { target: { value: "https://example.com/video" } },
    );
    expect(screen.getByRole("button", { name: "下一步 →" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "选题生成" }));

    expect(
      screen.getByPlaceholderText("如：个体户报税 3 个坑 / 新房除甲醛真相…"),
    ).toHaveValue("");
    expect(screen.getByRole("button", { name: "下一步 →" })).toBeDisabled();
  });

  it("开发模式进入文案步骤时只探测一次链接", async () => {
    vi.mocked(contentApi.probe).mockImplementation(
      () => new Promise(() => undefined),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <CreatePage />
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴抖音 / 小红书视频链接或视频ID…"),
      { target: { value: "https://www.douyin.com/video/7623347570785471796" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    expect(contentApi.probe).toHaveBeenCalledTimes(1);
  });

  it("链接解析期间明确提示等待原文，不误导为正在IP改写", async () => {
    vi.mocked(contentApi.probe).mockImplementation(
      () => new Promise(() => undefined),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴抖音 / 小红书视频链接或视频ID…"),
      { target: { value: "https://www.douyin.com/jingxuan?modal_id=waiting" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    expect(
      await screen.findByRole("button", { name: "等待原文提取完成" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "正在按 IP 改写…" }),
    ).not.toBeInTheDocument();
  });

  it("上传视频转写期间显示阶段进度且不会静默等待", async () => {
    vi.mocked(mediaDurationSeconds).mockResolvedValue(170);
    vi.mocked(confirmMeteredOperation).mockResolvedValue("quote-upload");
    vi.mocked(contentApi.parse).mockImplementation(
      () => new Promise(() => undefined),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const fileInput =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: {
        files: [new File(["video"], "sample.mp4", { type: "video/mp4" })],
      },
    });

    await waitFor(() =>
      expect(
        screen.getByRole("progressbar", { name: "视频转写进度" }),
      ).toHaveAttribute("aria-valuenow", "55"),
    );
    expect(
      screen.getByText("正在识别音频，较长视频需要一些时间"),
    ).toBeInTheDocument();
  });

  it("转写成功后刷新侧栏积分余额", async () => {
    vi.mocked(mediaDurationSeconds).mockResolvedValue(170);
    vi.mocked(confirmMeteredOperation).mockResolvedValue("quote-upload");
    vi.mocked(contentApi.parse).mockResolvedValue({
      transcript: {
        text: "真实转写文案",
        words: [],
        duration: 170,
        language: "zh",
      },
      degraded: false,
    });
    const loadQuota = vi.fn().mockResolvedValue(undefined);
    useQuota.setState({ load: loadQuota });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const fileInput =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, {
      target: {
        files: [new File(["video"], "sample.mp4", { type: "video/mp4" })],
      },
    });

    await waitFor(() => expect(loadQuota).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("progressbar", { name: "视频转写进度" }),
    ).toHaveAttribute("aria-valuenow", "100");
  });

  it("链接转写完成后先展示原文，不自动调用改写", async () => {
    vi.mocked(contentApi.probe).mockResolvedValue({ durationSeconds: 170 });
    vi.mocked(confirmMeteredOperation).mockResolvedValue("quote-link");
    vi.mocked(contentApi.parse).mockResolvedValue({
      transcript: {
        text: "从音频识别出的完整原文",
        words: [],
        duration: 170,
        language: "zh",
      },
      degraded: false,
      scriptId: "script-from-link",
    });
    vi.mocked(contentApi.rewrite).mockResolvedValue({
      text: "不应该自动出现的改写文案",
      validationPassed: true,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴抖音 / 小红书视频链接或视频ID…"),
      {
        target: {
          value: "https://www.douyin.com/jingxuan?modal_id=audio-first",
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("口播文案")).toHaveValue(
        "从音频识别出的完整原文",
      ),
    );
    expect(contentApi.rewrite).not.toHaveBeenCalled();
    expect(screen.getByText("完整原文提取完成")).toBeInTheDocument();
  });

  it("用户明确点击后携带自定义要求和文案资产执行IP改写", async () => {
    vi.mocked(contentApi.probe).mockResolvedValue({ durationSeconds: 170 });
    vi.mocked(confirmMeteredOperation)
      .mockResolvedValueOnce("quote-link")
      .mockResolvedValueOnce("quote-rewrite");
    vi.mocked(contentApi.parse).mockResolvedValue({
      transcript: {
        text: "待改写的完整原文",
        words: [],
        duration: 170,
        language: "zh",
      },
      degraded: false,
      scriptId: "script-bound-to-ip",
    });
    vi.mocked(contentApi.rewrite).mockResolvedValue({
      text: "结合IP生成的新文案",
      validationPassed: true,
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CreatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴抖音 / 小红书视频链接或视频ID…"),
      {
        target: {
          value: "https://www.douyin.com/jingxuan?modal_id=custom-rewrite",
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    await screen.findByDisplayValue("待改写的完整原文");

    fireEvent.change(
      screen.getByPlaceholderText("补充改写要求，如：保留案例，语气更克制"),
      { target: { value: "保留案例，结尾改成邀请私信" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "按当前 IP 改写" }));

    await waitFor(() =>
      expect(contentApi.rewrite).toHaveBeenCalledWith(
        "待改写的完整原文",
        "structure",
        "保留案例，结尾改成邀请私信",
        "script-bound-to-ip",
        "quote-rewrite",
      ),
    );
    expect(
      screen.getByRole("textbox", { name: "提取原文" }),
    ).toHaveValue("待改写的完整原文");
    expect(
      await screen.findByRole("textbox", { name: "IP 改写结果" }),
    ).toHaveValue("结合IP生成的新文案");
  });
});
