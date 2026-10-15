# 技术实现说明

本文档详细说明项目的技术实现细节，包括架构设计、关键模块和实现策略。

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         Client                               │
│                   (React + TypeScript)                       │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP/JSON
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Service                               │
│            (FastAPI + SQLAlchemy)                            │
│  - 订单 CRUD                                                 │
│  - 状态查询                                                   │
│  - SSE 推送（待实现）                                         │
└────────────────────┬────────────────────────────────────────┘
                     │ Database
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   SQLite Database                            │
│  - orders（订单表）                                           │
│  - jobs（任务表）                                             │
│  - payment_attempts（支付尝试记录）                           │
└────────────────────┬────────────────────────────────────────┘
                     │ Polling
                     ▼
┌─────────────────────────────────────────────────────────────┐
│               Orchestrator Worker                            │
│  - 轮询待处理任务                                             │
│  - 驱动状态机推进                                             │
│  - 调用 adapter 执行业务逻辑                                  │
└────────────────────┬────────────────────────────────────────┘
                     │ Adapter Protocol
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Adapters                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │  Checkout    │ │   Payment    │ │   Account    │        │
│  │   Adapter    │ │   Adapter    │ │   Adapter    │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## 核心模块详解

### 1. packages/contracts - 领域模型与契约

**职责**：定义领域模型、状态机规则、adapter 协议。

**关键组件**：

- `OrderStatus`：订单状态枚举（created → pending_checkout → awaiting_payment → paying → verifying → active → delivered）
- `PaymentStatus`：支付状态枚举（succeeded, declined, requires_action, processing, error）
- `BillingMode`：计费模式（standard 正价, promo 促销）
- `Plan`：订阅套餐（plus, pro_lite, pro, pro_max）
- `state_machine.py`：状态转换规则与验证

**设计原则**：
- 所有状态转换都是显式的，不允许跳跃
- 状态机是纯函数，便于测试
- 通过类型系统保证契约安全

### 2. packages/core - 核心工具库

**职责**：提供脱敏、配置加载等通用能力。

**关键组件**：

- `redaction.py`：统一脱敏层
  - 自动脱敏 session token、access token、cookie、卡号等敏感信息
  - logging 过滤器自动处理所有日志
  - 正则匹配 + 上下文感知

- `config.py`：配置加载
  - 从环境变量读取配置
  - 提供默认值
  - 检测缺失的上游配置

### 3. services/api - API 服务

**职责**：提供 RESTful API，处理订单 CRUD。

**技术栈**：
- FastAPI：现代异步 Web 框架
- SQLAlchemy：ORM 框架
- Pydantic：数据验证

**关键模块**：

- `db.py`：数据库连接与 ORM 模型
  ```python
  class OrderModel(Base):
      __tablename__ = "orders"
      id = Column(String, primary_key=True)
      status = Column(String, nullable=False)
      plan = Column(String, nullable=False)
      # ...
  ```

- `repository.py`：数据访问层（Repository 模式）
  ```python
  class OrderRepository:
      def create_order(self, order: Order) -> Order
      def get_order(self, order_id: str) -> Order
      def update_status(self, order_id: str, status: OrderStatus)
      def list_orders(self, status, limit) -> List[Order]
  ```

- `routers/orders.py`：订单路由
  - POST /api/orders - 创建订单
  - GET /api/orders/{id} - 查询订单
  - GET /api/orders - 列出订单

**设计亮点**：
- Repository 模式隔离数据访问逻辑
- ORM 模型与领域模型分离
- 使用 Pydantic 进行请求/响应验证

### 4. services/orchestrator - 编排引擎

**职责**：轮询任务、驱动状态机、协调各个 adapter。

**核心逻辑**：

```python
class WorkerEngine:
    async def process_jobs(self, repo, max_jobs):
        # 1. 查询待处理订单
        # 2. 占锁（乐观锁）
        # 3. 根据订单状态调用对应的处理阶段
        # 4. 更新状态
        # 5. 释放锁
    
    async def drive_order(self, repo, order, job):
        if order.status == OrderStatus.CREATED:
            await self.stage_checkout(...)
        elif order.status == OrderStatus.AWAITING_PAYMENT:
            await self.stage_payment(...)
        elif order.status == OrderStatus.VERIFYING:
            await self.stage_verify(...)
        # ...
```

**断点续跑机制**：
- 每个订单有对应的 Job 记录
- Job 包含：stage（当前阶段）、locked_by（锁持有者）、attempts（重试次数）
- 锁超时机制防止死锁（5 分钟超时）

**错误处理**：
- 业务错误（DomainError）：记录错误并重试
- 系统错误：记录日志并释放锁
- 达到最大重试次数：标记订单失败

### 5. Adapter 层 - 上游隔离

**设计原则**：
- **所有代码自己实现**，不依赖上游项目代码
- 仅通过 HTTP API 与上游交互
- 提供 Fake 实现用于离线测试

#### 5.1 Checkout Adapter

**职责**：生成 ChatGPT 结账链接。

**实现策略**：
```python
async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
    # 1. 使用 session 构建 Authorization 头
    # 2. 调用 ChatGPT backend-api/payments/checkout
    # 3. 提交套餐、支付方式、账单国家等信息
    # 4. 解析响应，提取结账链接
    # 5. 处理错误（401 session 失效、403 被拦截等）
```

**错误处理**：
- 401：Session 失效 → `INVALID_SESSION`
- 403：Cloudflare 拦截 → `CHECKOUT_UPSTREAM_ERROR`（提示更换代理）
- 超时：网络问题 → `CHECKOUT_UPSTREAM_ERROR`

#### 5.2 Payment Adapter

**职责**：执行直卡支付。

**实现策略**：
```python
async def pay(self, req: PaymentRequest) -> PaymentResult:
    # 1. 访问结账链接，获取 checkout session
    # 2. 构建支付 payload（包含卡信息或 payment_method_token）
    # 3. 使用支付代理提交支付请求
    # 4. 处理响应：
    #    - 302/303：3DS 重定向 → REQUIRES_ACTION
    #    - 200 succeeded：支付成功 → SUCCEEDED
    #    - 402/400：支付被拒 → DECLINED
    #    - 5xx：服务错误 → ERROR（状态未知，需对账）
```

**代理策略**：
- checkout_proxy：访问结账页面时使用（账单国家代理）
- approve_proxy：提交支付时使用（可能需要不同的代理）

**3DS 处理**：
- 检测 3DS 重定向（302/303 响应）
- 返回 `requires_action` 状态，包含验证 URL
- 客户在浏览器完成验证后，订单推进到 `paying`

#### 5.3 Account Adapter

**职责**：查询订阅状态（交付前校验）。

**实现策略**：
```python
async def subscription_status(self, session: str) -> SubscriptionInfo:
    # 1. 使用 session 调用 ChatGPT backend-api/me
    # 2. 解析响应中的订阅信息
    # 3. 判断订阅是否生效（status in ["active", "trialing", "paid"]）
    # 4. 提取到期时间、购买渠道等信息
```

**交付门槛**：
- 必须 `active=true` 且订阅接口确认生效
- 如果订阅未生效，保持 `verifying` 状态并重试
- 达到最大重试次数后标记失败

### 6. 数据持久化

**数据库设计**：

```sql
-- 订单表
CREATE TABLE orders (
    id TEXT PRIMARY KEY,           -- ord_xxxxx
    status TEXT NOT NULL,          -- 订单状态
    plan TEXT NOT NULL,            -- 套餐类型
    billing_country TEXT NOT NULL, -- 账单国家
    billing_mode TEXT NOT NULL,    -- 计费模式
    amount DECIMAL,                -- 金额
    currency TEXT,                 -- 货币
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 任务表（编排用）
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,        -- 关联订单
    stage TEXT NOT NULL,           -- 当前阶段
    checkout_url TEXT,             -- 结账链接
    locked_by TEXT,                -- 锁持有者
    locked_at TIMESTAMP,           -- 锁定时间
    attempts INTEGER DEFAULT 0,    -- 重试次数
    last_error TEXT,               -- 最后错误
    FOREIGN KEY(order_id) REFERENCES orders(id)
);

-- 支付尝试记录
CREATE TABLE payment_attempts (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    provider TEXT NOT NULL,        -- 支付提供商
    status TEXT NOT NULL,          -- 支付状态
    next_action TEXT,              -- 下一步操作（JSON）
    created_at TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(id)
);
```

**索引策略**：
- `orders.status`：按状态查询待处理订单
- `jobs.order_id`：快速查找订单的任务
- `jobs.locked_by`：查询被锁定的任务

### 7. 安全与合规

#### 7.1 凭证零持久化

**原则**：敏感凭证（session、卡号等）只在内存中流转，绝不落库。

**实现**：
- session：仅作为 API 请求参数传递，不存储在数据库
- payment_method_token：浏览器端生成，直接传给支付 API，不经过后端数据库
- card_number/cvv：只在浏览器端处理，后端永远不接触

**脱敏层**：
```python
# 所有日志自动脱敏
logger.info(f"Processing order {order_id} with session {session}")
# 实际输出：Processing order ord_123 with session ***
```

#### 7.2 默认安全配置

- 只监听 `127.0.0.1`（不对外暴露）
- 促销模式默认关闭（`GSS_ENABLE_PROMO_MODE=false`）
- 促销订单必须 `risk_acknowledged=true`

#### 7.3 审计与追踪

- 所有订单状态变更记录时间戳
- 所有支付尝试记录（包括失败原因）
- 所有任务执行记录（包括错误信息）

## 测试策略

### 单元测试

- `test_state_machine.py`：状态机转换规则（9 个测试）
- `test_mode.py`：模式开关逻辑（7 个测试）
- `test_redaction.py`：脱敏层（8 个测试）
- `test_config.py`：配置加载（6 个测试）

### 契约测试

- `test_adapters_smoke.py`：Adapter 协议契约（10 个测试）
- `test_pipeline.py`：流水线集成（9 个测试）

### 集成测试

- `test_database.py`：数据库持久化（1 个测试）

**测试覆盖率**：50 个测试，覆盖核心业务逻辑、状态机、数据持久化。

### Fake Adapter 策略

所有 adapter 提供 Fake 实现，用于离线测试：

```python
# 脚本式测试：控制支付结果序列
fake_payment = FakePaymentAdapter(
    scripted=[
        PaymentStatus.REQUIRES_ACTION,  # 第一次：需要 3DS
        PaymentStatus.SUCCEEDED,         # 第二次：成功
    ]
)
```

## 性能与扩展性

### 当前限制

- 单节点 worker（适合中小规模）
- SQLite 数据库（适合单机部署）
- 同步轮询（每 5 秒一次）

### 扩展路径

1. **水平扩展 worker**：
   - 使用分布式锁（Redis）替代数据库锁
   - 多个 worker 实例并行处理

2. **升级数据库**：
   - 迁移到 PostgreSQL 以支持更高并发
   - 添加连接池与读写分离

3. **优化轮询**：
   - 使用消息队列（RabbitMQ/Redis）替代轮询
   - 事件驱动架构

4. **缓存层**：
   - Redis 缓存订单状态
   - 减少数据库查询

## 部署架构

### 开发环境

```
API (uvicorn) + Worker (Python) + SQLite
```

### 生产环境

```
┌─────────────────────────────────────┐
│           Nginx / Caddy              │  (反向代理 + TLS)
└────────────┬────────────────────────┘
             │
┌────────────▼────────────────────────┐
│      API Service (容器)              │
│      - FastAPI                       │
│      - Gunicorn + Uvicorn            │
└────────────┬────────────────────────┘
             │
             │  SQLite / PostgreSQL
             ▼
┌────────────────────────────────────┐
│     Orchestrator Worker (容器)     │
│     - 状态机驱动                    │
│     - 断点续跑                      │
└────────────────────────────────────┘
```

## 未来优化方向

1. **SSE 实时推送**（T023-T024）
   - 客户端订阅订单状态变更
   - 实时推送状态更新

2. **批量任务**（T037-T041）
   - 支持批量创建订单
   - Canary 发布机制

3. **计费对账**（T042-T044）
   - 自动对账支付记录
   - 退款流程

4. **运营后台**（T045-T046）
   - 订单管理界面
   - 统计报表

5. **监控告警**
   - Prometheus metrics
   - 失败率告警
   - 性能监控
