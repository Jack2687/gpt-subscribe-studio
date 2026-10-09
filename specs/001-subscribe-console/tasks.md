---

description: "Task list for 订阅代开编排控制台 (001-subscribe-console)"

---

# Tasks: 订阅代开编排控制台（Subscribe Console）

**Input**: Design documents from `/specs/001-subscribe-console/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 按宪法第 V 条，离线契约测试是**必需**的（不是可选项）。

**Organization**: 任务按用户故事分组，每个故事可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属的用户故事（US1…US5）

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 项目初始化与骨架

- [ ] T001 创建 monorepo 目录结构（`apps/` `services/` `packages/` `deploy/` `docs/` `tests/`）
- [ ] T002 [P] 创建根 `pyproject.toml`（workspace）与 `.gitignore`（忽略 `reasonix.toml`、`.reasonix/`、凭证、runtime 数据）
- [ ] T003 [P] 配置 ruff + pytest（`pyproject.toml`）
- [ ] T004 [P] 创建 `apps/web` 的 Vite + React + TS 工程（`package.json`、`vite.config.ts`、`tsconfig.json`）
- [ ] T005 [P] 编写 `deploy/.env.example`（模式开关、上游路径、代理占位、不含真实凭据）

**Checkpoint**: 骨架可 `docker compose config` 校验通过

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 所有用户故事共同依赖的核心

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事

- [ ] T006 [P] 在 `packages/contracts` 定义 `OrderStatus` / `PaymentStatus` 枚举与合法迁移表（`state.py`）
- [ ] T007 [P] 定义 `Order` / `Job` / `PaymentAttempt` / `Mode` 数据模型（`models.py`，pydantic v2）
- [ ] T008 [P] 在 `packages/core` 实现统一脱敏层（token / cookie / 卡字段 / 代理密码）与结构化日志
- [ ] T009 [P] 实现配置加载（环境变量 + 分片配置 + 应急覆盖如 Stripe key / Sentinel 版本）
- [ ] T010 建立 SQLite 持久化与迁移（SQLAlchemy 2.x，`services/api/app/db.py`）
- [ ] T011 实现幂等键与去重（`idempotency_key` 唯一约束）
- [ ] T012 [P] 实现 `Fake*` 上游桩（fake checkout / fake payment / fake subscription），供离线测试
- [ ] T013 定义 adapter 协议接口（`services/{checkout,payment,account}/adapter.py` 的抽象基类）
- [ ] T014 编写 `scripts/release_check.py`（敏感信息扫描：卡号、token、代理密码、邮箱）

**Checkpoint**: 契约、脱敏、持久化、adapter 接口就绪 —— 用户故事可并行开始

---

## Phase 3: User Story 1 - 提交订单并生成结账链接 (P1) 🎯 MVP

**Goal**: 客户提交含三个模式开关的订单，拿到托管结账链接

**Independent Test**: fake session + fake checkout 上游下，`standard` 订单返回 `pending_checkout` 与链接

### Tests for User Story 1 ⚠️

- [ ] T015 [P] [US1] 契约测试：订单提交 schema 校验（`tests/contract/test_order_submit.py`）
- [ ] T016 [P] [US1] 集成测试：无效 session → `rejected`，`promo` 未确认 → 拒绝（`tests/integration/test_us1_submit.py`）

### Implementation for User Story 1

- [ ] T017 [P] [US1] `POST /api/orders` 路由与请求/响应 schema（`services/api/app/routers/orders.py`）
- [ ] T018 [P] [US1] session 导入与有效性预检（不落库，仅内存 + 临时文件）
- [ ] T019 [US1] `checkout` adapter 实现：调用上游 `direct_card` 提链逻辑生成托管结账链接
- [ ] T020 [US1] 编排：`created → pending_checkout` 迁移与 Job 落库
- [ ] T021 [P] [US1] 前端：订单表单（套餐 / 国家 / 三开关 / 授权与风险确认，`apps/web/src/pages/OrderNew.tsx`）
- [ ] T022 [US1] 前端：订单任务页与轮询（`apps/web/src/pages/OrderDetail.tsx`）

**Checkpoint**: 提交 → 拿到链接闭环可用

---

## Phase 4: User Story 2 - 卡支付执行与状态跟踪 (P1)

**Goal**: 按 `card_source` 执行支付，跟踪显式状态机直到终态

**Independent Test**: fake card + fake payment 上游跑通 `created → paying → active` 并覆盖 3DS 分支

### Tests for User Story 2 ⚠️

- [ ] T023 [P] [US2] 契约测试：`PaymentStatus` 迁移合法性（`tests/contract/test_payment_states.py`）
- [ ] T024 [P] [US2] 集成测试：3DS → `requires_action`；不确定终态 → `unknown` 且可重试不重复扣款

### Implementation for User Story 2

- [ ] T025 [P] [US2] `payment` adapter 实现：对接上游 `zkky` 直卡绑定与任务状态机
- [ ] T026 [US2] `card_source=platform` 的卡池选择与使用审计（`services/payment/card_pool.py`）
- [ ] T027 [US2] 支付执行状态机与终态幂等（`services/orchestrator/payment_stage.py`）
- [ ] T028 [US2] 提链池 / 支付池隔离的阶段路由（两阶段各自代理池，互不覆盖）
- [ ] T029 [P] [US2] 前端：浏览器端卡字段组件（敏感字段不出浏览器，产出 `PaymentMethod` 标识）

**Checkpoint**: 支付链路可用且状态可解释

---

## Phase 5: User Story 3 - 查询与交付前订阅验证 (P2)

**Goal**: 交付前 100% 校验订阅生效

**Independent Test**: fake 订阅接口返回 `active` → 状态 `active` 且可交付

### Tests for User Story 3 ⚠️

- [ ] T030 [P] [US3] 集成测试：支付成功但订阅未生效 → 停留 `verifying`，确认窗口内重试

### Implementation for User Story 3

- [ ] T031 [P] [US3] 订阅校验 adapter（`services/account/subscription_check.py`）
- [ ] T032 [US3] `paying → verifying → active` 迁移与确认窗口重试策略
- [ ] T033 [US3] `GET /api/orders/{id}` 与 SSE 状态推送（`services/api/app/routers/orders.py`）
- [ ] T034 [US3] 前端：订阅生效/有效期/购买渠道展示与交付入口

**Checkpoint**: 无校验不交付

---

## Phase 6: User Story 4 - 运营后台 (P3)

**Goal**: 账号库存、代理池、支付配置、批量任务

- [ ] T035 [P] [US4] 账号库存导入与合格性筛选（`services/account/inventory.py`）
- [ ] T036 [P] [US4] 代理池配置与出口探测（`services/checkout/proxy_roles.py`）
- [ ] T037 [US4] 批量任务创建与 Canary（`services/orchestrator/batch.py`）
- [ ] T038 [P] [US4] 运营后台页面（`apps/web/src/pages/Admin.tsx`）

---

## Phase 7: User Story 5 - 计费与对账 (P3)

**Goal**: 客户收入与上游成本对账

- [ ] T039 [P] [US5] 订单金额与成本记录模型（`packages/contracts/billing.py`）
- [ ] T040 [US5] 对账报表接口与页面

---

## Phase 8: Polish & Cross-Cutting

- [ ] T041 [P] 完成 `docs/architecture.md` / `upstream-integration.md` / `compliance.md`
- [ ] T042 安全加固：反代 + 鉴权、限流、请求超时、不可重放保护
- [ ] T043 [P] `deploy/docker-compose.yml` 全栈编排与健康检查
- [ ] T044 运行 `scripts/release_check.py` 与全量离线测试
- [ ] T045 校验 `quickstart.md` 可复现

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始
- **Foundational (Phase 2)**: 依赖 Setup —— **阻塞所有用户故事**
- **User Stories (Phase 3+)**: 依赖 Phase 2；US1 与 US2 均为 P1，建议按序（US2 依赖 US1 的订单）
- **Polish (Phase 8)**: 依赖目标用户故事完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 后可开始，无跨故事依赖
- **US2 (P1)**: 依赖 US1 产生的订单与结账链接
- **US3 (P2)**: 依赖 US2 的支付终态
- **US4 (P3)**: 可与 US3 并行
- **US5 (P3)**: 依赖 US2/US3 的订单终态

### Within Each User Story

- 契约测试先行，必须先失败再实现
- 模型 → 服务 → 路由
- 一个故事完成后才进入下一个优先级

## Implementation Strategy

### MVP First

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. US1 → **STOP & VALIDATE** → 4. US2（真正闭环）

> 当前骨架交付范围：**Phase 1 全部 + Phase 2 的 T006–T014 接口/契约部分 + 文档（T041）**。
> 其余任务由后续 `/speckit-implement` 迭代完成。

## Notes

- `[P]` = 不同文件、无依赖
- 涉及上游的 adapter 必须自带失败模式说明
- 每个任务或逻辑组完成后提交
