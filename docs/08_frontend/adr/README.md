# 前端 Architecture Decision Records

本目录保存会长期影响 pinkdooHub 前端结构、依赖和交付方式的决策。总体现状见 [前端架构](../frontend_architecture.md)。

## 状态

- `Proposed`：候选方案，仍需 Review 或 Spike；
- `Accepted`：已经批准，当前实现必须遵守；
- `Deprecated`：保留历史，但不建议新代码使用；
- `Superseded`：已被新的 ADR 替代，并应链接替代记录。

ADR 不通过静默改写来隐藏历史。重大方向改变时新增 ADR，并把旧记录标记为 Superseded。

## 当前记录

| ADR | 状态 | 决策 |
|-----|------|------|
| [ADR-001](ADR-001-use-taro-react-typescript.md) | Accepted | Taro 4 + React 18 + TypeScript strict |
| [ADR-002](ADR-002-keep-frontend-in-monorepo.md) | Accepted | 前端保留在现有仓库的 `miniapp/` |
| [ADR-003](ADR-003-use-webpack5-first.md) | Accepted | 首个工程使用 Webpack 5 |
| [ADR-004](ADR-004-api-types-from-openapi.md) | Accepted | 从 FastAPI OpenAPI 生成类型 |
| [ADR-005](ADR-005-cross-platform-ui-strategy.md) | Accepted | Taro 基础组件 + 受控 NutUI |
| [ADR-006](ADR-006-auth-and-payment-roadmap.md) | Accepted | MVP/正式发布分阶段认证与支付 |
