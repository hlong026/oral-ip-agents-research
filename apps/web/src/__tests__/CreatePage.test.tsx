import {
  billingApi,
  catalogApi,
  contentApi,
  pipelineApi,
} from "@oral/api-client";
import { useIp, useQuota, useTasks } from "@oral/stores";
import type {
  ModulePrice,
  Persona,
  PipelineTask,
  PricePreview,
} from "@oral/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
    billingApi: {
      ...actual.billingApi,
      pricePreview: vi.fn(),
    },
    pipelineApi: {
      ...actual.pipelineApi,
      create: vi.fn(),
      get: vi.fn(),
      confirm: vi.fn(),
      cancel: vi.fn(),
    },
    publishApi: {
      ...actual.publishApi,
      capabilities: vi.fn().mockResolvedValue([]),
      createJobs: vi.fn(),
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
      (_url, _file, _quoteId, onProgress) => {
        onProgress?.({
          id: "upload-job",
          status: "running",
          progress: 55,
          stage: "正在提取音轨并转写文案",
        });
        return new Promise(() => undefined);
      },
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
        screen.getByRole("progressbar", { name: "视频转写真实进度" }),
      ).toHaveAttribute("aria-valuenow", "55"),
    );
    expect(screen.getByText("正在提取音轨并转写文案")).toBeInTheDocument();
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
        expect.any(Function),
      ),
    );
    expect(screen.getByRole("textbox", { name: "提取原文" })).toHaveValue(
      "待改写的完整原文",
    );
    expect(
      await screen.findByRole("textbox", { name: "IP 改写结果" }),
    ).toHaveValue("结合IP生成的新文案");
  });

  it("IP改写期间显示后台任务返回的真实阶段进度", async () => {
    vi.mocked(contentApi.probe).mockResolvedValue({ durationSeconds: 170 });
    vi.mocked(confirmMeteredOperation)
      .mockResolvedValueOnce("quote-link")
      .mockResolvedValueOnce("quote-rewrite");
    vi.mocked(contentApi.parse).mockResolvedValue({
      transcript: {
        text: "等待改写的完整原文",
        words: [],
        duration: 170,
        language: "zh",
      },
      degraded: false,
      scriptId: "script-progress",
    });
    vi.mocked(contentApi.rewrite).mockImplementation(
      (_text, _intensity, _prompt, _scriptId, _quoteId, onProgress) => {
        onProgress?.({
          id: "rewrite-job",
          status: "running",
          progress: 45,
          stage: "正在生成 IP 化大纲",
        });
        return new Promise(() => undefined);
      },
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
      {
        target: {
          value: "https://www.douyin.com/jingxuan?modal_id=progress",
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    await screen.findByDisplayValue("等待改写的完整原文");

    fireEvent.click(screen.getByRole("button", { name: "按当前 IP 改写" }));

    await waitFor(() =>
      expect(
        screen.getByRole("progressbar", { name: "IP 改写真实进度" }),
      ).toHaveAttribute("aria-valuenow", "45"),
    );
    expect(screen.getByText("正在生成 IP 化大纲")).toBeInTheDocument();
    expect(
      screen.getByText("结构分析、IP 大纲、完整改写与质量校验均在后台执行。"),
    ).toBeInTheDocument();
  });
});

// ---------------- 合成步：就地提交 + 实时进度 + 成片预览 ----------------

const testPersona = {
  id: "ip-1",
  name: "测试 IP",
  isActive: true,
  voiceId: "voice-1",
  avatarId: "avatar-1",
  videoDuration: 60,
} as unknown as Persona;

const modulePriceItems = [
  { module: "tts", billingUnit: "per_minute", unitSize: 1 },
  { module: "digital_human", billingUnit: "per_minute", unitSize: 1 },
] as unknown as ModulePrice[];

const composeQuote = {
  quoteId: "quote-compose",
  priceVersion: "v1",
  expiresAt: new Date(Date.now() + 600_000).toISOString(),
  items: [
    { module: "tts", name: "语音合成", points: 60 },
    { module: "digital_human", name: "数字人渲染", points: 120 },
  ],
  estimatedPoints: 180,
  availablePoints: 10_000,
} as unknown as PricePreview;

function makeTask(overrides: Partial<PipelineTask> = {}): PipelineTask {
  return {
    id: "task-compose-1",
    ipId: "ip-1",
    title: "测试成片",
    mode: "auto",
    status: "running",
    steps: [
      { step: "voice", status: "done", progress: 100 },
      { step: "compose", status: "running", progress: 10 },
      { step: "publish", status: "pending", progress: 0 },
    ],
    compute: "cloud",
    quotaCost: 0,
    ...overrides,
  } as unknown as PipelineTask;
}

function renderStep(step: "compose" | "publish") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/create?step=${step}`]}>
        <CreatePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 等模块价格目录写入缓存后触发一次报价，保证单次点击对应单次报价请求 */
async function requestComposeQuote() {
  await waitFor(() => expect(catalogApi.modulePrices).toHaveBeenCalled());
  // 让 React Query 将已解析的目录写入缓存并完成重渲染
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "计算预计积分" }));
  await screen.findByText("预计合计");
  expect(billingApi.pricePreview).toHaveBeenCalledTimes(1);
}

describe("CreatePage 合成步就地提交", () => {
  beforeEach(() => {
    vi.mocked(catalogApi.modulePrices).mockResolvedValue({
      items: modulePriceItems,
    } as Awaited<ReturnType<typeof catalogApi.modulePrices>>);
    vi.mocked(billingApi.pricePreview).mockReset();
    vi.mocked(pipelineApi.create).mockReset();
    vi.mocked(pipelineApi.get).mockReset();
    useIp.setState({ current: testPersona, personas: [testPersona] });
    useTasks.setState({ tasks: {} });
    useQuota.setState({ quota: null, load: vi.fn() });
  });

  it("报价前禁止开始合成，计算积分后展示明细并解锁", async () => {
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    renderStep("compose");

    expect(screen.getByRole("button", { name: "开始合成" })).toBeDisabled();

    await requestComposeQuote();

    expect(screen.getByText("数字人渲染")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始合成" })).toBeEnabled();
  });

  it("开始合成以「暂不发布」方式提交，并原地展示实时进度面板", async () => {
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    vi.mocked(pipelineApi.create).mockResolvedValue([makeTask()]);
    vi.mocked(pipelineApi.get).mockResolvedValue(makeTask());
    renderStep("compose");

    await requestComposeQuote();
    fireEvent.click(screen.getByRole("button", { name: "开始合成" }));

    await screen.findByText("流水线时间线（实时）");
    expect(pipelineApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        ipId: "ip-1",
        platforms: [],
        quoteId: "quote-compose",
      }),
    );
    expect(screen.getByText("合成中")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "等待成片生成…" }),
    ).toBeDisabled();
  });

  it("成片生成后原地出现视频预览并解锁下一步", async () => {
    const doneTask = makeTask({
      status: "done",
      steps: [
        { step: "voice", status: "done", progress: 100 },
        {
          step: "compose",
          status: "done",
          progress: 100,
          artifacts: { final_video_key: "final/task-1.mp4" },
        },
        {
          step: "publish",
          status: "skipped",
          progress: 100,
          message: "未选择发布平台，成片已就绪",
        },
      ] as PipelineTask["steps"],
    });
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    vi.mocked(pipelineApi.create).mockResolvedValue([doneTask]);
    vi.mocked(pipelineApi.get).mockResolvedValue(doneTask);
    renderStep("compose");

    await requestComposeQuote();
    fireEvent.click(screen.getByRole("button", { name: "开始合成" }));

    const video = await screen.findByLabelText("成片预览");
    expect(video).toHaveAttribute("src", "/media/final/task-1.mp4");
    expect(screen.getByRole("button", { name: "下一步 →" })).toBeEnabled();
  });

  it("未生成成片时发布步给出警告并禁用提交", () => {
    renderStep("publish");

    expect(
      screen.getByText(
        "成片尚未生成，请先回到「合成」步完成合成后再配置发布。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "完成，稍后手动发布" }),
    ).toBeDisabled();
  });

  it("任务取消后可重新调整参数并回到报价表单", async () => {
    const canceledTask = makeTask({
      status: "canceled",
      steps: [
        { step: "voice", status: "done", progress: 100 },
        { step: "compose", status: "pending", progress: 0 },
        { step: "publish", status: "pending", progress: 0 },
      ] as PipelineTask["steps"],
    });
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    vi.mocked(pipelineApi.create).mockResolvedValue([canceledTask]);
    vi.mocked(pipelineApi.get).mockResolvedValue(canceledTask);
    renderStep("compose");

    await requestComposeQuote();
    fireEvent.click(screen.getByRole("button", { name: "开始合成" }));

    fireEvent.click(
      await screen.findByRole("button", { name: "重新调整参数并合成" }),
    );

    expect(screen.getByText("合成积分报价")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始合成" })).toBeDisabled();
  });
});
