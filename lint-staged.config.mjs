/**
 * 预提交格式化：只处理本次暂存的文件，不做整仓重排。
 *
 * 这是 CI 不可用期间唯一真正生效的格式门禁——`pnpm lint` 只有人主动跑才会
 * 执行，而本配置由 .husky/pre-commit 在每次 commit 时自动触发。
 *
 * vendor/ 等目录由 .prettierignore 排除；ruff 只匹配 server/ 下的 Python，
 * 因此不会碰到 vendor/ 里的 65 个第三方 .py。
 */
export default {
  "*.{ts,tsx,js,jsx,mjs,cjs,json}": "prettier --write",
  // ruff 装在 server/.venv，用 --project 指定项目即可在仓库根目录调用
  "server/**/*.py": [
    "uv run --project server ruff check --fix",
    "uv run --project server ruff format",
  ],
};
