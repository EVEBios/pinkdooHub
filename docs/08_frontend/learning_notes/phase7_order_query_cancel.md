# Phase 7.3 学习笔记：我的订单、详情与 Pending 取消

> 状态：**工程实现与微信开发者工具 Functional 全部通过。** 2026-08-24 已完成 Order 查询/详情/cancel Endpoint、运行时契约校验、登录守卫、列表筛选/分页、详情快照、Pending 取消状态收敛和从 7.2 unknown 进入服务端核对的入口。完整前端 25 套件 / 172 项、后端 Order HTTP 53 项、后端全量 1445 项（另 9 项 MySQL-only 跳过）、TypeScript、ESLint、Stylelint、OpenAPI 漂移和四端 production build 均通过。2026-08-24 用户确认清单第 1–9 项通过；2026-08-25 又使用独立客户端抢先把 Pending 变为 Paid，确认旧用户详情 cancel 收到 40921 后重新 GET 并收敛到 Paid，第 10 项双端竞态通过。本结论不代表真机或 H5 Functional 已通过。

## 1. 本阶段的最小纵向切片

```text
7.2 创建成功 / 结果未知 / 首页“我的订单”
                  │
                  ▼
GET /api/v1/orders?page=1&page_size=20&status=...
                  │
                  ▼
        当前用户订单列表与筛选
                  │
                  ▼
       GET /api/v1/orders/{id}
                  │
                  ▼
         服务端历史快照详情
                  │ Pending only
                  ▼
 PATCH /api/v1/orders/{id}/cancel（无 body）
                  │
                  ▼
       GET 详情重新读取权威结果
```

本阶段没有实现支付、微信支付、ADMIN 人工 Paid/Completed、订单删除、客户端创建幂等键或前端库存恢复。取消时的状态校验、Kit 库存恢复、流水和审计仍完全由现有 FastAPI Order/Inventory 事务负责。

## 2. 实施步骤与每步测试

### 7.3.1 扩展 Order Endpoint

`OrderApi` 新增：

- `listOrders()`：认证 GET，Query 只投影 `page/page_size/status`；
- `getOrderDetail()`：只接受正整数 Order ID；
- `cancelOrder()`：认证 PATCH，不传 `body`，且成功结果必须是 `cancelled`；
- 列表页、列表项和状态结果都从 `unknown` 开始逐字段校验，并做响应白名单投影。

**新知识：OpenAPI 生成类型只证明编译期形状，远端 JSON 在运行时仍是不可信输入。** 列表 Guard 同时核对页码、页大小、总数、页数公式、金额、UTC 时间、状态 value/label 和 item_count；不能因为 TypeScript 已有 `OrderListPage` 就直接断言网络响应。

测试：认证方法/路径/Query、null status 省略、未知字段隔离、坏分页/金额/状态拒绝、非法 ID 不发请求、40411/40921 结构化错误，以及 cancel 的 `body === undefined`。

### 7.3.2 我的订单列表

列表固定每页 20 条，支持全部、Pending、Paid、Cancelled、Completed 筛选，呈现 Loading/Empty/Error/Content 四态和下一页错误恢复。

**新知识：服务端分页事实必须来自 `page/pages/total`，不能用本页数组长度猜测是否还有下一页。** `item_count` 是订单 Item 行数，不是所有 quantity 的总和。

**新知识：筛选切换会形成请求竞态。** Hook 使用递增 sequence 丢弃迟到旧响应，并用同步 ref 阻止“加载更多”快速连点发出重复页请求；换筛选时旧列表立即退出 Content，避免不同筛选结果混在一起。

测试：第一页/下一页、筛选重置、下一页失败后保留已有内容、重复加载保护和迟到响应隔离；页面测试覆盖 Guest 登录回跳、四态、状态筛选和详情导航。

### 7.3.3 owner-only 详情与快照

详情路由只接受正安全整数 ID。页面只渲染后端 `OrderDetailOut`：订单号、状态、金额、历史商品名、Option 配置、单价、小计、数量、备注和 UTC 时间。

**新知识：订单快照不是当前 Product。** 商品改名、Option 改价或下架以后，历史订单仍必须显示创建时快照；详情页不能回查当前 Product 来替换名称、价格或配置。

**新知识：owner-only 是服务端授权边界。** 前端路由校验只能改善错误体验，不能证明用户拥有订单。后端对不存在和他人订单统一返回 `40411`，前端统一显示“订单不存在或不可访问”，避免资源枚举。

测试：路由正反例、Experience 完整 Option 快照、Kit 全 null Option 快照、40411 安全提示，以及非 Pending 状态不显示取消入口。

### 7.3.4 Pending 取消与状态收敛

用户确认后才调用 cancel；只在服务端详情为 Pending 时显示入口。Hook 使用 `idle/submitting/failed/unknown/succeeded` 判别联合，同一进行中的取消复用同一个 Promise。

**新知识：命令的“失败”与“结果未知”必须分开。** 业务拒绝可以明确展示并允许按事实修正；network/timeout/cancel、5xx 或成功响应契约损坏无法证明服务端事务未提交，必须进入 unknown，隐藏立即重试入口并引导回订单列表核对。

**新知识：无请求体 PATCH 不是发送空对象。** cancel 请求不设置 body，不能发送 `{}`；后端已有测试会主动拒绝任意 body。

**新知识：命令成功后重新查询是一种权威收敛。** cancel 返回 `OrderStatusOut` 后先把已确认的 cancelled 状态反映到页面，再 GET 详情取得完整服务端快照。若重拉失败，仍保留“取消已成功”，只附加刷新警告，不能把已提交的服务端事务降级为失败。

**新知识：40921 可能是跨端竞态，而不只是用户操作错误。** 订单可能已在其他端支付或取消；收到状态冲突后前端再 GET 详情，以服务端当前状态隐藏不再合法的按钮。客户端不自行模拟库存恢复，库存余额和 restore 流水由后端事务保证。

测试：确认弹窗、Pending 成功取消、重复点击单 PATCH、cancel 后 GET、成功但重拉失败、超时 unknown 不重发、40921 后重拉 Paid、40411、四种终态按钮可见性，以及列表→详情→无 body cancel→详情的真实 ApiClient vertical slice。

### 7.3.5 恢复入口与导航闭环

- 7.2 创建成功页增加“查看我的订单”；
- 7.2 unknown 提示直接进入我的订单核对，不提供重新 POST；
- 首页已登录区域增加“我的订单”；
- 登录 redirect 白名单增加固定订单列表地址；订单详情 Guest 先回订单列表登录，不允许任意动态详情 URL 穿过 redirect。

**新知识：登录回跳地址也是输入边界。** 只允许应用明确注册的固定页面；外部 URL、任意内部地址和畸形编码仍回退首页，不能为了“体验方便”开放通用 redirect。

## 3. 自动化与构建结果

```text
Phase 7.3 定向 Jest          8 suites / 61 tests PASS
miniapp 完整 Jest            25 suites / 172 tests PASS
TypeScript strict            PASS
ESLint（全 src）             PASS
Stylelint（全 CSS/SCSS）     PASS
OpenAPI generated drift      PASS
Order HTTP 契约              53 tests PASS
后端完整 SQLite              1445 passed / 9 MySQL-only skipped
weapp production build       PASS
alipay production build      PASS
tt production build          PASS
h5 production build          PASS
```

Taro Test Utils 仍输出 React 18 `ReactDOMTestUtils.act` 上游弃用告警。H5 build 成功，但 app entry 为 350 KiB、主 JS 为 266 KiB，超过 Webpack 244 KiB 建议线；同时保留 Taro/Webpack `[hash]` 弃用告警。两者均未被误报为错误，公开发布前仍需处理或接受明确的性能/升级决策。

首次 Node 包加载受 Windows 文件扫描影响出现长时间 I/O 等待；所有通过结论均来自工具真实退出码。ESLint、Stylelint、OpenAPI 和构建最终使用 Codex 工作区 Node 运行同一项目依赖，没有修改 `package.json` 或 lockfile。

## 4. 微信开发者工具 Functional 结果

2026-08-24 用户确认以下清单第 1–9 项均通过；2026-08-25 用户确认第 10 项双端 40921 竞态也通过：竞争客户端先把 Pending 订单变为 Paid，旧用户详情再取消时收到 40921，随后重新 GET 并采用服务端 Paid 状态，没有重复发送 cancel PATCH。

1. Guest 从“我的订单”登录并返回列表；
2. 全部与四种状态筛选，Empty/Error/下一页恢复；
3. 7.2 创建成功和 unknown 均能进入我的订单；
4. 详情只显示订单历史快照，Experience 有配置、Kit 无配置；
5. 他人/不存在订单统一显示不可访问；
6. Pending 取消确认，快速连点只提交一次；
7. 取消后状态变为 Cancelled，Kit 库存由后端恢复一次；
8. Paid/Cancelled/Completed 均无取消按钮；
9. 弱网取消进入 unknown 后不自动重发，可回列表核对；
10. 两端状态竞态触发 40921 时，页面重拉并采用服务端状态。

## 5. 下一步

Phase 7.3 用户侧 Order 查询、详情、取消与跨端冲突收敛已经收口。后续 ADMIN 订单列表/详情及 Pending → Paid → Completed 人工状态操作已由 Phase 7.4 完成并通过微信开发者工具 Functional；下一阶段转入 Phase 8 管理能力规划。
