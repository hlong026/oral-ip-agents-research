# 17 - Gate 4 发布工程验收记录

> 验收日期：2026-07-27
> 分支：`fix/system-closure`
> 范围：代码、依赖、容器、生产启动门禁、数据库迁移/备份/恢复、对象存储恢复。
> 说明：本记录只证明本地隔离环境的工程门禁，不替代远程 CI、真实供应商账号和生产域名验收。
> 后续：Gate 5 为桌面端增加两个固定 Tauri CORS 来源；当前口径以文档 16、18 为准。

## 结论

Gate 4 的本地工程验收通过：

- 后端全量测试：379 passed，1 skipped。
- Web：47 tests passed；Admin：9 tests passed；Playwright：6 tests passed。
- Ruff、Mypy、Prettier、TypeScript、前端构建通过。
- 运行中后端、OpenAPI 快照和自动生成 TypeScript 类型零漂移。
- `pip-audit` 与 `pnpm audit --prod` 均未发现已知漏洞。
- 生产镜像从仓库根目录构建成功，镜像 ID：
  `sha256:d571f535b3dc168e2d2bfec0bc407a538e33452b7d00c558a93b9cf53311d59e`。
- 镜像大小 653,106,520 bytes，以用户 `oral` / UID 10001 非 root 运行。
- 容器内 Chromium、FFmpeg、`social-auto-upload` 发布源码齐全；实际启动 Chromium 并加载抖音发布驱动成功。
- 隔离 PostgreSQL 16、Redis 7、MinIO 环境从空库迁移并以 `APP_ENV=prod` 启动成功。
- `/readyz` 返回 HTTP 200、`provider_mode=real_only`，数据库、Redis、对象存储均为 `ok=true`。
- PostgreSQL 自定义格式备份可读（246 个 TOC 条目），删除并重建数据库后恢复成功。
- 恢复探针值为 `gate4-restore-ok`，恢复 revision 为 `bb2c3d4e5f6a`。
- 最新迁移完成 `downgrade -1` 后重新 `upgrade head`，应用再次启动并通过 `/readyz`。
- MinIO 主桶对象删除后从备份桶恢复成功；恢复前后 ETag 均为
  `2f454b518243b984a1e542317ff1e43e`。

## 已固化的生产门禁

1. 生产启动拒绝短密钥、重复密钥、占位值和缺失配置。
2. 生产启动拒绝 SQLite、本地媒体存储、非 HTTPS 公网媒体地址、非 HTTPS CORS 域名和有头浏览器。
3. 生产 Redis 为强依赖；数据库、Redis、存储任一异常时 `/readyz` 返回 503。
4. 生产注册表不加载 Mock Provider。
5. CI 增加 Python/Node 生产依赖审计和实际 Docker 构建。
6. Docker 基础镜像和 uv 工具镜像使用固定摘要，Python 依赖由 `uv.lock` 决定。
7. Docker 镜像内置真实发布代码与 Chromium，并以非 root 用户运行。
8. 结构化日志、标准库日志和审计详情统一脱敏手机号、令牌、Cookie、签名参数和密钥。

## 尚需外部环境完成

- 远程 CI 必须在提交后实际运行并保持全绿。
- 生产 DNS、TLS、反向代理、负载均衡和告警通道尚未在真实环境验证。
- DeepSeek、Douyidou、DashScope、飞影及真实发布账号仍需按
  `11-第二阶段真实链路验收.md` 采集外部证据。
- IM 模块仍受合规 No-Go 和连续七天灰度门槛约束，不得随核心 Web 版本启用。
- Desktop 签名、公证、自动升级和真机安装属于 Gate 5，不在本次 Gate 4 本地验收范围。
