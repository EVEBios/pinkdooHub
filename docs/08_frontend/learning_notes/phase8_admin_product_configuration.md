# Phase 8.3 学习笔记：ADMIN Experience Option 与 Kit 价格管理

> 状态：**工程实现与自动化已完成；微信开发者工具 Functional 除改价前后订单快照外均已通过。** 2026-08-26 用户确认验收清单 1–11 通过；Phase 8.5 上下架按钮现已完成，第 12 项已纳入 Phase 8.4–8.5 合并 Functional。本阶段本身只开放 Experience Option 新增/恢复、修改、逻辑删除和 Kit 当前价格修改；图片、上下架/readiness 由后续 8.4–8.5 提供，Inventory、Audit 或 Product 恢复仍不在范围内。

## 1. 端点与聚合边界

| 用例 | Endpoint | 请求 | 成功响应 |
|------|----------|------|----------|
| 新增或恢复 Option | `POST /api/v1/admin/products/experience/{product_id}/options` | `duration_minutes`、`participants`、`day_type`、`price` | 新建 HTTP 201、恢复 HTTP 200，均为 `ExperienceOptionOut` |
| 修改 Option | `PATCH /api/v1/admin/options/{option_id}` | 至少一个真实变化字段 | `ExperienceOptionBaseOut` |
| 逻辑删除 Option | `DELETE /api/v1/admin/options/{option_id}` | 无 body | `DeletedResourceOut` |
| 修改 Kit 价格 | `PATCH /api/v1/admin/products/kit/{product_id}/price` | 仅 `price` | `KitPriceOut` |

Experience 的价格属于 Option，Kit 的价格属于 ProductKit 一对一扩展。配置页按 Product 类型分支，避免“万能价格表单”把两个领域模型混在一起。Kit 页面可以展示权威库存余额，但请求投影永远只有 `price`；库存写入必须经过 Phase 8.6 Inventory 流水与幂等键。

## 2. Option 全历史唯一与恢复原 ID

Option 的业务身份是：

```text
(product_id, duration_minutes, participants, day_type)
```

唯一性覆盖有效和已逻辑删除的全部历史：

- 没有历史组合：创建新 Option，服务端返回新 ID；
- 有效组合已存在：服务端返回 `40911`；
- 已删除同组合存在：恢复原记录，保留原 Option ID 和图片关联，只更新本次价格；
- PATCH 目标组合命中其他有效或已删除记录：同样返回 `40911`。

前端不维护“已删除 Option 列表”来模拟恢复，也不生成 ID。POST 对 UI 统一称为“新增 / 恢复”，最终只接受服务端响应的真实 Option ID。这样数据库唯一约束、并发处理和审计事务仍由后端单点负责。

## 3. PATCH、金额和删除语义

编辑表单从管理详情初始化，保存前比较规范化后的最终值：

- 数值相同的时长、人数和日期类型不发送；
- `99` 与响应中的 `99.00` 视为同一金额；
- 空差异在发请求前阻止；
- Option PATCH 字段不能显式为 `null`；
- 金额保持普通十进制字符串，最多两位小数，`0 < price <= 99999`；
- Option DELETE 无 body，只设置逻辑删除标记，不删除图片、不改变 Product status。

允许删除最后一个有效 Option。Draft/Offline 商品仍保留原状态；Phase 8.5 上架现由后端 ProductValidator 对“至少一个 Option”统一给出 readiness issue。客户端不提前复制 Validator。

## 4. 状态、权限与结果未知

只有 Draft/Offline 且未删除 Product 可修改配置。页面禁用 Online/已删除操作是即时反馈，不能替代服务端：

| code | 客户端语义 |
|------|------------|
| `40001` | Product 类型与当前配置页不匹配 |
| `40401/40402/40404` | Product、Option 或 Kit 扩展不存在 |
| `40903/40912` | Product 或 Option 已逻辑删除 |
| `40905` | Online Product 不可修改 |
| `40911` | Option 全历史组合冲突 |

页面先确认 Auth 已初始化且角色为 ADMIN+，再挂载详情与 mutation Hook；Guest 登录后只返回固定管理商品列表，动态配置路径不进入 redirect 白名单。FastAPI ADMIN+ dependency 仍是最终授权边界。

四类写用例共享独立配置状态机：

```text
idle → submitting → succeeded
                  ↘ failed
                  ↘ unknown
```

进行中 Promise 合并，避免快速点击形成重复写。network、timeout、cancel、成功响应 ContractError 和 HTTP 5xx 无法证明事务未提交，进入 unknown 且不自动重发；用户只能重新加载类型专属管理详情核对。明确业务拒绝进入 failed，可以修正表单后再次提交。

## 5. 历史订单快照

Option 或 Kit 改价只影响未来订单。订单创建时已经把商品名称、Option 维度和单价写入 Order Item 快照；Phase 7.3/7.4 的订单页面继续渲染这些快照，不能使用当前 Product/Option 详情覆盖历史事实。

因此人工验收必须保留一张改价前订单，完成 Option/Kit 改价后重新打开旧订单，确认名称、配置和单价保持不变；再创建新订单，确认使用新价格。

## 6. 自动化范围

自动化覆盖：

- 四个 Endpoint 的 URL、method、Bearer、请求白名单和响应 Runtime Guard；
- Option 新增/恢复完整请求、PATCH 差异、空 patch、DELETE 无 body；
- Kit 改价不发送 stock；
- 响应中的真实 Option ID、金额、Label 和图片白名单；
- Promise 合并、40911 明确失败、timeout unknown 不重发；
- 路由正安全整数与固定 Product 类型；
- 普通用户不挂载 Hook，Online/已删除只读；
- 删除确认中的历史快照和恢复原 ID 提示；
- 表单正整数、普通十进制金额与等价金额 diff。

最终门槛：8.3 定向 5 套件/48 项、完整前端 43 套件/306 项、TypeScript、ESLint、Stylelint、OpenAPI 漂移和四端 production build 均通过；Product API 52 项、完整后端 1446 项通过，9 项 MySQL-only 跳过。H5 主 JS 278 KiB、入口 362 KiB，仍有既有 244 KiB 性能建议与 Webpack `[hash]` 弃用告警。

## 7. 微信 Functional 验收清单

1. Draft Experience 新增一个全新组合，返回配置页后显示服务端 Option ID、维度和价格。
2. 修改 Option 仅改价格，再重新进入详情确认；再同时修改维度与价格确认成功。
3. 创建与现有有效组合相同的 Option，确认显示重复组合提示且不新增记录。
4. 逻辑删除一个 Option，确认从有效列表消失、Product status 不变。
5. 再次提交被删除的同组合和新价格，确认恢复的是原 Option ID；图片保留可在 Phase 8.4 图片管理页继续核对。
6. 删除最后一个有效 Option，确认 Draft/Offline 仍可保留并显示无法满足上架条件的提示。
7. Draft/Offline Kit 修改价格，确认库存余额完全不变。
8. 对 Online 与已删除 Product，确认表单和按钮只读；独立客户端制造状态竞争时，后端 `40905/40903/40912` 提示稳定。
9. 快速连续点击提交或删除，只产生一个进行中的业务请求。
10. 断网后提交进入结果未知，不自动重发；恢复网络后点击“重新加载详情核对”。
11. 普通用户直接进入配置路径不挂载管理 API；直接调用 ADMIN Endpoint 仍由后端返回 403。
12. 改价前旧订单保持原 Option/Kit 单价和配置快照，新订单使用新价格。

验收结果（2026-08-26）：第 1–11 项已通过。Phase 8.5 上下架界面已经交付，第 12 项现纳入 Phase 8.4–8.5 合并清单；不用手工改库或后端命令代替真实界面验收。

## 8. 知识点

1. **聚合类型决定价格归属。** Experience 的价格属于 Option，Kit 的价格属于 ProductKit；相似 UI 不代表相同领域模型。
2. **业务身份不等于数据库自增 ID。** Option 组合是业务唯一键，恢复流程必须保留服务端历史 ID。
3. **逻辑删除与新建不是两条独立历史。** 已删除组合再次 POST 是恢复，不是绕开唯一约束创建第二条版本。
4. **PATCH 发送意图，不发送整张表单。** 缺失字段表示不修改，等价金额要先规范化再比较。
5. **客户端按钮禁用不是并发控制。** 页面快照可能过期，最终仍由后端状态、唯一约束和事务裁决。
6. **Promise 合并不是服务端幂等。** 它只能减少本客户端重复点击；结果 unknown 后仍必须先读后端，不能盲目重发。
7. **当前主数据与历史交易事实必须分离。** 商品改价改变未来报价，不能改写已下单的 Order Item 快照。
8. **跨领域写入必须守住边界。** Kit 价格页面即使读到了 stock，也不能把 stock 带入 Product 请求，更不能绕开 Inventory 流水。
