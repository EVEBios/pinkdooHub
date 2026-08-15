# ADR-005：跨端 UI 使用 Taro 基础组件与受控 NutUI

> **Status:** Proposed
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

