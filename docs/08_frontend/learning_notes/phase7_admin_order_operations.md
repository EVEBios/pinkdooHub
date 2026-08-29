# Phase 7.4 学习笔记：ADMIN 订单查询与人工状态操作

> 状态：**Phase 7.4 工程实现与微信开发者工具 Functional 全部通过；2026-08-28 新增的商品名称筛选及 2026-08-29 管理筛选/日期交互增量也已完成验收。** 原阶段完成 ADMIN+ 订单列表/详情、完整筛选、Pending → Paid、Paid → Completed、普通用户前端边界、`admin` 分包和服务端状态收敛。商品名称增量后，完整前端为 47 套件/330 项，Order 后端 411 项、后端全量 1457 项（另 9 项 MySQL-only 跳过），TypeScript、ESLint、Stylelint、OpenAPI 漂移和四端 production build 均通过。2026-08-25 原清单已全部通过：断网时进入“结果待确认”且不自动重发 PATCH；Slow 3G 约 310 ms 正常返回，未触发 timeout；独立客户端抢先变更订单后，旧 ADMIN 页面收到 40921 并通过 GET 收敛到最新状态；普通用户直调 ADMIN API 返回 403 且不触发 Token refresh。本结论不代表 H5 Functional 已通过。

## 1. 最小纵向切片

```text
ADMIN+ 首页入口
      │
      ▼
GET /api/v1/admin/orders
      │ status/order_no/product_name(snapshot)/user_id/UTC range
      │ + server pagination
      ▼
GET /api/v1/admin/orders/{id}
      │
      ├─ Pending ── PATCH /paid（无 body）── GET 详情核对
      │
      ├─ Paid ───── PATCH /complete（无 body）── GET 详情核对
      │
      └─ Cancelled / Completed ── 无操作按钮
```

本阶段没有实现支付渠道、退款、任意状态编辑、订单删除、审计历史页面或库存调整。`/paid` 是现有后端明确提供的临时人工确认入口；支付与完成均不改变库存。

## 2. 实施步骤与测试

### 7.4.1 ADMIN Order Endpoint

`OrderApi` 新增：

- `listAdminOrders()`：认证 GET，只投影 `page/page_size/status/order_no/product_name/user_id/created_from/created_to`；
- `getAdminOrderDetail()`：认证 GET，只接受正整数 ID；
- `markOrderPaid()` 与 `completeOrder()`：认证、严格无 body PATCH；
- ADMIN 列表和详情只额外接受 `user_id/user_nickname`，继续复用金额、状态、时间和 Item 快照 Guard。

**新知识：生成类型仍不能替代 ADMIN 响应的运行时最小权限投影。** 即使服务端意外多返回手机号、内部备注或其他用户字段，Endpoint 也只重新构造契约允许的安全字段。

**新知识：命令式端点应校验“目标状态”，不能只校验响应形状。** `/paid` 返回合法但不是 `paid` 的 `OrderStatusOut` 仍是契约错误；`/complete` 同理。

测试覆盖完整 Query 编码、null/未知字段省略、安全用户字段、坏 ADMIN 响应拒绝、403/40411/40921 保留，以及两个 PATCH 的 `body === undefined`。

### 7.4.2 管理订单列表与筛选

管理列表位于 `admin` 分包，固定每页 20 条，支持状态、精确订单号、下单时商品名称快照、用户 ID、UTC 开始/结束日期和服务端分页。筛选草稿经纯函数校验后才变成请求条件。

2026-08-28 增补商品名称部分匹配。后端查询 `order_items.product_name` 快照而不是当前 Product 名称，并通过订单 ID 子查询过滤外层 Order；因此商品改名、下架或逻辑删除不影响历史检索，一张订单多条 Item 命中也不会放大 `total/pages/item_count`。客户端只新增输入、白名单 Query 和筛选快照传递，不改变列表响应形状。

**新知识：历史订单检索必须和历史展示使用同一事实来源。** 页面展示的是下单时名称与价格快照，如果搜索却关联当前 Product，商品改名后就会出现“看得到旧名、却按旧名搜不到”的矛盾。

**新知识：跨一对多关系筛选不能直接把 JOIN 结果拿去分页。** 多个 Item 命中会让同一 Order 出现多行，并可能同时破坏总数、页数和明细计数。先用 Item 子查询得到 Order ID，再在 Order 层计数、聚合和分页，可以保持列表原有语义。

**新知识：不要为了满足形式上的“有索引”而建立无效索引。** `%keyword%` 前导通配符不能利用普通 B-Tree；MySQL 中文 FULLTEXT 与 SQLite FTS 也不是同一套可移植设计。本阶段保留 ADMIN-only、严格长度和数据库分页，未来用生产 MySQL `EXPLAIN` 与真实关键词分布决定专用搜索方案。

**新知识：API 的排他时间上界和用户理解的“包含结束日”不同。** 界面连续输入 `20260831`，掩码组件显示为 `2026-08-31`；它作为结束日时，客户端发送 `created_to=2026-09-01T00:00:00.000Z`，从而遵守后端 `< created_to` 契约。

**新知识：离散按钮与文字输入可以采用不同提交时机。** 2026-08-29 起，状态按钮切换后立即与上一次已提交的商品名称、订单号、用户 ID 和日期组合查询；文字输入仍只在点击“查询”并通过校验后更新不可变筛选快照。按钮处理器必须基于已提交 filters 合并状态，不能直接解析包含未提交文字的 draft。后续页继续携带同一组条件，sequence 继续隔离旧请求迟到结果。

**新知识：待提交状态要比较“规范化后的用户输入”。** 商品名称先 trim、订单号先转大写，再与上次成功提交的输入快照比较。不同时显示“输入条件尚未应用”；校验失败不更新快照，因此提示不会误报为已生效。

**新知识：可以把“连续输入”与“固定日期格式”分离。** 日期组件只使用一个真实的数字 `Input`，内部值始终是最多 8 位的 `YYYYMMDD`；覆盖层把年、月、日与两个固定横杠显示为 `YYYY-MM-DD`。这样不需要用户手动输入横杠，也不需要在三个输入框之间切换焦点。

测试覆盖非法订单号、非正整数用户 ID、不足 8 位/无效/闰年日期、倒置范围、结束日转换、固定横杠显示、待提交提示、全筛选第一页/下一页保持和首屏错误。

### 7.4.3 权限边界与分包

- 首页只为 `admin/super_admin` 展示“管理订单”；
- 列表和详情在认证且角色为 ADMIN+ 后才挂载请求 Hook；
- 普通用户即使手工进入管理路由，也只看到无权限状态且不发 ADMIN API；
- 服务端仍以 ADMIN+ dependency 返回 403，前端隐藏入口和角色守卫只是体验边界；
- 登录 redirect 只增加固定 `/admin/pages/orders/index`，动态详情 URL 不进入白名单。

**新知识：前端授权判断的价值是避免无意义请求，不是授予权限。** 缓存中的角色可能过期或被篡改，真正的授权只能由 FastAPI Bearer + ADMIN+ dependency 决定。

**新知识：小程序分包是交付边界，不是安全边界。** 分包减少主包页面负担并按需加载，但不能隐藏代码或替代后端授权。

测试覆盖普通用户列表/详情零 ADMIN Hook、Guest 固定登录回跳、ADMIN 首页入口和管理详情导航。

### 7.4.4 Paid/Completed 状态收敛

详情 Hook 只从当前服务端状态派生唯一动作：Pending 为 `mark_paid`，Paid 为 `complete`，Cancelled/Completed 无动作。命令状态使用 `idle/submitting/failed/unknown/succeeded`，进行中的重复点击共享一个 Promise。

**新知识：不要给状态机做“通用下拉框”。** 当前契约只有两条 ADMIN 边：Pending → Paid 和 Paid → Completed。直接暴露任意目标状态会把非法迁移和未来业务规则泄漏到客户端。

**新知识：PATCH 超时也可能已经提交。** network/timeout/cancel/contract/5xx 进入 unknown、隐藏立即重试按钮并要求重新加载核对；明确的 40921 则自动 GET 详情，采用服务端最新状态。

**新知识：状态命令成功不等于后续读取也成功。** PATCH 返回目标状态后先更新已确认字段，再 GET 完整详情；GET 失败只显示刷新警告，不能把已成功的状态变更改写成失败。

测试覆盖 Pending/Paid 命令选择、Cancelled/Completed 无按钮、重复点击单 PATCH、成功后 GET、刷新失败保持成功、timeout unknown 不重放和 40921 后重读。

### 7.4.5 真实客户端纵向测试

纵向测试保留真实 `OrderApi → ApiClient`，只替换 transport 和 AuthSession，固定以下序列：

```text
管理列表 → Pending 详情 → empty-body paid → Paid 详情
         → empty-body complete → Completed 详情
```

每一步都断言 Bearer、HTTP method、URL、Query 和无 body 约束，防止页面单测全部通过但真实请求组合错误。

## 3. 自动化与构建结果

```text
miniapp 完整 Jest            31 suites / 213 tests PASS
TypeScript strict            PASS
ESLint（全 src）             PASS
Stylelint（全 CSS/SCSS）     PASS
OpenAPI generated drift      PASS
Order API 后端回归           107 tests PASS
后端完整 SQLite              1445 passed / 9 MySQL-only skipped
weapp production build       PASS
alipay production build      PASS
tt production build          PASS
h5 production build          PASS
```

Taro Test Utils 仍输出 React 18 `ReactDOMTestUtils.act` 上游弃用告警。H5 build 成功，但 app entry 为 359 KiB、主 JS 为 276 KiB，超过 Webpack 244 KiB 建议线；同时保留 Taro/Webpack `[hash]` 弃用告警。没有新增 npm/Python 依赖，没有修改 FastAPI API、数据库 Schema、迁移或生成的 OpenAPI 类型。

## 4. 微信开发者工具 Functional 清单

2026-08-25 用户确认以下清单全部通过。第 10 项的断网 unknown 分支已人工触发；Slow 3G 未超过 timeout，严格 timeout 保留为非阻断自动化/补测项。第 11 项使用微信开发者工具与独立 Swagger 客户端制造真实旧状态竞争，确认 40921 后采用服务端最新状态。

1. `dev_user` 首页不显示管理入口，手工进入管理列表/详情也不发 ADMIN 请求；
2. `dev_admin` 登录后显示管理入口，登录回跳返回管理列表；
3. 全部状态、精确订单号、历史商品名称、用户 ID、开始/结束日期及组合筛选正确；商品改名后旧订单仍可按旧名找到，多 Item 命中只显示一单；
4. Empty/Error/重新加载/下一页恢复正确；
5. 管理详情只显示 `user_id/user_nickname` 和历史订单快照；
6. Pending 仅显示“标记为已支付”，确认后变为 Paid，快速连点只提交一次；
7. Paid 仅显示“完成订单”，确认后变为 Completed；
8. Cancelled/Completed 均无状态操作按钮；
9. Paid/Complete 前后 Kit 库存与 Inventory 流水不变化；
10. 弱网命令结果未知时不自动重发，可重新加载核对；**2026-08-25 已通过断网分支：显示“结果待确认”且未自动再次 PATCH。Slow 3G 约 310 ms 返回，未触发 timeout；严格 timeout 作为非阻断补测。**
11. 两端同时变更触发 40921 时，页面采用服务端最新状态；
12. 普通用户直接请求 ADMIN API 由后端返回 403，且不触发 Token refresh。

## 5. 下一步

Phase 7.4 已收口，Phase 7.1–7.4 的工程、自动化与微信开发者工具 Functional 均完成。下一步规划 Phase 8 的第一条最小管理能力；仍不在没有冻结需求时提前实现审计页、退款、任意状态修改或支付占位。
