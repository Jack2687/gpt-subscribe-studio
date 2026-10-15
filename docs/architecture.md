# 架构总览（Architecture Overview）

**项目**: gpt-subscribe-studio
**定位**: 自托管的「ChatGPT 订阅代开」编排与交付平台
**日期**: 2026-10-09

## 1. 一句话定义

把 **账号**、**结账链接生成**、**卡支付执行** 三段能力编排成一条可观测、可断点续跑、
凭证零持久化的订阅开通流水线，并以容器化方式自托管。

## 2. 系统上下文

```text
        ┌──────────────┐        ┌──────────────────────────────┐
        │  客户浏览器   │        │  运营浏览器                   │
        │ (任务页/表单) │        │ (账号池/代理池/批量任务)      │
        └──────┬───────┘        └───────────────┬──────────────┘
               │  HTTPS(反代+鉴权)               │
               ▼                                ▼
        ┌──────────────────────────────────────────────────────┐
        │                  apps/web (React + Vite)              │
        │  含浏览器端卡支付组件：卡号/CVV 只在此处处理            │
        └───────────────────────────┬──────────────────────────┘
                                    │ 仅传不透明 PaymentMethod 标识
                                    ▼
        ┌──────────────────────────────────────────────────────┐
        │        services/api (FastAPI)  ── SQLite             │
        │  订单 · 任务查询 · SSE 状态推送 · 鉴权 · 幂等          │
        └───────────────────────────┬──────────────────────────┘
                                    │ Job 队列（DB 轮询 + 占锁）
                                    ▼
        ┌──────────────────────────────────────────────────────┐
        │            services/orchestrator (worker)            │
        │  显式状态机 · 断点续跑 · 终态幂等 · 阶段代理路由        │
        └───┬──────────────┬───────────────┬───────────────────┘
            ▼              ▼               ▼
   ┌────────────────┐ ┌────────────┐ ┌──────────────────┐
   │ services/      │ │ services/  │ │ services/        │
   │ checkout       │ │ payment    │ │ account          │
   │ (adapter)      │ │ (adapter)  │ │ (adapter)        │
   └───────┬────────┘ └─────┬──────┘ └────────┬─────────┘
           │                │                 │
           ▼                ▼                 ▼
   ┌────────────────┐ ┌────────────┐ ┌──────────────────┐
   │ GPT-Register-  │ │  zkky      │ │ GPT-Register-    │
   │ Tool (提链)     │ │ (直卡绑定)  │ │ Tool (注册/账号)  │
   └────────────────┘ └────────────┘ └──────────────────┘
                上游层：仅通过 adapter 接触，不复制无证代码
```

## 3. 分层与职责

| 层 | 目录 | 职责 | 不能做的事 |
|---|---|---|---|
| 接入层 | `apps/web` | 表单、任务页、卡字段组件、SSE 订阅 | 不把卡字段发往服务端 |
| 服务层 | `services/api` | 订单 CRUD、幂等、鉴权、状态推送 | 不做重活（编排） |
| 编排层 | `services/orchestrator` | 状态机推进、重试、断点续跑 | 不直连上游，只调 adapter |
| 能力层 | `services/{checkout,payment,account}` | 封装上游能力，声明失败模式 | 不泄漏上游字段到领域模型 |
| 共享层 | `packages/{contracts,core}` | 状态机枚举、模型、脱敏日志、配置 | 不含业务编排 |
| 上游层 | `vendor/upstream` | 引用与版本锁定 | **不存放复制的上游源码** |

## 4. 核心链路

```text
1) 提交订单    客户 → api：POST /api/orders（含三模式开关 + 授权确认）
2) 前置校验    session 有效性预检 / promo 风险确认 / 幂等键去重
3) 生成链接    orchestrator → checkout adapter → 托管结账链接（正价档位为默认）
4) 支付执行    orchestrator → payment adapter：卡池或客户卡标识 → 卡绑定/支付
               └─ 分支：requires_action(3DS) / unknown / declined
5) 订阅验证    orchestrator → account adapter：订阅接口确认生效（确认窗口内重试）
6) 交付        active → delivered，交付账号或通知客户；写入计费记录
```

状态机定义见 [`specs/001-subscribe-console/data-model.md`](../specs/001-subscribe-console/data-model.md)。

## 5. 凭证与数据边界（宪法 I）

```text
   session / token / Cookie   → 仅内存 + 受限临时文件，任务结束即删，绝不入库
   卡号 / CVV                 → 仅浏览器端组件，服务端只见 PaymentMethod 标识
   代理口令                    → 配置分片存储，日志全程脱敏
   业务库(SQLite)              → 订单/任务/审计，不含任何上述敏感字段
```

## 6. 部署拓扑

```text
   docker compose 网络（默认仅 loopback/内网）
   ├── api         (:8080)   FastAPI + SQLite volume
   ├── worker                orchestrator（可多副本，靠 Job 占锁）
   └── web         (:5173→静态托管)
   可选：caddy/nginx 反代 + 基础鉴权（公网暴露的**唯一**路径）
```

## 7. 关键设计决策

| 决策 | 结论 | 详见 |
|---|---|---|
| 如何结合三个上游 | adapter 引用，不复制无证代码 | [upstream-integration.md](./upstream-integration.md) |
| 状态机 | 显式枚举 + 迁移表，禁止布尔化 | `packages/contracts/state.py` |
| 存储 | SQLite 默认，Postgres 可迁移 | `specs/001-subscribe-console/research.md` |
| 开源许可证 | 本项目采用 MIT，但**不吸收**无许可证上游代码 | [compliance.md](./compliance.md) |

## 8. 维护约定

- 上游内部接口变更（Stripe key、Sentinel 版本、结账字段）只允许改 adapter，并用环境变量应急覆盖。
- 任何新增网络请求必须具备：超时、脱敏日志、不可重放保护。
- 发布前执行 `scripts/release_check.py`。
