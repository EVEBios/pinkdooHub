# ADR-001：使用 Taro 4、React 18 与 TypeScript

> **Status:** Accepted
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

前端首发微信小程序，但已明确在 6–12 个月内支持 H5、支付宝小程序和抖音小程序。开发者此前没有 TypeScript 和主要前端组件框架经验，需要兼顾学习曲线、跨端复用和长期可维护性。

候选方案：

1. 原生微信小程序 + TypeScript；
2. Taro + React + TypeScript；
3. Taro + Vue 3 + TypeScript；
4. uni-app + Vue 3 + TypeScript；
5. 为各平台分别开发。

## Decision

使用：

- Taro 4.x；
- React 18；
- TypeScript strict；
- Taro 标准组件和 API 作为跨端基础。

所有 `@tarojs/*` 依赖必须固定为相同精确版本。准确补丁版本由四端技术 Spike 验证后写入正式 `package.json`。

## Rationale

- Taro 官方覆盖四个已确定目标平台；
- React 与 TypeScript 的知识可以复用于未来 H5 和 `admin-web/`；
- 一套 Feature/API/组件核心比四套独立客户端更适合当前规模；
- TypeScript 可以在 OpenAPI DTO、null、状态和平台适配中提供静态保护；
- Taro 仍保留小程序页面、路由和平台能力模型，便于理解真实平台约束。

## Rejected Alternatives

### 原生微信小程序

只做微信时认知负担最低，但已经确定多端目标，后续迁移会产生重复页面和平台逻辑。

### Taro + Vue / uni-app

Vue 学习曲线可控，但未来 H5/管理端计划同样需要选择生态；当前决定统一使用 React，减少第二套组件模型。

### 每个平台独立开发

平台控制力最高，但重复业务、测试和 API 适配成本不符合当前团队规模。

### React 19

不首发追逐较新的运行组合。先使用 Taro 成熟支持的 React 18，升级必须单独 ADR 和四端回归。

## Consequences

正面：

- Feature、API 类型和大部分组件可共享；
- React/TypeScript 学习可迁移到 Web；
- 四端契约和构建可进入同一 CI。

代价：

- 同时学习 JavaScript、TypeScript、React、Taro 和平台约束；
- Taro 无法抹平全部平台差异，必须维护 Adapter 和矩阵；
- 不能把微信端通过误报为多端通过；
- 第三方 React Web 组件不能默认在小程序可用。

## Validation

- 四端空应用生产构建；
- 微信/H5 启动；
- React 组件和 Taro 页面生命周期测试；
- Request、Storage、Upload 最小验证；
- 一项平台差异 Adapter 示例。

## Spike 验证（2026-08-15）

- 精确版本锁定：Taro（全部 `@tarojs/*`）4.2.1、React/ReactDOM 18.3.1、TypeScript 5.9.3（strict）、Webpack 5.91.0、Sass 1.102.0、NutUI React Taro 2.7.15、Jest 29.7.0、`@tarojs/test-utils-react` 0.1.1、Node 24.13.0。
- weapp/alipay/tt/h5 生产构建通过，`Taro.request` 适配层、Storage、NutUI Button/Toast/Dialog/Input 与 Jest 组件测试可用。
- TypeScript strict 需要在 tsconfig 开启 `skipLibCheck`（Taro 4.2.1 声明文件本身不满足 strict），应用代码仍为严格检查。
- 结论不变：Taro 4 + React 18 + TypeScript strict 满足多端与学习目标。
