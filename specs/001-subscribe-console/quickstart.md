# Quickstart: 订阅代开编排控制台

**Feature**: 001-subscribe-console | **Date**: 2026-10-09

> 本文件描述**目标状态**的运行方式。当前仓库处于「骨架」阶段，服务与前端尚未实现，
> 下列命令在完成 `tasks.md` 对应任务后方可运行。

## 前置条件

- Docker 24+ 与 Docker Compose v2
- Python 3.11+（本地开发）
- Node.js 20+ 与 pnpm（前端开发）
- 上游引用已就位（见 `docs/upstream-integration.md`）

## 1. 配置

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：模式默认值、上游路径、代理占位
```

**不要**把 `deploy/.env` 提交到 Git。

## 2. 启动（容器化自托管）

```bash
cd deploy
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:8080/api/health
```

默认只监听回环地址，不对局域网/公网暴露。

## 3. 前端

```bash
cd apps/web
pnpm install
pnpm dev      # http://127.0.0.1:5173
```

## 4. 走一遍最小闭环（离线 fake 上游）

```bash
# 提交一个 standard + customer + customer_session 订单
curl -s -X POST http://127.0.0.1:8080/api/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-001' \
  -d '{
        "plan": "plus",
        "billing_country": "US",
        "mode": {
          "account_source": "customer_session",
          "card_source": "customer",
          "billing_mode": "standard"
        },
        "session": "<fake-session>",
        "payment_method_token": "pm_fake"
      }'

# 查询状态
curl -s http://127.0.0.1:8080/api/orders/<order_id>
```

在 fake 上游下，状态应从 `created → pending_checkout → awaiting_payment → paying → verifying → active`。

## 5. 测试

```bash
python -m pytest -q            # 离线契约测试，无需真实账号/卡/交易
python scripts/release_check.py  # 敏感信息检查
```

## 6. 常见错误

| 错误码 | 含义 | 处理 |
|---|---|---|
| `invalid_session` | session 无效或失效 | 重新导出 session |
| `promo_not_acknowledged` | `promo` 未确认风险 | 勾选风险确认或改用 `standard` |
| `billing_country_mismatch` | 代理出口国家 ≠ 账单国家 | 切换代理节点 |
| `payment_proxy_pool_unavailable` | 支付代理不可用 | 检查支付池配置 |
