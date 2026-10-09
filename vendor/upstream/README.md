# 上游引用（Upstream References）

本目录只存放上游项目的**引用与说明**，**不存放复制的源码**（见
[ADR 0001](../../docs/adr/0001-upstream-adapter-boundary.md) 与
[docs/upstream-integration.md](../../docs/upstream-integration.md)）。

## 为什么要这样做

- `GPT-Register-Tool` 与 `gpt-checkout-studio` **没有 LICENSE 文件** → 复制会侵权。
- 上游调用的是非官方接口、变更频繁 → 复制会让维护成本失控。

## 如何接入（三选一）

### 1. git submodule（推荐，版本可锁）

```bash
git submodule add https://github.com/2951461586/GPT-Register-Tool vendor/upstream/GPT-Register-Tool
git submodule add https://github.com/alexan0618/zkky             vendor/upstream/zkky
git submodule update --init --recursive
```

### 2. 路径依赖（本地已有克隆）

在 `deploy/.env` 里设置：

```env
UPSTREAM_GPT_REGISTER_TOOL_PATH=/abs/path/to/GPT-Register-Tool
UPSTREAM_ZKKY_PATH=/abs/path/to/zkky
```

### 3. 可选 Python 依赖（仅 MIT 上游）

`zkky` 为 MIT，可在保留版权声明的前提下作为可选依赖引入；但**仍优先走 adapter**
以统一失败处理。

## 各上游的用途

| 上游 | 许可证 | 用在哪个 adapter |
|---|---|---|
| `2951461586/GPT-Register-Tool` | ⚠️ 无 LICENSE | `services/checkout`、`services/account` |
| `JJianggg/gpt-checkout-studio` | ⚠️ 无 LICENSE | `apps/web`（仅交互参考） |
| `alexan0618/zkky` | MIT | `services/payment` |

> ⚠️ 需先获得作者授权，才可将其代码 vendored 进本仓库。
