# 口播IP智能体产品调研 (Oral IP Agents Research)

> 对市面主流口播IP智能体（AI数字人口播视频自动化工具）的全面调研，并输出自有产品的功能需求清单。

## 项目简介

本项目聚焦"口播IP智能体"这一 AI 应用赛道：以"对标文案提取 → 文案仿写 → 声音克隆 → 数字人口播 → 字幕/BGM/封面 → 多平台发布"全链路自动化为核心特征的一类产品。通过调研市面主流产品的平台分布、功能模块、业务逻辑、技术实现与商业模式，为我们自己的口播IP智能体产品定义提供决策依据。

当前应用采用两个前端和一个 FastAPI 模块化后端：

- 用户端 `apps/web`：内容创作、套餐展示、激活码兑换、积分报价与任务执行。
- 管理端 `apps/admin`：套餐 SKU、价格版本、激活码、用户、Provider、成本与审计。
- 后端：用户数据面 `/api/v1/*`，管理控制面 `/api/admin/v1/*`。两类 JWT 使用不同 audience，不能跨端复用。

## 本地启动

```bash
pnpm install
pnpm dev:web       # http://localhost:5173
pnpm dev:admin     # http://localhost:5174

cd server
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
# 另开终端启动持久任务 Worker
uv run dramatiq app.workers.tasks --processes 1 --threads 4
# IM_ENABLED=true 的开发/测试环境另开独立私信监听 Worker
uv run python -m app.workers.im_listener
```

私信监听意图保存在数据库，实际 WebSocket 连接只由独立监听 Worker 持有；
Redis 租约保证同一账号不会被多个 Worker 重复监听。生产环境仍受第三阶段
Go/No-Go 门禁约束，不得仅通过设置 `IM_ENABLED=true` 绕过授权与灰度验收。
`IM_GRAY_ENFORCED=true` 默认为开启；管理员必须先把账号加入灰度名单，监听、手动发送和自动回复才会进入 Provider 链路。管理端“私信自动回复安全”页面提供灰度名单、24 小时监控和风控事件登记。
启用 IM 时必须提供真实 `DOUYIN_IM_APP_KEY`，缺失即拒绝启动，不会降级为 Mock 并写入伪成功。灰度账号默认最多 20 个（`IM_GRAY_MAX_ACCOUNTS`）；原始监控事件默认保留 14 天（`IM_METRIC_RETENTION_DAYS`），七日聚合证据由验收脚本单独保存。
`IM_HISTORY_RETENTION_DAYS` 默认为 90 天，监听 Worker 每
`IM_CLEANUP_INTERVAL_HOURS` 小时分批清理终态历史；待发送、发送中和失败可重试消息不会被自动清理。

本地后端需要可执行的 `ffprobe`（由 FFmpeg 提供），用于在冻结按时长计费的
ASR 或数字分身积分前验证上传媒体的真实时长；服务端 Docker 镜像已内置 FFmpeg。

首次部署可临时设置 `BOOTSTRAP_ADMIN_PHONE` 和至少 12 位的
`BOOTSTRAP_ADMIN_PASSWORD`。管理员创建成功后，应从部署环境删除引导密码。
生产环境必须分别配置 `APP_SECRET`、`CONFIG_ENCRYPTION_KEY`、
`ACTIVATION_SECRET`、`PUBLISH_SESSION_ENCRYPTION_KEY` 和
`FEIYING_WEBHOOK_SECRET`；用途、格式和更换影响已逐项写在
`server/.env.example` 中。供应商密钥只保存在后端，用户端没有配置入口。

## 容器化前后端联调

这套方式与远程服务器的服务边界一致：PostgreSQL、Redis、MinIO、数据库迁移、
FastAPI 和任务 Worker 都运行在容器中；本地用户端和管理端只通过
`http://127.0.0.1:8000` 调用容器 API。

```bash
cp server/.env.example server/.env
# 编辑 server/.env：将 APP_ENV 改为 staging，替换所有 REPLACE_* 安全值。
# 可选：需要调整宿主机映射端口时执行 cp .env.example .env。
docker compose up -d --build
curl --fail http://127.0.0.1:8000/readyz

pnpm dev:web
pnpm dev:admin
# 或自动验证容器 API、Vite 代理和现有端到端流程
pnpm e2e:container
```

`/readyz` 只有在数据库、Redis 和对象存储全部可用时才返回 200。Compose 会先
创建 MinIO bucket、执行 Alembic 迁移，再启动 API 和 Worker；不会把宿主机源码
挂进容器，因此这里验证的是实际构建出的镜像。需要启用已审批的 IM 监听器时，
使用 `docker compose --profile im up -d`；当前生产 No-Go 门禁仍会拒绝直接启用。

前端部署到其他电脑或域名时，在构建用户端前设置 `VITE_API_BASE`；
`VITE_WS_BASE` 可省略，客户端会从 API 域名自动推导 `ws://`/`wss://` 地址。
管理端使用 `VITE_ADMIN_API_BASE`。示例分别见 `apps/web/.env.example` 和
`apps/admin/.env.example`。

### 桌面端真实登录

桌面端是 Tauri 壳，内置用户端 Web 构建产物，但登录、令牌刷新和用户资料都只会
调用后端容器 API。打包前把可公开访问的 HTTPS API 写入本机忽略的环境文件：

```bash
cp apps/web/.env.desktop.example apps/web/.env.local
# 编辑 apps/web/.env.local：替换为 https://你的域名/api/v1
pnpm --filter @oral/desktop tauri:build
```

后端 `CORS_ORIGINS` 必须同时保留你的浏览器前端域名及
`tauri://localhost,http://tauri.localhost,https://tauri.localhost`；这些分别覆盖
Tauri 2 的 macOS/Linux、Windows 默认协议和 Windows HTTPS 协议。首次用户需先
通过激活码注册，之后桌面端会用真实 PostgreSQL 中的账号、密码哈希和 JWT 双令牌
完成登录及自动刷新。

角色为 `admin` 的账号仍必须通过报价与任务参数校验，但会生成零积分预留：不会创建
额度账户、扣费流水或用量记录，也不受付费套餐门槛限制。管理员角色只能由受控部署
流程授予，不能通过用户端注册获得。

价格目录首次启动会从旧流水线固定扣费生成 `legacy-v1` 已发布版本，保证迁移前后扣费口径一致。后续价格变更必须新建并发布版本，已报价或已冻结的任务继续使用原价格快照。

包年套餐首月积分在激活时发放，后续按 30 天周期在用户查询余额或订阅时幂等补发，且不超过套餐到期日。积分以带到期日的批次保存，冻结时优先消耗最早到期批次，取消或失败时按原批次恢复。管理员赠送或扣减积分只能通过带原因的调整流水完成，不能直接改余额。

## 测试环境

后端单元测试会在 `server/tests/conftest.py` 中创建临时 SQLite、临时存储和
进程内通知，不需要配置服务器环境变量。Playwright 默认也会临时注入测试
变量并启动 API。只有手动启动本地测试 API 时，才需执行：

```bash
cp server/.env.test.example server/.env.test
cd server
set -a; source .env.test; set +a
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

该模板只用于本地测试，刻意不配置任何真实 Provider、发布账号或 IM 凭据；
`REDIS_URL` 指向不可用端口以验证进程内通知降级，因此不能据此判断生产
`/readyz` 状态。本地 API 存活检查使用 `/healthz`。

`pnpm e2e:container` 专门验证容器依赖和 `/readyz`，运行前必须通过
`docker compose up -d --build postgres redis minio minio-init migrate server worker`
启动 PostgreSQL、Redis、MinIO、API 和 Worker；它不使用 `.env.test` 的降级配置。

第二阶段真实验收则必须使用真实、受控的预发布基础设施和 Provider 凭据。复制
`server/.env.stage2.example` 为未跟踪的 `server/.env.stage2`，填入密钥管理服务
注入的值后，在同一终端 `source .env.stage2`，再执行
`uv run python scripts/stage2_acceptance.py`。该模板刻意保持 `IM_ENABLED=false`；
私信灰度必须等待 Go/No-Go 条件和独立审批完成。

## 文档结构

| 文档                                                                                       | 说明                                                                                                                                                            |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [docs/01-市场调研报告.md](docs/01-市场调研报告.md)                                         | 9+ 款主流产品的深度调研：平台分布、功能模块、业务逻辑、技术方案、商业模式与横向对比                                                                             |
| [docs/02-产品功能需求清单.md](docs/02-产品功能需求清单.md)                                 | 基于调研结论输出的自有产品功能需求清单（核心/辅助/扩展功能 + 优先级分期）                                                                                       |
| [docs/03-核心模块技术分析报告.md](docs/03-核心模块技术分析报告.md)                         | P0 三大模块（文案/声音/数字人）的技术选型分析：可行性、成本、合规与最终推荐                                                                                     |
| [docs/04-视频合成模块调研与技术选型报告.md](docs/04-视频合成模块调研与技术选型报告.md)     | 视频合成模块：客户现状、市场方案、GitHub 开源项目评估与自建合成引擎选型                                                                                         |
| [docs/05-前端页面布局与全栈技术脚手架方案.md](docs/05-前端页面布局与全栈技术脚手架方案.md) | 前端页面布局（IA + 线框）、五端前端脚手架（Tauri/React/Expo Monorepo）、后端架构与脚手架（FastAPI 模块化单体 + Provider 抽象层 + 云端为主、本地备用的算力调度） |
| [docs/06-最终开发文档.md](docs/06-最终开发文档.md)                                         | **最终权威开发文档**：整合评审 01–05，含 14 项冲突裁决、修订后需求基线、技术架构、模块设计、成本模型、合规风控与统一实施计划。与 01–05 冲突时以本文档为准       |
| [docs/09-双端套餐积分接口.md](docs/09-双端套餐积分接口.md)                                 | 用户端/管理端边界、套餐和价格版本、报价冻结及部署配置说明                                                                                                       |
| [docs/10-项目三阶段修复与开发计划-复审版.md](docs/10-项目三阶段修复与开发计划-复审版.md)   | 三阶段修复顺序、启动条件、退出门槛和真实验收口径                                                                                                                |
| [docs/11-第二阶段真实链路验收.md](docs/11-第二阶段真实链路验收.md)                         | 第二阶段真实 Provider、MP4、计费、发布包和真实发布的证据采集方法                                                                                                |
| [docs/12-第三阶段S3-01-Go-No-Go决策.md](docs/12-第三阶段S3-01-Go-No-Go决策.md)             | 第三阶段当前 No-Go 结论、工程门禁和重新评审所需证据                                                                                                             |
| [docs/13-第三阶段七天灰度验收.md](docs/13-第三阶段七天灰度验收.md)                         | S3-14 灰度准入、监控指标、每日证据采集和连续七天退出判定                                                                                                        |

## 调研覆盖产品

- **旗博士口播智能体**（本地工具型，买断制）
- **罗根智能体 / 罗根口播智能体**（云端方案 + 开源 Agent 框架）
- **轻语 IP 智能体**（全终端、双算力，轻语科技）
- **茄条 AI 智能体**（开源引流 + 私域售卖）
- **AIPGPT**（企业级多智能体平台，天空十方）
- **淘金 AI（极享科技）**（Web 端全链路引擎）
- **Deepshow**（本地部署 + 源码交付，企业私有化）
- **夜神 AI 超级IP口播智能体**
- **大厂 SaaS 参照系**：蝉镜、闪剪、腾讯智影、讯飞智作、HeyGen

## 核心结论速览

1. 赛道产品形态分三类：**本地买断工具**（旗博士/茄条）、**云端 SaaS**（罗根/蝉镜/淘金）、**企业私有化/平台型**（Deepshow/AIPGPT）。
2. 全链路流水线（文案→声音→数字人→剪辑→发布）已是标配，**差异化竞争点**在于：算力架构（本地/云端/混合）、终端覆盖、IP 人设管理、矩阵账号运营、知识库与数据闭环。
3. 主流技术栈高度趋同且大多基于开源组件：Whisper（ASR）、CosyVoice / GPT-SoVITS（TTS/声音克隆）、HeyGem / Wav2Lip / EchoMimic（数字人驱动）、FFmpeg（视频合成）、social-auto-upload（多平台发布）、LLM API（文案仿写）。
4. 商业模式：买断授权（¥299–¥1999）+ 云算力续费 + 课程/陪跑 + 代理分销 + 企业定制，灰色地带存在大量低价盗版（淘宝/闲鱼 ¥6.8 起）。
5. 我们的机会点：**混合算力 + 全终端 + IP 人设一致性管理 + 矩阵自动化 + 合规风控**，对标竞品的短板逐一击破（详见需求清单）。

## 调研时间

2026 年 7 月
