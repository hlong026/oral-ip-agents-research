import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import VoicesPage from "../pages/VoicesPage";

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  status: vi.fn(),
  confirm: vi.fn(),
  reject: vi.fn(),
}));

vi.mock("@oral/api-client", () => ({
  voiceApi: {
    list: apiMocks.list,
    status: apiMocks.status,
    confirm: apiMocks.confirm,
    reject: apiMocks.reject,
  },
  personaApi: { update: vi.fn() },
  HttpError: class HttpError extends Error {
    status = 400;
    body = { code: "ERROR", message: this.message };
  },
}));

vi.mock("@oral/stores", () => ({
  useIp: () => ({ current: null, personas: [], load: vi.fn() }),
}));

const voice = (id: string, name: string, status: string, demoUrl: string) => ({
  id,
  name,
  source: "clone" as const,
  gender: "unknown",
  emotion: "neutral",
  sampleUrl: null,
  demoUrl,
  status,
  createdAt: "2026-07-21T00:00:00Z",
});

describe("VoicesPage 克隆确认闭环", () => {
  it("轮询训练任务并允许试听、确认或拒绝", async () => {
    apiMocks.list.mockResolvedValue([
      voice("voice-training", "训练完成声", "training", ""),
      voice("voice-reject", "待拒绝声", "pending_confirm", "/media/reject.mp3"),
    ]);
    apiMocks.status.mockResolvedValue({
      id: "voice-training",
      status: "pending_confirm",
      demoUrl: "/media/demo.mp3",
    });
    apiMocks.confirm.mockResolvedValue(
      voice("voice-training", "训练完成声", "ready", "/media/demo.mp3"),
    );
    apiMocks.reject.mockResolvedValue(
      voice("voice-reject", "待拒绝声", "rejected", "/media/reject.mp3"),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <VoicesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const trainingCard = (await screen.findByText("训练完成声")).closest(
      ".card-hover",
    ) as HTMLElement | null;
    expect(trainingCard).not.toBeNull();
    expect(apiMocks.status).toHaveBeenCalledWith("voice-training");
    expect(within(trainingCard!).getByText("待试听确认")).toBeInTheDocument();
    expect(
      trainingCard!.querySelector('audio[src="/media/demo.mp3"]'),
    ).toBeInTheDocument();

    fireEvent.click(
      within(trainingCard!).getByRole("button", { name: "确认使用" }),
    );
    expect(apiMocks.confirm).toHaveBeenCalledWith("voice-training");

    const rejectCard = screen
      .getByText("待拒绝声")
      .closest(".card-hover") as HTMLElement;
    fireEvent.click(
      within(rejectCard!).getByRole("button", { name: "拒绝结果" }),
    );
    expect(apiMocks.reject).toHaveBeenCalledWith("voice-reject");
    expect(container.querySelectorAll("audio").length).toBeGreaterThan(0);
  });
});
