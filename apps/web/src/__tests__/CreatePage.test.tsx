import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CreatePage from "../pages/CreatePage";

vi.mock("@oral/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oral/api-client")>();
  return {
    ...actual,
    catalogApi: {
      ...actual.catalogApi,
      modulePrices: vi.fn().mockResolvedValue({ items: [] }),
    },
  };
});

describe("CreatePage 来源模式切换", () => {
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
});
