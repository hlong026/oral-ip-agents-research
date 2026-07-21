import { describe, expect, it } from "vitest";
import { operationQuantity, textOperationUsage } from "../lib/meteredOperation";

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
});
