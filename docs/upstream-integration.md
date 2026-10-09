# 上游集成说明（Upstream Integration）

**日期**: 2026-10-09

本平台的能力来自三个上游项目。**它们不被复制进本仓库的源码树**，而是以
「adapter 接口 + 引用」的方式集成。原因有两个：许可证，以及上游是非官方且频繁变更的接口。

## 1. 集成总览

| 上游 | 许可证 | 集成方式 | 对应 adapter | 能力 |
|---|---|---|---|---|
| [`2951461586/GPT-Register-Tool`](https://github.com/2951461586/GPT-Register-Tool) | ⚠️ **无 LICENSE 文件** | 路径依赖 / submodule 引用 | `services/checkout/adapter.py`、`services/account/adapter.py` | 邮箱 OTP 注册、账号/Session 管理、`direct_card` 提链、协议支付状态机、代理分片 |
| [`JJianggg/gpt-checkout-studio`](https://github.com/JJianggg/gpt-checkout-studio) | ⚠️ **无 LICENSE 文件** | 仅作交互与流程参考 | `apps/web`（自行实现） | 档位/国家选择、session 导入、托管结账链接流程、订阅查询 |
| [`alexan0618/zkky`](https://github.com/alexan0618/zkky) | ✅ MIT | adapter 引用（MIT 允许复用，需保留版权声明） | `services/payment/adapter.py` | 直卡绑定、任务状态机、提链池/支付池隔离、离线契约测试 |
| [`github/spec-kit`](https://github.com/github/spec-kit) | ✅ MIT | 开发方法论（`.specify/`） | 无（不进入运行时） | SDD 流程与模板 |

> ⚠️ 标记表示：**当前不可直接复制其代码**。若要 vendored，需先获得作者明确授权，
> 或在 LICENSE 变更为开源后重新评估。

## 2. 目录约定

```text
vendor/upstream/
├── README.md            # 各上游的版本锁定与接入步骤（本文件）
└── .gitkeep
```

运行时通过以下方式之一引用上游：

1. **git submodule**（推荐，版本可锁）：
   ```bash
   git submodule add https://github.com/2951461586/GPT-Register-Tool vendor/upstream/GPT-Register-Tool
   ```
2. **路径依赖**：在 `deploy/.env` 中设置 `UPSTREAM_GPT_REGISTER_TOOL_PATH=/abs/path`。
3. **可选 Python 依赖**：仅对 MIT 上游（`zkky`）可用。

**不要**把上游源码 `cp` 进 `services/` 或 `packages/`。

## 3. Adapter 契约

每个能力服务暴露一个 `adapter.py`，实现 `packages/contracts/adapter.py` 中的协议：

```python
class CheckoutAdapter(Protocol):
    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult: ...
    def capabilities(self) -> AdapterCapabilities: ...
```

`AdapterCapabilities` 必须声明：

| 字段 | 含义 |
|---|---|
| `source` | 上游仓库与 commit/版本 |
| `license` | 上游许可证（含「保留所有权利」） |
| `supports` | 支持的档位 / 支付方式 / 国家 |
| `failure_modes` | 已知失败模式与分类（可重试 / 永久失败） |

## 4. 上游变更的应对

| 变更 | 影响面 | 应对 |
|---|---|---|
| Stripe publishable key 轮换 | `checkout` adapter | 环境变量 `PP_STRIPE_PUBLISHABLE_KEY` 应急覆盖 |
| Sentinel SDK 版本轮换 | `account` adapter | `OPENAI_SENTINEL_VERSION` 覆盖 |
| 结账接口字段变化 | `checkout` adapter | 只改 adapter，补离线契约测试 |
| 档位标识变化 | `apps/web` + `contracts` | 更新契约枚举，前端同步 |

## 5. 合规提示

- 上游 README 自身的免责声明同样适用于本平台：仅在获得授权、符合上游服务条款与地区法规时使用。
- `promo`（促销/零元）相关能力来自上游，属于**平台风控与支付合规的高风险区**，
  本平台默认关闭并要求显式风险确认，详见 [compliance.md](./compliance.md)。
