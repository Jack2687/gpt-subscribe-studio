# Feature Specification: 订阅代开编排控制台（Subscribe Console）

**Feature Branch**: `001-subscribe-console`

**Created**: 2026-10-09

**Status**: Draft

**Input**: 用户描述：把 `GPT-Register-Tool`、`gpt-checkout-studio`、`zkky` 三个项目整合为一个
自托管的「ChatGPT 订阅代开」编排平台；支持「客户交付 session / 平台提供账号」两种账号来源，
「客户提交卡 / 平台提供卡」两种卡片来源，以及「正价 / 促销」两种计费模式；以容器化自托管方式
部署，并以 spec-kit SDD 驱动开发。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 客户提交开通需求并拿到结账链接 (Priority: P1)

客户打开 Web 控制台，粘贴或上传自己的 ChatGPT session，选择套餐档位、账单国家、
`billing_mode`（正价/促销）、`card_source`（自己的卡/平台卡），勾选授权确认后提交。
系统创建订单，异步生成托管结账链接，并返回任务详情页。

**Why this priority**: 没有「订单 + 结账链接」就不存在业务闭环，其余全部依赖于此。

**Independent Test**: 用 fake session 与 fake checkout 上游提交一个 `standard` 订单，
任务页应出现结账链接且状态为 `pending_checkout`。

**Acceptance Scenarios**:

1. **Given** 已进入控制台，**When** 提交含三个模式开关的订单，**Then** 返回 `job_id` 且状态为 `created`
2. **Given** `account_source=customer_session` 且 session 无效，**When** 提交，**Then** 返回语义化
   401 错误，订单置为 `rejected`，不推进状态机
3. **Given** `billing_mode=promo` 但未勾选风险确认，**When** 提交，**Then** 拒绝并提示必须确认风险

---

### User Story 2 - 卡支付执行与状态跟踪 (Priority: P1)

系统根据 `card_source` 选择卡片来源，调用支付服务执行卡绑定与支付，跟踪状态机直到
「订阅生效 / 3DS 待处理 / 失败」，并保证不重复扣款。

**Why this priority**: 这是「正常开通」区别于「只提链」的核心，决定业务是否真的能交付。

**Independent Test**: 用 fake card + fake payment 上游跑通 `created → paying → active`
全链路，并单独覆盖 `requires_action`（3DS）分支。

**Acceptance Scenarios**:

1. **Given** 订单处于 `pending_checkout`，**When** 支付上游返回 3DS，**Then** 状态为
   `requires_action`，且仅保留不透明 next-action 数据（不含敏感字段）
2. **Given** 支付上游返回成功且订阅接口确认生效，**Then** 状态为 `active`
3. **Given** 上游返回不确定终态，**Then** 状态为 `unknown`，可重试且**不重复扣款**

---

### User Story 3 - 客户查询与交付前订阅验证 (Priority: P2)

客户在任务页看到实时状态、订阅是否生效、有效期与购买渠道；系统在交付前必须用订阅接口二次确认。

**Why this priority**: 交付未生效的订阅会造成退款与信任崩塌。

**Independent Test**: fake 订阅接口返回 `active`，任务页应显示「已生效」与有效期。

**Acceptance Scenarios**:

1. **Given** 支付已成功但订阅接口未生效，**Then** 状态停留在 `verifying`，在确认窗口内重试
2. **Given** 订阅接口确认 `active`，**Then** 状态为 `active` 并标记可交付

---

### User Story 4 - 运营后台：账号库存 / 代理池 / 支付配置 (Priority: P3)

运营可维护平台账号库存、代理池（提链池与支付池隔离）、支付方式配置，并基于合格账号发起批量任务。

**Why this priority**: 提升人效，但不阻塞最小可用闭环。

**Independent Test**: 导入若干 fake 账号后，可筛选合格账号并创建批量任务。

**Acceptance Scenarios**:

1. **Given** 配置了提链池与支付池，**When** 发起任务，**Then** 两阶段使用各自代理池且互不覆盖

---

### User Story 5 - 计费与对账 (Priority: P3)

记录客户订单金额与上游成本（代理/接码/卡），输出对账报表。

**Why this priority**: 商业化必需，但可后置于闭环。

**Independent Test**: 一笔 fake 订单产生客户收入与成本两条记录，报表差额正确。

**Acceptance Scenarios**:

1. **Given** 一笔已完成订单，**Then** 报表显示收入、成本与毛利

---

### Edge Cases

- 代理实际出口国家与所选账单国家不一致 → 明确报 `billing_country_mismatch`
- 上游轮换 Stripe publishable key 或 Sentinel SDK 版本 → 支持环境变量覆盖，不阻断启动
- 支付成功但订阅延迟生效 → 在确认窗口内重试，避免过早交付
- 同一订单重复提交 → 依赖 `idempotency_key` 去重
- 卡片被拒 / 命中 `unusual activity` → 归类为可重试或永久失败，不无限重试
- 会话在链路中途失效（401）→ 按分层恢复策略处理，失败则闭环报错，绝不换用不匹配出口

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 允许客户提交订单，包含 `account_source` / `card_source` /
  `billing_mode` / 套餐档位 / 账单国家。
- **FR-002**: 系统 MUST 为每个订单生成唯一 `job_id`，并驱动显式状态机。
- **FR-003**: 系统 MUST 通过 checkout adapter 生成托管结账链接（正价档位为默认）。
- **FR-004**: 系统 MUST 在 `card_source=customer` 时仅接收浏览器端产出的 `PaymentMethod`
  标识，**服务端不得接触卡号/CVV**。
- **FR-005**: 系统 MUST 在 `card_source=platform` 时从平台卡池选择卡片，并写入使用审计。
- **FR-006**: 系统 MUST 在支付成功后、交付前调用订阅校验接口确认订阅生效。
- **FR-007**: 系统 MUST 对终态做幂等处理（不重复扣款、不重复交付）。
- **FR-008**: 系统 MUST 对 session / token / 卡字段 / 代理口令做统一脱敏。
- **FR-009**: 系统 MUST 支持 `promo` 模式，默认关闭，提交时要求显式风险确认。
- **FR-010**: 系统 MUST 提供订单状态查询接口与任务页。
- **FR-011**: 系统 MUST 支持断点续跑（进程重启后未完成订单可恢复）。
- **FR-012**: 系统 MUST 以容器化方式自托管部署，默认不对外暴露端口。

### Key Entities *(include if feature involves data)*

- **Order**: 订单；含三个模式开关、套餐、账单国家、状态、`idempotency_key`。
- **Job**: 编排任务；`order_id`、阶段、尝试次数、脱敏后的最后错误。
- **PaymentAttempt**: 支付尝试；`provider`、状态、不透明 `next_action`。
- **Credential**: 会话凭证；**仅临时态，不持久化到业务库**。
- **PlatformCard**: 平台卡池条目；归属、状态、使用审计（不含卡号全量）。
- **ProxyPool**: 代理池；角色（`checkout` / `approve` / `mailbox`）、脱敏条目。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 单笔订单从提交到拿到结账链接 < 60s（不含外部网络耗时）。
- **SC-002**: 离线契约测试覆盖状态机全部终态分支，整体执行 < 30s。
- **SC-003**: 交付前订阅校验覆盖率 100%（无校验不交付）。
- **SC-004**: 敏感字段泄漏为 0（release check 通过）。
- **SC-005**: 进程重启后未完成订单恢复率 100%。

## Assumptions

- 使用者已获得账号、支付方式与代理的合法授权。
- 上游 ChatGPT Web 内部结账接口随时可能变更，可用性不由本项目承诺。
- 默认单机自托管，目标规模为百级并发任务、分钟级 10+ 订单。
- 客户浏览器可运行本地支付组件（用于处理卡片敏感字段）。
