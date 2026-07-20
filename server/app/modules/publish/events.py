"""publish 领域事件
- publish_updated → CHANNEL_TASKS：{"kind": "publish_updated", "jobId", "userId", "status"}
- 发布失败/登录态失效 → CHANNEL_ALERT（红色告警）
- 授权成功/发布成功 → CHANNEL_FEED（动态流）
"""
