---
version: 1
slug: "miniapp-ribbon-ledger-completion"
primary_target: "miniapp/src/styles/theme.scss"
related_targets: ["miniapp/src/pages","miniapp/src/admin/pages","miniapp/src/admin/styles"]
---

# Ribbon Ledger — Complete Product Surface

## Surface

顾客认证、商品详情、购物车、订单，以及 ADMIN+ 商品、订单、库存、用户和审计工作流。真实工程实现；所有服务端权威状态、路由、权限与写操作语义保持不变。

## Mode

Operate

## Visual thesis

让暖纸白成为安静工作台，让真实商品图、紧凑中文层级和可核对数字成为视觉主体；深莓果只标记当前选择、权威结果与明确下一步。

## Content plan

- 顾客页按“当前对象或身份 → 选择或清单 → 服务端事实说明 → 单一下一步”组织。
- 订单页按“状态与总额 → 商品快照 → 时间和备注 → 允许的操作”组织。
- 管理列表按“工作范围 → 筛选 → 数量摘要 → 可扫描记录”组织。
- 管理详情和表单按“对象身份 → 当前状态或边界 → 编辑工作区 → 核对与返回”组织。

## Interaction thesis

- 所有按钮、筛选与列表记录共享 160ms 的颜色、边线、阴影和按压位移反馈，并服从减少动态偏好。
- 筛选选择只在浅粉轨道与窄域莓果选中态之间过渡，不使用装饰动画。
- 可点击记录在按下时轻微收紧阴影，输入聚焦时由浅粉实底切换为白底和强一档腮红边线。

## Direction contract

THESIS: 同一个 Ribbon Ledger 系统同时服务轻松选购与准确运营，装饰永远不压过状态、金额、库存和操作后果。

OWN-WORLD: 克制莓果粉、暖纸白、瓷白内容面、窄色域渐变、功能性玻璃层、紧凑中文排版和表格数字。

STORY: 顾客从真实商品进入清单与订单；管理员从范围和筛选进入记录、详情与受约束命令。

FIRST VIEWPORT: 每页首屏直接给出对象、任务和首个可操作区域；不使用营销式 Hero、英文 eyebrow 或无任务价值的装饰卡片。

FORM: Code-led Taro mobile workspace，默认 750 设计宽度；H5 显式固定可读字号和 44px 触控高度。CONCEPT-ROLL-SEED: none（本轮沿用用户在 Impeccable 方向轮之前明确选定的本地 A 方案，没有生成 concept-roll seed，不补造）。QUALITY-BAR-CARD: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/ribbon-ledger.jpg`（仅作方向质量基准和 critique reference，不是 approved comp 或像素级 fidelity spec）。

FINISH: 全部注册路由均继承设计令牌，关键状态和真实长内容在 390px 与 768px H5 视口通过验证，微信产物通过既有发布检查。

## Requirements

- 不新增 Hello Kitty、emoji、手绘 SVG、虚构商品图或第三方运行时依赖。
- 真实商品图片继续来自 Product API；无图、加载失败、空、错误、加载和禁用状态均保留。
- 所有输入、按钮和筛选保持足够触控面积，文字垂直居中，普通动作不使用 Taro `mini` 预设。
- 普通中文文案控制行宽；订单号、ID、原因和时间可安全换行；金额和数量使用表格数字。
- 透明和模糊只出现在筛选、认证或关键操作层，并始终保留不透明实色回退。
