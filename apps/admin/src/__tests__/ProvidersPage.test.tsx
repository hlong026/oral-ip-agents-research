import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProvidersPage from "../pages/ProvidersPage";

describe("provider configuration page", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads and saves both Douyidou credential fields", async () => {
    const savedSettings: Array<Record<string, string>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/providers/status")) {
          return jsonResponse({
            items: [
              {
                provider: "douyidou",
                enabled: false,
                configured: true,
                missingFields: [],
                probeMode: "sample",
              },
            ],
          });
        }
        if (init?.method === "PUT") {
          const body = JSON.parse(String(init.body)) as {
            settings: Record<string, string>;
          };
          savedSettings.push(body.settings);
          return jsonResponse({ settings: body.settings });
        }
        return jsonResponse({
          settings: {
            douyidou_app_id: "existing-app-id",
            douyidou_app_secret: "configured",
            douyidou_base_url: "https://gateway.diadi.cn",
            douyidou_enabled: "false",
          },
        });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ProvidersPage />
      </QueryClientProvider>,
    );

    const heading = await screen.findByRole("heading", {
      name: "Douyidou 视频解析",
    });
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const form = within(section as HTMLElement);
    const appId = form.getByLabelText("App ID");
    await waitFor(() => {
      expect(appId).toHaveValue("existing-app-id");
      expect(
        form.getByLabelText("App Secret（已配置，留空不覆盖）"),
      ).toHaveValue("");
    });
    expect(form.queryByLabelText("优先级")).not.toBeInTheDocument();

    fireEvent.change(appId, { target: { value: "new-app-id" } });
    fireEvent.change(form.getByLabelText("App Secret（已配置，留空不覆盖）"), {
      target: { value: "new-app-secret" },
    });
    fireEvent.click(form.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(savedSettings).toContainEqual(
        expect.objectContaining({
          douyidou_app_id: "new-app-id",
          douyidou_app_secret: "new-app-secret",
        }),
      );
    });
  });

  it("loads and saves the DashScope routing parameters", async () => {
    const savedSettings: Array<Record<string, string>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/providers/status")) {
          return jsonResponse({
            items: [
              {
                provider: "dashscope_asr",
                enabled: false,
                configured: true,
                missingFields: [],
                probeMode: "credential",
              },
            ],
          });
        }
        if (init?.method === "PUT") {
          const body = JSON.parse(String(init.body)) as {
            settings: Record<string, string>;
          };
          savedSettings.push(body.settings);
          return jsonResponse({ settings: body.settings });
        }
        return jsonResponse({
          settings: {
            dashscope_api_key: "configured",
            dashscope_workspace_id: "workspace-old",
            dashscope_region: "cn-beijing",
            asr_model: "fun-asr",
            asr_flash_model: "fun-asr-flash-old",
            asr_flash_threshold_sec: "300",
            dashscope_enabled: "false",
          },
        });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ProvidersPage />
      </QueryClientProvider>,
    );

    const heading = await screen.findByRole("heading", {
      name: "DashScope ASR",
    });
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const form = within(section as HTMLElement);
    await waitFor(() => {
      expect(form.getByLabelText("Workspace ID（可选）")).toHaveValue(
        "workspace-old",
      );
    });
    expect(form.queryByLabelText("Base URL")).not.toBeInTheDocument();

    fireEvent.change(form.getByLabelText("Workspace ID（可选）"), {
      target: { value: "workspace-new" },
    });
    fireEvent.change(form.getByLabelText("地域"), {
      target: { value: "ap-southeast-1" },
    });
    fireEvent.change(form.getByLabelText("异步模型"), {
      target: { value: "fun-asr-new" },
    });
    fireEvent.change(form.getByLabelText("短音频同步模型"), {
      target: { value: "fun-asr-flash-new" },
    });
    fireEvent.change(form.getByLabelText("同步分流阈值（秒）"), {
      target: { value: "180" },
    });
    fireEvent.click(form.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(savedSettings).toContainEqual(
        expect.objectContaining({
          dashscope_workspace_id: "workspace-new",
          dashscope_region: "ap-southeast-1",
          asr_model: "fun-asr-new",
          asr_flash_model: "fun-asr-flash-new",
          asr_flash_threshold_sec: "180",
        }),
      );
    });
  });

  it("shows missing fields and reports a successful credential probe", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/providers/status")) {
          return jsonResponse({
            items: [
              {
                provider: "deepseek",
                enabled: true,
                configured: false,
                missingFields: ["API Key"],
                probeMode: "credential",
              },
              {
                provider: "hifly",
                enabled: true,
                configured: true,
                missingFields: [],
                probeMode: "credential",
              },
            ],
          });
        }
        if (
          String(input).endsWith("/providers/hifly/probe") &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            provider: "hifly",
            status: "verified",
            message: "凭据有效，账户连接正常",
            details: { credits: 100 },
          });
        }
        return jsonResponse({
          settings: {
            deepseek_enabled: "true",
            feiying_enabled: "true",
            feiying_api_key: "configured",
            feiying_base_url: "https://hfw-api.hifly.cc",
          },
        });
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ProvidersPage />
      </QueryClientProvider>,
    );

    const deepseek = (
      await screen.findByRole("heading", { name: "DeepSeek / LLM" })
    ).closest("section") as HTMLElement;
    expect(await within(deepseek).findByText("缺少：API Key")).toBeVisible();

    const hifly = screen
      .getByRole("heading", { name: "HiFly 数字人/声音" })
      .closest("section") as HTMLElement;
    fireEvent.click(within(hifly).getByRole("button", { name: "测试连接" }));

    expect(
      await within(hifly).findByText("凭据有效，账户连接正常"),
    ).toBeVisible();
  });
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}
