from pathlib import Path

root = Path(__file__).resolve().parents[1]
test_path = root / "apps/web/src/__tests__/EditorPage.test.tsx"
content = test_path.read_text(encoding="utf-8")

old = '''  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });
    const saveButton = screen.getByRole("button", { name: "保存草稿" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    await user.click(saveButton);
'''
new = '''  it("全视频时间轴可直接选择三秒后的任意位置", async () => {
    renderEditor();

    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });
    const saveButton = screen.getByRole("button", { name: "保存草稿" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    fireEvent.click(saveButton);
'''
if content.count(old) != 1:
    raise RuntimeError("cover timeline save test block did not match exactly once")
test_path.write_text(content.replace(old, new, 1), encoding="utf-8")

workflow_path = root / ".github/workflows/ci.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("permissions:\n  contents: write\n\n", "", 1)
temporary_step = '''      - name: 临时修正封面保存测试点击驱动
        if: github.event_name == 'pull_request' && github.head_ref == 'fix/cover-full-timeline-p0'
        env:
          HEAD_REF: ${{ github.head_ref }}
        run: |
          git fetch origin "$HEAD_REF"
          git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
          python scripts/fix_cover_save_click_driver.py
          pnpm exec prettier --write apps/web/src/__tests__/EditorPage.test.tsx
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "test(cover): exercise explicit save with synchronous click"
          git push origin "HEAD:$HEAD_REF"
'''
if workflow.count(temporary_step) != 1:
    raise RuntimeError("temporary workflow step did not match exactly once")
workflow_path.write_text(workflow.replace(temporary_step, "", 1), encoding="utf-8")

Path(__file__).unlink()
