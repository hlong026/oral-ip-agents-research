import { expect, test } from "@playwright/test";

const CONTAINER_API = "http://127.0.0.1:8000";

test("容器后端及依赖均已就绪", async ({ request }) => {
  const response = await request.get(`${CONTAINER_API}/readyz`);

  expect(response.ok()).toBeTruthy();
  await expect(response.json()).resolves.toEqual({
    ok: true,
    database: true,
    redis: true,
    storage: true,
  });
});

test("Web 前端通过 Vite proxy 读取容器 API", async ({ request }) => {
  const response = await request.get(
    "http://127.0.0.1:5173/api/v1/catalog/plans",
  );

  expect(response.ok()).toBeTruthy();
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(Array.isArray(await response.json())).toBeTruthy();
});

test("Web 前端通过 Vite proxy 分段读取 MinIO 媒体", async ({ request }) => {
  const response = await request.get(
    "http://127.0.0.1:5173/media/e2e/probe.txt",
    {
      headers: { Range: "bytes=5-13" },
    },
  );

  expect(response.status()).toBe(206);
  expect(response.headers()["accept-ranges"]).toBe("bytes");
  expect(response.headers()["content-range"]).toBe("bytes 5-13/20");
  expect(await response.text()).toBe("container");
});
