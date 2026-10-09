# Phase 1 Data Model: 订阅代开编排控制台

**Feature**: 001-subscribe-console | **Date**: 2026-10-09

## 状态机

### OrderStatus

```text
created ──► pending_checkout ──► awaiting_payment ──► paying ──► verifying ──► active ──► delivered
   │               │                    │                │           │           │
   │               │                    │                │           │           └─► refunded
   └───────────────┴────────────────────┴────────────────┴───────────┴───────────────► failed
                                                          │
                                                          └──► requires_action ──► paying（3DS 回跳后）
                                                          └──► unknown ──► paying（可重试，不重复扣款）
   created ──► rejected（校验失败：无效 session / promo 未确认）
```

> **终态定义**：没有任何出边的状态。因此 `delivered` **不是**终态（交付后仍可 `refunded`），
> 真正的终态是 `rejected` / `failed` / `refunded`。

**合法迁移表**（实现于 `packages/contracts/state.py`）

| from | allowed to |
|---|---|
| `created` | `pending_checkout`, `rejected`, `failed` |
| `pending_checkout` | `awaiting_payment`, `failed` |
| `awaiting_payment` | `paying`, `failed` |
| `paying` | `verifying`, `requires_action`, `unknown`, `failed` |
| `requires_action` | `paying`, `failed` |
| `unknown` | `paying`, `failed` |
| `verifying` | `active`, `failed` |
| `active` | `delivered`, `refunded` |
| `delivered` | `refunded` |

### PaymentStatus

```text
initiated ──► processing ──► succeeded
     │             │
     │             ├──► requires_action
     │             └──► declined
     └──► error
```

## 实体

### Order

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `idempotency_key` | str | 唯一，防重复提交 |
| `account_source` | enum | `customer_session` \| `platform_account`，默认前者 |
| `card_source` | enum | `customer` \| `platform`，默认前者 |
| `billing_mode` | enum | `standard` \| `promo`，默认前者；后者需 `risk_acknowledged=true` |
| `plan` | enum | `plus` \| `pro_lite` \| `pro` \| `pro_max` |
| `billing_country` | str | ISO 国家码，须与代理出口一致 |
| `status` | OrderStatus | 见状态机 |
| `amount` | Decimal | 订单金额（客户侧） |
| `cost` | Decimal | 上游成本 |
| `created_at` / `updated_at` | datetime | 审计 |

**约束**: 不含任何 session / token / 卡字段（宪法 I）。

### Job

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `order_id` | FK | 所属订单 |
| `stage` | enum | `checkout` \| `payment` \| `verify` |
| `attempts` | int | 尝试次数 |
| `locked_by` / `locked_at` | str/datetime | 单 worker 占用锁（断点续跑） |
| `last_error` | str | **已脱敏** |
| `checkout_url` | str | 托管结账链接（正价档位） |

### PaymentAttempt

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `order_id` | FK | 所属订单 |
| `provider` | str | 支付方式标识（如 `direct_card`） |
| `status` | PaymentStatus | 见状态机 |
| `next_action` | JSON | **不透明** 3DS/next-action 数据（不含敏感字段） |
| `proxy_role` | str | 使用的代理角色（脱敏） |

### Credential（**不持久化**）

会话凭证仅在内存与受限临时文件中存在，任务结束即删除。**不落业务库**。

### PlatformCard

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | 标识（**非卡号**） |
| `pool` | str | 卡池归属 |
| `status` | enum | `available` \| `in_use` \| `blocked` |
| `usage_audit` | JSON | 使用记录（订单、时间），不含全量卡号 |

### ProxyPool

| 字段 | 类型 | 说明 |
|---|---|---|
| `role` | enum | `checkout` \| `approve` \| `mailbox` |
| `entries` | JSON | 脱敏后的代理条目（密码以占位符存储） |
| `stage_countries` | JSON | 各阶段出口国家 |

**隔离约束**: `checkout` 与 `approve` 池独立保存，互不覆盖；邮箱收件走 `mailbox`。

## Mode 组合矩阵

| account_source | card_source | billing_mode | 含义 |
|---|---|---|---|
| `customer_session` | `customer` | `standard` | 客户账号 + 客户卡，正价开通 |
| `customer_session` | `platform` | `standard` | 客户账号 + 平台卡，正价代付 |
| `customer_session` | `customer` | `promo` | 客户账号 + 客户卡，促销（高风险） |
| `platform_account` | `platform` | `standard` | 平台账号 + 平台卡，开通后交付账号 |
| `platform_account` | `platform` | `promo` | 平台账号 + 平台卡，促销（最高风险） |

> `promo` 组合在 UI 与 `docs/compliance.md` 双重标注风险，非默认路径。
