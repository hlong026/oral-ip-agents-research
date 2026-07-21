import { STEP_ORDER, type PipelineTask, type StepState } from "@oral/types";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import TaskCard from "../components/TaskCard";

function stepsWith(currentIdx: number): StepState[] {
  return STEP_ORDER.map((step, i) => ({
    step,
    status: i < currentIdx ? "done" : i === currentIdx ? "running" : "pending",
    progress: i < currentIdx ? 100 : 0,
  }));
}

function makeTask(overrides: Partial<PipelineTask> = {}): PipelineTask {
  return {
    id: "t-001",
    ipId: "ip-001",
    title: "如何做好一碗牛肉面",
    sourceUrl: "",
    mode: "auto",
    status: "running",
    steps: stepsWith(3), // voice 步执行中
    currentStep: "voice",
    compute: "cloud",
    quotaCost: 128,
    createdAt: "2026-07-19T00:00:00Z",
    updatedAt: "2026-07-19T00:01:00Z",
    ...overrides,
  };
}

function renderCard(task: PipelineTask) {
  return render(
    <MemoryRouter>
      <TaskCard task={task} />
    </MemoryRouter>,
  );
}

describe("TaskCard 统一 PipelineTask 模型渲染", () => {
  it("渲染 8 步 mini-pipe 状态点", () => {
    const { container } = renderCard(makeTask());
    expect(container.querySelectorAll("[title]").length).toBe(8);
  });

  it("执行中：状态 chip + 当前步文案 + 进度百分比", () => {
    renderCard(makeTask());
    expect(screen.getByText("执行中")).toBeInTheDocument();
    expect(screen.getByText(/中…$/)).toBeInTheDocument(); // 声音 中…
    expect(screen.getByText(/38%/)).toBeInTheDocument(); // 3/8 ≈ 38%
    expect(screen.getByText(/128 点/)).toBeInTheDocument();
  });

  it("整卡链接到任务详情 /tasks/:id", () => {
    renderCard(makeTask());
    expect(screen.getByRole("link")).toHaveAttribute("href", "/tasks/t-001");
  });

  it("manual 待确认：提示等待确认", () => {
    renderCard(
      makeTask({
        mode: "manual",
        status: "waiting_confirm",
        currentStep: "rewrite",
      }),
    );
    expect(screen.getByText("待确认")).toBeInTheDocument();
    expect(screen.getByText(/等待确认/)).toBeInTheDocument();
    expect(screen.getByText(/手动/)).toBeInTheDocument();
  });
});
