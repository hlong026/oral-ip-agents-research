import { contentApi } from "@oral/api-client";
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
    vi.mocked(confirmMeteredOperation).mockReset();
    vi.mocked(mediaDurationSeconds).mockReset();
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
});
