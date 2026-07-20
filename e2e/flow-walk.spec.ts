import { expect, test, type Page } from "@playwright/test";

/** 13 个流程页（settings/account 不在动线内） */
const FLOW_PAGES = [
  "/",
  "/create",
  "/scripts",
  "/tasks",
  "/assets/personas",
  "/assets/voices",
  "/assets/avatars",
  "/assets/materials",
  "/assets/templates",
  "/editor",
  "/publish/jobs",
  "/publish/accounts",
  "/analytics",
];

const FLOW_STEP_LABELS = ["链接/选题", "文案", "声音", "数字人", "合成", "发布"];

/** 经真实后端注册并把 refreshToken 注入 localStorage（oral_rt） */
async function loginViaApi(page: Page, request: import("@playwright/test").APIRequestContext) {
  const phone = `139${Math.floor(10000000 + Math.random() * 90000000)}`;
  const res = await request.post("http://localhost:8000/api/v1/auth/register", {
    data: { phone, password: "E2e@12345", nickname: "E2E 走查" },
  });
  expect(res.ok()).toBeTruthy();
  const tokens = await res.json();
  await page.addInitScript((rt) => localStorage.setItem("oral_rt", rt), tokens.refreshToken as string);
}

test.beforeEach(async ({ page, request }) => {
  await loginViaApi(page, request);
});

test("登录页渲染（公开路由）", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText(/登录|注册/).first()).toBeVisible();
});

test("13 个流程页均可达且 flow-bar 六步可见", async ({ page }) => {
  for (const path of FLOW_PAGES) {
    await page.goto(path);
    // 未跳回登录页
    await expect(page).not.toHaveURL(/\/login/);
    // flow-bar 六步动线齐全
    const bar = page.getByTestId("flow-bar");
    await expect(bar).toBeVisible();
    for (const label of FLOW_STEP_LABELS) {
      await expect(bar.getByRole("link", { name: new RegExp(label) })).toBeVisible();
    }
  }
});

test("settings/account 不显示 flow-bar", async ({ page }) => {
  for (const path of ["/settings", "/account"]) {
    await page.goto(path);
    await expect(page.getByTestId("flow-bar")).toHaveCount(0);
  }
});

test("一键成片 7 步向导：step 参数驱动 flow-bar 当前步高亮", async ({ page }) => {
  const cases: Array<{ step: string; active: string }> = [
    { step: "link", active: "链接/选题" },
    { step: "script", active: "文案" },
    { step: "voice", active: "声音" },
    { step: "avatar", active: "数字人" },
    { step: "compose", active: "合成" },
    { step: "edit", active: "合成" },
    { step: "publish", active: "发布" },
  ];
  for (const c of cases) {
    await page.goto(`/create?step=${c.step}`);
    const bar = page.getByTestId("flow-bar");
    const activeLink = bar.getByRole("link", { name: new RegExp(c.active) });
    await expect(activeLink).toBeVisible();
    await expect(activeLink).toHaveClass(/bg-brand-grad/);
  }
});
