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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
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
      script: vi.fn(),
      updateScript: vi.fn(),
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
    // 向导状态已持久化到 sessionStorage，用例间必须清理避免 taskId 泄漏
    sessionStorage.clear();
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

// ---------------- 视频合成步：进入即自动报价开始合成 + 实时进度 + 成片预览 ----------------

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

function renderStep(step: "compose" | "publish", opts?: { bare?: boolean }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // 合成步需要前四步产物：默认通过 scriptId 注入文案，bare 模拟直达缺料场景
  const entry =
    step === "compose" && !opts?.bare
      ? "/create?step=compose&scriptId=script-1"
      : `/create?step=${step}`;
  // 任务创建后会跳转 /tasks/:id，用桩页面断言跳转行为
  function TaskDetailStub() {
    const { id } = useParams();
    return <div>任务详情桩：{id}</div>;
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/create" element={<CreatePage />} />
          <Route path="/tasks/:id" element={<TaskDetailStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CreatePage 视频合成步全自动", () => {
  beforeEach(() => {
    // 向导状态已持久化到 sessionStorage，用例间必须清理避免 taskId 泄漏
    sessionStorage.clear();
    vi.mocked(catalogApi.modulePrices).mockResolvedValue({
      items: modulePriceItems,
    } as Awaited<ReturnType<typeof catalogApi.modulePrices>>);
    vi.mocked(billingApi.pricePreview).mockReset();
    vi.mocked(pipelineApi.create).mockReset();
    vi.mocked(pipelineApi.get).mockReset();
    vi.mocked(contentApi.script).mockReset();
    vi.mocked(contentApi.updateScript).mockReset();
    vi.mocked(contentApi.script).mockResolvedValue({
      id: "script-1",
      title: "测试文案",
      originalText: "原始文案",
      rewrittenText: "这是一段超过十个字的测试口播文案，用于满足合成前置校验。",
      currentVersion: 2,
    } as Awaited<ReturnType<typeof contentApi.script>>);
    vi.mocked(contentApi.updateScript).mockResolvedValue({
      id: "script-1",
      title: "测试文案",
      originalText: "原始文案",
      rewrittenText: "这是一段超过十个字的测试口播文案，用于满足合成前置校验。",
      currentVersion: 2,
    } as Awaited<ReturnType<typeof contentApi.updateScript>>);
    useIp.setState({ current: testPersona, personas: [testPersona] });
    useTasks.setState({ tasks: {} });
    useQuota.setState({ quota: null, load: vi.fn() });
  });

  it("进入合成步自动报价并以「暂不发布」方式创建任务，随后直接跳转任务详情页", async () => {
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    vi.mocked(pipelineApi.create).mockResolvedValue([makeTask()]);
    vi.mocked(pipelineApi.get).mockResolvedValue(makeTask());
    renderStep("compose");

    await screen.findByText("任务详情桩：task-compose-1");
    expect(billingApi.pricePreview).toHaveBeenCalledTimes(1);
    expect(pipelineApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        ipId: "ip-1",
        scriptId: "script-1",
        scriptVersion: 2,
        platforms: [],
        quoteId: "quote-compose",
      }),
    );
  });

  it("已有文案时报价不包含文案生成模块（rewrite 步将跳过）", async () => {
    vi.mocked(billingApi.pricePreview).mockResolvedValue(composeQuote);
    vi.mocked(pipelineApi.create).mockResolvedValue([makeTask()]);
    vi.mocked(pipelineApi.get).mockResolvedValue(makeTask());
    renderStep("compose");

    await screen.findByText("任务详情桩：task-compose-1");
    const request = vi.mocked(billingApi.pricePreview).mock.calls[0]?.[0];
    expect(
      request?.items.map((item: { module: string }) => item.module),
    ).not.toContain("script_generation");
  });

  it("积分余额不足时显示启动失败并可重试，不创建任务", async () => {
    vi.mocked(billingApi.pricePreview).mockResolvedValue({
      ...composeQuote,
      availablePoints: 10,
    } as PricePreview);
    renderStep("compose");

    await screen.findByText("积分余额不足，请先兑换积分包或续费套餐");
    expect(screen.getByText("合成启动失败")).toBeInTheDocument();
    expect(pipelineApi.create).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "重试合成" })).toBeEnabled();
  });

  it("未生成成片时发布步给出警告并禁用提交", () => {
    renderStep("publish");

    expect(
      screen.getByText(
        "成片尚未生成，请先回到「视频合成」步完成合成后再配置发布。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "完成，稍后手动发布" }),
    ).toBeDisabled();
  });

  it("直达合成步但缺少文案时只引导补齐，不自动报价扣费", async () => {
    renderStep("compose", { bare: true });

    await screen.findByText("缺少口播文案，请先完成「文案二创」步");
    expect(screen.getByText("暂无法开始合成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "去补齐 →" })).toBeEnabled();
    expect(billingApi.pricePreview).not.toHaveBeenCalled();
    expect(pipelineApi.create).not.toHaveBeenCalled();
  });
});
