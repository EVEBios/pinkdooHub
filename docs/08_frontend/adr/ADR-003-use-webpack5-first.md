# ADR-003：首个 Taro 工程使用 Webpack 5

> **Status:** Proposed
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

Taro 4 支持 Webpack 4、Webpack 5 和 Vite。H5 使用 Vite 通常有较好的开发启动体验，但多小程序场景还要考虑分包、CommonJS、第三方组件和平台插件兼容。开发者第一次使用 Taro，不应同时承担业务、React 与较新编译组合的定位成本。

## Proposed Decision

首个正式工程使用 Webpack 5。暂不选择 Webpack 4；暂不在普通功能开发中切换 Vite。

## Rationale

- Webpack 5 是 Taro 已长期支持的编译路径；
- 对小程序依赖、组件库和插件的兼容经验更成熟；
- 持久缓存/依赖预编译可改善开发体验；
- 第一阶段优先降低多端兼容风险，而不是追求单一 H5 启动速度。

## Trade-offs

- H5 开发启动和热更新可能不如 Vite；
- 需要承受 Webpack 配置复杂度，但业务代码不得依赖其私有能力；
- 如果 Vite 在实际目标版本已稳定解决关键风险，Spike 可能否决本提案。

## Spike

在相同 Taro/React/组件样例下验证：

- weapp/alipay/tt/h5 生产构建；
- 启动与增量编译；
- 分包；
- SCSS；
- NutUI 候选组件；
- Jest 测试；
- 包体积和 warning；
- Windows 本地和 CI 行为。

如果 Webpack 5 四端通过且无阻断，将状态改为 Accepted。若 Vite 显著更稳定或 Webpack 5 阻断，则新增替代 ADR，而不是直接改本文结论。

