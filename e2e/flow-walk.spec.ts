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

const FLOW_STEP_LABELS = [
  "链接/选题",
  "文案",
  "声音",
  "数字人",
  "合成",
  "发布",
];

const API_BASE = "http://127.0.0.1:8000/api";
const E2E_ADMIN_PHONE = "18800000000";
const E2E_ADMIN_PASSWORD = "E2eAdmin@12345";

/** 管理员生成真实 SKU/激活码，再走 Activation 开户。 */
async function loginViaApi(
  page: Page,
  request: import("@playwright/test").APIRequestContext,
) {
  const adminLogin = await request.post(`${API_BASE}/admin/v1/auth/login`, {
    data: {
      phone: E2E_ADMIN_PHONE,
      password: E2E_ADMIN_PASSWORD,
      deviceId: "e2e-admin",
    },
  });
  expect(adminLogin.ok()).toBeTruthy();
  const adminTokens = await adminLogin.json();
  const adminHeaders = {
    Authorization: `Bearer ${adminTokens.accessToken as string}`,
  };
  const unique = `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;

  const planResponse = await request.post(`${API_BASE}/admin/v1/plans`, {
    headers: adminHeaders,
    data: {
      code: `E2E_${unique.replaceAll("-", "_").toUpperCase()}`,
      name: "E2E 激活套餐",
      subtitle: "Playwright",
      description: "端到端开户专用",
      badge: "测试",
      skuType: "annual_bundle",
      audience: "public",
      durationDays: 30,
      monthlyPoints: 100,
      oneTimePoints: 0,
      listPriceCents: 100,
      displayPriceCents: 100,
      entitlements: [],
      maxConcurrency: 1,
      maxResolution: "1080p",
      purchaseInstructions: "E2E",
    },
  });
  expect(planResponse.ok()).toBeTruthy();
  const plan = await planResponse.json();
  const published = await request.post(
    `${API_BASE}/admin/v1/plans/${plan.id as string}/publish`,
    {
      headers: adminHeaders,
    },
  );
  expect(published.ok()).toBeTruthy();

  const batchResponse = await request.post(
    `${API_BASE}/admin/v1/activation/batches`,
    {
      headers: adminHeaders,
      data: {
        name: `E2E-${unique}`,
        skuVersionId: plan.id,
        count: 1,
        channel: "playwright",
      },
    },
  );
  expect(batchResponse.ok()).toBeTruthy();
  const batch = await batchResponse.json();
  const phone = `139${Math.floor(10000000 + Math.random() * 90000000)}`;
  const res = await request.post(`${API_BASE}/v1/activation/activate`, {
    data: {
      code: batch.codes[0],
      phone,
      password: "E2e@12345",
      nickname: "E2E 走查",
      deviceFingerprint: `playwright-${unique}`,
    },
  });
  expect(res.ok()).toBeTruthy();
  const tokens = await res.json();
  await page.addInitScript((rt) => {
    if (!localStorage.getItem("oral_rt")) localStorage.setItem("oral_rt", rt);
  }, tokens.refreshToken as string);
}

test.beforeEach(async ({ page, request }) => {
  await loginViaApi(page, request);
});

test("登录页渲染（公开路由）", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText(/登录|激活码注册/).first()).toBeVisible();
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
      await expect(
        bar.getByRole("link", { name: new RegExp(label) }),
      ).toBeVisible();
    }
  }
});

test("套餐/账号页不显示 flow-bar", async ({ page }) => {
  for (const path of ["/pricing", "/account"]) {
    await page.goto(path);
    await expect(page.getByTestId("flow-bar")).toHaveCount(0);
  }
});

test("一键成片 7 步向导：step 参数驱动 flow-bar 当前步高亮", async ({
  page,
}) => {
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
