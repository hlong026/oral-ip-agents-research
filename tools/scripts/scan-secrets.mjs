#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const patterns = [
  ["private key", /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/g],
  ["AWS access key", /AKIA[0-9A-Z]{16}/g],
  ["GitHub token", /gh[pousr]_[A-Za-z0-9]{36,}/g],
  ["OpenAI key", /sk-(?:proj-)?[A-Za-z0-9_-]{20,}/g],
  ["Google API key", /AIza[0-9A-Za-z_-]{35}/g],
  ["Slack token", /xox[baprs]-[0-9A-Za-z-]{20,}/g],
  ["Stripe live key", /(?:sk|rk)_live_[0-9A-Za-z]{20,}/g],
  ["npm token", /npm_[0-9A-Za-z]{36}/g],
];

const files = execFileSync("git", [
  "ls-files",
  "--cached",
  "--others",
  "--exclude-standard",
  "-z",
])
  .toString("utf8")
  .split("\0")
  .filter(Boolean);
const findings = [];

for (const file of files) {
  if (file === "tools/scripts/scan-secrets.mjs") continue;
  if (!existsSync(file)) continue;
  const data = readFileSync(file);
  if (data.includes(0)) continue;
  const content = data.toString("utf8");
  for (const [label, pattern] of patterns) {
    pattern.lastIndex = 0;
    for (const match of content.matchAll(pattern)) {
      const line = content.slice(0, match.index).split("\n").length;
      findings.push(`${file}:${line} (${label})`);
    }
  }
}

if (findings.length > 0) {
  console.error("检测到疑似真实凭据（仅显示位置，不输出内容）：");
  for (const finding of findings) console.error(`- ${finding}`);
  process.exit(1);
}

console.log(`秘密扫描通过：已检查 ${files.length} 个受版本控制文件`);
