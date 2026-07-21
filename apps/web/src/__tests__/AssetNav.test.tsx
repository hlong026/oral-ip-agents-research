import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AssetNav from "../components/AssetNav";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AssetNav />
    </MemoryRouter>,
  );
}

describe("AssetNav 资产二级导航", () => {
  it("渲染 3 个资产页签（模板/素材库为 V1.1 未上架，入口隐藏）", () => {
    renderAt("/assets/voices");
    for (const label of ["IP 档案", "数字人", "声音"]) {
      expect(screen.getByText(label, { exact: false })).toBeInTheDocument();
    }
    // V1.1 未上架页签不出现
    expect(
      screen.queryByText("模板", { exact: false }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("素材库", { exact: false }),
    ).not.toBeInTheDocument();
  });

  it("当前路由对应页签高亮", () => {
    renderAt("/assets/voices");
    const active = screen.getByText("声音", { exact: false }).closest("a");
    expect(active?.className).toContain("bg-brand-from/15");
    const inactive = screen.getByText("IP 档案", { exact: false }).closest("a");
    expect(inactive?.className).not.toContain("bg-brand-from/15");
  });
});
