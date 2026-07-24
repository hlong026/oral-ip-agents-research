import type { User } from "@oral/types";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  restoreSession: vi.fn(),
  me: vi.fn(),
}));

vi.mock("@oral/api-client", () => ({
  authApi: {
    login: vi.fn(),
    me: apiMocks.me,
  },
  billingApi: { quota: vi.fn() },
  personaApi: { list: vi.fn(), activate: vi.fn() },
  restoreSession: apiMocks.restoreSession,
  setTokens: vi.fn(),
}));

import { useSession } from "@oral/stores";

describe("会话启动恢复", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSession.setState({ user: null, ready: false });
  });

  it("先刷新访问令牌，再读取当前用户", async () => {
    const user = { id: "user-1" } as User;
    apiMocks.restoreSession.mockResolvedValue(true);
    apiMocks.me.mockResolvedValue(user);

    await useSession.getState().bootstrap();

    expect(apiMocks.restoreSession).toHaveBeenCalledOnce();
    expect(apiMocks.me).toHaveBeenCalledOnce();
    expect(apiMocks.restoreSession.mock.invocationCallOrder[0]).toBeLessThan(
      apiMocks.me.mock.invocationCallOrder[0]!,
    );
    expect(useSession.getState()).toMatchObject({ user, ready: true });
  });

  it("刷新令牌失败时直接结束启动，不再发送必然失败的用户请求", async () => {
    apiMocks.restoreSession.mockResolvedValue(false);

    await useSession.getState().bootstrap();

    expect(apiMocks.me).not.toHaveBeenCalled();
    expect(useSession.getState()).toMatchObject({ user: null, ready: true });
  });
});
