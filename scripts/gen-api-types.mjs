#!/usr/bin/env node
/**
 * OpenAPI → TS 类型生成（契约同源，06 文档 §8 工程规范）
 *
 * 用法：
 *   node scripts/gen-api-types.mjs                 # 从运行中的后端拉取 openapi.json 生成
 *   node scripts/gen-api-types.mjs --file <path>   # 从本地 openapi 快照生成
 *   node scripts/gen-api-types.mjs --check         # CI 零漂移校验：与现有产物不一致则退出码 1
 *
 * 产物：packages/types/src/generated.ts（每次后端发版重新生成，禁止手改）
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_FILE = resolve(ROOT, "packages/types/src/generated.ts");
const SNAPSHOT = resolve(ROOT, "server/openapi.snapshot.json");
const DEFAULT_URL = process.env.ORAL_OPENAPI_URL ?? "http://127.0.0.1:8000/openapi.json";

const args = process.argv.slice(2);
const CHECK = args.includes("--check");
const fileIdx = args.indexOf("--file");
const FILE = fileIdx >= 0 ? resolve(args[fileIdx + 1]) : null;
const urlIdx = args.indexOf("--url");
const URL_ = urlIdx >= 0 ? args[urlIdx + 1] : DEFAULT_URL;

async function loadSpec() {
  if (FILE) {
    return JSON.parse(readFileSync(FILE, "utf-8"));
  }
  try {
    const res = await fetch(URL_);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    if (existsSync(SNAPSHOT)) {
      console.warn(`[gen-api] ${URL_} 不可达（${e.message}），回退本地快照 ${SNAPSHOT}`);
      return JSON.parse(readFileSync(SNAPSHOT, "utf-8"));
    }
    throw e;
  }
}

function refName(ref) {
  const raw = ref.split("/").pop();
  // 清洗为合法 TS 标识符
  return raw.replace(/[^A-Za-z0-9_]/g, "_");
}

function tsType(schema, ctx) {
  if (!schema || typeof schema !== "object") return "unknown";
  if (schema.$ref) return refName(schema.$ref);
  if (Array.isArray(schema.anyOf)) {
    const parts = schema.anyOf.map((s) => tsType(s, ctx));
    return [...new Set(parts)].join(" | ");
  }
  if (Array.isArray(schema.oneOf)) {
    const parts = schema.oneOf.map((s) => tsType(s, ctx));
    return [...new Set(parts)].join(" | ");
  }
  if (Array.isArray(schema.allOf) && schema.allOf.length === 1) return tsType(schema.allOf[0], ctx);
  if (Array.isArray(schema.enum)) {
    return schema.enum.map((v) => JSON.stringify(v)).join(" | ");
  }
  switch (schema.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "null":
      return "null";
    case "array":
      return `${wrap(tsType(schema.items, ctx))}[]`;
    case "object": {
      if (schema.properties) return inlineObject(schema, ctx);
      if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
        return `Record<string, ${tsType(schema.additionalProperties, ctx)}>`;
      }
      return "Record<string, unknown>";
    }
    default:
      return "unknown";
  }
}

function wrap(t) {
  return t.includes(" | ") ? `(${t})` : t;
}

function inlineObject(schema, ctx) {
  const required = new Set(schema.required ?? []);
  const props = Object.entries(schema.properties ?? {}).map(([name, prop]) => {
    const opt = required.has(name) ? "" : "?";
    return `${JSON.stringify(name)}${opt}: ${tsType(prop, ctx)}`;
  });
  return `{ ${props.join("; ")} }`;
}

function genInterface(name, schema) {
  if (Array.isArray(schema.enum)) {
    return `export type ${name} = ${schema.enum.map((v) => JSON.stringify(v)).join(" | ")};`;
  }
  if (schema.type === "object" && schema.properties) {
    const required = new Set(schema.required ?? []);
    const lines = Object.entries(schema.properties).map(([prop, propSchema]) => {
      const opt = required.has(prop) ? "" : "?";
      const doc = propSchema.description ? `  /** ${propSchema.description} */\n` : "";
      return `${doc}  ${JSON.stringify(prop)}${opt}: ${tsType(propSchema)};`;
    });
    return `export interface ${name} {\n${lines.join("\n")}\n}`;
  }
  return `export type ${name} = ${tsType(schema)};`;
}

function generate(spec) {
  const schemas = spec?.components?.schemas ?? {};
  const names = Object.keys(schemas).filter((n) => !["ValidationError", "HTTPValidationError"].includes(n));
  const blocks = names.map((n) => genInterface(refName(n), { ...schemas[n], $ref: undefined }));
  const version = spec?.info?.version ?? "unknown";
  return `/**
 * 由后端 OpenAPI 契约自动生成（scripts/gen-api-types.mjs）
 * API 版本：${version} · 生成时间：${new Date().toISOString()}
 * 禁止手改：每次后端发版执行 pnpm gen:api 重新生成，CI 以 --check 校验零漂移。
 */

${blocks.join("\n\n")}
`;
}

const spec = await loadSpec();
const output = generate(spec);

if (CHECK) {
  const current = existsSync(OUT_FILE) ? readFileSync(OUT_FILE, "utf-8") : "";
  // 漂移判定忽略生成时间行
  const strip = (s) => s.replace(/ · 生成时间：.*\n/, "\n");
  if (strip(current) !== strip(output)) {
    console.error("[gen-api] 契约漂移：packages/types/src/generated.ts 与后端 OpenAPI 不一致，请执行 pnpm gen:api");
    process.exit(1);
  }
  console.log("[gen-api] 契约零漂移 ✓");
} else {
  writeFileSync(OUT_FILE, output);
  console.log(`[gen-api] 已生成 ${OUT_FILE}（${Object.keys(spec.components?.schemas ?? {}).length} 个 schema）`);
}
