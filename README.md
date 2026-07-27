# 口播IP智能体产品调研 (Oral IP Agents Research)

> 对市面主流口播IP智能体（AI数字人口播视频自动化工具）的全面调研，并输出自有产品的功能需求清单。

## 项目简介

本项目聚焦"口播IP智能体"这一 AI 应用赛道：以"对标文案提取 → 文案仿写 → 声音克隆 → 数字人口播 → 字幕/BGM/封面 → 多平台发布"全链路自动化为核心特征的一类产品。通过调研市面主流产品的平台分布、功能模块、业务逻辑、技术实现与商业模式，为我们自己的口播IP智能体产品定义提供决策依据。

当前应用采用客户端、服务端、文档三层目录，服务端仍为模块化单体：

- 用户端 `client/apps/web`：内容创作、套餐展示、激活码兑换、积分报价与任务执行。
- 管理端 `client/apps/admin`：套餐 SKU、价格版本、激活码、用户、Provider、成本与审计。
- 桌面端 `client/apps/desktop-shell`：用户端 Web 的 Tauri 壳。
- 后端 `server/`：用户数据面 `/api/v1/*`，管理控制面 `/api/admin/v1/*`。两类 JWT 使用不同 audience，不能跨端复用。
- 项目文档 `docs/`：按产品、架构、工程、运营与设计资料分类；本地开发基础设施在 `infra/`，自动化工具和端到端测试在 `tools/`。

## 本地启动

前端工具链要求 Node.js 22.22.0 或更高版本、pnpm 9 或更高版本。

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
ASR 或数字分身积分前验证上传媒体的真实时长；服务端 Docker 镜像已内置
FFmpeg、Chromium 和真实平台发布驱动，并以非 root 用户运行。

`infra/docker-compose.yml` 只用于本地开发，显式固定 `APP_ENV=dev`，不得直接用于
生产。默认不会启动合规 No-Go 的 IM 监听器；仅在授权的开发预研中使用
`docker compose -f infra/docker-compose.yml --profile im-research up im-listener`。

首次部署可临时设置 `BOOTSTRAP_ADMIN_PHONE` 和至少 12 位的
`BOOTSTRAP_ADMIN_PASSWORD`。管理员创建成功后，应从部署环境删除引导密码。
生产环境必须配置五把互不相同且至少 32 字节的随机密钥：
`APP_SECRET`、`CONFIG_ENCRYPTION_KEY`、`ACTIVATION_SECRET`、
`PUBLISH_SESSION_ENCRYPTION_KEY` 和 `FEIYING_WEBHOOK_SECRET`。生产启动还会
拒绝 SQLite、本地存储、非 HTTPS 公网媒体地址、非正式 Web/Tauri CORS 来源、
占位配置及有头浏览器。完整流程见 `docs/operations/16-生产切换上线检查清单.md`；供应商
密钥只保存在后端，用户端没有配置入口。

## 桌面端构建与分发

桌面端是 Web 用户端的 Tauri 壳，生产构建必须显式注入同一个正式 HTTPS API，
且路径必须以 `/api/v1` 结尾。HTTP、WebSocket 和 CSV 导出都会从该地址派生：

```bash
VITE_API_BASE='https://<正式API域名>/api/v1' \
  pnpm --filter @oral/desktop tauri:build --no-bundle
```

上述命令只证明桌面工程和生产前端可以编译，不代表安装包可对外分发。macOS 分发
必须配置正式 `APPLE_SIGNING_IDENTITY` 及一组完整的 Apple 公证凭证后执行：

```bash
VITE_API_BASE='https://<正式API域名>/api/v1' \
  pnpm --filter @oral/desktop check:distribution
VITE_API_BASE='https://<正式API域名>/api/v1' \
  pnpm --filter @oral/desktop release:mac
```

当前没有启用自动更新插件：仓库尚未引入更新依赖、更新服务器和签名公钥，客户端
不得宣称支持自动更新。Windows 签名安装包必须在受控 Windows CI/机器完成构建、
签名和安装验证。详细状态见 `docs/operations/18-Gate5桌面端与IM收口验收记录.md`。

价格目录首次启动会从旧流水线固定扣费生成 `legacy-v1` 已发布版本，保证迁移前后扣费口径一致。后续价格变更必须新建并发布版本，已报价或已冻结的任务继续使用原价格快照。

包年套餐首月积分在激活时发放，后续按 30 天周期在用户查询余额或订阅时幂等补发，且不超过套餐到期日。积分以带到期日的批次保存，冻结时优先消耗最早到期批次，取消或失败时按原批次恢复。管理员赠送或扣减积分只能通过带原因的调整流水完成，不能直接改余额。

## 文档结构

文档入口见 [docs/README.md](docs/README.md)。主要权威资料为：

- [最终开发文档](docs/architecture/06-最终开发文档.md)：需求、技术架构和实施基线。
- [工程开发计划](docs/engineering/10-项目三阶段修复与开发计划-复审版.md)：阶段、门禁与验收口径。
- [生产切换检查清单](docs/operations/16-生产切换上线检查清单.md)：部署、迁移、回滚和停机检查。
- [UI 原型](docs/design/prototypes/ui-mockup/index.html)：静态页面和交互参考。

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
