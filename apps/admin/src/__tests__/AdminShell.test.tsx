import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ADMIN_TOKEN_KEY } from "../lib/adminHttp";
import App from "../App";

describe("admin app routing", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("redirects anonymous visitors to admin login", () => {
    render(
      <MemoryRouter initialEntries={["/plans"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "管理员登录" }),
    ).toBeInTheDocument();
  });

  it("shows protected navigation after admin token exists", () => {
    localStorage.setItem(ADMIN_TOKEN_KEY, "test-token");

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("管理控制台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "我的创作空间" })).toHaveAttribute(
      "href",
      "http://localhost:5173",
    );
    expect(screen.getByRole("link", { name: "套餐 SKU" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "用户管理" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "成本与审计" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "私信安全" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "运营总览" }),
    ).toBeInTheDocument();
  });
});
