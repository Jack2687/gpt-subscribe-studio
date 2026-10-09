# 架构决策记录（ADR）

按时间顺序记录不可轻易回退的决策。

| 编号 | 标题 | 状态 |
|---|---|---|
| [0001](./0001-upstream-adapter-boundary.md) | 上游以 adapter 边界集成，不复制无许可证代码 | Accepted |
| [0002](./0002-explicit-order-state-machine.md) | 订单与支付使用显式状态机 | Accepted |
| [0003](./0003-self-hosted-docker-sqlite.md) | 容器化自托管 + SQLite 默认存储 | Accepted |

新增 ADR 的规则：

- 文件名 `NNNN-短横线标题.md`，编号递增。
- 至少包含：背景 / 决策 / 理由 / 被否方案 / 影响。
- 一旦 Accepted，修改需新增一条 ADR 而不是改写历史。
