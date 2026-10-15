# gpt-subscribe-studio Constitution

> 本宪法定义gpt-subscribe-studio平台不可妥协的工程与合规原则。所有 `spec` / `plan` / `tasks`
> 及代码提交必须通过 Constitution Check。

## Core Principles

### I. 凭证零持久化（Credential Zero-Persistence）

会话令牌、Cookie、`PaymentMethod`、卡片敏感字段与代理口令：

- 一律不写入业务数据库、不写入业务日志、不写入 Git；
- 卡片敏感字段只允许在**浏览器端支付组件**内处理，服务端仅接收不透明的
  `PaymentMethod` 标识（延续 `zkky` 的边界）；
- 需要落盘时只允许写入权限受限的系统临时文件，任务结束即删除；
- 日志与异常必须统一经过脱敏层（Access Token / Cookie / 代理密码 / API Key / 卡字段）。

**理由**：这是本平台唯一真正的不可逆风险面，一次泄漏即业务终结。

### II. 上游隔离与适配器边界（Adapter Boundary）

- **不复制、不 fork 没有明确开源许可证的上游仓库**；通过 `adapter` 接口 +
  上游引用（submodule / 可选依赖 / 路径依赖）集成；
- 上游的内部接口、字段、Stripe key、Sentinel SDK 版本变化**只允许影响 adapter 层**，
  不得渗透到领域模型；
- 每个 adapter 必须声明：上游来源、许可证、能力、失败模式。

**理由**：上游是闭源且频繁变更的非官方接口，耦合越深越不可维护，且直接复制存在侵权风险。

### III. 显式状态机（Explicit State Machine）

- 订单与支付必须用显式状态建模，**禁止用布尔值代替状态**；
- 必须区分：`请求成功` / `待确认` / `3DS 或 next-action` / `订阅最终生效`；
- 每个状态迁移必须可观测、可重放、可断点续跑（进程重启后能恢复）。

**理由**：上游终态大量是「不确定」，布尔化会直接导致重复扣款或错误交付。

### IV. 模式可插拔（Pluggable Modes）

三个正交开关必须显式建模并在订单上留痕：

| 开关 | 取值 | 默认 |
|---|---|---|
| `billing_mode` | `standard`（正价） \| `promo`（促销/零元） | `standard` |
| `card_source` | `customer`（客户提交卡） \| `platform`（平台卡池） | `customer` |
| `account_source` | `customer_session`（客户交付 session） \| `platform_account`（平台账号库存） | `customer_session` |

`promo` 必须显式启用、要求风险确认，且**不得作为默认路径**。

**理由**：业务确实需要两种开通方式并存，但高风险模式必须是「显式选择」而非「默认发生」。

### V. 契约先行与离线可测（Contract-First, Offline-Testable）

- 跨服务共享结构先在 `packages/contracts` 定义，再写实现；
- 所有网络路径必须能用 fake session / fake card / fake 上游做**离线契约测试**，
  不依赖真实账号与真实交易；
- 新网络请求必须具备超时、脱敏日志与不可重放保护。

**理由**：真实账号与真实交易无法用于测试，离线契约测试是唯一可持续的回归手段。

### VI. 合规边界优先（Compliance Boundary First）

- 平台定位为「**代开编排与交付**」，仅在获得授权且符合上游服务条款、地区法规的场景使用；
- `promo` 模式属于平台风控与支付合规的高风险区，必须在文档与 UI **双重标注**，
  且**不实现绕过支付校验的行为**；
- 每次发布必须通过敏感信息检查（release check）。

**理由**：业务可持续性依赖边界清晰，而非能力最大化。

## 技术与安全约束

- **语言/运行时**：Python 3.11+；前端 React + Vite + TypeScript。
- **部署**：容器化自托管（Docker / Docker Compose）；默认只监听内网或回环，
  公网暴露必须经反向代理 + 鉴权。
- **存储**：默认 SQLite（本地优先），预留 PostgreSQL 迁移路径。
- **依赖**：新增依赖必须固定版本并说明用途。

## 开发流程

- 采用 **Spec-Driven Development**（spec-kit）：
  `constitution → specify → plan → tasks → implement → converge`；
- 每个 feature 一个 `specs/NNN-*/` 目录，先评审 `spec.md` 再写代码；
- 提交信息与文档使用中文；代码标识符、路径、命令保持原文。

## Governance

- 本宪法优先于其他实践；修改必须记录理由并递增版本（语义化版本）。
- 所有 PR / 评审必须执行 Constitution Check；引入的复杂度必须被证明必要。
- 运行时开发指引见 `AGENTS.md` 与 `docs/`。

**Version**: 1.0.0 | **Ratified**: 2026-10-09 | **Last Amended**: 2026-10-09
