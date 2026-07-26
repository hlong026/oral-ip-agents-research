import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import FlowBar from "../shell/FlowBar";

const STEP_LABELS = ["链接/选题", "文案", "声音", "数字人", "合成", "发布"];

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <FlowBar />
    </MemoryRouter>,
  );
}

function linkOf(label: string): HTMLAnchorElement {
  return screen.getByText(label).closest("a") as HTMLAnchorElement;
}

/** 已完成步骤以 Check SVG 图标标记（FlowBar 内仅完成态渲染 svg） */
function checkIcons(container: HTMLElement) {
  return container.querySelectorAll("svg");
}

describe("FlowBar 全局六步动线", () => {
  it("渲染全部六步", () => {
    renderAt("/");
    for (const label of STEP_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("任务中心页：合成步当前高亮，前四步标记完成", () => {
    const { container } = renderAt("/tasks");
    expect(linkOf("合成").className).toContain("bg-brand-grad");
    // 前四步显示 ✓ 图标
    expect(checkIcons(container)).toHaveLength(4);
  });

  it("一键成片向导 ?step=voice：声音步当前高亮", () => {
    const { container } = renderAt("/create?step=voice");
    expect(linkOf("声音").className).toContain("bg-brand-grad");
    expect(checkIcons(container)).toHaveLength(2); // 链接/选题、文案 已完成
  });

  it("向导 ?step=publish：发布步当前高亮，前五步完成", () => {
    const { container } = renderAt("/create?step=publish");
    expect(linkOf("发布").className).toContain("bg-brand-grad");
    expect(checkIcons(container)).toHaveLength(5);
  });

  it("工作台首页：无当前步（不属于六步动线）", () => {
    const { container } = renderAt("/");
    for (const label of STEP_LABELS) {
      expect(linkOf(label).className).not.toContain("bg-brand-grad");
    }
    expect(checkIcons(container)).toHaveLength(0);
  });
});
