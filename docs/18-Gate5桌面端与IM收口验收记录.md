# 18 - Gate 5 桌面端与 IM 收口验收记录

> 验收日期：2026-07-31
> 结论：桌面端工程构建 **Go**；桌面安装包对外分发 **No-Go**；IM 生产放量 **No-Go**

## 1. 本阶段收口范围

本阶段只处理能够由仓库代码和本地验证闭环的事项：

1. 桌面端 HTTP、WebSocket 和 CSV 导出统一使用构建时注入的正式 API；
2. 桌面构建拒绝相对地址、HTTP、localhost、IP/内网/保留域名、凭证嵌入、
   查询参数和非 `/api/v1` 地址；
3. 启用 Tauri CSP、固定主窗口标签、显式 capability 和 Windows HTTPS scheme；
4. 后端生产 CORS 仅接受正式 HTTPS Web 来源及两个固定 Tauri 来源；
5. macOS 分发前拒绝临时签名和不完整公证凭证；
6. IM 七日工具支持完全离线的退出门禁评估。
7. 灰度账号数量上限在 PostgreSQL 中使用事务级 advisory lock 原子执行，避免并发
   管理员同时越过上限。
8. IM 公开发送、重试和自动发送授权入口从后端路由、API Client 和前端移除。
9. 历史 `auto` 规则在只读配置下强制降级为建议，不进入发送队列。
10. 桌面抖音官方页面按账号使用独立、哈希化的数据目录，不共享登录态。
11. 全局 Kill Switch 同时停止现有监听意图并阻止 Worker 恢复或创建新监听。

真实签名、公证、Windows 安装、正式域名/TLS、真实 Provider 与连续七日 IM
运行都依赖外部环境或账号，不能由本地测试替代。

## 2. 已完成的代码门禁

### 2.1 远程 API 链路

- `VITE_API_BASE` 必须是公网正式域名的绝对 HTTPS 地址，且路径以 `/api/v1`
  结尾。
- API 客户端统一通过 `buildApiUrl` 拼接请求和 CSV 导出地址。
- 任务 WebSocket 从同一 API 来源派生：`https` 自动转换为 `wss`，路径固定为
  `/ws/tasks`。
- 相对 API 地址只保留给浏览器同源开发场景，桌面生产检查不允许使用。

### 2.2 Tauri 安全边界

- CSP 已从关闭改为显式策略；脚本只允许本地来源，连接只允许 IPC、HTTPS 和 WSS。
- 主窗口固定为 `main`，capability 固定为 `default`，没有新增文件系统或 Shell 权限。
- Windows WebView 使用 HTTPS scheme，对应后端固定 CORS 来源
  `https://tauri.localhost`。
- 已移除 macOS `signingIdentity: "-"`。没有正式签名身份时，分发检查直接失败。

CORS 只约束浏览器来源，不替代 JWT、桌面包签名或服务端权限校验；固定 Tauri 来源
不应被当作客户端身份凭据。

`connect-src` 中的 `https:` / `wss:` 是协议级限制，用于构建时才确定的正式 API，
不是目标主机白名单。桌面业务 API 由构建值锁定，真正的访问控制仍由 JWT、后端
权限、TLS 和已签名安装包共同完成。

### 2.3 分发前检查

`scripts/check-desktop-release.mjs` 分为两层：

- `check:release`：所有桌面生产构建必须通过的代码与配置检查；
- `check:distribution`：在上述检查基础上，macOS 还必须具备正式签名身份，以及
  App Store Connect API 或 Apple ID 公证凭证中的完整一组。

检查脚本不打印凭证内容。当前 `check:distribution` 只完成 macOS 直接分发预检；
Linux 和 Windows 都会失败关闭。Windows 必须另行建立受控 CI 签名与安装验收门禁。

### 2.4 IM 灰度上限

管理员批准灰度账号时，数量判断与启用操作在同一临界区完成：

- 生产 PostgreSQL 使用事务级 `pg_advisory_xact_lock`，覆盖多进程 API 副本；
- 开发/测试数据库使用进程锁，保证本地并发回归可重复；
- 重复批准已经启用的同一账号不额外占用名额；
- 达到上限时事务回滚并返回 `IM_GRAY_LIMIT_REACHED`。

### 2.5 IM 只读与多账号边界

- `IM_LISTEN_ONLY=true` 是当前生产绑定，公开 OpenAPI 不包含发送、失败重试或自动发送授权路由。
- 规则页面只能保存 `deliveryMode=suggestion`；数据库中的历史 `auto` 规则也会被服务层
  强制写成 `suggested` 并标记 `ListenOnlyMode`。
- 人工回复只打开抖音官方页面，不注入脚本、不代替用户点击发送。
- 桌面窗口标签和 WebView `data_directory` 都由账号 ID 的 SHA-256 摘要派生；原始账号 ID
  不进入路径，不同账号不会复用同一会话目录。
- 全局急停将监听状态改为断开，`start_listener` 返回 `IM_GLOBAL_STOPPED`，独立 Worker
  在恢复连接前再次检查开关。
- 七日退出门禁要求每天存在在线监听和真实连接尝试，同时要求
  `sendSuccess + sendFailure == 0`；任何服务端发送活动都判定失败。

### 2.6 人工升级与回滚策略

当前未引入自动更新依赖。正式分发前采用以下人工流程：

1. 每个发布版本保存已签名安装包、SHA-256 校验值、版本号和对应 commit；
2. 发布通知明确最低服务端版本、升级窗口和数据备份要求；
3. 用户退出应用后覆盖安装，不删除应用数据目录，因此登录态和本地令牌按现有策略保留；
4. 至少保留上一个已签名稳定版本；需要回滚时退出应用并覆盖安装该版本；
5. 服务端 API 和数据库迁移必须在回滚窗口内向前兼容。若某次迁移无法无损回退，
   该版本不得沿用本流程，必须单独提供数据回滚脚本和停机方案；
6. macOS 公证、Windows 签名、干净机器安装/覆盖/回滚验证均属于外部门禁，未取得证据时
   仍为 `EXTERNAL_BLOCKED`。

## 3. 当前验证证据

### 3.1 已通过

```text
桌面发布检查脚本：3 passed
后端完整测试：478 passed, 1 skipped
Web 完整测试：62 passed
Admin 完整测试：10 passed
Playwright 端到端：6 passed
Ruff / Mypy / Prettier / TypeScript：passed
实时 OpenAPI 契约零漂移：passed
秘密扫描：758 个受版本控制文件通过
pnpm audit / pip-audit：无已知漏洞
桌面 release 配置检查：passed
cargo test --locked：2 passed
cargo check --locked：passed
Tauri release no-bundle 构建：passed
```

Tauri release 二进制已在本地生成，证明 Rust 壳、生产 Web 资源和当前配置能够完成
工程编译。本次结构门禁使用合成 HTTPS API 地址，只验证地址和构建约束，不证明该域名、
DNS、TLS 或远端 API 可用。该二进制也不是签名、公证后的交付安装包。

### 3.2 按设计拒绝

未提供 Apple 分发凭证时：

```text
macOS 分发必须配置正式 APPLE_SIGNING_IDENTITY，禁止临时签名
```

2026-07-31 对现有 IM 证据执行离线退出门禁时：

```text
requiredDates: 2026-07-25 ... 2026-07-31
availableDates: []
exitReady: false
reason: 连续证据不足 7 天
exit code: 3
```

以上是门禁正确工作，不是构建失败。

## 4. 发布状态矩阵

| 模块           | 工程状态             | 对外发布状态 | 剩余硬门槛                                             |
| -------------- | -------------------- | ------------ | ------------------------------------------------------ |
| Web/API/Worker | 本地发布工程已收口   | 条件 Go      | 远程 CI、正式域名/TLS、真实 Provider 和 staging 全链路 |
| macOS 桌面端   | release 工程编译通过 | No-Go        | 正式 API、开发者签名、公证、干净机器安装与运行验收     |
| Windows 桌面端 | 配置门禁已收口       | No-Go        | Windows CI 构建、代码签名、安装/卸载和远程链路验收     |
| 自动更新       | 人工升级/回滚流程已定义，自动更新未实现 | No-Go | 更新服务、Tauri updater 依赖、离线私钥和公钥 |
| 抖音 IM        | 只读代码门禁已收口   | No-Go        | 授权真实账号、监听实证、连续七天指标与负责人签署       |

## 5. 外部收口顺序

1. 确定正式 API 域名并完成 DNS/TLS、CORS 和对象存储回源验证；
2. 用真实 Provider 在 staging 完成文案、声音、数字人、合成、计费和发布闭环；
3. 配置 Apple 签名/公证，在干净 macOS 机器验收安装包；
4. 在 Windows CI/机器完成签名安装包和干净机验收；
5. 获得受控 IM 账号后，从新的连续七天窗口采集证据；
6. 所有硬门槛通过后，由发布负责人分别签署 Web、桌面和 IM 的 Go 决策。

任一外部门槛缺失时，系统应保持当前失败关闭状态，不通过修改配置、跳过检查或使用
Mock 结果绕过。
