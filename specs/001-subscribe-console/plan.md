# Implementation Plan: 订阅代开编排控制台（Subscribe Console）

**Branch**: `001-subscribe-console` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-subscribe-console/spec.md`

## Summary

构建一个自托管的「ChatGPT 订阅代开」编排平台：客户在前端提交开通订单（含账号来源、卡片来源、
计费模式三个开关），后端以显式状态机驱动「结账链接生成 → 卡支付执行 → 订阅验证 → 交付」链路。

三个上游项目以 **adapter 方式集成**而非代码复制：

- `GPT-Register-Tool` → `account` / `checkout` adapter（注册引擎、`direct_card` 提链、协议支付状态机）
- `zkky`（直卡开源，MIT）→ `payment` adapter（浏览器端卡绑定、任务状态机、代理角色隔离）
- `gpt-checkout-studio` → `apps/web` 交互参考（档位与国家选择、session 导入、托管结账链接流程）

## Technical Context

**Language/Version**: Python 3.11+；TypeScript 5.x + React 19 + Vite（前端）

**Primary Dependencies**: FastAPI、uvicorn、pydantic v2、SQLAlchemy 2.x、httpx、curl_cffi（Chrome
指纹）、structlog；前端 React + Vite + TanStack Query

**Storage**: 默认 SQLite（本地优先、可断点续跑）；预留 PostgreSQL 迁移路径

**Testing**: pytest（离线契约测试：fake session / fake card / fake 上游，无真实交易）

**Target Platform**: Linux 容器（Docker Compose 自托管）；开发环境 macOS / Linux 均可

**Project Type**: 多服务 Web 应用（monorepo）

**Performance Goals**: 单机百级并发任务；单订单 < 60s（不含外部网络）；分钟级 10+ 订单

**Constraints**: 默认不暴露公网端口（仅 loopback / 内网 + 反代鉴权）；无许可证上游不得复制代码；
卡敏感字段不过服务端

**Scale/Scope**: 首批 5 个后端服务 + 1 个前端 + 1 个 worker；10+ 实体；3 个 adapter 边界

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 本方案如何满足 |
|---|---|
| I. 凭证零持久化 | `Credential` 只存在于内存/受限临时文件；卡字段交浏览器端组件；全局脱敏中间件 |
| II. 上游隔离与适配器边界 | `services/*/adapter.py` 是唯一接触上游的位置；`vendor/upstream` 只放引用说明，不复制无证代码 |
| III. 显式状态机 | `packages/contracts/state.py` 定义 `OrderStatus` / `PaymentStatus` 枚举与合法迁移表 |
| IV. 模式可插拔 | `Order.mode` 三开关，默认 `standard/customer/customer_session`，`promo` 需风险确认 |
| V. 契约先行与离线可测 | `packages/contracts` 先定义；`tests/` 全离线，`Fake*` 上游实现 |
| VI. 合规边界优先 | `docs/compliance.md` + UI 双重标注；release check 脚本扫描敏感信息 |

**结论**: 无违规项，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-subscribe-console/
├── plan.md              # 本文件
├── research.md          # Phase 0：上游能力与许可证调研
├── data-model.md        # Phase 1：实体与状态机
├── quickstart.md        # Phase 1：本地起服务
├── contracts/           # Phase 1：OpenAPI + 事件契约
└── tasks.md             # Phase 2：任务清单
```

### Source Code (repository root)

```text
gpt-subscribe-studio/
├── apps/
│   └── web/                     # 客户控制台 + 运营后台（React + Vite + TS）
│       ├── src/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── api/
│       │   └── card-payment/    # 浏览器端卡字段组件（敏感字段不出浏览器）
│       └── package.json
├── services/
│   ├── api/                     # FastAPI 网关：订单、任务查询、SSE 状态推送
│   │   └── app/
│   │       ├── routers/
│   │       ├── deps.py
│   │       └── main.py
│   ├── orchestrator/            # 编排 worker：消费 Job、驱动状态机、断点续跑
│   ├── checkout/                # 结账链接生成（adapter → 上游 direct_card）
│   ├── payment/                 # 卡绑定与支付执行（adapter → 上游 zkky）
│   └── account/                 # 账号注册 / 库存 / 订阅校验（adapter → GPT-Register-Tool）
├── packages/
│   ├── contracts/               # 共享 schema：Order / Job / PaymentAttempt / 状态机
│   └── core/                    # 共享：脱敏日志、transport、指纹、配置加载
├── vendor/
│   └── upstream/                # 上游引用（submodule / 版本锁定说明），不放复制代码
├── deploy/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── Dockerfile.api
├── docs/
│   ├── architecture.md
│   ├── upstream-integration.md
│   ├── compliance.md
│   └── directory-map.md
├── specs/
│   └── 001-subscribe-console/
└── tests/
    ├── contract/
    ├── integration/
    └── unit/
```

**Structure Decision**: 采用 monorepo。理由：(1) 三个上游项目本身就是「账号 / 结账 / 支付」三段
能力，拆成独立包后 adapter 边界天然隔离；(2) 共享契约必须单点定义，避免多 repo 漂移；
(3) 自托管场景希望一条 `docker compose up` 起全栈。

## Complexity Tracking

> 无 Constitution Check 违规，无需填写。
