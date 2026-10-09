# 合规与使用边界（Compliance & Usage Boundaries）

**日期**: 2026-10-09

> 本文不是法律意见。使用前请自行评估所在地法律、上游服务条款与支付网络规则。

## 1. 平台定位

本平台是**自托管的编排工具**，用于把「账号、结账链接生成、卡支付」三段能力串成一条
可观测的流水线。它不提供账号、不提供支付通道、不代理任何上游服务。

## 2. 三个模式开关的合规含义

| 开关 | 低风险取值 | 高风险取值 | 风险说明 |
|---|---|---|---|
| `billing_mode` | `standard`（正价） | `promo`（促销/零元） | 促销/零元往往依赖平台活动或支付漏洞，可能构成**滥用平台促销**，触及上游风控与支付网络规则 |
| `card_source` | `customer`（客户卡） | `platform`（平台卡） | 平台卡必须来自**合法持有并授权**的卡片；严禁使用盗刷、代持、他人名下未授权卡片 |
| `account_source` | `customer_session`（客户账号） | `platform_account`（平台账号） | 批量注册/交付账号通常违反上游服务条款，可能触发封禁与法律风险 |

**默认值**：`standard` + `customer` + `customer_session`（宪法第 IV 条）。
`promo` 必须显式开启（`DCP_ENABLE_PROMO=true`）**且**订单上勾选风险确认。

## 3. 平台**不**做的事

- ❌ 不实现绕过支付校验、篡改金额、伪造促销资格的行为。
- ❌ 不存储卡号 / CVV（服务端只见浏览器端产出的不透明 `PaymentMethod` 标识）。
- ❌ 不持久化 session / token / Cookie。
- ❌ 不提供可用于盗刷、欺诈、批量滥用的自动化能力。

## 4. 使用者的责任

- 确认对所使用的**账号、卡片、代理**拥有合法授权。
- 遵守 OpenAI / 支付服务商 / 代理服务商的服务条款与所在地区法规。
- 承担第三方服务费用、账号安全与数据合规责任。
- 「帮他人开通并收费」属于你与客户之间的商业关系；请自行确认该业务在当地的合法性，
  以及是否需要相应的经营资质。

## 5. 工程层面的护栏

| 护栏 | 位置 | 作用 |
|---|---|---|
| 默认只监听回环地址 | `deploy/docker-compose.yml` | 防止无意暴露到公网 |
| `promo` 默认关闭 | `packages/core/src/dcp_core/config.py` | 高风险模式需显式开启 |
| promo 风险确认 | `packages/contracts/src/dcp_contracts/models.py` | 订单必须留痕 |
| 卡字段不出浏览器 | `apps/web/src/card-payment/CardFields.tsx` | 最小化敏感数据接触面 |
| 统一脱敏日志 | `packages/core/src/dcp_core/redaction.py` | 防止凭证进入日志 |
| 发布前敏感信息扫描 | `scripts/release_check.py` | 防止凭证进入仓库 |

## 6. 上游许可证

`GPT-Register-Tool` 与 `gpt-checkout-studio` **没有 LICENSE 文件**，本仓库不复制其代码，
仅通过 adapter 引用；`zkky` 为 MIT。详见
[upstream-integration.md](./upstream-integration.md) 与
[ADR 0001](./adr/0001-upstream-adapter-boundary.md)。
