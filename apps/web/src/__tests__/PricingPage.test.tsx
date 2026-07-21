import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PricingPage from "../pages/PricingPage";

const apiMocks = vi.hoisted(() => ({
  plans: vi.fn(),
  modulePrices: vi.fn(),
  redeem: vi.fn(),
  subscription: vi.fn(),
}));

vi.mock("@oral/api-client", () => ({
  catalogApi: {
    plans: apiMocks.plans,
    modulePrices: apiMocks.modulePrices,
  },
  activationApi: {
    redeem: apiMocks.redeem,
    subscription: apiMocks.subscription,
  },
  HttpError: class HttpError extends Error {
    status = 400;
    body = { code: "ERROR", message: this.message };
  },
}));

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("PricingPage 套餐与积分", () => {
  it("展示公开套餐和模块积分价格，隐藏内部套餐", async () => {
    apiMocks.plans.mockResolvedValue([
      {
        code: "ANNUAL_STANDARD_2026",
        version: 1,
        skuType: "annual_bundle",
        audience: "public",
        name: "标准包年",
        subtitle: "适合稳定内容生产",
        description: "包年权益",
        badge: "推荐",
        sortOrder: 1,
        durationDays: 365,
        monthlyPoints: 3000,
        oneTimePoints: 0,
        listPriceCents: 398000,
        displayPriceCents: 298000,
        entitlements: ["数字人视频", "声音克隆"],
        maxConcurrency: 2,
        maxResolution: "1080p",
        purchaseInstructions: "联系管理员获取激活码",
        publishedAt: "2026-08-01T00:00:00Z",
        retiredAt: null,
      },
      {
        code: "INTERNAL_2026",
        version: 1,
        skuType: "internal_annual",
        audience: "internal",
        name: "内部员工包",
        sortOrder: 2,
        durationDays: 365,
        monthlyPoints: 9999,
        oneTimePoints: 0,
        entitlements: [],
      },
    ]);
    apiMocks.modulePrices.mockResolvedValue({
      version: "2026-08-v1",
      updatedAt: "2026-08-01T00:00:00Z",
      items: [
        {
          module: "tts",
          displayName: "TTS 文本生成语音",
          billingUnit: "per_1k_chars",
          unitSize: 1000,
          pointsPerUnit: 20,
          minimumPoints: 20,
          enabled: true,
          publicDescription: "不足 1000 字按最低消费",
          version: "2026-08-v1",
          effectiveAt: "2026-08-01T00:00:00Z",
        },
      ],
    });
    apiMocks.subscription.mockResolvedValue({
      planType: "annual_bundle",
      planSkuCode: "ANNUAL_STANDARD_2026",
      planExpiresAt: "2027-08-01T00:00:00Z",
      activatedAt: "2026-08-01T00:00:00Z",
      quotaBalance: 3000,
    });

    renderWithQueryClient(<PricingPage />);

    expect(await screen.findByText("标准包年")).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, node) => node?.textContent === "积分：每月 3,000 积分",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("TTS 文本生成语音")).toBeInTheDocument();
    expect(screen.getByText("每 1000 字")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, node) => node?.textContent === "20 点").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("内部员工包")).not.toBeInTheDocument();
    expect(screen.getByText("当前套餐")).toBeInTheDocument();
  });
});
