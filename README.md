# gpt-subscribe-studio

> 自托管的 **ChatGPT 订阅开通与编排平台**。  
> 将「粘贴 Session → 生成结账会话 / 托管长链 → 浏览器端安全填卡（Stripe Elements） → 协议确认与 3DS 处理 → 订阅生效校验 → 交付」串成一条**可观测、可断点续跑、凭证零持久化**的完整流水线。

---

## 目录

- [项目定位与边界](#项目定位与边界)
- [核心特性](#核心特性)
- [支持的套餐与地区](#支持的套餐与地区)
- [系统架构](#系统架构)
- [工作流与状态机](#工作流与状态机)
- [目录结构](#目录结构)
- [快速开始（本地开发）](#快速开始本地开发)
- [容器化部署](#容器化部署)
  - [方式一：开发 / 标准编排部署（`deploy/docker-compose.yml`）](#方式一开发--标准编排部署deploydocker-composeyml)
  - [方式二：单容器全栈加固部署（`deploy/server/compose.yml`）](#方式二单容器全栈加固部署deployservercomposeyml)
- [代理设置说明](#代理设置说明)
- [配置参考（环境变量）](#配置参考环境变量)
- [API 接口概览](#api-接口概览)
- [安全与合规护栏](#安全与合规护栏)
- [测试与发布检查](#测试与发布检查)
- [免责声明与风险提示](#免责声明与风险提示)
- [进阶文档与 ADR](#进阶文档与-adr)
- [许可证](#许可证)

---

## 项目定位与边界

### 这是什么
一套**独立、自包含、自托管**的 ChatGPT 订阅代开与开通工具平台：
- **双轨开通流程**：
  - **Plus / Go / Pro（Standard、More、Max）**：页面内嵌官方 Stripe Payment Element，卡片在浏览器端直接生成 `ctoken_`（ConfirmationToken），由后端完成税费同步、协议确认（支持 `oaics_` 内部会话与 `cs_live_` 自定义结账会话）、Sentinel 审批及 3DS 引导。
  - **Team**：自动生成 `pay.openai.com/c/pay/cs_live_...` 托管长链（支持自定义席位数、月付/年付、工作空间名称与优惠码），支付完成后一键校验订阅状态。
- **三种正交模式建模**：支持 `billing_mode`（`standard` / `promo`）、`card_source`（`customer` / `platform`）、`account_source`（`customer_session` / `platform_account`）显式校验。
- **全部核心协议自研实现**：内置基于 `curl_cffi`（Chrome 指纹模拟）的 ChatGPT/Stripe 协议客户端与 Node.js Sentinel 风控令牌桥接器，**无需依赖或复制第三方本地上游仓库代码即可独立运行**。

### 这不是什么
- **不提供** ChatGPT 账号库存或支付卡通道。
- **不接触、不存储**明文卡号与 CVV（仅由浏览器端 Stripe iframe 处理）。
- **不落盘**客户 Session（仅存进程内存金库 `SecretVault`，交付后立即销毁，30 分钟自动过期）。
- **不绕过**支付校验：只有 Stripe 确认扣款成功（含 3DS 验证通过）才标记订单成功。订阅是否真正生效不再作为交付门槛，需自行到账号中核对。合规边界详见 [docs/compliance.md](docs/compliance.md)，使用前请先阅读 [免责声明与风险提示](#免责声明与风险提示)。

### 灵感参考与上游致谢

本项目在设计初期参考了以下开源项目的交互或流程思路，但**所有业务与协议代码均由本仓库独立实现**，不复制无许可证上游源码：

| 参考项目 | 借鉴思路 | 上游许可证 | 本仓库实现位置 |
|---|---|---|---|
| [`2951461586/GPT-Register-Tool`](https://github.com/2951461586/GPT-Register-Tool) | `direct_card` 提链、Sentinel 令牌签发、协议支付状态机 | ⚠️ 无 LICENSE | `packages/core/src/gss_core/chatgpt.py`、`sentinel.py`（独立重写） |
| [`JJianggg/gpt-checkout-studio`](https://github.com/JJianggg/gpt-checkout-studio) | 选地区/档位 → 生成结账的本地优先交互体验 | ⚠️ 无 LICENSE | `apps/web`（基于 React 19 + Mantine v9 独立实现） |
| [`alexan0618/zkky`](https://github.com/alexan0618/zkky) | 提链/支付分阶段代理隔离、任务状态机 | ✅ MIT | `packages/core/src/gss_core/proxies.py`、`services/payment` |
| [`github/spec-kit`](https://github.com/github/spec-kit) | Spec-Driven Development（SDD）开发方法论 | ✅ MIT | `.specify/`、`specs/001-subscribe-console/` |

---

## 核心特性

1. **浏览器端安全填卡（卡号不出浏览器）**
   - 前端动态挂载 Stripe Payment Element（`js.stripe.com/basil/stripe.js`），卡号、有效期、CVV 仅在 Stripe 官方 iframe 内输入并换取 `ctoken_`。
   - 服务端仅接收不透明的 `payment_method_token`（`ctoken_` 或 `pm_`），从根源杜绝卡号泄露。

2. **凭证零持久化与全局脱敏**
   - **内存金库（`SecretVault`）**：客户粘贴的 Session（支持完整 JSON、JWT `accessToken`、**或单独的 session token**）仅保存在进程内存，设置 30 分钟 TTL，一旦订阅确认交付立即从内存清除（`vault.drop`）。
   - **Session Token 自动换取**：可直接粘贴 `__Secure-next-auth.session-token` Cookie（JWE 格式），系统自动用账单国对齐的代理出口换取 `accessToken`，降低 Cloudflare 403，提升成功率。
   - **全链路日志脱敏（`gss_core.redaction`）**：自动拦截并掩码日志与异常中的 JWT、`accessToken`、Session Cookie、银行卡号（Luhn 识别）及代理账密。

3. **自包含的 ChatGPT & Stripe 协议引擎**
   - 使用 `curl_cffi` 模拟真实浏览器 TLS 指纹（`chrome136`）及配套 Client Hints。
   - 内置 `sentinel_bridge.js`（Node.js 桥），自动完成页面预热、`webDeploymentAttestation` 提取以及 `OpenAI-Sentinel-Token` / `OpenAI-Sentinel-SO-Token` 签发。
   - 同时兼容 ChatGPT 内部结账会话（`oaics_...`）与 Stripe Custom Checkout 会话（`cs_live_...`），支持自动计算税费（`/payments/checkout/taxes` 与 `tax_region`）及确认金额对齐。

4. **智能动态出口代理管理**
   - Web 界面自带「代理设置」面板，支持一键粘贴解析 `http://user:pass@host:port`、`user:pass@host:port`、`host:port:user:pass`、`socks5://...` 等多种格式。
   - 自动识别供应商用户名中的地区（`region` / `country` / `area` / `cc`）与会话（`sid` / `session`）参数，保留原大小写风格。
   - **按单对齐与异常自愈**：创建订单时自动将代理出口重写为所选账单国家并分配全新随机 `sid`（同一订单内提链与支付保持一致）；若遇上游判定 `unusual activity`，自动轮换新 `sid` 重试。

5. **显式状态机与严格交付门槛**
   - 12 种订单状态与 6 种支付尝试状态，所有状态迁移均经纯函数迁移表校验（`ORDER_TRANSITIONS` / `PAYMENT_TRANSITIONS`）。
   - 区分 `requires_action`（3DS 跳转验证）、`unknown`（不确定终态，避免盲目重试导致重复扣款）、`verifying`（等待订阅生效）。
   - **交付规则**：扣款成功（Stripe PaymentIntent 为 `succeeded`，含 3DS 验证通过）即视为订单成功并推进至 `delivered`；订阅状态查询只作为附带信息，查询失败或尚未生效不影响订单结果。Team 托管长链订单仍需用户付款后点击查询，以订阅状态为准。

6. **离线可测（Fake Adapter 体系）**
   - Checkout、Payment、Account 三大能力层均提供 `Fake*` 实现（设置 `GSS_USE_FAKE=true` 即可启用），无需真实 Session、真实银行卡或代理即可跑通全链路测试。

---

## 支持的套餐与地区

### 订阅档位（`Plan`）

| 档位标识 | 界面名称 | 开通方式 | 默认参考报价 | 说明 |
|---|---|---|---|---|
| `plus` | **Plus** | 页内填卡（Custom Checkout） | $20.00 / 月 | 官方 ChatGPT Plus |
| `go` | **Go** | 页内填卡（Custom Checkout） | $8.00 / 月 | 官方 ChatGPT Go |
| `pro_lite` | **Pro Standard** | 页内填卡（Custom Checkout） | $100.00 / 月 | Pro 标准用量档 |
| `pro` | **Pro More** | 页内填卡（Custom Checkout） | $200.00 / 月 | Pro 进阶用量档 |
| `pro_max` | **Pro Max** | 页内填卡（Custom Checkout） | $500.00 / 月 | Pro 最高用量档 |
| `team` | **Team** | 托管长链（Hosted Checkout） | 按席位与周期计费 | 支持 2–999 席位、月付(`month`)/年付(`year`)、工作空间名、优惠码 |

### 支持的账单国家/地区（25 个）

系统内置以下 25 个国家/地区的对应币种、语言（Locale）、时区（Timezone）及默认账单地址模板：

`US`（美国/USD）、`PH`（菲律宾/PHP）、`CL`（智利/CLP）、`EG`（埃及/EGP）、`JP`（日本/JPY）、`GB`（英国/GBP）、`TR`（土耳其/TRY）、`BR`（巴西/BRL）、`MX`（墨西哥/MXN）、`IN`（印度/INR）、`ID`（印尼/IDR）、`VN`（越南/VND）、`TH`（泰国/THB）、`MY`（马来西亚/MYR）、`SG`（新加坡/SGD）、`KR`（韩国/KRW）、`AU`（澳大利亚/AUD）、`CA`（加拿大/CAD）、`DE`（德国/EUR）、`NL`（荷兰/EUR）、`PL`（波兰/PLN）、`AR`（阿根廷/ARS）、`SA`（沙特/SAR）、`AE`（阿联酋/AED）、`ZA`（南非/ZAR）。

> **说明**：结账地区由订单所选的 `billing_country` 决定，系统会自动把出口代理对齐到该地区；session 导出国家无需一致——创建结账前程序会用同一出口调用 `/api/auth/session` 刷新凭证（软失败不阻断），使 accessToken/cookie 与本次出口 IP 同批次。若仍被上游判定 `unusual activity`，再用账单国网络导出的新 session 重试即可。

### 三种正交模式开关

| 开关字段 | 可选值 | 默认值 | 说明 |
|---|---|---|---|
| `billing_mode` | `standard` \| `promo` | `standard` | `promo`（促销/零元）默认全局关闭（需 `GSS_ENABLE_PROMO=true` 且订单显式传 `risk_acknowledged=true`） |
| `card_source` | `customer` \| `platform` | `customer` | `customer` 为客户在浏览器填卡；`platform` 为平台卡池标识 |
| `account_source` | `customer_session` \| `platform_account` | `customer_session` | `customer_session` 为客户粘贴自有账号 Session |

---

## 系统架构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                         apps/web (React 19 + Mantine)                    │
│   ┌────────────────────┐  ┌────────────────────┐  ┌──────────────────┐   │
│   │  开通 (OrderNew)   │  │ 开通记录 (History) │  │ 代理设置 (Proxy) │   │
│   │  + Stripe Elements │  │ (浏览器本地记录)   │  │ (解析/保存/测速) │   │
│   └─────────┬──────────┘  └────────────────────┘  └────────┬─────────┘   │
└─────────────┼──────────────────────────────────────────────┼─────────────┘
              │ 仅传 session + ctoken_ (卡号不经本站)         │
              ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        services/api (FastAPI)                            │
│   - /api/orders (创建订单、发起支付、校验订阅、查询状态、Idempotency-Key) │
│   - /api/settings/proxies (阶段代理网关配置、解析预览、连通性探测)        │
│   - TestAccessMiddleware (生产单容器模式下提供单密码登录与同源 CSRF 防护) │
└─────────────┬──────────────────────────────────────────────┬─────────────┘
              │                                              │
              ▼                                              ▼
┌──────────────────────────────────────┐    ┌──────────────────────────────┐
│     services/orchestrator            │    │   存储与内存金库             │
│   - SubscribePipeline (同步核心管线) │    │   - SecretVault (内存 30m)   │
│   - WorkerEngine (后台轮询/断点续跑) │    │   - SQLite ORM / Store       │
└─────┬───────────────┬──────────────┬─┘    │   - proxy-gateways.json      │
      ▼               ▼              ▼      └──────────────────────────────┘
┌───────────┐   ┌───────────┐  ┌───────────┐
│ services/ │   │ services/ │  │ services/ │
│ checkout  │   │ payment   │  │ account   │
│ (adapter) │   │ (adapter) │  │ (adapter) │
└─────┬─────┘   └─────┬─────┘  └─────┬─────┘
      └───────────────┼──────────────┘
                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        packages/core & packages/contracts                │
│   - gss_core.chatgpt   : ChatGPT / Stripe 协议客户端 (curl_cffi)         │
│   - gss_core.sentinel  : OpenAI-Sentinel 令牌签发桥 (Node.js)            │
│   - gss_core.proxies   : 地区/SID 动态重写与网关持久化                    │
│   - gss_core.redaction : 全局日志与异常敏感信息脱敏                      │
│   - gss_contracts      : 状态机迁移表、领域模型、错误码与 Adapter 协议   │
└──────────────────────────────────────────────────────────────────────────┘
```

分层职责与单向依赖约束详见 [docs/architecture.md](docs/architecture.md) 与 [docs/directory-map.md](docs/directory-map.md)。

---

## 工作流与状态机

### 订单状态机（`OrderStatus`）

```text
created ──► pending_checkout ──► awaiting_payment ──► paying ──► verifying ──► active ──► delivered
  │                │                    │               │           │            │           │
  ├─► rejected     └─► failed           └─► failed      ├─► failed  └─► failed   └───────────┴─► refunded
  └─► failed                                            │
                                                        ├─► requires_action (3DS) ──► paying / failed
                                                        └─► unknown (待对账/重查)  ──► paying / failed
```

### 典型开通流程

1. **阶段一：配置订单并创建结账（`POST /api/orders`）**
   - 用户在前端粘贴 ChatGPT Session（`https://chatgpt.com/api/auth/session` 返回的 JSON 或 `accessToken`），选择套餐与账单地区。
   - 后端解析校验 Session，按所选地区对齐出口代理并生成专属随机 `sid`。
   - 调用 `UpstreamCheckoutAdapter`：预热页面 → 签发 Sentinel 令牌 → 请求 `/backend-api/payments/checkout`：
     - **Plus / Go / Pro**：获取 `checkout_session_id`（`oaics_` 或 `cs_live_`）、Stripe `publishable_key`、含税报价与默认账单地址，状态推进至 `awaiting_payment`。
     - **Team**：生成 `https://pay.openai.com/c/pay/cs_live_...` 托管长链，状态推进至 `awaiting_payment`。

2. **阶段二：完成支付（`POST /api/orders/{id}/pay` 或托管长链）**
   - **Plus / Go / Pro（页内填卡）**：
     - 前端用 `publishable_key` 渲染 Stripe Payment Element，用户填写账单地址与卡信息。
     - 点击「确认支付」时，浏览器直接向 Stripe 请求生成 `ctoken_...`（ConfirmationToken）并传给后端。
     - 后端调用 `UpstreamPaymentAdapter`：同步账单税费（`/payments/checkout/taxes`）→ 确认结账（内部 `/payments/checkout/confirm` 或 Stripe `/v1/payment_pages/{cs_id}/confirm` + Sentinel approve）→ 处理 PaymentIntent。
     - 若需 3DS 验证，返回 `requires_action` 与跳转链接，前端自动每 4 秒轮询订单状态直至完成。
   - **Team（托管长链）**：
     - 用户点击「打开长链」或复制链接在浏览器中完成付款，随后点击「我已支付，查询订阅」。

3. **阶段三：订阅校验与交付（`POST /api/orders/{id}/verify`）**
   - 后端调用 `UpstreamAccountAdapter` 请求 ChatGPT 订阅接口，确认套餐已激活（`active=true`）。
   - 校验通过后状态推进为 `active → delivered`，同时立即销毁内存金库中的 Session 凭证（`vault.drop`）。

---

## 目录结构

```text
gpt-subscribe-studio/
├── apps/
│   └── web/                        # React 19 + TypeScript + Vite 6 + Mantine v9 前端控制台
│       ├── src/
│       │   ├── api/                # 后端 API 客户端与本地历史记录存储
│       │   ├── card-payment/       # 浏览器端 Stripe Payment Element 组件 (CardFields.tsx)
│       │   ├── components/         # PlanPicker / SessionField / BillingForm / ProxySettings 等组件
│       │   ├── pages/              # OrderNew 开通主流程页
│       │   ├── App.tsx             # 顶层标签页布局（开通 / 开通记录 / 代理设置）
│       │   └── plans.ts            # 套餐档位与 25 个国家/地区定义
├── services/
│   ├── api/                        # FastAPI 服务：订单路由、代理设置路由、SQLAlchemy 仓储、登录鉴权中间件
│   ├── orchestrator/               # 编排层：SubscribePipeline 与后台 WorkerEngine（轮询/乐观锁/断点续跑）
│   ├── checkout/                   # 结账能力层：UpstreamCheckoutAdapter & FakeCheckoutAdapter
│   ├── payment/                    # 支付能力层：UpstreamPaymentAdapter & FakePaymentAdapter
│   └── account/                    # 账号能力层：UpstreamAccountAdapter & FakeAccountAdapter
├── packages/
│   ├── contracts/                  # 领域契约：OrderStatus/PaymentStatus 状态机、Mode 校验、Adapter 协议、错误码
│   └── core/                       # 核心库：ChatGPT/Stripe 客户端、Sentinel 桥、动态代理、内存金库、脱敏日志、配置
│       └── src/gss_core/
│           └── sentinel_assets/    # Node.js Sentinel 令牌签发脚本与资源
├── deploy/
│   ├── .env.example                # 环境变量配置模板
│   ├── docker-compose.yml          # 标准容器编排（api + worker）
│   ├── Dockerfile.api              # API / Worker 镜像构建文件
│   └── server/                     # 生产单容器全栈加固部署（含编译前端 + 单密码登录页 + 最小权限配置）
├── tests/
│   ├── unit/                       # 单元测试（协议、脱敏、代理、配置、管线、Session 解析等）
│   ├── contract/                   # 契约测试（状态机迁移表、三正交模式组合校验）
│   └── integration/                # 集成测试（订单 API、代理设置 API、SQLite 持久化、同源访问控制）
├── scripts/
│   └── release_check.py            # 发布前敏感信息扫描脚本（Luhn 卡号、API Key、JWT、代理口令）
├── docs/                           # 架构设计、快速开始、实现细节、合规说明、ADR 决策记录
└── specs/001-subscribe-console/    # Spec-Driven Development 工件（spec / plan / tasks / openapi）
```

---

## 快速开始（本地开发）

### 环境要求

- **Python**: `>= 3.10`（推荐 `3.12`）
- **uv**: Python 包与虚拟环境管理器
- **Node.js**: `>= 18`（用于前端构建，以及真实模式下运行 `sentinel_bridge.js` 签发风控令牌）
- **npm / pnpm**: 前端包管理

### 1. 安装后端依赖

```bash
# 克隆本仓库后进入项目根目录
cd gpt-subscribe-studio

# 使用 uv 同步虚拟环境
uv sync --python 3.12
```

### 2. 启动后端 API

**离线测试模式（使用 Fake Adapter，无需真实 Session 和代理）：**

```bash
GSS_USE_FAKE=true uv run --python 3.12 uvicorn gss_api.main:app \
  --reload --host 127.0.0.1 --port 8080
```

**真实协议模式（默认，直接请求 ChatGPT / Stripe）：**

```bash
uv run --python 3.12 uvicorn gss_api.main:app \
  --reload --host 127.0.0.1 --port 8080
```

启动后可访问：
- 健康检查：`http://127.0.0.1:8080/api/health`
- OpenAPI 交互文档：`http://127.0.0.1:8080/docs`

### 3. 启动前端开发服务器

打开新终端：

```bash
cd apps/web
npm install
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`（Vite 会自动将 `/api` 请求代理至 `http://127.0.0.1:8080`）。

### 4. （可选）启动后台 Orchestrator Worker

若使用异步数据库任务轮询与断点续跑 Worker：

```bash
# 离线 Fake 模式
uv run --python 3.12 python -m gss_orchestrator.worker --fake --poll-interval 5

# 真实模式
uv run --python 3.12 python -m gss_orchestrator.worker --poll-interval 5
```

---

## 容器化部署

本项目提供两种 Docker 部署方案，默认均**仅绑定本地回环地址（`127.0.0.1`）**，如需公网访问请置于 Nginx / Caddy 等 HTTPS 反向代理之后。

### 方式一：开发 / 标准编排部署（`deploy/docker-compose.yml`）

分离运行 `api` 与 `worker` 两个服务，适合本地容器验证或配合独立前端静态托管：

```bash
cd deploy
cp .env.example .env
# 按需编辑 .env

docker compose up -d --build
curl -s http://127.0.0.1:8080/api/health
```

### 方式二：单容器全栈加固部署（`deploy/server/compose.yml`）

专为自有服务器生产运行设计：
- 将编译后的前端静态产物（`apps/web/dist`）、FastAPI 后端、Node.js Sentinel 运行时打包进同一镜像。
- 内置 `TestAccessMiddleware`：未登录访问自动跳转 `/login` 单密码鉴权页，登录成功后签发 `__Host-gss_session`（`Secure` + `HttpOnly` + `SameSite=Strict`，有效期 12 小时），并对非 GET 请求执行 Origin/Host 同源校验。
- 容器安全加固：非 root 用户（UID `10001`）、只读根文件系统（`read_only: true`）、移除全部 Linux Capabilities（`cap_drop: [ALL]`）、禁止提权（`no-new-privileges:true`）。

**部署步骤：**

```bash
# 1. 构建前端静态产物
cd apps/web && npm ci && npm run build && cd ../..

# 2. 准备服务器私有配置目录（切勿放入 Git 仓库）
mkdir -p /opt/gss-private/proxy-config
cat > /opt/gss-private/container-auth.json << 'EOF'
{"password": "your-strong-access-password"}
EOF
chmod 600 /opt/gss-private/container-auth.json

# 3. 启动加固容器（默认监听宿主机 127.0.0.1:18120）
export GSS_RELEASE="$(date +%Y%m%d%H%M)"
export GSS_PRIVATE_DIR="/opt/gss-private"
# 可选：指定固定公网 Origin（不填则自动按请求 Host 同源校验）
# export GSS_PUBLIC_ORIGIN="https://subscribe.example.com"

docker compose -f deploy/server/compose.yml up -d --build
```

随后将反向代理（Caddy / Nginx）指向 `http://127.0.0.1:18120` 即可。

---

## 代理设置说明

本项目不内置任何代理，部署后无需修改环境变量或重启服务，直接在 Web 界面的 **「代理设置」** 标签页配置即可：

1. **支持的输入格式**（一行粘贴）：
   - `http://账号:密码@主机:端口` / `https://账号:密码@主机:端口` / `socks5://账号:密码@主机:端口`
   - `账号:密码@主机:端口`
   - `主机:端口:账号:密码`
   - `主机:端口`（无认证网关）

2. **动态地区与 SID 路由**：
   - 推荐在代理账号中包含地区与会话参数，例如：`acct-region-US-sid-abc123`。
   - 系统自动识别 `region` / `country` / `area` / `cc` 以及 `sid` / `session` / `sessid` / `sessionid`，替换时保留原键名与大小写风格（如供应商要求小写 `us` 会自动保持小写）。
   - 若账号中未包含地区或 SID 参数，系统会在末尾追加 `-region-XX` 与 `-sid-随机8位字符`。
   - 每笔订单创建时，系统会自动将出口地区替换为订单所选地区，并生成全新的随机 `sid`，保证同一订单在「创建结账」与「确认支付」两个阶段使用完全一致的出口 IP。

3. **安全存储与连通性测试**：
   - 代理配置原子写入服务端 `${GSS_CONFIG_DIR}/proxy-gateways.json`（权限 `0700`），API 与前端界面**绝不回显**代理用户名与密码。
   - 点击「测试连接」会通过代理请求 `https://api64.ipify.org?format=json`，返回当前出口 IP 与毫秒级耗时。

---

## 配置参考（环境变量）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `GSS_BIND_HOST` | `127.0.0.1` | API 服务监听地址（安全护栏默认仅回环） |
| `GSS_BIND_PORT` | `8080` | API 服务监听端口 |
| `GSS_DATA_DIR` | `runtime`（容器内 `/data`） | 数据目录（SQLite 数据库存放在 `${GSS_DATA_DIR}/app.db`） |
| `GSS_CONFIG_DIR` | `config`（容器内 `/config`） | 配置目录（存放 `proxy-gateways.json` 及分片配置） |
| `GSS_PROXY_CONFIG` | `${GSS_CONFIG_DIR}/proxy-gateways.json` | 代理网关持久化文件路径覆盖 |
| `GSS_USE_FAKE` | `false` | 设为 `true` / `1` 时启用离线 `Fake*` Adapter，不发真实外部请求 |
| `GSS_ENABLE_PROMO` | `false` | 设为 `true` 时允许创建 `billing_mode=promo` 订单（订单仍需 `risk_acknowledged=true`） |
| `GSS_AUTH_FILE` | 无（仅 `deploy/server` 使用） | 单容器部署模式下的登录密码 JSON 文件路径 |
| `GSS_PUBLIC_ORIGIN` | 空（自动同源校验） | 单容器部署模式下允许的公网 Origin（如 `https://example.com`） |
| `SENTINEL_NODE` | `node` | 用于执行 `sentinel_bridge.js` 的 Node.js 可执行文件路径 |
| `PP_STRIPE_PUBLISHABLE_KEY` | 空 | 应急覆盖：上游轮换 Stripe 公钥时覆盖使用 |
| `OPENAI_SENTINEL_VERSION` | 空 | 应急覆盖：指定 OpenAI Sentinel 版本号 |
| `OPENAI_SENTINEL_DISABLE_QUICKJS` | 空 | 应急覆盖：禁用 QuickJS 执行分支 |

---

## API 接口概览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查，返回版本号、是否开启促销、当前是否为 Fake 模式等 |
| `POST` | `/api/orders` | 创建订单并生成结账会话/托管长链（支持 `Idempotency-Key` 请求头幂等去重） |
| `GET` | `/api/orders/{order_id}` | 查询指定订单的最新状态、结账信息、`next_action`（3DS）及订阅详情 |
| `POST` | `/api/orders/{order_id}/pay` | 提交浏览器生成的 `payment_method_token`（`ctoken_`）与账单地址完成支付确认 |
| `POST` | `/api/orders/{order_id}/verify` | 主动触发订阅生效校验（用于 Team 长链支付后确认或支付后复查） |
| `GET` | `/api/settings/proxies` | 获取 `checkout` 与 `approve` 阶段的代理配置摘要（脱敏，不含账密） |
| `POST` | `/api/settings/proxies/parse` | 预览解析粘贴的代理字符串，检测是否含地区与 SID 参数（不保存） |
| `PUT` | `/api/settings/proxies` | 保存同一代理到提链与支付阶段 |
| `PUT` | `/api/settings/proxies/{role}` | 按阶段（`checkout` / `approve`）单独更新代理配置 |
| `POST` | `/api/settings/proxies/{role}/test` | 测试指定阶段代理连通性，返回出口 IP 与响应耗时 |

完整请求/响应 Schema 定义见 [`services/api/src/gss_api/schemas.py`](services/api/src/gss_api/schemas.py) 与 [`specs/001-subscribe-console/contracts/openapi.yaml`](specs/001-subscribe-console/contracts/openapi.yaml)。

---

## 安全与合规护栏

| 护栏项 | 实现机制 | 代码位置 |
|---|---|---|
| **凭证零落盘** | Session 仅驻留内存 `SecretVault`（30m TTL，交付即删），数据库表无任何凭证字段 | `packages/core/src/gss_core/vault.py`、`packages/contracts/src/gss_contracts/models.py` |
| **卡号不出浏览器** | Stripe Payment Element 托管输入，前端只产出 `ctoken_` | `apps/web/src/card-payment/CardFields.tsx` |
| **全局日志脱敏** | Logging Filter + 正则自动擦除 JWT、Cookie、卡号、代理口令 | `packages/core/src/gss_core/redaction.py` |
| **无校验不交付** | `assert_deliverable` 强制要求 `OrderStatus.ACTIVE` 且 `SubscriptionInfo.active=True` | `services/orchestrator/src/gss_orchestrator/pipeline.py` |
| **高风险模式默认关闭** | `GSS_ENABLE_PROMO=false` 默认关闭，开启后仍强制要求 `risk_acknowledged=true` | `packages/core/src/gss_core/config.py`、`packages/contracts/src/gss_contracts/models.py` |
| **默认回环监听 & 同源鉴权** | Compose 默认仅绑定 `127.0.0.1`；服务端模式内置 `__Host-` 签名 Cookie 与同源校验 | `deploy/docker-compose.yml`、`services/api/src/gss_api/test_access.py` |
| **发布前敏感扫描** | Git 跟踪文件静态扫描（含 Luhn 卡号校验、API Key、JWT、代理账密检测） | `scripts/release_check.py` |

---

## 测试与发布检查

本项目包含 **127 项**自动化测试（涵盖单元测试、契约测试与集成测试），全程离线运行，不依赖外部网络或真实凭证：

```bash
# 运行全部测试套件
uv run --python 3.12 --with pytest pytest -v

# 仅运行契约测试（状态机迁移表 + 模式开关组合）
uv run --python 3.12 --with pytest pytest tests/contract/ -v

# 仅运行单元测试（ChatGPT/Stripe 协议、代理重写、脱敏、Session 解析等）
uv run --python 3.12 --with pytest pytest tests/unit/ -v

# 仅运行集成测试（订单 API、代理设置 API、SQLite 持久化、同源鉴权）
uv run --python 3.12 --with pytest pytest tests/integration/ -v

# 构建前端并进行 TypeScript 类型检查
cd apps/web && npm run build && cd ../..

# 发布前敏感信息检查（确保无真实密钥、卡号或代理口令被提交）
python3 scripts/release_check.py
```

---

## 进阶文档与 ADR

- [快速开始指南](docs/getting-started.md)
- [架构设计总览](docs/architecture.md)
- [技术实现详解](docs/implementation-details.md)
- [目录职责与依赖边界](docs/directory-map.md)
- [合规与数据边界说明](docs/compliance.md)
- [上游集成与许可证边界](docs/upstream-integration.md)
- **架构决策记录（ADR）**：
  - [ADR 0001: 上游 Adapter 边界与许可证隔离](docs/adr/0001-upstream-adapter-boundary.md)
  - [ADR 0002: 显式订单与支付状态机](docs/adr/0002-explicit-order-state-machine.md)
  - [ADR 0003: 自托管 Docker + SQLite 部署选型](docs/adr/0003-self-hosted-docker-sqlite.md)

---

## 免责声明与风险提示

**使用本项目前请完整阅读以下内容。使用、部署、修改或分发本项目，即表示你已理解并接受这些风险。**

1. **仅供学习与技术研究**
   本项目是对公开网页行为的协议层研究与工程实践，不构成任何商业服务承诺，也不保证可用于生产环境。

2. **与第三方无关联**
   本项目与 OpenAI、ChatGPT、Stripe 及任何支付、代理服务商均无隶属、授权或合作关系。相关名称、商标归其各自所有者。

3. **依赖非公开接口，可能违反服务条款**
   本项目通过模拟浏览器请求的方式调用 ChatGPT 与 Stripe 的**非公开、未文档化**接口，并使用代理出口与浏览器指纹模拟。这类用法可能违反 OpenAI、Stripe 及相关服务的服务条款或使用政策。上游随时可能修改接口、风控策略或版本，导致功能部分或全部失效，且不会另行通知。

4. **账号风险：可能被限制、风控或封禁**
   使用本项目可能导致用于开通的 ChatGPT 账号、关联的支付方式、代理 IP 乃至相关账户被**风控、限制功能、暂停或永久封禁**，已开通的订阅也可能被取消或回收。这类损失无法恢复，本项目及其作者不提供任何补偿或申诉协助。

5. **资金风险**
   - 扣款成功即视为订单成功，订阅是否真正生效**不作为**交付前提。可能出现「已扣款但订阅未生效」「重复扣款」「被拒付或退款」「金额与预期不符（含税费、汇率、活动价变动）」等情况，请在使用后自行到账号与账单中核对。
   - 促销、优惠活动（`promo`）由上游控制，资格、价格与有效期可能随时变化，滥用促销可能触发风控或被追缴。
   - 3DS 验证、银行风控、卡片限额等均可能导致支付失败或状态不确定。

6. **合法授权与使用者责任**
   你必须确保对所使用的账号、Session、银行卡、代理拥有合法授权，并遵守所在地法律法规、上游服务条款与支付网络规则。**严禁**将本项目用于盗刷、使用他人未授权的卡片或账号、欺诈、批量滥用或任何违法用途。「代他人开通并收费」属于你与客户之间的商业关系，是否合法及是否需要资质由你自行判断并承担责任。

7. **数据与安全责任**
   本项目设计上不落盘 Session、不接触明文卡号，但部署环境、代理、日志、反向代理与服务器的安全由使用者自行负责。请勿将真实凭证、抓包文件（HAR）、代理账密提交到任何仓库或发给他人。

8. **无担保与责任限制**
   本项目按「现状」提供，不附带任何明示或暗示的担保，包括但不限于适销性、特定用途适用性、稳定性与不侵权。在适用法律允许的最大范围内，作者及贡献者不对因使用或无法使用本项目造成的任何直接或间接损失（包括但不限于账号封禁、资金损失、数据丢失、业务中断、第三方索赔）承担责任。

如果你不接受以上任何一条，请不要使用本项目。

---

## 许可证

本仓库代码基于 **MIT License** 开源。详见 [docs/compliance.md](docs/compliance.md) 与 [docs/upstream-integration.md](docs/upstream-integration.md)。

