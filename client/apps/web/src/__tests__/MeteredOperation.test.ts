import { billingApi, catalogApi } from "@oral/api-client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  confirmMeteredOperation,
  operationQuantity,
  textOperationUsage,
} from "../lib/meteredOperation";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("operationQuantity", () => {
  const usage = {
    seconds: 125,
    characters: 1800,
    tokens: 900,
    images: 3,
    assets: 2,
  };

  it("uses raw usage matching the configured billing unit", () => {
    expect(operationQuantity("per_action", usage)).toBe(1);
    expect(operationQuantity("per_minute", usage)).toBe(125);
    expect(operationQuantity("per_second", usage)).toBe(125);
    expect(operationQuantity("per_1k_chars", usage)).toBe(1800);
    expect(operationQuantity("per_1k_tokens", usage)).toBe(900);
    expect(operationQuantity("per_image", usage)).toBe(3);
    expect(operationQuantity("per_asset", usage)).toBe(2);
  });

  it("never submits a zero quantity", () => {
    expect(operationQuantity("per_1k_chars", { characters: 0 })).toBe(1);
  });

  it("counts Unicode characters consistently with the backend", () => {
    expect(textOperationUsage("口播😀")).toEqual({
      characters: 3,
      tokens: 2,
      assets: 1,
    });
  });

  it("creates a one-time quote without showing a deduction confirmation popup", async () => {
    vi.spyOn(catalogApi, "modulePrices").mockResolvedValue({
      version: "test",
      items: [
        {
          module: "asr",
          displayName: "语音转写",
          billingUnit: "per_action",
          unitSize: 1,
          pointsPerUnit: 2,
          minimumPoints: 2,
        },
      ],
    });
    vi.spyOn(billingApi, "pricePreview").mockResolvedValue({
      quoteId: "quote-test",
      priceVersion: "test",
      estimatedPoints: 2,
      availablePoints: 100,
      expiresAt: "2026-07-24T12:00:00Z",
      items: [],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    await expect(
      confirmMeteredOperation("asr", "上传转写", {
        seconds: 60,
        assets: 1,
      }),
    ).resolves.toBe("quote-test");
    expect(confirm).not.toHaveBeenCalled();
  });
});
