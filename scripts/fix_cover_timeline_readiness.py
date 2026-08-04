from pathlib import Path

root = Path(__file__).resolve().parents[1]
editor_path = root / "apps/web/src/pages/EditorPage.tsx"
content = editor_path.read_text(encoding="utf-8")

old_calc = '''  const latestCandidateMs = allCoverCandidates.reduce(
    (latest, candidate) => Math.max(latest, candidate.timestampMs),
    0,
  );
  const coverTimelineMaxMs = Math.max(
    0,
    artifactDurationMs > 0 ? artifactDurationMs - 1 : latestCandidateMs,
  );
'''
new_calc = '''  const latestCandidateMs = allCoverCandidates.reduce(
    (latest, candidate) => Math.max(latest, candidate.timestampMs),
    0,
  );
  const coverTimelineReady =
    artifactDurationMs > 0 || allCoverCandidates.length > 0;
  const coverTimelineMaxMs = coverTimelineReady
    ? Math.max(
        0,
        artifactDurationMs > 0 ? artifactDurationMs - 1 : latestCandidateMs,
      )
    : 0;
'''
if content.count(old_calc) != 1:
    raise RuntimeError("cover timeline calculation did not match exactly once")
content = content.replace(old_calc, new_calc, 1)

old_range = '''                        step={100}
                        value={Math.min(
                          coverTimelineMaxMs,
                          content.cover.selectedFrameMs,
                        )}
'''
new_range = '''                        step={100}
                        disabled={!coverTimelineReady}
                        value={Math.min(
                          coverTimelineMaxMs,
                          content.cover.selectedFrameMs,
                        )}
'''
if content.count(old_range) != 1:
    raise RuntimeError("cover timeline range did not match exactly once")
content = content.replace(old_range, new_range, 1)

old_button = '''                          type="button"
                          className="btn-ghost px-3 py-1 text-xs"
                          onClick={() => selectCoverFrame(currentTimeMs)}
'''
new_button = '''                          type="button"
                          className="btn-ghost px-3 py-1 text-xs"
                          disabled={!coverTimelineReady}
                          onClick={() => selectCoverFrame(currentTimeMs)}
'''
if content.count(old_button) != 1:
    raise RuntimeError("current playback cover button did not match exactly once")
content = content.replace(old_button, new_button, 1)
editor_path.write_text(content, encoding="utf-8")

test_path = root / "apps/web/src/__tests__/EditorPage.test.tsx"
tests = test_path.read_text(encoding="utf-8")
old_slider = '''    const timeline = await screen.findByLabelText("封面时间轴");
    fireEvent.change(timeline, { target: { value: "20000" } });
    await vi.advanceTimersByTimeAsync(500);

    expect((timeline as HTMLInputElement).value).toBe("20000");
'''
new_slider = '''    const timeline = await screen.findByLabelText("封面时间轴");
    await waitFor(() => {
      expect(timeline).toBeEnabled();
      expect(timeline).toHaveAttribute("max", "29999");
    });
    fireEvent.change(timeline, { target: { value: "20000" } });
    await vi.advanceTimersByTimeAsync(500);

    await waitFor(() =>
      expect((timeline as HTMLInputElement).value).toBe("20000"),
    );
'''
if tests.count(old_slider) != 1:
    raise RuntimeError("slider test did not match exactly once")
tests = tests.replace(old_slider, new_slider, 1)

old_save_start = '''  it("保存草稿按钮立即提交当前编辑内容", async () => {
    renderEditor();
'''
new_save_start = '''  it("保存草稿按钮立即提交当前编辑内容", async () => {
    vi.useRealTimers();
    const user = userEvent.setup();
    renderEditor();
'''
if tests.count(old_save_start) != 1:
    raise RuntimeError("explicit save test start did not match exactly once")
tests = tests.replace(old_save_start, new_save_start, 1)

old_save_body = '''    const title = await screen.findByLabelText("标题");
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
'''
new_save_body = '''    const title = await screen.findByLabelText("标题");
    await user.clear(title);
    await user.type(title, "立即保存的标题");
    const saveButton = screen.getByRole("button", { name: "保存草稿" });
    await waitFor(() => expect(saveButton).toBeEnabled());
    await user.click(saveButton);

    await waitFor(() =>
      expect(pipelineApi.savePublicationDraft).toHaveBeenLastCalledWith(
        task.id,
        expect.objectContaining({
          content: expect.objectContaining({ title: "立即保存的标题" }),
        }),
      ),
    );
'''
if tests.count(old_save_body) != 1:
    raise RuntimeError("explicit save test body did not match exactly once")
tests = tests.replace(old_save_body, new_save_body, 1)
test_path.write_text(tests, encoding="utf-8")

workflow_path = root / ".github/workflows/ci.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("permissions:\n  contents: write\n\n", "", 1)
temporary_step = '''      - name: 临时修复封面时间轴就绪竞态
        if: github.event_name == 'pull_request' && github.head_ref == 'fix/cover-full-timeline-p0'
        env:
          HEAD_REF: ${{ github.head_ref }}
        run: |
          git fetch origin "$HEAD_REF"
          git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
          python scripts/fix_cover_timeline_readiness.py
          pnpm exec prettier --write apps/web/src/pages/EditorPage.tsx apps/web/src/__tests__/EditorPage.test.tsx
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "fix(editor): wait for cover timeline metadata before selection"
          git push origin "HEAD:$HEAD_REF"
'''
if workflow.count(temporary_step) != 1:
    raise RuntimeError("temporary workflow step did not match exactly once")
workflow_path.write_text(workflow.replace(temporary_step, "", 1), encoding="utf-8")

Path(__file__).unlink()
