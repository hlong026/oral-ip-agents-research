import { billingApi, catalogApi } from "@oral/api-client";
import type { BillingUnit } from "@oral/types";

export interface OperationUsage {
  seconds?: number;
  characters?: number;
  tokens?: number;
  images?: number;
  assets?: number;
}

export function textOperationUsage(text: string): OperationUsage {
  const characters = Array.from(text).length;
  return {
    characters,
    tokens: Math.max(1, Math.ceil(characters / 2)),
    assets: 1,
  };
}

export async function mediaDurationSeconds(file: File): Promise<number> {
  const url = URL.createObjectURL(file);
  const media = document.createElement(
    file.type.startsWith("audio/") ? "audio" : "video",
  );
  media.preload = "metadata";
  try {
    return await new Promise<number>((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error("读取媒体时长超时")),
        10_000,
      );
      media.onloadedmetadata = () => {
        window.clearTimeout(timeout);
        if (!Number.isFinite(media.duration) || media.duration <= 0) {
          reject(new Error("无法读取媒体时长"));
          return;
        }
        resolve(Math.max(1, Math.ceil(media.duration)));
      };
      media.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error("无法读取媒体时长"));
      };
      media.src = url;
    });
  } finally {
    media.removeAttribute("src");
    URL.revokeObjectURL(url);
  }
}

export function operationQuantity(
  unit: BillingUnit,
  usage: OperationUsage,
): number {
  const values: Record<BillingUnit, number> = {
    per_action: 1,
    per_minute: usage.seconds ?? 0,
    per_second: usage.seconds ?? 0,
    per_1k_chars: usage.characters ?? 0,
    per_1k_tokens: usage.tokens ?? 0,
    per_image: usage.images ?? 1,
    per_asset: usage.assets ?? 1,
  };
  return Math.max(1, Math.ceil(values[unit]));
}

/** 获取当前价目并返回只可使用一次的报价 ID；费用信息由页面内联展示。 */
export async function confirmMeteredOperation(
  module: string,
  label: string,
  usage: OperationUsage,
): Promise<string> {
  const catalog = await catalogApi.modulePrices();
  const price = catalog.items.find((item) => item.module === module);
  if (!price) throw new Error(`${label}当前未配置积分价格，暂不可用`);

  const quote = await billingApi.pricePreview({
    items: [
      {
        module,
        quantity: operationQuantity(price.billingUnit, usage),
      },
    ],
  });
  return quote.quoteId;
}
