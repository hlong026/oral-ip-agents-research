# 后台用户调用记录查看功能设计规范 (ADMIN USAGE VIEW)

**状态**: Draft  
**版本**: v1.0  
**日期**: 2026-07-30  
**负责人**: Qoder  

---

## 📋 需求背景

### 业务痛点
当前后台用户在查看用户清单时：
- ❌ 只能看到激活码掩码（如 `****1234`），无法获取完整信息
- ❌ 无法通过激活码定位用户的全部调用记录
- ❌ 无法追踪用户的积分消耗明细和任务执行情况
- ❌ 客服/运营需要跨多个系统查询用户数据，效率低下

### 核心目标
构建一个完整的"激活码 → 用户 → 调用记录"三阶联动查询系统，使管理员能够：
- ✅ 在用户列表中直接查看每个用户的完整调用历史
- ✅ 按用户/激活码筛选和搜索调用记录
- ✅ 导出单个用户的消费明细用于对账
- ✅ 快速诊断用户的积分异常问题

---

## 🏗️ 架构设计

### 数据流向
```mermaid
graph LR
    A[Admin Frontend] --> B[Admin API Gateway]
    B --> C{Route}
    C -->|GET /admin/v1/users/{id}/usage | D[Billing Repository]
    C -->|GET /admin/v1/users | E[Auth Repository]
    C -->|GET /admin/v1/activation-codes | F[Activation Repository]
    D --> G[(PostgreSQL/SQLite)]
    E --> G
    F --> G
    G -->|Return Usage Records| D
    G -->|Return User Info| E
    G -->|Return Activation Codes| F
    D -->|JSON Response| B
    B -->|Rendered HTML| A
```

### 模块职责划分

#### 后端 (Server-side)
| 组件 | 职责 | 技术栈 |
|------|------|--------|
| `modules/admin/router.py` | Admin 路由聚合 | FastAPI Router |
| `modules/billing/repository.py` | 用量查询数据访问 | SQLAlchemy Async |
| `modules/activation/models.py` | 激活码 ORM | SQLAlchemy |
| `core/db.py` | 数据库连接池 | SQLAlchemy Engine |

#### 前端 (Admin Portal)
| 组件 | 职责 | 技术栈 |
|------|------|--------|
| `UsersPage.tsx` | 主列表页 + 用户详情 Drawer | React + TanStack Query |
| `UserUsageDrawer.tsx` | 用户详情弹窗组件 | React + Tailwind |
| `AdminApi.ts` | HTTP 客户端封装 | TypeScript Fetch API |

---

## 🎯 功能需求

### FR1: 用户列表增强

#### 页面位置
- **路径**: `/admin/users` (现有 UsersPage)
- **触发方式**: 点击"👁️ 查看"按钮或用户行内任意区域

#### UI 布局
采用 **Drawer (侧滑抽屉)** 方案，避免模态框遮挡过多上下文：

```tsx
┌─────────────────────────────────────────┐
│  User Details           [X Close]       │
├─────────────────────────────────────────┤
│                                          │
│  ┌─ Basic Information ────────────────┐ │
│  │ Name:          张三                 │ │
│  │ Phone:         138****5678          │ │
│  │ Activation:    DY·ABCD****1234      │ │ ← 完整激活码可复制
│  │ Balance:       9,876 points         │ │
│  │ Plan:          premium_monthly      │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  ┌─ Usage History ────────────────────┐ │
│  │ ⏱️ Time │ Step    │ Points │ Trace ID  │
│  │────────────────────────────────────│  │
│  │ 07/30   │ tts     │ -80    │ abc... │ │
│  │ 07/30   │ voice   │ -120   │ def... │ │
│  │ 07/29   │ compose │ -30    │ ghi... │ │
│  │ ...                              │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  [Export CSV]  [Adjust Credits]          │
└─────────────────────────────────────────┘
```

#### 数据展示规则
- **基本信息区**：显示静态用户数据 + 完整掩码激活码
- **调用记录表**：分页表格（默认每页 20 条）
  - 字段：时间戳、步骤名、积分变化、trace_id、操作链接
  - 排序：最新优先
  - 高亮：负数积分（退款）用绿色标记
- **操作区**：CSV 导出按钮 + 积分调整入口

---

### FR2: 后端 API 新增

#### API Endpoint 定义

##### 1. GET `/admin/v1/users/{user_id}/usage`

**用途**: 查询指定用户的分页调用记录

**请求参数**
```typescript
interface GetUserUsageRequest {
  user_id: string;  // URL Path
  page?: number;     // Query String, default 1
  pageSize?: number; // Query String, default 20, range [1, 100]
  step?: string;     // Optional filter: "tts", "voice", etc.
  startDate?: string;// Optional ISO date, e.g., "2026-07-01"
  endDate?: string;  // Optional ISO date
}
```

**响应结构**
```typescript
interface GetUserUsageResponse {
  items: UsageItem[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

interface UsageItem {
  id: string;                    // QuotaUsage ID
  traceId: string;               // 任务追踪 ID
  taskId: string;                // 任务 ID
  step: string;                  // 步骤名
  resolution: string;            // 分辨率
  points: number;                // 积分（正扣费，正退还）
  compute: string;               // "cloud" | "local"
  createdAt: string;             // ISO 8601 timestamp
}
```

**错误处理**
| HTTP Code | Error Code | Message |
|-----------|------------|---------|
| 404 | USER_NOT_FOUND | 用户不存在 |
| 403 | ACCESS_DENIED | 尝试访问其他管理员的数据 |
| 422 | INVALID_DATE_FORMAT | 日期格式错误 |

**实现伪代码**
```python
@router.get("/users/{user_id}/usage")
async def admin_get_user_usage(
    user_id: str,
    page: int = Query(1),
    pageSize: int = Query(20),
    step: str | None = None,
    startDate: str | None = None,
    endDate: str | None = None,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # 权限校验：admin 只能看自己创建的 or 全看？
    if not await is_same_org(_admin_id, user_id):
        raise HTTPException(403, "无权限访问该用户数据")
    
    # 基础查询
    query = select(QuotaUsage).where(QuotaUsage.user_id == user_id)
    
    # 可选过滤
    if step:
        query = query.where(QuotaUsage.step == step)
    if startDate:
        query = query.where(QuotaUsage.created_at >= parse_iso(startDate))
    if endDate:
        query = query.where(QuotaUsage.created_at <= parse_iso(endDate))
    
    # 分页
    total = count(query)
    records = query.order_by(QuotaUsage.created_at.desc()).offset(offset).limit(limit)
    
    return {
        "items": serialize_usage_records(records),
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "hasMore": (page * pageSize) < total
    }
```

---

##### 2. GET `/admin/v1/users/{user_id}/usage?export=csv`

**用途**: 导出单个用户的完整消费明细

**实现复用现有逻辑**
- 复用 `billing/router.py` 中的 `api_usage()` 导出函数
- 仅修改 `user_id` 来源 (URL path vs auth token)

**CSV 格式**
```csv
时间，步骤，分辨率，点数，通道，trace_id
2026-07-30T14:23:01+08:00,tts,1080p,-80,cloud,abc123def456
2026-07-30T14:22:58+08:00,voice,1080p,-120,cloud,def456ghi789
```

---

### FR3: 前端组件拆分

#### Component: UserUsageDrawer

**Props 接口**
```typescript
interface UserUsageDrawerProps {
  userId: string;
  userName: string;
  userPhone: string;
  activationCodeMasked: string | null;
  balance: number;
  onClose: () => void;
}
```

**状态管理**
```typescript
// TanStack Query hooks
const { data: usageData } = useQuery({
  queryKey: ['admin-user-usage', userId],
  queryFn: () => adminApi.getUserUsage(userId),
});

const { mutate: exportCsv } = useMutation({
  mutationFn: (userId: string) => 
    adminApi.downloadUserUsageCsv(userId),
});
```

**UI 交互**
- **打开动画**: 从右侧滑入 (transition: transform 300ms ease-out)
- **加载状态**: Skeleton 骨架屏占位
- **空状态**: "暂无调用记录" 文案 + 图标
- **错误处理**: Toast 提示 + 重试按钮

---

## 🎨 视觉设计规范

### 色彩系统
| 元素 | Primary Color | Secondary | Alert | Success |
|------|---------------|-----------|-------|---------|
| 积分扣减 | `#EF4444` | - | - | - |
| 积分退还 | `-` | - | - | `#10B981` |
| 边框线 | `#E5E7EB` | `#F3F4F6` | - | - |
| 文字主色 | `#1F2937` | `#6B7280` | `#DC2626` | `#065F46` |

### 排版规范
- **标题层级**: H2 = 20px semi-bold, H3 = 16px medium
- **正文**: 14px regular, 行高 1.5
- **等宽数字**: `font-family: 'JetBrains Mono', monospace`

### 间距系统
- **区块间隔**: 24px
- **字段间距**: 12px
- **边距**: 16px (移动端 12px)

### 组件规格
```tsx
// Drawer 宽度
width: 800px (md breakpoint: 100%)
maxWidth: calc(100vw - 32px)

// 圆角
borderRadius: 8px (content areas), 0 (full-screen drawer)

// 阴影
boxShadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1)
```

---

## 🔐 安全与权限控制

### 权限矩阵
| 角色 | 查看他人数据 | 导出 CSV | 调整积分 |
|------|-------------|----------|---------|
| Super Admin | ✅ | ✅ | ✅ |
| Operator | ✅ | ✅ | ❌ |
| Viewer | ❌ | ❌ | ❌ |

**实现策略**: 后端所有 API 需校验 `X-Admin-Role` header 或使用 OAuth2 scope

### 审计日志
所有敏感操作需记录到 `audit_logs` 表：
```sql
INSERT INTO audit_logs (
  event_type, user_id, target_id, detail, ip_address
) VALUES (
  'admin_user_usage_viewed',
  current_admin_id,
  requested_user_id,
  '{"page":1,"step":"tts"}',
  client_ip
);
```

---

## 🧪 测试策略

### 单元测试覆盖率目标
- **后端**: ≥ 90% (SQLAlchemy queries + Pydantic validation)
- **前端**: ≥ 80% (React components + Query hooks)

### 关键测试用例

#### Backend Tests
```python
@pytest.mark.asyncio
async def test_admin_can_view_user_usage(user, admin_user):
    # Create usage records
    for i in range(50):
        await create_quota_usage(user.id, step="tts", points=-100)
    
    # Make request
    response = await client.get(f"/admin/v1/users/{user.id}/usage?page=1&pageSize=20")
    
    # Assert
    assert response.status_code == 200
    assert len(response.json()["items"]) == 20
    assert response.json()["total"] == 50

@pytest.mark.asyncio
async def test_admin_cannot_view_other_user_usage(user, other_admin):
    # Unauthorized access attempt
    response = await client.get(f"/admin/v1/users/{user.id}/usage")
    assert response.status_code == 403
```

#### Frontend Tests (Jest + React Testing Library)
```tsx
test('UserUsageDrawer displays usage records correctly', async () => {
  const mockUsageData = {
    items: [{ id: '1', step: 'tts', points: -100, createdAt: '...' }],
    total: 1,
    page: 1,
    pageSize: 20
  };
  
  render(
    <MockQueryWrapper>
      <UserUsageDrawer 
        userId="123" 
        userName="张三" 
        onClose={mockOnClose} 
      />
    </MockQueryWrapper>
  );
  
  await waitFor(() => expect(screen.getByText('张三')).toBeInTheDocument());
  expect(screen.getByText('tts')).toBeInTheDocument();
});
```

---

## 📊 性能优化

### 数据库层面
1. **索引策略**
   ```sql
   CREATE INDEX idx_quota_usage_user_created ON quota_usage(user_id, created_at DESC);
   CREATE INDEX idx_activation_code_bound ON activation_codes(bound_user_id) 
     WHERE bound_user_id IS NOT NULL;
   ```

2. **查询优化**
   - 使用覆盖索引避免回表
   - 分页限制 `LIMIT 100` 防止深分页扫描
   - 日期范围查询强制走索引

3. **连接池配置**
   ```python
   # core/db.py
   engine = create_async_engine(
       DATABASE_URL,
       pool_size=10,
       max_overflow=20,
       pool_recycle=3600,
   )
   ```

### 前端层面
1. **懒加载**
   - Drawer 内容异步渲染
   - 初始只加载第一页数据

2. **缓存策略**
   ```typescript
   const queryClient = useQueryClient();
   // Cache duration: 5 minutes
   queryClient.prefetchQuery({
     queryKey: ['admin-user-usage', userId],
     gcTime: 5 * 60 * 1000,
   });
   ```

3. **虚拟化列表**
   - 超过 50 条记录启用 `react-window` 虚拟滚动
   - 避免 DOM 节点过多导致重绘卡顿

---

## 🚀 上线计划

### 阶段一：MVP (Minimum Viable Product)
- [ ] 后端 API 基本查询功能
- [ ] 前端 Drawer 基础视图
- [ ] 单位置集成验证

### 阶段二：完善功能
- [ ] 日期/步骤筛选
- [ ] CSV 导出增强
- [ ] 审计日志接入

### 阶段三：生产发布
- [ ] 灰度发布 (10% 流量)
- [ ] 监控告警配置
- [ ] 文档更新 + 培训

---

## 📈 监控指标

### 后端埋点
| Metric | Type | Description |
|--------|------|-------------|
| `admin_usage_api_latency_ms` | Histogram | P95 < 200ms |
| `admin_usage_query_error_rate` | Counter | < 0.1% |
| `admin_user_profile_views_per_day` | Gauge | DAU 趋势 |

### 前端埋点
| Event | Payload | Trigger |
|-------|---------|---------|
| `drawer_open` | `{ user_id, source }` | User clicks "View" button |
| `usage_page_change` | `{ page, total }` | Pagination switch |
| `csv_export_click` | `{ user_id, record_count }` | Export button click |

---

## 🔗 依赖关系

### 外部依赖
| 库名 | 版本 | 用途 | License |
|------|------|------|---------|
| fastapi | >=0.104.0 | Web framework | BSD |
| sqlalchemy | >=2.0.0 | ORM | MIT |
| react-query | ^5.0 | Data fetching | MIT |
| tailwindcss | ^3.3.0 | Styling | MIT |

### 内部依赖
- `modules/billing`: 用量数据源
- `modules/auth`: 用户身份验证
- `core/audit`: 审计日志服务

---

## 📚 相关文档

- [计费系统设计文档](./docs/billing-design.md)
- [后台管理 API 规范](./docs/admin-api-spec.md)
- [设备绑定与安全模型](./docs/device-binding-security.md)

---

**文档维护者**: @qoder  
**最后更新**: 2026-07-30  
**下次评审日期**: 2026-08-06
