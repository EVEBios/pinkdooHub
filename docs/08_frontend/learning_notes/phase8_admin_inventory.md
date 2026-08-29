# Phase 8.6：Kit Inventory 管理前端

> **状态：** 工程实现、自动化、四端生产构建、后端完整回归与微信开发者工具 Functional 全部完成；2026-08-29 按钮即时筛选与待应用提示增量也已验收通过。
> **完成日期：** 2026-08-28
> **范围：** ADMIN+ Kit 库存调整、指定 Kit 流水、全局流水、导航与权限边界。
> **不包含：** 新库存后端规则、直接设置最终库存、删除商品库存查询、普通用户库存管理、Product 删除恢复、真机/H5 Functional。

## 1. 规划结论与依赖

8.6 没有新增后端能力，而是消费已经完成并通过 MySQL 门槛的三个 Inventory API：

1. `POST /api/v1/admin/products/kit/{product_id}/inventory-adjustments`；
2. `GET /api/v1/admin/products/kit/{product_id}/inventory-transactions`；
3. `GET /api/v1/admin/inventory-transactions`。

依赖方向固定为：

```text
管理页面
  → Inventory Feature（筛选、分页、幂等意图状态）
    → Inventory Endpoint（请求投影、响应 Runtime Guard）
      → ApiClient（Bearer、信封、refresh、HTTP status metadata）
        → Taro JSON Transport
```

Product 管理详情只负责提供 Kit ID、当前状态和权威库存入口，不直接调用 Inventory API。库存写入继续由后端 Inventory Service 拥有事务、行锁、流水和 Audit；前端绝不直接改 `stock`，也不通过 Kit price PATCH 偷渡库存。

## 2. 路由与权限规划

- 全局流水是固定页面 `/admin/pages/inventory-transactions/index`，加入登录 redirect 白名单；首页只为 ADMIN+ 显示“库存流水”。
- 指定 Kit 库存页是动态页面 `/admin/pages/product-inventory/index?id={product_id}`，不加入 redirect 白名单。Guest 从该页登录时返回固定管理商品列表，防止任意动态地址进入认证回跳集合。
- Kit 管理详情增加“管理库存”；Draft、Offline、Online 均可进入，逻辑删除 Kit 禁用入口。
- 页面必须在挂载 Product/Inventory Hook 前完成 Guest/角色判断。普通用户不会主动请求管理 API，但这只是体验层边界；FastAPI ADMIN+ dependency 仍是最终授权事实。
- 指定 Kit 页先读取管理详情，确认未删除且类型为 Kit 后才挂载调整与流水 Hook。已删除商品不调用指定 Kit Inventory 查询，因为后端会按资源规则拒绝。

## 3. HTTP 201/200 与 ApiClient metadata

既有 `ApiClient.request<T>()` 只返回信封中的 `data`，但库存调整必须区分：

- HTTP 201：首次成功创建流水；
- HTTP 200：同一个幂等请求重放，返回既有结果。

因此 Client 新增窄接口 `requestWithMeta<T>()`，返回最终一次请求的 `{data, statusCode}`。原有 `request<T>()` 行为不变，继续只返回 data。若 access token 过期并完成一次 refresh，metadata 取刷新后重放请求的最终状态，不取第一次 `1006` 的状态。

Inventory Endpoint 只接受 200/201；其他 2xx 即使信封正确也视为契约错误。Endpoint 对调整响应、流水和分页逐字段校验并白名单重建，包含：

- 正安全整数 ID、库存 `0..999999`、非零整数变化量；
- `after = before + change`；
- 四类 transaction 与三类 source 的组合关系；
- Order 来源必须有合法 source ID 与订单号；
- admin 调整必须有操作人，migration 期初余额不得伪装操作人；
- UTC 时间、页数公式与页大小；
- 丢弃内部幂等键、技术字段和未知额外字段。

## 4. 幂等业务意图状态机

幂等键不是“每次 HTTP 请求一个 key”，而是“每次业务意图一个 key”：

```text
新调整意图
  └─ 生成 key + 冻结 productId/change/reason
       ├─ 201 → created → 清除意图；下一次操作生成新 key
       ├─ 200 → replayed → 清除意图；明确未重复扣增
       ├─ 明确 4xx/业务拒绝 → failed → 清除意图；修正后是新意图、新 key
       └─ network/timeout/cancel/contract/5xx
            → unknown → 保留原意图
                 └─ 用户点击“安全重试”
                      → 原 productId/change/reason + 原 key
```

实现约束：

- 写请求不自动重试；只有用户点击“安全重试同一次调整”才重发；
- unknown 时禁用输入和新提交，避免把未确认意图与新意图混在一起；
- 快速重复点击合并为同一个进行中 Promise；
- key 是 1–128 个可打印 ASCII 字符，只保存在当前页面内存，不写 Storage、UI、日志、错误消息或响应模型；
- 同 key 不允许修改 change/reason。服务端 `40933` 是明确冲突，清除旧意图后由用户重新发起；
- 页面成功后同时重读 Product 管理详情与第一页流水，以服务端余额和流水收敛界面。

## 5. 流水筛选与分页

指定 Kit 与全局页复用一套筛选组件和分页 Hook：

- transaction type：期初余额、管理员调整、订单扣减、取消恢复；
- source type：migration、admin、order；
- Order source ID 只能与 `source_type=order` 一起发送；
- 全局页额外支持 Product ID；指定 Kit 页不发送 Product ID；
- 日期输入按 UTC 自然日解释。开始日转当日 `00:00:00Z`，包含式结束日转次日 `00:00:00Z`，与后端 `[created_from, created_to)` 一致；
- 筛选草稿与已提交筛选分离。transaction/source 按钮自 2026-08-29 起点击后立即与上一次已提交的 ID/日期组合并回到第一页；Product ID、Order source ID 和日期仍只在点击“查询”后生效；
- 当 ID/日期草稿的规范化值与上次成功提交快照不同时，显示“输入条件尚未应用”浅色提示；校验失败不会错误更新已提交快照；
- 来源从 `order` 切到 migration/admin/all 时，同时清空界面中的 source ID 草稿并从已提交筛选移除 source ID，避免按钮即时查询产生不自洽组合；
- 页码、总数和总页数只信任服务端，sequence 隔离迟到旧响应，重复“加载更多”不会发出并行请求；
- Order 来源流水提供 ADMIN 订单详情入口，展示使用服务端订单号快照。

## 6. 页面与文件落点

- `miniapp/src/api/endpoints/inventory.ts`：三个 Endpoint、请求白名单、状态码判别和 Runtime Guard；
- `miniapp/src/features/inventory/idempotency.ts`：无新增依赖的 key 工厂；
- `miniapp/src/features/inventory/inventory_filters.ts`：筛选解析、UTC 半开区间和 Query 生成；
- `miniapp/src/features/inventory/use_inventory_adjustment.ts`：幂等意图状态机；
- `miniapp/src/features/inventory/use_inventory_transaction_list.ts`：两类服务端分页列表；
- `miniapp/src/admin/components/inventory.tsx`：共享筛选、流水卡片与四态；
- `miniapp/src/admin/pages/product-inventory/`：Kit 余额、调整和指定 Kit 流水；
- `miniapp/src/admin/pages/inventory-transactions/`：全局流水；
- `miniapp/src/api/client.ts`：向后兼容的 `requestWithMeta()`。

## 7. 自动化与工程门槛

本阶段新增/更新测试覆盖：

- 调整请求 path/header/body 白名单，201/200 分支、非法 2xx 与响应不自洽；
- 四类流水、source 元数据组合、额外字段丢弃、分页公式；
- 路由正安全整数、UTC 日期、source ID 依赖和 key Header 约束；
- unknown 不自动重发、安全重试原样复用 key/request、双击 Promise 合并、明确失败后新 key；
- 全局/指定 Kit 筛选分页、迟到/重复加载边界；
- Guest 固定回跳、普通用户零管理 Hook、已删除 Kit 阻断、Online Kit 可管理；
- Product 详情与首页导航回归。

实际门槛结果：

- 定向：9 套件、42 项通过；
- 前端完整：60 套件、375 项通过；
- TypeScript strict、ESLint、Stylelint、OpenAPI 类型漂移检查通过；
- weapp、alipay、tt、h5 production build 通过；
- 后端完整 SQLite：1465 项通过，9 项 MySQL-only 按配置跳过；
- 三端 `admin` 分包约 167 KiB；H5 主 JS 283 KiB、入口 370 KiB，保留既有 244 KiB 性能建议和 Webpack `[hash]` 弃用告警；
- `npm ls --depth=0` 正常；官方 registry 仍报告 Taro H5 上游链 10 项风险（4 moderate、1 high、5 critical），破坏性强制降级未执行。

没有修改后端 API、OpenAPI、数据库 Schema/迁移、依赖或版本候选。

## 8. 微信开发者工具 Functional 清单

> **验收结果（2026-08-28）：** 用户确认本节 Functional 全部验证完成并通过；该结论针对微信开发者工具与当前本地联调环境，不替代真机、H5、支付宝或抖音 Functional。

### 8.1 入口与权限

1. Guest 在 Console 执行：

   ```js
   wx.navigateTo({ url: '/admin/pages/inventory-transactions/index' })
   ```

   点击登录后应返回全局库存流水固定页；未登录时不请求 Inventory API。
2. Guest 直接进入动态 Kit 页：

   ```js
   wx.navigateTo({ url: '/admin/pages/product-inventory/index?id=7' })
   ```

   登录回跳目标应是管理商品列表，而不是动态 Kit 页。
3. 普通用户进入两个页面均显示无管理权限；Network 中没有 Inventory 请求。用真实 HTTP 工具携带普通用户 access 请求 ADMIN Endpoint 时，FastAPI 返回 403。
4. ADMIN 首页显示“库存流水”；Experience 详情没有“管理库存”；Kit 详情有该入口。

### 8.2 库存调整

1. 分别从 Draft、Offline、Online Kit 进入，确认都可提交；逻辑删除 Kit 不可进入管理库存。
2. 提交 `+5` 与原因，预期显示“首次调整已提交”，余额和流水同步增加，Network 状态为 201。
3. 提交负数使余额仍不小于 0，预期余额正确减少。
4. 验证空原因、0、非整数、超范围在前端阻止；让负数导致余额小于 0，预期服务端 `40932`，余额不变。
5. 快速连点提交，只出现一条新流水。
6. 用断网/请求失败制造 unknown：页面应提示不会自动重发、输入保持锁定；恢复网络后点击“安全重试同一次调整”。若原请求已提交，Network 返回 200，页面提示命中原结果且库存只变化一次；若原请求未到达，可能返回 201，但仍只产生一次业务变化。
7. 不在 Console、Storage、UI、响应 body 或应用日志中寻找/打印幂等键；只在 Network 的该次请求 Header 中确认存在即可。

### 8.3 流水查询

1. 指定 Kit 页只显示该 Product 的流水；全局页可按 Product ID 筛选。
2. 依次验证四类流水和三类来源；Order source ID 只有选择“订单”后可填。
3. Order 来源卡片能进入对应 ADMIN 订单详情。
4. 验证 UTC 开始/结束日期、组合筛选、Empty、Error 重试和超过 20 条时的“加载更多”；翻页后筛选保持不变，列表不重复。
5. 流水不显示内部 key、手机号、Token、技术 `updated_at` 等非契约字段。

## 9. 知识点

- HTTP success 不只有 200；业务需要区分 201/200 时，Client 应以窄 metadata 接口保留状态码，同时保持既有 data-only 调用兼容。
- Idempotency-Key 绑定业务意图，不绑定按钮点击或传输尝试；安全重试必须复用原 payload 和原 key。
- “结果未知”不是失败：客户端无法证明事务未提交时，自动换 key 重发可能造成重复库存变化。
- UI 防连点、Promise 合并和后端幂等分别解决不同层次的问题，三者不能互相替代。
- 生成 TypeScript 类型只提供编译期帮助；外部 JSON 仍要从 `unknown` 校验并做白名单投影。
- 客户端角色守卫用于避免错误挂载，真正授权必须由后端对每个 ADMIN Endpoint 执行。
- 日期筛选的“包含结束日”需要转换为次日排他上界，才能和后端 UTC 半开区间一致。
- 库存余额、流水、Audit 和 Order 库存生命周期是同一服务端事实；前端成功后应重新读取，而不是本地猜测事务结果。
