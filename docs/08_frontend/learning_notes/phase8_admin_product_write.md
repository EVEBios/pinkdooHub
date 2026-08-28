# Phase 8.2 学习笔记：ADMIN Product 创建、基本编辑与逻辑删除

> 状态：**工程实现、自动化与微信开发者工具 Functional 均已完成。** 本阶段只开放 Experience/Kit 草稿创建、名称/描述编辑与 Product 逻辑删除；不包含 Option、创建后的 Kit 价格调整、图片、上下架、Inventory、Audit 页面或删除恢复。

## 1. 端点与表单边界

| 用例 | Endpoint | 客户端字段 | 成功响应 |
|------|----------|------------|----------|
| 创建 Experience | `POST /api/v1/admin/products/experience` | `name`、可选 `description` | `ExperienceProductCreateOut`，HTTP 201 |
| 创建 Kit | `POST /api/v1/admin/products/kit` | `name`、可选 `description`、必填 `price` | `KitProductCreateOut`，HTTP 201 |
| 编辑基本信息 | `PATCH /api/v1/admin/products/{id}` | 至少一个真正变化的 `name`/`description` | `ProductBasicInfoOut`，HTTP 200 |
| 逻辑删除 | `DELETE /api/v1/admin/products/{id}` | 无 body | `DeletedResourceOut`，HTTP 200 |

Experience 与 Kit 使用独立表单组件。Experience 不接受 price/options/images；Kit 创建必须有 price，但不接受 stock，后端固定以零库存建立草稿。创建后类型不可变，创建响应中的真实 ID 与类型用于进入现有管理详情。

基本信息 PATCH 先对规范化后的当前值与服务端初始值做差异比较，只发送真正改变的字段。`description` 缺失表示不修改，显式 `null` 表示清空；空字符串和纯空白在客户端规范化为 `null`。空 patch 在发请求前阻止。

## 2. 状态与删除规则

- Draft/Offline 可编辑名称和描述；Online 由后端 `40905` 拒绝；
- Draft/Offline 可逻辑删除；Online 必须先下架，后端返回 `40904`；
- 已删除 Product 返回 `40903`，页面禁用编辑和删除操作并明确说明不提供恢复；
- Phase 8.2 不自动下架，也不提供恢复按钮；上下架属于 8.5；
- 删除只改变 Product `is_deleted`，不臆造关联 Option/Image/Kit 数据变化。

## 3. 写请求状态机

所有 mutation 使用同一个可测试用例 Hook，状态固定为：

```text
idle → submitting → succeeded
                  ↘ failed
                  ↘ unknown
```

同一 Hook 的进行中 Promise 被复用，避免同一事件帧快速点击发出重复请求。明确 Business/权限/校验错误进入 `failed`；network、timeout、cancel、成功响应 ContractError 和 HTTP 5xx 无法证明服务端未提交，进入 `unknown`，且不自动重发。

- 创建 unknown：返回管理列表，按名称/类型核对是否已产生草稿；
- 编辑 unknown：重新进入详情核对服务端名称/描述；
- 删除 unknown：重新加载详情或包含删除记录的列表核对；
- 成功后的导航以服务端 ID/类型为准，不用客户端虚构聚合。

## 4. 页面与权限

- 管理列表提供明确的“新建 Experience”和“新建 Kit”入口；
- 创建页只接受固定 `type=experience|kit`；
- 管理详情对未删除且非 Online 商品开放“编辑基本信息”和“逻辑删除”；Online 显示需先下架的说明；
- 编辑页同时校验正安全整数 ID 与 Product 类型；
- Guest 登录只返回固定管理列表，动态创建/编辑/详情路径不进入登录 redirect 白名单；
- 普通用户在页面守卫阶段拦截，不能挂载查询或 mutation Hook；后端 ADMIN+ 仍是最终授权事实。

## 5. 自动化与 Functional 门槛

自动化覆盖请求白名单、响应 Runtime Guard、非法 ID、类型专属创建字段、PATCH 差异、无 body DELETE、Promise 合并、unknown 不重放、业务错误映射、权限守卫、表单边界、成功导航和删除确认。Phase 8.2 定向 7 套件/56 项与完整前端 41 套件/288 项均已通过；TypeScript strict 通过。Taro Test Utils 仍输出既有 React `act` 弃用提示，不影响断言。

微信 Functional 至少覆盖 Experience/Kit 创建、零库存 Kit、基本信息单字段 PATCH、描述清空、Draft/Offline 删除、默认列表隐藏与 `include_deleted` 查回、Online/已删除操作边界、快速连点、断网 unknown 和普通用户权限。

2026-08-26 用户确认上述业务 Functional 全部通过。验收后曾发现管理页白色图案和登录框输入 `_` 闪烁，并在当时作为独立视觉问题延期；管理搜索框和登录用户名/密码框启用 Taro `alwaysEmbed` 后的首次复测没有解决白色图案，因此该尝试不能被当作修复证明。2026-08-29 专项排查确认白色图案来自带白色卡片视觉样式的原生 `Form`：将视觉背景、边框、圆角和内边距迁移到外层 `View`，让内层 `Form` 只保留提交语义，并把无提交语义的 Product 创建/编辑/配置容器直接改为 `View` 后，用户复测库存流水、管理商品、Kit 管理库存、管理订单和预防性调整页面全部通过。登录 `_` 闪烁后续无法再复现，用户确认已消失，两项均标记为已解决。

工程实现对应：

- `AdminProductApi` 的四类写请求、严格请求投影与四类响应 Runtime Guard；
- `useAdminProductMutation()` 的统一判别状态与进行中 Promise 合并；
- 管理列表两类创建入口、类型专属创建页、真实详情驱动的基本信息编辑页；
- 管理详情的状态边界、删除确认、unknown 后权威核对入口；
- 固定创建/编辑路由解析与 ADMIN+ 页面守卫。

## 6. 知识点

1. **PATCH 的缺失与 null 是不同协议语义。** 缺失是不修改，null 是明确清空，表单状态不能直接整体序列化。
2. **前端禁用按钮不替代服务端状态校验。** 页面快照可能过期，40904/40905 仍必须稳定处理。
3. **非幂等创建的超时不是失败证明。** POST unknown 必须先核对服务端，再决定是否重新创建。
4. **创建表单按聚合类型拆分。** Experience 的价格属于 Option，Kit 的价格属于 Kit 扩展；万能表单会模糊领域边界。
5. **逻辑删除不是级联删除。** UI 只展示 Product 删除事实，历史关联数据继续由后端保留。
