# 22 - 腾讯云 COS 迁移与权限操作手册

## 1. 目标与边界

本手册用于把现有 MinIO/S3 对象迁移到腾讯云 COS。迁移工具保持对象 Key 原样不变，不修改数据库中的媒体 Key，不自动删除源对象。

迁移执行顺序：

1. 使用只读源账号执行 `--dry-run`。
2. 给目标 COS 账号配置最小写入权限。
3. 正式迁移并保存 manifest/checkpoint。
4. 执行 `--verify-only`，核验数量、大小、可比较 ETag 和确定性抽样 SHA-256。
5. 灰度切换 `STORAGE_DRIVER=s3` 与腾讯云 COS 配置。
6. 保留源存储只读观察期，确认无回滚需求后再制定清理计划。

## 2. CAM 最小权限

模板位于：

- `deploy/tencent-cos/cam-runtime-policy.template.json`
- `deploy/tencent-cos/cam-migration-source-policy.template.json`

替换 `${REGION}`、`${APPID}`、`${BUCKET}`、`${PREFIX}` 后导入 CAM。生产程序与迁移源账号必须分离；禁止使用主账号密钥，禁止授予 `action: *` 或不限定 Bucket 的 `resource: *`。

运行时账号需要：HeadBucket、Get/Head/Put/Delete Object，以及分块上传的初始化、上传、列举、完成和终止权限。源迁移账号仅需列举 Bucket、Head/Get Object。

## 3. 环境变量

密钥只允许通过环境变量或部署平台 Secret 注入，不支持命令行密钥参数。

```bash
export SOURCE_S3_ENDPOINT=http://minio.internal:9000
export SOURCE_S3_REGION=us-east-1
export SOURCE_S3_BUCKET=oral-media
export SOURCE_S3_ACCESS_KEY='***'
export SOURCE_S3_SECRET_KEY='***'

export S3_ENDPOINT=https://cos.ap-guangzhou.myqcloud.com
export S3_REGION=ap-guangzhou
export S3_BUCKET=oral-media-1250000000
export S3_ACCESS_KEY='CAM SecretId'
export S3_SECRET_KEY='CAM SecretKey'
```

腾讯云 Bucket 必须使用 `BucketName-APPID` 完整名称，Endpoint 不包含 Bucket 名。

## 4. Dry Run

```bash
cd server
uv run python scripts/migrate_storage_to_cos.py \
  --source-addressing-style path \
  --target-addressing-style virtual \
  --manifest /secure/cos-migration-manifest.jsonl \
  --checkpoint /secure/cos-migration-checkpoint.json \
  --dry-run
```

Dry Run 只列举源对象并写入 `planned` 记录，不调用目标上传接口。

## 5. 正式迁移

```bash
cd server
uv run python scripts/migrate_storage_to_cos.py \
  --source-addressing-style path \
  --target-addressing-style virtual \
  --sample-sha256-rate 0.10 \
  --multipart-threshold-mb 64 \
  --multipart-chunksize-mb 16 \
  --max-concurrency 4 \
  --manifest /secure/cos-migration-manifest.jsonl \
  --checkpoint /secure/cos-migration-checkpoint.json
```

工具行为：

- 对象 Key 原样写入目标 Bucket。
- 已存在且大小一致的对象先验证再跳过。
- 每个对象完成后原子更新 checkpoint。
- manifest 使用 JSONL 追加写入并 `fsync`。
- 普通 ETag 仅在源和目标都不是 multipart ETag 时比较。
- SHA-256 抽样由 Key 哈希确定，同一参数重复运行抽样集合保持一致。
- 发生错误后返回非零退出码，不自动删除源对象。

## 6. 断点续传

```bash
uv run python scripts/migrate_storage_to_cos.py \
  --resume \
  --manifest /secure/cos-migration-manifest.jsonl \
  --checkpoint /secure/cos-migration-checkpoint.json
```

`--resume` 会从 manifest 中读取 `copied`、`verified`、`skipped_existing` 状态并跳过已完成 Key。不得删除或人工编辑 manifest；确需修正时先复制留档。

## 7. 只验证

```bash
uv run python scripts/migrate_storage_to_cos.py \
  --verify-only \
  --sample-sha256-rate 0.10 \
  --manifest /secure/cos-verify-manifest.jsonl \
  --checkpoint /secure/cos-verify-checkpoint.json
```

验收条件：

- `errors=0`。
- 源对象均能在 COS 找到。
- 对象大小一致。
- 可比较 ETag 一致。
- 抽样 SHA-256 一致。
- 应用 `/readyz` 中 `dependencies.storage.ok=true`。

## 8. 灰度与回滚

切换前冻结写入或安排短暂停机窗口，执行最后一轮增量迁移与验证。切换后 API、Worker 和 Migration 必须使用同一环境变量版本。

需要回滚时：

1. 停止新任务和 Worker。
2. 恢复上一版环境变量与镜像。
3. 将源存储恢复为读写。
4. 验证 `/readyz`、媒体播放和一个最小流水线。
5. COS 中新增对象暂不删除，待差异清单核对后处理。

## 9. 安全要求

- manifest、checkpoint、控制台输出均不得出现 SecretId/SecretKey。
- 文件应放在权限受控目录，不提交 Git。
- CAM 密钥切换完成后立即轮换迁移临时账号。
- 生产 COS 建议启用版本控制、生命周期、访问日志和告警。
- 未完成 `--verify-only` 前不得下线源存储。
