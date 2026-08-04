from pathlib import Path

root = Path(__file__).resolve().parents[1]
editor_path = root / "apps/web/src/pages/EditorPage.tsx"
content = editor_path.read_text(encoding="utf-8")

replacements = [
    (
        "  const [saveTick, setSaveTick] = useState(0);\n",
        "",
    ),
    (
        """    return () => window.clearTimeout(timer);
    // saveTick makes explicit save requests reuse the same save path.
  }, [dirty, effectiveTaskId, content, saveTick]);
""",
        """    return () => window.clearTimeout(timer);
  }, [dirty, effectiveTaskId, content]);
""",
    ),
    (
        "                  onClick={() => setSaveTick((value) => value + 1)}\n",
        "                  onClick={() => void saveNow()}\n",
    ),
]
for old, new in replacements:
    if content.count(old) != 1:
        raise RuntimeError(f"expected exactly one EditorPage match: {old!r}")
    content = content.replace(old, new, 1)
editor_path.write_text(content, encoding="utf-8")

workflow_path = root / ".github/workflows/ci.yml"
workflow = workflow_path.read_text(encoding="utf-8")
workflow = workflow.replace("permissions:\n  contents: write\n\n", "", 1)
temporary_step = '''      - name: 临时修复剪辑页显式保存
        if: github.event_name == 'pull_request' && github.head_ref == 'fix/cover-full-timeline-p0'
        env:
          HEAD_REF: ${{ github.head_ref }}
        run: |
          git fetch origin "$HEAD_REF"
          git checkout -B "$HEAD_REF" "origin/$HEAD_REF"
          python scripts/fix_editor_explicit_save.py
          pnpm exec prettier --write apps/web/src/pages/EditorPage.tsx
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "fix(editor): save publication drafts immediately on request"
          git push origin "HEAD:$HEAD_REF"
'''
if workflow.count(temporary_step) != 1:
    raise RuntimeError("temporary workflow step did not match exactly once")
workflow_path.write_text(workflow.replace(temporary_step, "", 1), encoding="utf-8")

Path(__file__).unlink()
