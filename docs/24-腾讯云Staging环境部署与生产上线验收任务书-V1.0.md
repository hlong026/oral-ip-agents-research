# 腾讯云 Staging 环境部署 + 生产上线验收任务书 V1.0

> 项目：口播 IP 智能体 / oral-ip-agents-research  
> 基线分支：`master`  
> 基线能力：腾讯云 COS 适配、COS 迁移工具、生产 Docker/Compose、发布与回滚脚本、Release Manifest、全仓 CI、Production Deployment Gate 已完成。  
> 本任务书目标：把当前“代码可生产部署”推进到“真实腾讯云 Staging 可运行、可验证、可回滚，并具备 Production Go/No-Go 证据”。

---

## 1. 阶段目标

本阶段不继续扩张产品功能，优先完成以下闭环：

1. 在腾讯云建立独立 Staging 环境。
2. 使用真实 PostgreSQL、Redis、腾讯云 COS、容器镜像和域名运行当前系统。
3. 用真实媒体完成上传、处理、合成、封面、人工发布包及至少一个已验证发布平台的端到端测试。
4. 验证 Worker 重启、API 重启、数据库迁移、COS 故障、发布失败等恢复路径。
5. 建立日志、监控、备份和回滚证据。
6. 形成 Production Go / No-Go 决策清单，未满足 Gate 时禁止正式生产切流。

### 1.1 本阶段完成定义

满足以下条件才允许宣布 Staging 完成：

- Staging 使用真实腾讯云 COS，而非 MinIO。
- API、Worker、Migration 使用同一不可变 Server 镜像 digest。
- Gateway、Web、Admin、Server 均使用不可变镜像 digest。
- `/readyz` 返回 `ok=true`，数据库、Redis、COS 均正常。
- 两类真实输入素材均连续成功至少 3 次。
- 真实输出 MP4 可播放，字幕、封面和时间轴一致。
- 人工发布 ZIP 可生成、下载并解压，且大文件过程中无明显 OOM。
- 至少一个平台在测试账号上完成真实发布或完成明确的人工发布验收。
- Worker/API 分别重启一次，任务可恢复，无重复扣费、重复发布或状态漂移。
- 数据库已完成备份与恢复演练。
- COS 迁移已完成 `dry-run -> resume -> verify-only` 证据。
- Release Manifest、测试报告、回滚点、镜像 digest 均留档。

---

## 2. 当前工程基线

当前仓库已经具备：

- `docker-compose.prod.yml`：生产应用编排，不创建 PostgreSQL、Redis、MinIO。
- `deploy/scripts/deploy.sh`：校验、拉镜像、停旧 API/Worker、执行 Alembic、启动、验证 `/readyz`。
- `deploy/scripts/rollback.sh`：按上一版不可变镜像回滚，不自动数据库 downgrade。
- `deploy/Dockerfile.frontend`：Web/Admin 构建与非 root Nginx 运行镜像。
- `deploy/Dockerfile.gateway`：Gateway 不可变镜像。
- COS boto3/S3 兼容配置、Multipart、超时重试和 `/readyz` 存储检查。
- MinIO/S3 -> 腾讯云 COS 的迁移工具，支持 dry-run、resume、verify-only、Manifest 和 Checkpoint。
- CAM 最小权限模板、COS 生命周期人工评审模板。
- Release Manifest 示例与 JSON Schema。
- 全仓 CI 与 Production Deployment Gate。

本阶段原则：**不重写上述能力，只补 Staging、真实云环境验收与 Production Gate。**

---

## 3. 环境策略

### 3.1 环境分层

| 环境 | 用途 | 数据 | 第三方账号 | 是否允许真实发布 |
| --- | --- | --- | --- | --- |
| dev/local | 日常开发 | 假/本地测试数据 | Mock/测试 Provider | 否 |
| staging | 上线前真实集成与回归 | 脱敏真实样本/测试数据 | 测试账号 | 仅验证账号白名单 |
| production | 正式用户 | 正式业务数据 | 正式账号 | 仅已验收平台 |

### 3.2 Staging 两种拓扑

#### STG-LITE（最小成本联调）

适合第一次把系统跑起来：

- 1 台腾讯云 CVM。
- Gateway/Web/Admin/API/Worker 使用 Docker。
- 腾讯云 COS 使用真实 Bucket。
- PostgreSQL/Redis 可以暂时运行在独立 Staging 容器或使用云托管实例。
- 使用 Staging 子域名。

限制：只用于早期联调；不得直接视为生产等价环境。

#### STG-PARITY（上线验收推荐）

正式 Production Go/No-Go 前必须达到：

- 应用 CVM/容器宿主机。
- 外部 PostgreSQL。
- 外部 Redis。
- 腾讯云 COS。
- 腾讯云容器镜像仓库。
- HTTPS 入口 / CLB 或经过批准的等价入口。
- Staging Web/Admin/API 域名。
- 与 Production 相同的容器拓扑、环境变量结构和发布脚本。

### 3.3 环境隔离

Staging 与 Production 必须至少隔离：

- COS Bucket 或对象前缀。
- 数据库实例/数据库名。
- Redis DB/实例。
- JWT/Encryption Secret。
- Provider API Key。
- 发布账号。
- 域名。
- 日志索引与告警渠道。

禁止 Staging Worker 使用 Production 发布 Cookie 或正式平台账号。

---

## 4. 云资源前置清单

### CLOUD-001 腾讯云地域确认

**目标**：统一 CVM、COS、数据库、Redis 等主要资源地域，避免无意的公网跨地域访问。

需要记录：

- `TENCENT_REGION`
- CVM Region/Zone
- COS Region
- PostgreSQL Region
- Redis Region

**验收**：Release Manifest 和部署台账记录明确，环境变量与 COS Endpoint 一致。

### CLOUD-002 腾讯云 COS Staging Bucket

需要确认：

- 完整 Bucket 名（含 APPID）。
- Region。
- S3/COS Endpoint。
- Staging 与 Production 是否分 Bucket；推荐分离。
- 默认私有读写。
- CORS 当前无需开放浏览器直传时保持最小化。

**验收**：使用应用 Runtime CAM 可以执行 `HeadBucket`、上传、下载、HeadObject；无 List/Delete 全局越权。

### CLOUD-003 CAM Runtime 账号

创建独立 Runtime CAM 身份：

- Server/Worker 只拥有应用运行需要的 COS 权限。
- 不使用腾讯云主账号 SecretId/SecretKey。
- 不授予账号级 `*` 权限。
- Secret 仅存 Staging 服务器私有 env / Secret 管理，不写入 Git 和聊天记录。

**验收**：最小权限正向用例通过，越权 Bucket/Prefix 用例失败。

### CLOUD-004 CAM Migration 账号

单独创建数据迁移身份：

- 源对象存储只读。
- 目标 COS 指定 Bucket/Prefix 可写。
- 迁移结束后可以停用或回收。

**验收**：迁移工具可执行，但无法删除源对象。

### CLOUD-005 PostgreSQL

Staging 最终验收应使用 PostgreSQL，与 Production Schema 和 Alembic 路径一致。

要求：

- 独立 Staging 数据库。
- 强密码与网络 ACL/安全组。
- 自动备份或可验证备份方案。
- 服务器可访问，公网不可直接暴露数据库端口。

**验收**：完整 Alembic upgrade，应用读写、并发任务和恢复测试通过。

### CLOUD-006 Redis

要求：

- 独立 Staging Redis。
- 网络仅允许应用访问。
- 根据队列恢复策略启用合适持久化。

**验收**：Worker 正常消费；Redis 短暂重启后应用不会产生重复结算或重复发布。

### CLOUD-007 镜像仓库

需要准备 Server/Gateway/Web/Admin 四类镜像仓库。

要求：

- Staging 部署只接受 `@sha256:<digest>`。
- 禁止 `latest` 作为部署依据。
- 每次发布保留对应 Git commit 和四个 digest。

### CLOUD-008 域名、HTTPS 和入口

至少需要：

- Staging Web 域名。
- Staging Admin 域名。
- HTTPS 证书。
- 入口只转发到 Gateway。
- Server、Worker、Web、Admin 内部端口禁止公网直接访问。

**验收**：公网只暴露 HTTPS 入口；API/媒体/WebSocket 通过 Gateway 正常访问。

---

## 5. 代码开发任务

### STG-CODE-001 Staging 配置模板

新增：

- `deploy/.env.staging.example`
- `server/.env.staging.example`

要求：

- 不包含真实凭据。
- 配置字段与 Production 保持一致。
- `APP_ENV=staging` 或等价明确环境标识。
- Storage 必须为 `s3`，COS Region/Endpoint/Bucket 必填。
- Provider 默认使用测试密钥与测试账号。

**Acceptance Criteria**：

- 缺失关键变量时启动失败关闭。
- 配置中不存在 localhost/MinIO 默认值被误用于 Staging 的可能。

### STG-CODE-002 Staging 部署脚本

新增：

- `deploy/scripts/deploy-staging.sh`

职责：

1. 校验配置文件权限。
2. 校验四个镜像 digest。
3. 校验目标环境必须是 Staging，禁止误操作 Production。
4. 校验 Compose。
5. 拉取镜像。
6. 停旧 API/Worker。
7. 数据库 Migration。
8. 启动服务。
9. 验证 `/readyz`。
10. 输出 Release Manifest 草稿。

**Acceptance Criteria**：脚本不能通过一个 Staging 配置误连 Production Bucket、数据库或域名。

### STG-CODE-003 Preflight 工具

新增：

- `deploy/scripts/preflight-staging.sh`

检查：

- Docker/Compose 版本可用。
- 磁盘、内存、inode 基本容量。
- DNS 解析。
- PostgreSQL 连通。
- Redis 连通。
- COS HeadBucket/写入/读取测试对象。
- 四个镜像 digest 可拉取。
- FFmpeg、Chromium/发布 Worker 依赖存在于 Server 镜像。
- Staging 域名和 `/readyz` 配置一致。

**验收**：Preflight 非零退出码代表禁止部署。

### STG-CODE-004 Staging Smoke Test

新增：

- `deploy/scripts/staging-smoke.sh`

最低测试：

- Gateway health。
- API `/readyz`。
- Web 首页。
- Admin 首页。
- 登录。
- 上传小型测试媒体。
- COS 中出现对象。
- API 媒体访问正常。
- Worker 可领取一个安全测试任务。

输出 JSON/Markdown 结果供证据归档。

### STG-CODE-005 Production Acceptance Runner

新增：

- `deploy/scripts/production-acceptance.sh`
- `deploy/acceptance/acceptance-cases.yaml`

自动/半自动汇总：

- 基础健康检查。
- 数据库/Redis/COS。
- 媒体上传与读取。
- 任务创建、状态流转、重试。
- 余额冻结/释放/结算。
- 生成文件可读取。
- 人工发布包。
- 重启恢复。
- 发布平台验收结果。

人工步骤必须显式标为 `manual_pending/manual_pass/manual_fail`，不得自动伪造成功。

### STG-CODE-006 数据库备份/恢复脚本

新增受控工具：

- `deploy/scripts/backup-database.sh`
- `deploy/scripts/restore-database-staging.sh`

要求：

- 备份默认写入受控目录或对象存储位置。
- 记录时间、数据库身份、Alembic revision、SHA-256。
- Restore 只允许 Staging，Production 恢复必须人工确认并使用单独流程。

**验收**：Staging 空库恢复后核心记录、任务和账务数据一致。

### STG-CODE-007 手动 Staging GitHub Actions

新增 `workflow_dispatch` 工作流：

- 默认只允许 `staging` Environment。
- 只部署已合并 `master` 的 commit。
- 构建/推送四个镜像或读取已发布 digest。
- 执行 Preflight。
- 执行 Staging Deploy。
- 执行 Smoke。
- 上传验收 Artifact。

注意：GitHub Environment Secrets 本身由仓库管理员人工配置，代码不得写入任何凭据。

### STG-CODE-008 证据归档

建立：

- `evidence/staging/README.md`（只存模板与说明）。

真实执行证据优先放 GitHub Actions Artifact/安全对象存储，不把账号 Cookie、Token、客户媒体或敏感日志提交 Git。

---

## 6. Staging 数据迁移任务

### DATA-001 迁移前盘点

统计：

- 对象数量。
- 总容量。
- 最大对象。
- 关键业务 Prefix。
- 数据库中引用的对象 Key 数量。

### DATA-002 Dry Run

执行迁移工具 `--dry-run`。

**验收**：

- 不产生目标写入。
- Manifest 能准确列出计划对象。
- 对象 Key 不改变。

### DATA-003 小批量迁移

先迁移一个测试 Prefix。

验收：

- Size 一致。
- ETag 可比对象一致。
- SHA-256 抽样一致。
- 应用可以读取。

### DATA-004 全量/分批迁移

使用 `--resume`。

要求：

- Checkpoint 持久化。
- 中断后继续不重复搬运已完成对象。
- Error 记录不得被当作成功跳过。

### DATA-005 Verify Only

正式迁移后执行 `--verify-only`。

**通过条件**：关键 Prefix 100% 验证；非关键大批量对象按既定规则完成 size/hash 抽验；所有错误均有处理结论。

### DATA-006 切换与观察

切换 `STORAGE_DRIVER=s3`/COS 配置后：

- 旧源对象暂不删除。
- 至少保留一个完整观察周期和回滚窗口。
- 任何删除必须单独审批。

---

## 7. 真实业务 E2E 验收

### E2E-001 登录与权限

- 正常账号登录。
- 无权限账号访问受控 API 被拒绝。
- Admin 与普通用户权限隔离。

### E2E-002 媒体上传

至少使用：

1. 一条短视频/音频。
2. 一条较长真实业务视频。

检查：

- 上传完成。
- COS 对象存在。
- 数据库 Key 正确。
- API 媒体访问正常。

### E2E-003 内容处理主链

至少覆盖：

`输入 -> ASR -> 文案/脚本 -> TTS/数字人 -> FFmpeg -> 字幕 -> 封面 -> 成片`

检查：

- 状态机无非法跳转。
- 超时/失败可恢复。
- 最终 MP4 可播放。
- 字幕时间轴、封面时间点和最终输出一致。

### E2E-004 计费/积分一致性

验证：

- 任务开始冻结。
- 成功结算。
- 失败释放。
- 重试不重复扣费。
- 并发任务不突破套餐边界。

### E2E-005 人工发布包

验证：

- 大文件生成 ZIP 不 OOM。
- ZIP 包含视频、封面、metadata。
- 下载、解压、人工发布流程可执行。

### E2E-006 自动/半自动发布

仅对 `PUBLISH_VERIFIED_PLATFORMS` 中的测试平台执行。

验收证据：

- 发布账号。
- 平台。
- 发布时间。
- 平台返回 ID/URL（若平台可提供）。
- 截图/日志证据。
- 失败状态真实性。

未验证平台必须保持 `export_only`，禁止为了验收修改为“伪成功”。

---

## 8. 稳定性与故障恢复验收

### RES-001 API Restart

在无任务、任务进行中分别重启 API。

通过条件：

- 数据库状态不丢失。
- 前端可恢复轮询。
- 不重复创建任务。

### RES-002 Worker Restart

处理任务时重启 Worker。

通过条件：

- 任务可恢复或明确进入可重试状态。
- 无重复扣费。
- 无重复发布。

### RES-003 Redis Restart

短暂重启/断开 Redis。

通过条件：应用可诊断失败，恢复后队列不产生不可控重复消费。

### RES-004 COS Failure

临时使用无权限凭据或测试 Prefix 模拟 403/404。

通过条件：

- `/readyz` 能反映存储异常。
- 业务失败关闭。
- 不把缺失媒体标记成成功。
- 恢复凭据后可继续。

### RES-005 FFmpeg Subtitle Filter

验证生产镜像 subtitles/libass 能力；模拟缺失时 Fail-Closed 仍生效。

### RES-006 数据库迁移失败

在 Staging 演练迁移失败：

- 新 API/Worker 不启动。
- 旧版本回滚策略明确。
- 数据库备份可恢复。

---

## 9. 安全验收

### SEC-001 Secret

禁止出现在：

- Git。
- Release Manifest。
- `/readyz`。
- 前端 bundle。
- Actions 普通日志。

### SEC-002 文件权限

生产/Staging env 文件：`0400` 或 `0600`。

### SEC-003 网络暴露面

公网仅允许经过批准的 HTTPS 入口；数据库、Redis、Worker、Server 内部端口不直接暴露。

### SEC-004 COS 最小权限

验证 Runtime CAM：

- 应用 Bucket/Prefix 正常。
- 非授权 Bucket/Prefix 被拒绝。
- 无必要 Delete 权限时删除必须失败。

### SEC-005 发布账号

Cookie/Session：

- 加密存储。
- 不记录明文日志。
- 测试账号与 Production 账号隔离。

---

## 10. 监控、日志和备份最低上线标准

### OBS-001 日志

至少收集：

- Gateway access/error。
- Server JSON 日志。
- Worker 日志。
- 发布 Worker 错误。

统一字段至少包括：

- timestamp
- level
- request_id/trace_id
- user_id（允许记录时）
- job_id
- module
- error_code
- duration_ms

禁止记录 Secret/Cookie/Authorization。

### OBS-002 告警

最低告警：

- `/readyz` 连续失败。
- API 5xx 异常升高。
- Worker 队列积压。
- 任务失败率升高。
- COS 403/404 升高。
- 宿主机 CPU/内存/磁盘告警。
- 容器频繁重启。

### OBS-003 数据库备份

上线前必须具备：

- 自动备份或可靠周期备份。
- 最近一次恢复演练成功证据。
- RPO/RTO 记录。

### OBS-004 COS

生产上线前人工确认：

- 版本控制策略。
- 生命周期策略。
- Multipart 未完成清理。
- 最终成片与中间文件留存期限。
- 访问日志。

上述云资源修改不由应用仓库脚本自动执行。

---

## 11. Production Go / No-Go Gate

### G0 — Code Gate

必须全部通过：

- CI。
- Production Deployment Gate。
- 无 Critical/High 阻塞安全问题。
- master commit 已锁定。

### G1 — Infrastructure Gate

必须完成：

- Production COS。
- Production PostgreSQL。
- Production Redis。
- 镜像仓库。
- 域名/HTTPS。
- 网络安全组。
- Runtime CAM。

### G2 — Backup Gate

- 数据库上线前备份完成。
- 恢复方案已在 Staging 验证。
- Release Manifest 写入 backup ID/revision。

### G3 — Migration Gate

- COS dry-run 完成。
- 小批量验证完成。
- 全量迁移/目标初始化完成。
- verify-only 无未处理关键错误。

### G4 — Business E2E Gate

两种真实输入，各连续成功至少 3 次；核心流程无人工改数据库/改状态才能完成的情况。

### G5 — Resilience Gate

API/Worker 重启、COS/Redis 短暂故障、迁移失败路径已验证。

### G6 — Publish Gate

- 至少一个平台真实测试发布成功；或业务明确批准首发仅 `export_only`。
- 未验收平台不得标记为 verified。

### G7 — Security Gate

- Secret scan 通过。
- CAM 最小权限通过。
- 网络暴露面通过。
- 发布账号隔离通过。

### G8 — Release Gate

Release Manifest 完整，包括：

- Git commit。
- Server/Gateway/Web/Admin digest。
- Alembic revision。
- DB backup ID。
- COS Bucket/Region。
- COS migration manifest hash。
- Go/No-Go 结论。
- 审批人。

**任何 G0-G8 阻塞项为 Fail 时：No-Go。**

---

## 12. 正式上线执行顺序

1. 冻结本次 release commit。
2. CI + Production Deployment Gate 全绿。
3. 构建并推送四个不可变镜像。
4. 生成 Release Manifest 草稿。
5. Production 数据库备份。
6. COS 最终迁移/增量同步与 verify-only。
7. Production Preflight。
8. 停止旧 API/Worker。
9. Alembic Migration。
10. 启动 Server/Worker/Web/Admin/Gateway。
11. `/readyz`。
12. Smoke Test。
13. 最小业务 E2E。
14. 发布能力验证。
15. 观察期监控。
16. Release Manifest 完成签署。

---

## 13. 回滚原则

触发条件示例：

- `/readyz` 无法恢复。
- 核心 E2E 失败。
- 数据库严重异常。
- Worker 大量失败/重复扣费。
- 媒体无法读取。
- 发布发生不可控重复行为。

回滚：

- 使用上一版四个镜像 digest。
- 不自动执行 Alembic downgrade。
- 若旧镜像不兼容新 Schema，必须先停止服务、备份数据库并人工评审数据库回退。
- COS 源数据在观察窗口内不删除，必要时可切回旧 Storage 配置。

---

## 14. 任务依赖与执行顺序

### P0-A：Staging 代码工具

1. STG-CODE-001 配置模板。
2. STG-CODE-003 Preflight。
3. STG-CODE-002 Staging Deploy。
4. STG-CODE-004 Smoke。
5. STG-CODE-006 DB Backup/Restore。
6. STG-CODE-005 Production Acceptance Runner。
7. STG-CODE-007 GitHub Actions。
8. STG-CODE-008 Evidence。

每个子任务：独立 branch -> commit -> PR -> review -> CI -> merge `master`。

### P0-B：腾讯云 Staging 资源

CLOUD-001 ~ CLOUD-008。

此部分需要腾讯云账号控制台或 IaC 权限；禁止把真实 Secret 提交仓库。

### P0-C：Staging 部署

资源完成后执行：

Preflight -> 部署 -> Smoke -> COS 小批量迁移 -> E2E。

### P0-D：稳定性/安全/恢复

RES + SEC + OBS 全部执行。

### P0-E：Production Go/No-Go

G0-G8 全部评审。

---

## 15. 需要准备但不要提交到聊天或 Git 的敏感配置

实际部署前由环境管理员在服务器/GitHub Environment 中配置：

- COS Runtime CAM SecretId/SecretKey。
- COS Migration CAM 凭据。
- PostgreSQL URL/密码。
- Redis URL/密码。
- JWT Secret。
- Encryption Key。
- Provider API Keys。
- 发布平台 Session/Cookie。
- TCR Registry 凭据。

非敏感信息可以进入部署台账：

- Region。
- Bucket 完整名称。
- 域名。
- 镜像仓库路径。
- CVM 内网地址。

---

## 16. 交付物

本阶段最终应产出：

1. Staging 配置模板。
2. Staging Preflight。
3. Staging Deploy。
4. Smoke Test。
5. Production Acceptance Runner。
6. DB Backup/Restore 工具。
7. Staging GitHub Actions。
8. Staging 环境部署记录。
9. COS 迁移 Manifest/Checkpoint/Verify 报告。
10. E2E 验收报告。
11. 故障恢复报告。
12. 安全验收报告。
13. 监控和备份验收记录。
14. Production Release Manifest。
15. Production Go/No-Go 结论。

---

## 17. 本阶段第一批实际开发任务

从本任务书合并后立即按以下顺序执行：

### PR-A — Staging Configuration & Preflight

- `.env.staging.example`
- Server staging 配置模板
- `preflight-staging.sh`
- COS/DB/Redis/镜像/环境隔离检查
- 自动测试

### PR-B — Staging Deploy & Smoke

- `deploy-staging.sh`
- `staging-smoke.sh`
- Staging fail-closed 防误部署
- Smoke Artifact

### PR-C — Backup/Restore & Acceptance

- DB Backup
- Staging Restore
- Production Acceptance Runner
- Acceptance Cases

### PR-D — Staging GitHub Actions

- workflow_dispatch
- staging Environment
- Preflight -> Deploy -> Smoke
- Evidence Artifact

完成 PR-A~D 后，代码侧 Staging 工具链才能判定 P0 完成；随后进入真实腾讯云资源接入与验收执行。
