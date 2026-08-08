# Staging 验收证据边界

本目录只保存**证据规范和说明**，不提交真实 Staging 运行证据、客户媒体、数据库备份、Cookie、Token 或腾讯云凭据。

## 1. 真实证据保存位置

`Staging deployment` GitHub Actions 在自托管 Staging Runner 上执行后，会将允许离开服务器的非敏感 JSON 复制到临时导出目录并上传为 GitHub Actions Artifact：

- `deploy-<git-sha>.json`
- `smoke-<git-sha>.json`
- `acceptance-<git-sha>.json`（仅运行 Go/No-Go 时产生）
- `backups/db-<sha-prefix>-<timestamp>.json`（仅备份元数据）

Artifact 默认保留 14 天。需要长期留档时，应复制到经过权限治理的运维证据存储，而不是提交到 Git。

## 2. 明确禁止上传的内容

以下内容不得进入 GitHub Artifact 或本仓库：

- PostgreSQL `.dump` 备份文件。
- `/etc/oral/*.env`。
- 激活码、密码、JWT、Authorization Header。
- 发布 Cookie / Session。
- Tencent CAM SecretId / SecretKey。
- Provider API Key。
- 原始客户音视频、最终成片或人工发布 ZIP。
- 包含上述信息的完整应用日志。

数据库 `.dump` 只保留在 `STAGING_BACKUP_DIR` / `PRODUCTION_BACKUP_DIR` 指定的受控私有文件系统或后续批准的备份系统中。

## 3. 人工验收结果

人工 Gate 使用 `/etc/oral/staging-acceptance-results.json`（或部署控制文件指定的等价私有路径）。

- 默认状态必须是 `manual_pending`。
- `manual_pass` 必须同时提供非空 evidence 引用。
- evidence 应指向已审批的截图、工单、测试报告或受控日志位置，不得直接嵌入 Secret。
- `manual_pending`、`manual_fail`、没有 evidence 的 `manual_pass` 都必须导致 Production Acceptance `NO_GO`。

模板位于：`deploy/acceptance/manual-results.example.json`。

## 4. 自托管 Runner 前置条件

`Staging deployment` Workflow 不会自动创建腾讯云资源或 Runner。实际执行前必须人工完成：

1. 在 Staging CVM 或受控同 VPC 主机安装 GitHub Actions self-hosted runner。
2. Runner 标签至少包含 `self-hosted`, `linux`, `oral-staging`。
3. 将 Runner 绑定到 GitHub `staging` Environment，并配置审批规则。
4. 创建 `/etc/oral/staging-deploy.env`、runtime env、smoke env，权限 `0400`/`0600`。
5. 部署控制文件中的四个镜像必须使用不可变 `@sha256:` digest。
6. `RELEASE_GIT_COMMIT` 必须与 Workflow 输入一致，而且该 commit 必须已合并进入 `master`。
7. PostgreSQL、Redis、COS、DNS/HTTPS 和镜像仓库必须已由腾讯云资源 Gate 验收。

## 5. Workflow 行为

手动触发 `Staging deployment` 后顺序固定为：

`checkout merged master commit -> validate private control files -> Preflight -> Deploy/Migration -> authenticated Smoke -> DB Backup -> optional Production Acceptance -> collect JSON evidence`

`run_acceptance=true` 时，任何未完成人工 Gate 都会让 Workflow 以 `NO_GO` 失败结束，但 `acceptance-*.json` 仍会通过 `if: always()` 的证据步骤上传，便于定位阻塞项。

## 6. 为什么不在 GitHub Hosted Runner 上部署

真实 Staging PostgreSQL、Redis 和应用内网端口应位于腾讯云 VPC，生产级部署不应为了 Hosted Runner 临时暴露数据库/Redis 公网入口。因此正式 Staging 部署使用带 `oral-staging` 标签的腾讯云自托管 Runner；普通 PR/CI 仍使用 GitHub Hosted Runner 做代码与镜像契约验证。
