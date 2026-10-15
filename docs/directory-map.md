# 目录职责（Directory Map）

**日期**: 2026-10-09

```text
gpt-subscribe-studio/
├── .specify/                    # spec-kit SDD 骨架（constitution / templates / scripts）
├── .claude/skills/speckit-*     # spec-kit 生成的 agent skills
├── apps/
│   └── web/                     # React + Vite 前端（客户控制台 + 运营后台）
├── services/
│   ├── api/                     # FastAPI 网关：订单、查询、SSE、鉴权、幂等
│   ├── orchestrator/            # 编排 worker：状态机推进、重试、断点续跑
│   ├── checkout/                # 能力：结账链接生成（adapter → GPT-Register-Tool）
│   ├── payment/                 # 能力：卡绑定与支付执行（adapter → zkky）
│   └── account/                 # 能力：注册 / 账号库存 / 订阅校验（adapter → GPT-Register-Tool）
├── packages/
│   ├── contracts/               # 共享契约：状态机枚举、模型、adapter 协议
│   └── core/                    # 共享底座：脱敏日志、transport、配置加载
├── vendor/
│   └── upstream/                # 上游引用与版本锁定（**不放复制代码**）
├── deploy/                      # docker-compose、.env.example、Dockerfile
├── docs/                        # 架构、上游集成、合规、目录职责、ADR
├── specs/                       # SDD 工件（每个 feature 一个 NNN-* 目录）
├── scripts/                     # release_check.py 等工具
└── tests/                       # 离线契约测试 / 集成测试 / 单元测试
```

## 职责与边界速查

| 路径 | 拥有 | 禁止 |
|---|---|---|
| `apps/web` | UI、卡字段组件、SSE 订阅 | 禁止把卡号/CVV 发往服务端 |
| `services/api` | HTTP 契约、鉴权、幂等、持久化 | 禁止直接调用上游 |
| `services/orchestrator` | 状态迁移、重试策略、Job 占锁 | 禁止内联上游 HTTP 细节 |
| `services/*/adapter.py` | 唯一的**上游接触点** | 禁止把上游字段泄漏进 `packages/contracts` |
| `packages/contracts` | 跨服务结构、状态机 | 禁止依赖任何服务实现 |
| `packages/core` | 脱敏、日志、配置、transport | 禁止含业务编排逻辑 |
| `vendor/upstream` | 引用与版本说明 | 禁止存放复制的上游源码 |
| `deploy` | 编排与运行配置 | 禁止提交真实凭据 |

## 依赖方向（单向）

```text
apps/web ──► services/api ──► services/orchestrator ──► services/{checkout,payment,account}
                                        │                              │
                                        └──────────► packages/contracts ◄──┘
                                                          ▲
                                                   packages/core
```

`packages/*` 不得反向依赖 `services/*`；`services/*/adapter.py` 是唯一的出站边界。
