"""pipeline 领域事件定义（进度经 core.events 总线推送，engine._emit/_feed 统一出口）"""

# 任务进度：{"kind": "task_updated", "taskId", "userId"} → CHANNEL_TASKS
# 动态流：  {"kind": "feed", "event": {...}, "userId"}      → CHANNEL_FEED
# 降级事件：{"kind": "provider_fallback", ...}               → CHANNEL_TASKS（registry 发出）
