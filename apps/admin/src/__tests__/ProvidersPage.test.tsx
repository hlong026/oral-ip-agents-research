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
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
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
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}
