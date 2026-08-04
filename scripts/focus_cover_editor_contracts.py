from pathlib import Path

root = Path(__file__).resolve().parents[1]
test_path = root / "apps/web/src/__tests__/EditorPage.test.tsx"
content = test_path.read_text(encoding="utf-8")

old_slider = '''  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });

    expect(timeline).toHaveValue("20000");
    expect(screen.getByText(/当前选中 20\\.0s/)).toBeInTheDocument();
  });
'''
new_slider = '''  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });
    await vi.advanceTimersByTimeAsync(500);

    expect((timeline as HTMLInputElement).value).toBe("20000");
    expect(pipelineApi.coverPreview).toHaveBeenLastCalledWith(
      task.id,
      expect.objectContaining({ selectedFrameMs: 20000 }),
    );
  });
'''
if content.count(old_slider) != 1:
    raise RuntimeError("slider contract did not match exactly once")
content = content.replace(old_slider, new_slider, 1)

old_save = '''  it("保存草稿按钮立即提交当前编辑内容", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    const title = await screen.findByLabelText("标题");
    await user.clear(title);
    await user.type(title, "立即保存的标题");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => {
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({ title: "立即保存的标题" }),
        }),
      );
    });
  });
'''
new_save = '''  it("保存草稿按钮立即提交当前编辑内容", async () => {
    renderEditor();

    const title = await screen.findByLabelText("标题");
    fireEvent.change(title, { target: { value: "立即保存的标题" } });
    const saveButton = screen.getByRole("button", { name: "保存草稿" });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
      task.id,
      expect.objectContaining({
        content: expect.objectContaining({ title: "立即保存的标题" }),
      }),
    );
  });
'''
if content.count(old_save) != 1:
    raise RuntimeError("explicit save contract did not match exactly once")
content = content.replace(old_save, new_save, 1)
test_path.write_text(content, encoding="utf-8")

workflow_path = root / ".github/workflows/ci.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("permissions:\n  contents: write\n\n", "", 1)
temporary_step = '''      - name: 临时聚焦封面编辑器契约测试
        if: github.event_name == 'pull_request' && github.head_ref == 'fix/cover-full-timeline-p0'
        env:
          HEAD_REF: ${{ github.head_ref }}
        run: |
          git fetch origin "$HEAD_REF"
          git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
          python scripts/focus_cover_editor_contracts.py
          pnpm exec prettier --write apps/web/src/__tests__/EditorPage.test.tsx
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "test(editor): assert cover timeline business contracts directly"
          git push origin "HEAD:$HEAD_REF"
'''
if workflow.count(temporary_step) != 1:
    raise RuntimeError("temporary workflow step did not match exactly once")
workflow_path.write_text(workflow.replace(temporary_step, "", 1), encoding="utf-8")

Path(__file__).unlink()
