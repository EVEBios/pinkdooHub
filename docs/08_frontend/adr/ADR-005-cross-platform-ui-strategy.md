# ADR-005：跨端 UI 使用 Taro 基础组件与受控 NutUI

> **Status:** Accepted
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

原生微信 TDesign 不能作为微信、支付宝、抖音和 H5 的统一 React 组件基础。完全自研组件成本过高；直接让所有页面深度依赖第三方组件又会扩大平台差异和替换成本。

## Proposed Decision

采用三层策略：

```text
@tarojs/components
  → verified @nutui/nutui-react-taro（按需）
  → project component boundary
  → business page
```

布局和基本展示优先 Taro 标准组件。表单、Dialog、Toast、Picker、Upload 等候选使用 NutUI，但复杂组件必须先完成四端 Spike；业务关键组件由项目封装稳定 Props/Events。

## Rationale

- Taro 标准组件是跨端最小基线；
- NutUI React 面向 H5 和小程序，使用 TypeScript，覆盖常用移动端交互；
- 项目封装可以吸收第三方差异并支持单点替换；
- 不需要从零实现所有基础控件。

## Rules

- 不全量引入组件库；
- 不把 NutUI DTO 当作业务领域类型；
- 不把主题变量散落在页面；
- 新复杂组件先更新兼容矩阵；
- 不支持某端时显式替换/降级，不伪装成功；
- 不以截图一致为唯一标准，还要测试事件、disabled、loading、value 和错误行为。

## Spike Matrix

验证 Button、Input/Form、Dialog/Toast、Picker、Upload、ImagePreview、InfiniteLoading 和 Safe Area：

- weapp/alipay/tt/h5 构建；
- 实际渲染；
- 交互事件；
- 受控值；
- 异常和卸载；
- 样式覆盖；
- Tree shaking/包体积。

如果关键组件在目标端存在阻断，将缩小 NutUI 使用范围或评估其他候选，并用替代 ADR 记录。

## Spike Result（2026-08-15）

`spikes/taro-four-end-spike` 中验证 Button、Toast、Dialog、Input：

| 组件/能力 | weapp | alipay | tt | h5 | 结论 |
|-----------|-------|--------|----|-----|------|
| Button（type/loading/disabled/事件） | ✅ 编译 | ✅ 编译 | ✅ 编译 | ✅ 编译 | 四端可用，受控用法由组件测试覆盖 |
| Toast（visible/content/onClose） | ✅ 编译 | ✅ 编译 | ✅ 编译 | ✅ 编译 | 受控开关四端可用 |
| Dialog（visible/onConfirm/onCancel） | ✅ 编译 | ✅ 编译 | ✅ 编译 | ✅ 编译 | 受控开关四端可用 |
| Input（受控 value/onChange） | ✅ 编译 | ✅ 编译 | ✅ 编译 | ✅ 编译 | 受控值四端可用 |

Picker、Upload、ImagePreview、InfiniteLoading、Safe Area 未进入本次最小 Spike，正式工程按需引入时再逐项更新矩阵；不把微信端通过误报为四端通过。

**关键体积结论**：2.7.15 没有按组件 JS 入口，`import { ... } from '@nutui/nutui-react-taro'` 桶导入会把整库（avatar/tour/sidenavbar 等）打入产物；全量主题 `default.scss` 使 h5 CSS 达 202 KiB、入口合计 485 KiB（超过 webpack 244 KiB 建议线）。正式工程必须实现按需引入（babel-plugin-import 或等价方案）并把包体积纳入构建门槛后，才允许 NutUI 进入业务页面。
