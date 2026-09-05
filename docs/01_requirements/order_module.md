# 订单模块（Order Module）

> **Contract Version:** v1.3
>
> **Status:** Kit/Mixed Inventory + Wallet Settlement/Full Refund implemented in repository；M4 not applied to persistent databases
>
> **Last Updated:** 2026-09-05

---

## 1. 模块目标

Phase 4.2 建立可追溯的订单、商品与 Experience Option 快照、用户/管理员查询、权限隔离，以及明确的订单状态生命周期。本文是 Order 业务行为的权威来源；HTTP 形状见 [Order API](../03_api/order_api.md)，表结构见 [Database Design](../02_database/database_design.md)。

Phase 4.3.7–4.3.8 已在既有订单边界上接入 Kit/混合下单、创建时库存扣减及 Pending 取消幂等恢复。Wallet/Payment/Refund v1 进一步接入余额支付、人工付款结算事实、PAID/COMPLETED 全额退款和订单资金查询；真实微信 Provider 仍关闭，M4 尚未应用持久数据库。资金权威规则见 [Wallet Module](wallet_module.md)。

---

## 2. 已实现范围与未纳入能力

### 2.1 已实现范围

- 为已上架、未逻辑删除的 Experience、Kit 或两者混合创建订单；Experience 必须有当前有效 Option，Kit 必须省略 Option。
- 保存 Product 名称、Experience Option 配置（仅 Experience）和数据库价格快照。
- 创建事务先锁定并复验当前账号仍是 `role=user/status=normal` 的普通 USER，再创建 Pending Order；随后稳定锁定并扣减所有 Kit，写不可变 Order 来源库存流水。
- 用户分页查看自己的订单及详情。
- 管理员分页筛选全部订单及查看详情。
- 用户取消自己的 Pending 订单。
- Pending Kit/混合订单取消时，原子恢复全部 Kit 并写不可变 Order 来源流水。
- ADMIN+ 可将 Pending 订单登记为人工线下已支付；M4 接入后同事务创建 `method=manual` 的成功 Payment 与唯一 PaymentSettlement，不冒充微信支付。
- 普通 USER 使用钱包余额支付自己的 Pending 订单；余额、资金流水、Payment、Settlement、Order Paid 与 Audit 原子提交。
- ADMIN+ 为状态正常的普通 USER 按商品创建代客钱包订单；真实 Order/快照、Kit 扣减、钱包扣减、Payment/Settlement、直接 Paid 和双审计原子提交。
- 人工确认 Paid 同时创建 `method=manual` 的成功 Payment 和唯一 Settlement，不再产生无来源 Paid 状态。
- ADMIN+ 完成 Paid 订单。
- 用户/ADMIN+ 查看订单聚合后的 Payment/Refund 事实。
- ADMIN+ 对普通 USER 的 PAID/COMPLETED 已结算订单执行一次全额退款；PAID Kit 恢复库存，COMPLETED 不恢复。
- 创建与每次状态变迁的顺序审计，以及管理员分页查询订单审计历史。

### 2.2 明确不在本阶段

- Wallet/Payment/Refund 新增资金路径的钱包专项并发、真实 1205/1213 与 EXPLAIN 扩展门槛；旧 Inventory Phase 4.3.11 门槛已通过，但不能替代该新增验证。
- 真实微信下单、支付通知、查单、关单、退款和对账；当前微信路径稳定 503 且零写入。
- 超时自动取消、已支付订单取消、部分退款和用户自助退款。
- 订单删除、订单修改、后台任意状态设置。
- 订单统计、报表、销量聚合、发货和物流。

任何 Kit 不可售或库存不足时整个请求失败，不允许部分创建或部分扣减。

---

## 3. 角色与能力

| 角色 | 能力 |
|------|------|
| 已认证普通用户 | 创建 Experience、Kit 或混合订单；分页查看自己的订单；查看详情/资金事实；取消自己的 Pending 订单；使用钱包余额支付自己的 Pending 订单 |
| ADMIN+ | 分页筛选全部订单；查看详情/资金事实；为正常普通 USER 创建代客钱包订单；仅为正常普通 USER 的 Pending 订单登记人工付款；完成订单；对普通 USER 已结算订单执行全额退款；查看订单审计历史 |

`ADMIN+` 表示 `admin` 和 `super_admin`。普通用户访问不存在或不属于自己的订单时，对外统一表现为订单不存在，避免泄露其他用户的资源是否存在。

---

## 4. 创建订单

### 4.1 输入规则

每个订单包含 1 至 10 个 Item；每个 Item 包含：

- `product_id`
- `experience_option_id`：Experience 必填正整数；Kit 可省略或显式为 `null`
- `quantity`，范围为 1 至 99

`remark` 可选，最大 500 字符。客户端不得提交商品名称、配置快照、单价、小计、总额、订单号、用户 ID 或状态。

同一请求中 `(product_id, experience_option_id)` 组合必须唯一。重复 Item 作为请求参数错误拒绝，不在 Service 中静默合并，以免客户端误提交被掩盖。

### 4.2 聚合有效性

Service 必须批量加载本次请求涉及的 Product、非空 ExperienceOption ID 和 Kit 扩展，禁止逐 Item 查询。每个 Item 必须满足：

1. Product 存在且 `is_deleted = false`；
2. Product `status = online`；
3. Experience 必须提交存在、未删除且归属正确的 Option；
4. Kit 必须省略 Option 且存在 ProductKit 扩展；
5. 事务内取得全部 Kit 行锁后再次确认 Kit Product 可售及余额充足。

Product、Option 或 Kit 扩展不可用时只返回稳定不可用语义，不向用户暴露内部生命周期细节；库存不足只返回 Product ID 与请求数量。

### 4.3 快照与金额

订单创建时，每个 OrderItem 保存：

- Product ID 与 `product_name` 快照；
- ExperienceOption ID 与三项 Option 快照；Kit 的这些字段全部为 `null`；
- `product_price` 快照；
- `quantity` 与 `subtotal`。

Experience 单价来自当前有效 Option，Kit 单价来自 ProductKit；都不能信任客户端。内部金额全部使用 `Decimal`：

```text
subtotal = product_price × quantity
total_amount = Σ subtotal
```

数据库使用 `DECIMAL(10,2)`；API 中 `product_price`、`subtotal` 和 `total_amount` 固定输出两位小数字符串，例如 `"99.00"`。Product 或 Option 后续改名、改配置、改价、下架或逻辑删除均不得改变历史订单快照。

### 4.4 原子性

以下步骤使用同一个数据库事务：

1. 按 User ID 锁定 User 行，锁后复验目标仍存在、`role=user` 且 `status=normal`；
2. 创建 Pending Order；
3. 按 Product ID 升序一次锁定全部 Kit，锁后重检并批量保存余额与扣减流水；
4. 批量创建 OrderItem；
5. 顺序写入 `CREATE_ORDER` 审计；
6. 使用同一事务连接重载响应所需订单聚合。

任一步失败必须整体回滚。创建前的批量候选快照读取不产生审计。纯 Experience 订单跳过库存步骤。

### 4.5 ADMIN+ 代客钱包订单

`POST /api/v1/admin/users/{user_id}/wallet-orders` 复用同一 `OrderCreate` 请求和 Product/Option/Kit 权威快照规则，但只允许 ADMIN/SUPER_ADMIN 为状态正常的普通 USER 操作，并要求 `Idempotency-Key`。disabled 目标因该用例属于消费而拒绝；deleted 目标禁止资金写入；管理员不能以自身或其他管理员为目标。

该用例在一个事务中锁定并重检目标 User，创建 Order 后锁 WalletAccount，再按 Product ID 升序锁定全部 Kit；随后写 Items、成功的 wallet Payment、钱包扣款流水、唯一 Settlement，将 Order 保存为 Paid，并顺序写 `CREATE_ORDER`、`PAY_ORDER`。因此响应中的新订单直接为 `paid`，不存在可由客户端观察或操作的 Pending 间隙。余额不足、库存不足或任一后置写入失败时，Order、Items、库存、钱包、Payment、Settlement 与两条审计全部回滚。

同 key 只有在操作者、目标 USER、Item 顺序和内容以及 remark 全部一致时重放，返回首次 Order/Payment 和首次扣款后的历史余额；不同意图返回资金幂等冲突。该路径由 `WALLET_ADMIN_WRITE_ENABLED` 控制，不能用通用余额调账 reason 替代。

---

## 5. 订单编号

订单号格式冻结为：

```text
OD + 26 位大写 Crockford Base32 ULID
```

示例：

```text
OD01K2M7Y0J7A3N5Q8T4V6W9X2BC
```

规则：

- 总长度 28，匹配 `^OD[0-9A-HJKMNP-TV-Z]{26}$`，数据库列使用 `VARCHAR(28)` 和 `UNIQUE(order_no)`；
- ULID 的时间部分使用 UTC 毫秒时间，随机部分使用密码学安全随机源；
- 编号可按时间近似排序，跨实例无需共享 Redis 或数据库序列表；
- 数据库唯一约束是最终并发兜底；唯一冲突时整个创建事务回滚并由创建用例重新生成编号，最多尝试 3 次，第三次仍冲突则保留根因进入服务器错误兜底；
- 业务排序仍使用 `created_at DESC, id DESC`，不得把订单号当作精确排序或分页游标；
- 不再承诺“YYYYMMDD + 当日六位严格序号”。若未来业务必须展示严格日序号，需要单独设计持久化序列表或 Redis 原子递增及失败策略。

---

## 6. 订单状态机

### 6.1 状态定义

| Enum | DB 值 | API value | label | 说明 |
|------|-------|-----------|-------|------|
| `PENDING` | 0 | `pending` | 待支付 | 已创建，等待付款确认 |
| `PAID` | 1 | `paid` | 已支付 | 已确认支付，等待服务完成 |
| `CANCELLED` | 2 | `cancelled` | 已取消 | Pending 订单由用户取消 |
| `COMPLETED` | 3 | `completed` | 已完成 | Paid 订单已完成 |

### 6.2 唯一允许的流转

```text
pending ──→ paid ──→ completed
   │
   └──→ cancelled
```

| 流转 | 触发方 | 用例 |
|------|--------|------|
| `pending → cancelled` | 订单所属用户 | 主动取消 |
| `pending → paid` | 订单所属 USER / ADMIN+ | USER 余额支付，或 ADMIN+ 登记人工付款 |
| `paid → completed` | ADMIN+ | 服务完成确认 |

ADMIN+ 代客钱包订单是在单一事务中创建新订单并直接提交为 `paid`，不是对一个已提交 Pending Order 开放第四条状态变迁，也不放宽既有状态 API。

除上述三条外全部拒绝。尤其不支持 `paid → cancelled`、重复取消、重复确认支付、重复完成或通用 `update_order_status(status)`。状态冲突必须返回当前状态、操作名和要求状态；失败不修改订单且不写审计。

状态冲突的稳定 `operation` 值分别为 `cancel`、`mark_paid` 和 `complete`。这些值属于业务错误契约，不使用审计 action，也不随 Python 方法重命名而变化。

每次状态变迁都必须在事务内锁定 Order 行（MySQL 使用 `SELECT ... FOR UPDATE`），锁定后重新读取并校验当前状态，再顺序执行状态更新、审计和响应重载。并发请求只能有一个成功；后获得锁的请求看到新状态后返回 `OrderStatusConflict`，不得产生第二条成功审计。SQLite 真实事务测试必须覆盖等价的串行结果，但不能把 SQLite 的锁行为当作 MySQL 实现依据。

`OrderStatus` 在业务层保持 `IntEnum`，数据库仍使用 `SMALLINT`。Model 的 Pending 默认值以及 Repository 的更新、筛选参数在进入 ORM/asyncmy 边界前必须显式转换为原生整数，避免 MySQL 将 Enum 对象编码成 `OrderStatus.*` 字符串；读取值再由 Service/Mapper 归一化为 `OrderStatus`。该规则不改变状态机、API 或物理 Schema。

人工确认支付是受控线下付款登记。Wallet/Payment v1 先只读定位 owner，再在事务内按 `User → Order` 锁序锁定复验；只有 `role=user/status=normal` 的 Pending 订单可以在相同事务中创建 `method=manual` 的成功 Payment 与唯一 PaymentSettlement。staff、disabled 或 deleted owner 均拒绝，Order/Payment/Settlement/Audit 零写入；`complete` 的既有 ADMIN+ 语义不因此改变。真实微信支付接入后仍不得由客户端回调直接写 Paid，必须由可信服务端通知/查单在统一状态规则下落结算。

M4 前已经由唯一 `MARK_ORDER_PAID` Audit 证明人工确认的 PAID/COMPLETED 历史订单，通过受控 `legacy_manual_settlement_backfill` 补齐同额 manual Payment/Settlement 后才能进入 v1 退款。命令默认 preview，apply 必须复用预览冻结的 `through_order_id`；缺失/重复 Audit 或现有资金事实矛盾均阻断并人工裁决，不得仅凭 OrderStatus 猜测支付渠道。

### 6.3 支付结算与退款状态

OrderStatus 继续只表达履约生命周期，Payment 与 Refund 使用独立字符串状态；全额退款不会把 Paid/Completed 改为 Cancelled，也不会回退 Completed。

- `Payment.method`：`wallet` / `manual` / `wechat`；当前只有 wallet 和 manual 可以成功结算。
- `Payment.status`：`pending` / `succeeded` / `failed` / `closed`。
- `PaymentSettlement.order_id UNIQUE`、`payment_id UNIQUE`，数据库保证一个订单最多一个成功结算。
- `Refund.status`：`pending` / `succeeded` / `failed`；Order 与 Settlement 均一对一限制，v1 只允许一次全额退款。
- Completed 订单退款窗口为完成后 30 天；PAID 订单不使用该窗口。
- `complete` 在 Order 行锁内检查已存在 Settlement 的 Refund；`pending` 或 `succeeded` Refund 阻止完成。

余额支付固定锁定 `User → Order → Payment/Settlement 事实 → WalletAccount`；扣款、不可变钱包流水、成功结算、Order Paid 与 `PAY_ORDER` Audit 原子提交。客户端不提交金额，资金金额必须等于服务端 `Order.total_amount`。

ADMIN+ 代客钱包订单锁定 `User → 新建 Order → WalletAccount → ProductKit(Product ID 升序)` 的有效序列；Payment/Settlement 是本事务中新建事实，无需先锁历史行。它一次提交创建、库存扣减、钱包扣减、结算、直接 Paid 和双审计，不允许拆成“先建 Pending、后另调账”的两个业务动作。

退款固定锁定 `User → Order → PaymentSettlement → Payment → Refund → WalletAccount → ProductKit(Product ID 升序)` 的有效子序列。钱包退款入账、Refund succeeded、PAID Kit 库存恢复流水与 `REFUND_ORDER` Audit 原子提交；COMPLETED 退款不恢复库存。微信退款当前在进入写事务前返回 503。

---

## 7. 查询、权限与字段隔离

### 7.1 用户端

- 列表固定按当前用户过滤，可选按状态过滤，稳定排序为 `created_at DESC, id DESC`。
- 详情只允许订单所属用户访问。
- 用户端列表与详情不返回 `user_id`、昵称、用户名、手机号或其他内部用户信息。
- 列表不返回 `items` 和 `remark`；仅返回 `item_count`。`item_count` 是 OrderItem 明细行数，不是各行 `quantity` 之和。详情返回 `items` 和 `remark`，但不重复返回列表派生字段 `item_count`。

### 7.2 管理端

- 支持按状态、精确订单号、订单商品名称、用户 ID、创建时间范围筛选并分页。
- 商品名称筛选使用 `order_items.product_name` 的下单时快照进行包含匹配，不关联当前 Product 名称；Product 后续改名、下架或逻辑删除都不得改变历史订单的检索结果。
- 同一订单有多条 Item 命中商品名称时，列表仍只返回一条订单，`total`、`pages` 和 `item_count` 均按原订单语义计算；商品名称可以与其他管理端筛选条件组合使用。
- 时间范围采用 UTC ISO 8601；`created_from` 包含边界，`created_to` 不包含边界。
- 列表和详情可返回 `user_id` 与 `user_nickname`，不得返回用户名、手机号、密码、Token 等非必要字段；详情不返回列表派生字段 `item_count`。
- 无筛选时同样按 `created_at DESC, id DESC` 稳定排序。

所有列表必须分页，不允许全表加载；详情一次预加载 Items，禁止 N+1 查询。

---

## 8. 审计契约

订单审计使用共享 `AuditLogService`，固定 `target_type = "order"`、`target_id = Order.id`，与对应写操作共享事务连接。

| action | 操作者 | 说明 |
|--------|--------|------|
| `CREATE_ORDER` | 自助下单 USER / 代客下单 ADMIN+ | Order、Items 与审计同事务 |
| `CANCEL_ORDER` | 订单所属用户 | `pending → cancelled` |
| `MARK_ORDER_PAID` | ADMIN+ | `pending → paid` |
| `COMPLETE_ORDER` | ADMIN+ | `paid → completed` |
| `PAY_ORDER` | 自助支付 USER / 代客下单 ADMIN+ | 钱包 Payment、流水、Settlement 与 Paid 事实同事务 |
| `REFUND_ORDER` | ADMIN+ | 全额退款、资金/库存变化与 Refund 同事务 |

ADMIN+ 代客钱包订单由管理员作为操作者，按顺序同时写 `CREATE_ORDER` 与 `PAY_ORDER`；两条审计的 `target_type`、`target_id` 均指向同一个新 Order。`CREATE_ORDER` 描述额外记录 `assisted_for_user_id`，不得包含客户联系方式或钱包余额。

`description` 使用不超过 256 字符的紧凑 JSON，仅保存定位所需的非敏感摘要：创建记录 `item_count` 与两位小数总额；状态变迁记录 `before_status` 与 `after_status`。不得写入订单备注或用户联系方式。审计失败时业务写入整体回滚。

订单审计历史仅通过 ADMIN+ 独立分页端点查询，不嵌入订单详情。排序为 `created_at DESC, id DESC`。

---

## 9. 数据生命周期

- Phase 4.2 不提供订单或订单项的物理删除、逻辑删除接口。
- Order → User、OrderItem → Order/Product/ExperienceOption 的历史外键采用 `ON DELETE RESTRICT`。
- Product 与 ExperienceOption 的正常删除仍为逻辑删除；历史订单依靠快照展示，同时保留原始 ID 以便追溯。
- Payment、Settlement、Refund、钱包和库存流水均保留历史外键并使用 `ON DELETE RESTRICT`；退款不删除或重写原订单/支付事实。
- 超时取消、统计、部分退款和用户自助退款不得通过隐藏任务或未文档化入口提前实现。

---

## 10. 错误优先级

- 用户按 ID 查询/取消：先通过 `id + current_user_id` 获取可见订单；不存在或属于他人统一为 `OrderNotFound`。
- 管理员状态变迁：先判断订单存在，再检查当前状态。
- 创建订单：先完成请求形状校验，再批量解析 Product/Option/Kit；按请求顺序检查 Product 可售性、类型与 Option 形状、Experience Option 和 Kit 扩展，随后计算候选金额。写事务中取得全部 Kit 锁后重检可售性与库存，并按请求顺序返回首个稳定错误。
- 同一请求包含多个无效 Item 时，不保证向客户端枚举全部业务问题；Service 按请求 Item 顺序返回首个稳定业务错误，数据库写入尚未开始。

具体错误码、HTTP 状态和响应数据见 [Order API §3](../03_api/order_api.md#3-错误契约)。HTTP 状态由命名异常类型决定，禁止根据业务 code 数字段推断。

---

## 11. 后续阶段

| 阶段 | 内容 |
|------|------|
| Phase 4.3 Inventory | 4.3.1–4.3.12 创建扣减、Pending 取消恢复、查询/Mapper、管理 API、真实 MySQL 门槛与 Final Review 均已完成 |
| Wallet/Payment/Refund v1 | 余额支付、ADMIN+ 代客钱包订单、人工结算事实、订单资金查询、一次全额退款已在仓库实现；M4 未应用持久数据库 |
| 后续 Payment | 真实微信下单、签名/验签、通知幂等、查单、关单、退款和对账 |
| 后续 Order | 超时取消、部分退款、用户自助退款、取消原因、统计、报表与订单删除策略 |

真实微信和后续 Order 扩展不属于当前 Wallet/Payment/Refund v1 冻结范围。

---

## 12. Phase 4.3 Inventory 联动契约（创建扣减与取消恢复已实现）

Phase 4.3.1 已冻结 Order v1.1 的 Inventory 联动方向，权威细节见 [Inventory Module](inventory_module.md)：

- 原路径 `POST /api/v1/orders` 将同时接受纯 Experience、纯 Kit 和混合订单；Kit Item 可省略 `experience_option_id` 或显式提交 `null`，其 Option ID 与三项 Option 快照为 `null`。
- 创建事务先锁定 User 并复验仍为 NORMAL 普通 USER，再写 Pending Order 取得稳定 ID；随后按 Product ID 升序锁定全部 ProductKit，并在同一事务内扣减余额、写 Inventory 流水、批量创建 Items、写 `CREATE_ORDER` 审计和重载响应；任一步失败时 Order 也回滚。
- 任一 Kit 库存不足时整单回滚；用户错误只返回 `product_id` 与 `requested_quantity`，不披露精确可用量。
- Pending 取消在现有 Order 行锁和状态重检基础上，原子、幂等恢复全部 Kit Item；既有订单的 `pending -> paid` 与 `paid -> completed` 均不改变库存，`paid -> cancelled` 仍禁止。ADMIN+ 代客钱包订单在创建事务中扣减 Kit 并直接提交为 Paid；独立全额退款中，PAID Kit 按快照恢复库存并写 `order_refund_restore`，COMPLETED 不恢复。
- 自动扣减/恢复使用数据库唯一幂等键；重复取消同时由 Order 状态机和 Inventory 唯一约束保护。
- Order Service 拥有创建/取消外层事务并协调 Inventory Repository，不调用 Inventory Service。

Phase 4.3.7 已实现请求形状、创建扣减、流水、快照、响应与既有 POST 路由；Phase 4.3.8 已实现 owner cancel 的 Order 行锁、Item 最小快照、稳定 Kit 集合锁、restore 幂等检查、余额/恢复流水、Cancelled/Audit/重载原子事务及 MySQL 1205/1213 完整用例重试。`40922` 阶段门禁已移除，既有订单的支付与完成继续不改变库存；Wallet/Payment/Refund v1 新增代客 Paid 创建扣减和 PAID 全额退款恢复两条独立路径。
