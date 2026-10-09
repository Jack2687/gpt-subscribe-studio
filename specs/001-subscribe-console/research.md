# Phase 0 Research: 上游能力与集成策略

**Feature**: 001-subscribe-console | **Date**: 2026-10-09

## 决策 1：如何「结合」三个上游项目

| 上游 | 能力摘要 | 许可证 | 集成方式 |
|---|---|---|---|
| `2951461586/GPT-Register-Tool` | Windows WPF + Python：邮箱 OTP 注册、账号/Session 管理、**协议支付提链**（`direct_card`、PayPal、GoPay、GCash、MoMo…）、代理分片、批量支付状态机与断点续跑 | **无 LICENSE 文件**（默认保留所有权利） | **仅 adapter 引用**：以路径依赖 / submodule 方式调用其 Python 模块，不复制源码 |
| `JJianggg/gpt-checkout-studio` | React+Vite 本地工具：粘 session → 选国家/档位 → 复用上游 `direct_card_extract.py` 生成**正价**托管结账链接；含订阅查询 | **无 LICENSE 文件** | **仅作交互与流程参考**，前端自行实现 |
| `alexan0618/zkky`（直卡开源） | 仅监听 `127.0.0.1` 的直卡绑定服务：浏览器端卡字段组件、任务状态机、提链池/支付池隔离、离线契约测试 | **MIT** | 优先 adapter 引用；必要时可在保留版权声明下复用 |
| `github/spec-kit` | Spec-Driven Development 工具包 | MIT | 仅作为开发方法论（本仓库 `.specify/`） |

**Rationale**: 两个无许可证的上游若直接复制会有侵权风险，且它们的内部接口频繁变更。adapter
模式同时解决合规与可维护性。

**Alternatives rejected**:
- 直接 fork 三个项目并合并 → 许可证风险 + 三套状态机互不兼容。
- 只做 shell 脚本串联 → 无法满足状态机显式化与断点续跑。

## 决策 2：状态机为什么必须是显式的

上游返回大量「不确定终态」（`unusual activity`、支付成功但订阅延迟生效、3DS 未回调）。
`zkky` 已经区分「请求成功 / 待确认 / 3DS next action / 订阅生效」，`GPT-Register-Tool` 也把
`account_deactivated` 归为永久失败。本平台沿用并统一为一套枚举 + 迁移表。

**Alternatives rejected**: 用 `success: bool` + `retry: bool` 两个布尔 → 无法表达 3DS 与延迟生效，
会导致重复扣款。

## 决策 3：存储与并发

- 默认 **SQLite**：自托管、零依赖、单文件备份；与上游「本地优先」理念一致。
- 预留 **PostgreSQL**：当批量任务并发升高时切换，仅替换 `services/api/app/db.py` 的 DSN。
- 任务编排先用**数据库轮询 + 单 worker 占用锁**，避免引入 Redis 作为最小依赖。

**Alternatives rejected**: 直接用 Celery/Redis → 增加自托管复杂度，百级任务不需要。

## 决策 4：卡敏感字段的边界

沿用 `zkky` 的边界：**卡字段只由浏览器端支付组件处理**，服务端只接收不透明的
`PaymentMethod` 标识。`card_source=platform` 时，卡池条目同样以标识 + 受限临时文件形式引用。

**Rationale**: 宪法第 I 条要求；同时满足 PCI 最小化接触面。

## 未决问题（NEEDS CLARIFICATION）

- **Q1**: `card_source=platform` 的卡池以什么形式提供（加密文件 / 外部密钥管理）？
- **Q2**: 交付形态是「交付账号凭据」还是「客户自有账号已开通」，是否需要邀请码/子账号？
- **Q3**: `promo` 模式上线前是否需要单独的合规评审清单？
