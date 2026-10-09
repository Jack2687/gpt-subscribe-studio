# 快速开始指南

## 环境要求

- Python 3.12+
- Docker & Docker Compose（可选，用于生产部署）
- uv（Python 包管理器）

## 本地开发

### 1. 安装依赖

```bash
# 克隆项目
git clone <repo-url>
cd 直卡协议

# 使用 uv 安装所有依赖
uv sync --python 3.12
```

### 2. 配置环境

```bash
# 创建配置文件
cp deploy/.env.example deploy/.env

# 编辑配置（可选）
vim deploy/.env
```

关键配置项：

```env
# 数据库路径
DCP_DB_PATH=data/dcp.db

# 服务绑定地址（默认只监听 localhost）
DCP_BIND_HOST=127.0.0.1
DCP_BIND_PORT=8080

# 促销模式（默认关闭，需要显式开启）
DCP_ENABLE_PROMO_MODE=false

# 上游配置（可选，未配置时使用 Fake adapter）
UPSTREAM_GPT_REGISTER_TOOL_PATH=/path/to/GPT-Register-Tool
UPSTREAM_ZKKY_PATH=/path/to/zkky
```

### 3. 运行测试

```bash
# 运行所有测试（包括单元测试、契约测试、集成测试）
uv run --python 3.12 --with pytest pytest -v

# 只运行单元测试
uv run --python 3.12 --with pytest pytest tests/unit/ -v

# 只运行集成测试
uv run --python 3.12 --with pytest pytest tests/integration/ -v
```

### 4. 启动 API 服务

```bash
# 进入 API 服务目录
cd services/api

# 启动开发服务器
uv run --python 3.12 uvicorn dcp_api.main:app --reload --host 127.0.0.1 --port 8080
```

访问 http://127.0.0.1:8080/docs 查看 API 文档。

### 5. 启动 Orchestrator Worker

在另一个终端：

```bash
# 进入 orchestrator 目录
cd services/orchestrator

# 启动 worker（测试模式，使用 Fake adapter）
uv run --python 3.12 python -m dcp_orchestrator.worker --fake --poll-interval 5

# 或者使用真实 adapter（需要配置上游路径）
uv run --python 3.12 python -m dcp_orchestrator.worker --poll-interval 5
```

Worker 会轮询数据库中的待处理任务并驱动状态机推进。

## 使用 API

### 创建订单

```bash
# 创建一个测试订单
curl -X POST http://127.0.0.1:8080/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "plan": "plus",
    "billing_country": "US",
    "billing_mode": "standard",
    "card_source": "customer",
    "account_source": "customer_session"
  }'
```

响应示例：

```json
{
  "id": "ord_abc123",
  "status": "created",
  "plan": "plus",
  "billing_country": "US",
  "billing_mode": "standard",
  "created_at": "2026-10-09T12:00:00Z"
}
```

### 查询订单状态

```bash
curl http://127.0.0.1:8080/api/orders/ord_abc123
```

### 列出所有订单

```bash
curl http://127.0.0.1:8080/api/orders
```

## 测试模式（Fake Adapter）

当没有配置上游路径时，系统会自动使用 Fake adapter 进行测试：

- **FakeCheckoutAdapter**：生成假的结账链接
- **FakePaymentAdapter**：模拟支付成功
- **FakeAccountAdapter**：模拟订阅已激活

这样可以在不依赖真实上游服务的情况下测试完整流程。

## 生产部署（Docker Compose）

### 1. 构建镜像

```bash
cd deploy
docker compose build
```

### 2. 启动服务

```bash
# 启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 查看服务状态
docker compose ps
```

### 3. 健康检查

```bash
curl http://127.0.0.1:8080/api/health
```

### 4. 停止服务

```bash
docker compose down
```

## 核心工作流

### User Story 1: 客户提供 session，客户提供卡

1. **客户准备**：
   - 导出 ChatGPT session token
   - 准备支付卡信息

2. **创建订单**：
   ```bash
   POST /api/orders
   {
     "plan": "plus",
     "billing_country": "US",
     "billing_mode": "standard",
     "card_source": "customer",
     "account_source": "customer_session"
   }
   ```

3. **Worker 自动处理**：
   - `created` → 生成结账链接 → `pending_checkout`
   - 客户访问链接 → `awaiting_payment`
   - 执行支付 → `paying`
   - 支付成功 → `verifying`
   - 订阅校验通过 → `active`
   - 交付 → `delivered`

4. **客户查询**：
   ```bash
   GET /api/orders/{order_id}
   ```

## 常见问题

### Q: 如何切换到真实 adapter？

A: 在 `.env` 中配置上游路径：

```env
UPSTREAM_GPT_REGISTER_TOOL_PATH=/path/to/GPT-Register-Tool
UPSTREAM_ZKKY_PATH=/path/to/zkky
```

重启服务后会自动使用真实 adapter。

### Q: 如何开启促销模式？

A: 在 `.env` 中设置：

```env
DCP_ENABLE_PROMO_MODE=true
```

然后创建订单时指定 `billing_mode: "promo"`，并且必须设置 `risk_acknowledged: true`。

### Q: 数据存储在哪里？

A: SQLite 数据库文件位于 `data/dcp.db`（可通过 `DCP_DB_PATH` 配置）。

### Q: 如何查看详细日志？

A: 所有日志都经过脱敏处理。查看方式：

```bash
# API 服务日志
docker compose logs -f api

# Worker 日志
docker compose logs -f worker
```

### Q: 测试全部通过代表什么？

A: 50 个测试通过意味着：

- ✅ 状态机转换规则正确
- ✅ 模式开关逻辑正确
- ✅ 数据持久化正常
- ✅ Adapter 协议契约满足
- ✅ 脱敏层工作正常
- ✅ 配置加载正确

但**不代表**真实的 ChatGPT API 集成已完成（需要实际测试）。

## 下一步

1. 阅读 [架构文档](architecture.md) 了解系统设计
2. 阅读 [上游集成指南](upstream-integration.md) 了解如何对接真实 API
3. 查看 [任务清单](../specs/001-subscribe-console/tasks.md) 了解开发进度
4. 贡献代码前阅读 [宪法](../constitution.md) 了解设计原则
