import { describe, expect, it } from "vitest";

import { buildPricePreviewRequest } from "../pages/CreatePage";

describe("创建任务积分报价", () => {
  it("已有文案时按文案时长和字符数生成后续模块用量", () => {
    const request = buildPricePreviewRequest(
      {
        sourceUrl: "https://example.com/video",
        topic: "",
        scriptText: "一".repeat(1000),
        count: 2,
      },
      [
        { module: "asr", billingUnit: "per_minute", unitSize: 60 },
        {
          module: "script_generation",
          billingUnit: "per_1k_tokens",
          unitSize: 1000,
        },
        { module: "tts", billingUnit: "per_1k_chars", unitSize: 1000 },
        { module: "digital_human", billingUnit: "per_second", unitSize: 1 },
        { module: "hd_export", billingUnit: "per_action", unitSize: 1 },
      ],
    );

    expect(request.items).toEqual([
      { module: "script_generation", quantity: 500 },
      { module: "tts", quantity: 1000 },
      { module: "digital_human", quantity: 280 },
      { module: "hd_export", quantity: 1 },
    ]);
  });

  it("不会向报价接口发送未发布价格的模块", () => {
    const request = buildPricePreviewRequest(
      { sourceUrl: "", topic: "选题", scriptText: "", count: 1 },
      [
        { module: "topic_generation", billingUnit: "per_action", unitSize: 1 },
        { module: "tts", billingUnit: "per_1k_chars", unitSize: 1000 },
      ],
    );

    expect(request.items.map((item) => item.module)).toEqual([
      "topic_generation",
      "tts",
    ]);
  });

  it("空文案按人设目标时长估算而不是按一秒估算", () => {
    const request = buildPricePreviewRequest(
      { sourceUrl: "", topic: "新选题", scriptText: "", count: 1 },
      [
        { module: "tts", billingUnit: "per_1k_chars", unitSize: 1000 },
        { module: "digital_human", billingUnit: "per_second", unitSize: 1 },
      ],
      90,
    );

    expect(request.items).toEqual([
      { module: "tts", quantity: 322 },
      { module: "digital_human", quantity: 90 },
    ]);
  });
});
