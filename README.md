# 直卡协议 · DirectCard Protocol

> 自托管的 **ChatGPT 订阅代开** 编排与交付平台。
> 把「账号 → 结账链接 → 卡支付 → 订阅校验 → 交付」串成一条可观测、可断点续跑、
> **凭证零持久化** 的流水线，一条 `docker compose up` 起全栈。

本项目把三个既有开源项目的能力**整合为一个可商业化运营的平台**：

| 上游 | 提供什么 | 许可证 | 在本项目中的位置 |
|---|---|---|---|
| [`2951461586/GPT-Register-Tool`](https://github.com/2951461586/GPT-Register-Tool) | 账号注册、邮箱 OTP、Session 管理、`direct_card` 提链、协议支付状态机 | ⚠️ **无 LICENSE** | `services/checkout`、`services/account`（**adapter 引用，不复制代码**） |
| [`JJianggg/gpt-checkout-studio`](https://github.com/JJianggg/gpt-checkout-studio) | 本地优先的 React 交互：选国家/档位 → 生成托管结账链接 | ⚠️ **无 LICENSE** | `apps/web`（仅交互与流程参考） |
| [`alexan0618/zkky`](https://github.com/alexan0618/zkky) | 直卡绑定、任务状态机、提链池/支付池隔离 | ✅ MIT | `services/payment`（adapter 引用） |
| [`github/spec-kit`](https://github.com/github/spec-kit) | Spec-Driven Development 工具包 | ✅ MIT | 开发方法论（`.specify/`） |

## 这是什么 / 不是什么

**是**：一套自托管编排平台，支持「客户交付 session / 平台账号」「客户提交卡 / 平台卡池」
「正价 / 促销」三种正交模式，并保证交付前订阅已确认生效。

**不是**：不提供账号、不提供支付通道、不存储卡号、不实现绕过支付校验的行为。
合规边界见 [docs/compliance.md](docs/compliance.md)。

## 三种正交模式

| 开关 | 取值 | 默认 |
|---|---|---|
| `billing_mode` | `standard`（正价） \| `promo`（促销/零元） | `standard` |
| `card_source` | `customer`（客户卡） \| `platform`（平台卡池） | `customer` |
| `account_source` | `customer_session`（客户交付 session） \| `platform_account`（平台账号库存） | `customer_session` |

`promo` **默认关闭**，且订单必须显式 `risk_acknowledged=true`。

## 架构

```text
apps/web ──► services/api ──► services/orchestrator ──► services/{checkout,payment,account}
                                        │                              │
                                        └──────────► packages/contracts ◄──┘
                                                          ▲
                                                   packages/core
```

- 六层分层、单向依赖、adapter 作为**唯一**上游接触点 → [docs/architecture.md](docs/architecture.md)
- 目录职责与依赖方向 → [docs/directory-map.md](docs/directory-map.md)
- 不可回退决策 → [docs/adr/](docs/adr/)

## 核心特性

- **显式状态机**：`created → pending_checkout → awaiting_payment → paying → verifying → active → delivered`，
  支持 `requires_action`（3DS）/ `unknown`（不确定终态，可重试不重复扣款）。
- **凭证零持久化**：session 仅内存/受限临时文件；卡字段只由浏览器端组件处理；全局脱敏日志。
- **交付门槛**：`active` **且** 订阅接口确认生效才允许交付（无校验不交付）。
- **上游隔离**：Stripe key / Sentinel 版本轮换可用环境变量应急覆盖，不需改代码。
- **离线可测**：`Fake*` adapter 让全链路测试不依赖真实账号、真实卡与真实交易。

## 快速开始

```bash
# 1) 配置
cd deploy && cp .env.example .env      # 编辑：上游路径、模式默认值

# 2) 起服务（默认仅监听 127.0.0.1）
docker compose up -d --build
curl -s http://127.0.0.1:8080/api/health

# 3) 前端（开发期）
cd ../apps/web && pnpm install && pnpm dev   # http://127.0.0.1:5173
```

详细链路与常见错误见 [specs/001-subscribe-console/quickstart.md](specs/001-subscribe-console/quickstart.md)。

## 目录结构

```text
apps/web/                 React + Vite 控制台（含浏览器端卡字段组件）
services/api/             FastAPI：订单、查询、SSE、幂等
services/orchestrator/    编排 worker：状态机推进、断点续跑
services/checkout/        结账链接生成（adapter）
services/payment/         卡绑定与支付执行（adapter）
services/account/         注册 / 账号库存 / 订阅校验（adapter）
packages/contracts/       状态机、领域模型、adapter 协议
packages/core/            脱敏日志、配置加载
vendor/upstream/          上游引用与版本锁定（不放复制代码）
deploy/                   docker-compose、Dockerfile、.env.example
docs/                     架构、上游集成、合规、目录职责、ADR
specs/                    SDD 工件（spec / plan / tasks / data-model / contracts）
```

## 开发与测试

```bash
# 离线契约 + 单元测试（无需真实账号 / 卡 / 交易）
uv run --python 3.12 --with pytest pytest

# 发布前敏感信息检查（凭证零持久化护栏）
python scripts/release_check.py
```

开发流程遵循 spec-kit 的 Spec-Driven Development：
`constitution → specify → plan → tasks → implement → converge`。
当前 feature 规格见 [specs/001-subscribe-console/](specs/001-subscribe-console/)，
任务清单见 [tasks.md](specs/001-subscribe-console/tasks.md)。

## 平台护栏

| 护栏 | 位置 |
|---|---|
| 默认只监听回环地址 | `deploy/docker-compose.yml` |
| `promo` 默认关闭 + 风险确认 | `packages/core/src/dcp_core/config.py`、`packages/contracts/.../models.py` |
| 卡字段不出浏览器 | `apps/web/src/card-payment/CardFields.tsx` |
| 统一脱敏日志 | `packages/core/src/dcp_core/redaction.py` |
| 发布前敏感信息扫描 | `scripts/release_check.py` |
| adapter 能力与失败模式自述 | `services/*/src/*/adapter.py` |

## 现状与 Roadmap

**当前阶段：核心功能实现完成**。已完成：

- ✅ spec-kit SDD 工件（constitution / spec / plan / tasks / data-model / contracts）
- ✅ `packages/contracts`：状态机 + 模式开关 + adapter 协议（16 项契约测试）
- ✅ `packages/core`：脱敏层 + 配置加载
- ✅ SQLite 持久化层（SQLAlchemy ORM + repository 模式）
- ✅ 真实 checkout adapter（自己实现 ChatGPT 结账 API 对接）
- ✅ 真实 payment adapter（自己实现直卡支付流程与 3DS 处理）
- ✅ 真实 account adapter（自己实现订阅状态查询）
- ✅ orchestrator worker（轮询、状态机驱动、断点续跑）
- ✅ API 路由升级（使用数据库替代内存存储）
- ✅ 三个能力服务 adapter 骨架（含 `Fake*` 实现用于离线测试）
- ✅ 所有 50 个测试通过

**待实现**（见 [tasks.md](specs/001-subscribe-console/tasks.md)）：
- 📋 Web 前端（React 订单表单与状态页面，T021-T022）
- 📋 SSE 实时推送（T023-T024）
- 📋 批量任务与 Canary（T037-T041）
- 📋 计费对账与退款（T042-T044）
- 📋 运营后台（T045-T046）

**重要说明**：所有 adapter 代码都是**自己重新编写**，不依赖上游项目代码，仅参考其流程思路。
通过 adapter 模式完全隔离上游，确保许可证合规与代码可维护性。

## 许可

本项目代码采用 MIT。**第三方上游代码不包含在本仓库内**，其许可与条款各自独立；
`GPT-Register-Tool` 与 `gpt-checkout-studio` 无 LICENSE，需先获授权才可 vendored。
详见 [docs/upstream-integration.md](docs/upstream-integration.md)。
