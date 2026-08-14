# 库存模块（Inventory Module）

> **Contract Version:** v0.6
>
> **Status:** Implemented and Final-Review Complete（Phase 4.3.12；v0.6.0 未发布候选；未应用持久环境）
>
> **Last Updated:** 2026-08-14

---

## 1. 模块目标与当前边界

Inventory 负责 Kit 当前可售库存、不可变库存流水、管理员调整，以及 Order 创建/取消引发的自动扣减与恢复。本文是库存业务行为的权威来源；HTTP 草案见 [Inventory API](../03_api/inventory_api.md)。

Phase 4.3.1–4.3.12 已完成契约、领域/Schema、Model/数据库设计、离线 MySQL 迁移、Repository、管理员调整、Kit/混合订单创建扣减、Pending 取消恢复、查询 Service/Mapper、三个 ADMIN+ Inventory API、真实 MySQL/HTTP 发布门槛和最终 Review。Order Service 现在拥有创建和取消的库存外层事务：创建写 `order_deduction`，取消按 OrderItem 快照恢复并写 `order_cancellation_restore`；余额、流水、Order、Audit 与响应重载原子提交。Inventory Router 已接入调整、指定 Kit 流水和全局流水，统一使用严格 Schema、Mapper、成功/错误信封和 JWT ADMIN+ 权限。旧直接设置库存端点与 Kit 创建请求中的 `stock` 已按冻结破坏性契约移除，新 Kit 固定从 0 开始并经 adjustment 入库。完整迁移链、正/零库存回填、Repository smoke、真实竞争与查询计划已在隔离 MySQL 8.0.46 实例通过；最终 Review 同步收紧 Product Kit 详情响应的库存上限并清理数据库文档的旧规划描述。代码已收口为 v0.6.0 未发布候选，但未应用任何持久、共享或生产数据库。

## 2. 现状审计

| 边界 | 当前已实现 | Phase 4.3 冻结目标 |
|------|------------|--------------------|
| 权威余额 | `product_kits.stock` | 继续作为唯一当前可售余额 |
| 管理维护 | ADMIN+ adjustment API 已接入；允许任意未删除 Kit，旧直接设置端点已移除；完整 HTTP/MySQL 门槛已通过 | 保持当前已实现语义 |
| Order Item | 已支持 Experience 必填 Option、Kit 省略/null Option，以及混合请求 | 保持当前已实现语义 |
| 创建订单 | 已在 Pending 创建事务中原子扣减全部 Kit Item，最后一件与交叉多 Kit 真实竞争通过 | 保持当前已实现语义 |
| 取消订单 | Pending 取消已原子、幂等恢复全部 Kit Item，同单真实取消竞争通过 | 保持当前已实现语义 |
| 支付/完成 | 只修改 Order + Audit | 保持现状，不再改变库存 |
| 流水/幂等 | 管理调整、Order 扣减/恢复均写不可变流水并由数据库唯一键兜底 | 保持当前已实现语义 |
| 并发 | 管理调整、创建和取消均已使用行锁、锁后校验和有限重试；真实 MySQL 竞争、1205 重试和 EXPLAIN 已通过 | 稳定顺序锁、锁后校验、同事务余额/流水/Order/Audit |

现有 `OrderItem` 已把 Experience Option 外键及三项 Option 快照声明为 nullable，因此持久化形状可以承载 Kit；当前限制来自 Schema 与 Service，而不是必须重建 OrderItem 表。

## 3. 权威余额与流水

采用 **余额表 + 流水表（balance + ledger）**：

```text
ProductKit.stock = 唯一的当前可售库存
InventoryTransaction = 每一次已提交库存变化的不可变历史
```

规则：

- 商品详情直接读取 `ProductKit.stock`，不得通过实时汇总流水计算当前库存。
- 余额变化和对应流水必须使用同一数据库连接、同一事务提交。
- 除 Kit 创建的零初始值和 Inventory 迁移基线外，余额不得脱离流水单独改变。
- 已提交流水不得修改或删除；纠错通过新的反向调整流水完成。
- 所有库存必须满足 `0 <= stock <= 999999`。
- 流水必须满足 `after_quantity = before_quantity + change_quantity`；常规变化的 `change_quantity != 0`。

### 3.1 期初余额

Inventory 增量迁移为启用时 `stock > 0` 的每个 Kit 生成一条 `opening_balance` 流水：`before=0`、`change=stock`、`after=stock`，并使用稳定迁移幂等键。零库存以余额 `0` 作为隐式基线，不创建零变化流水。

Phase 4.3.4 已在 `2_20260814104655_add_inventory_transactions.py` 中实现该数据迁移：先创建流水表，再按 `product_kits.product_id` 升序执行单条 `INSERT ... SELECT`。时间使用 `UTC_TIMESTAMP(6)`，原因固定为 `Inventory opening balance migration`，操作人和 source ID 均为空。迁移不修改 `product_kits.stock`，也不使用 `INSERT IGNORE` 或 `ON DUPLICATE KEY UPDATE` 掩盖冲突。

MySQL DDL 会隐式提交，因此“建表 + 期初数据”不能被宣称为一个可回滚事务。执行前必须暂停 Product 旧库存写入，确认所有现存 stock 位于 `0..999999`，完成备份并在临时 MySQL 8+ 演练；如果建表成功但期初插入失败，保留现场并人工制定前滚恢复，不能直接重跑或删除表。显式 downgrade 会删除全部 Inventory 流水且不会反向修改当前余额，只能在停机、备份和单独授权后执行。

Inventory 接入后，新建 Kit 的初始 `stock` 固定为 `0`；首次入库通过管理员调整完成。Product 创建请求中的 `stock` 字段已在 v0.6.0 候选中移除。这避免绕过流水创建非零余额。

## 4. 库存发生时点与 Order 矩阵

创建 Pending 订单时把 Kit 数量视为实际扣减，不再建立独立“预占库存”字段。未来超时取消复用相同恢复用例；未来支付接入只推进订单状态。

| Order 操作 | Order 状态变化 | Inventory 行为 |
|------------|----------------|----------------|
| 创建纯 Experience 订单 | 新建 `pending` | 不操作库存 |
| 创建纯 Kit 订单 | 新建 `pending` | 扣减全部 Kit Item |
| 创建混合订单 | 新建 `pending` | 只扣减 Kit Item |
| 用户取消 Pending | `pending -> cancelled` | 恢复全部 Kit Item |
| ADMIN+ 确认支付 | `pending -> paid` | 不改变库存 |
| ADMIN+ 完成订单 | `paid -> completed` | 不改变库存 |
| 已支付订单取消 | 不允许 | 不恢复库存 |
| 重复取消 | 状态冲突 | 不产生第二次恢复或流水 |

纯 Experience、纯 Kit、Experience + Kit 混合订单均允许。任一 Kit 不可售或库存不足时整单失败：所有 Kit 扣减、Order、OrderItem、InventoryTransaction 与 `CREATE_ORDER` 审计必须全部回滚。

## 5. Item 与快照规则

Phase 4.3 的创建 Item 形状：

```json
{"product_id": 1, "experience_option_id": 2, "quantity": 1}
```

```json
{"product_id": 5, "quantity": 2}
```

- Experience 必须提交有效且属于该 Product 的 `experience_option_id`。
- Kit 的 `experience_option_id` 可以省略或显式为 `null`，两者都规范化为无 Option；提交正整数 Option ID 则拒绝。
- 同一请求按 `(product_id, experience_option_id)` 判重；因此同一 Kit Product 最多出现一行。
- Kit 的名称、价格、数量和小计使用 OrderItem 现有公共快照字段；Option ID 与三项 Option 快照为 `null`。
- 客户端不得提交价格、名称、before/after、库存余额或流水类型。

## 6. 管理员库存调整

ADMIN+（`admin`、`super_admin`）可以增加或减少 Draft、Online、Offline 的未删除 Kit 库存。Online Kit 允许补货和盘点；Product 内容、图片和价格的 Online 修改限制不变。

请求语义为：

```json
{"change": 20, "reason": "采购入库"}
```

规则：

- `change` 是 strict integer，拒绝 boolean、float 和数字字符串。
- `-999999 <= change <= 999999` 且不得为 `0`。
- 服务端计算 `after = before + change`；结果必须位于 `0..999999`。
- `reason` 必填，去除首尾空白后长度为 `1..256`。
- Product ID 来自 path，操作者来自认证上下文，时间来自服务器。
- 客户端不能提交最终余额、before/after、operator、transaction type、source 或内部幂等键。
- 调整、Inventory 流水与共享 AuditLog 必须原子提交；失败全部回滚。

旧端点 `PATCH /api/v1/admin/products/kit/{product_id}/stock` 已在 Phase 4.3.10 直接移除，不做兼容包装；Kit 创建请求也不再接受 `stock`。这是 v0.6.0 的明确破坏性变化：新 Kit 固定以 0 建立隐式基线，首次入库必须调用 adjustment。

## 7. 流水类型、来源与操作人

第一版冻结四个稳定英文字符串 value：

| transaction type | change 符号 | source | operator |
|------------------|-------------|--------|----------|
| `opening_balance` | 正数 | `migration` | `null` |
| `admin_adjustment` | 正或负 | `admin` | 当前管理员 |
| `order_deduction` | 负数 | `order` | 下单用户 |
| `order_cancellation_restore` | 正数 | `order` | 取消用户（订单所属用户） |

系统自动订单事件仍记录触发该事件的已认证用户，而不是伪造管理员。未来无用户参与的定时取消可以令 operator 为空，但必须保留 Order source 与幂等键。

管理员原因使用调用方提交并规范化后的文本；订单与迁移事件使用服务端稳定原因，不接受客户端伪造。流水 API 不输出内部幂等键，也不输出操作者手机号、用户名、Token 或订单备注。

Phase 4.3.3 持久化字段冻结为：`product_id` 关联 `products.id`、可空 `operator_id` 关联 `users.id`，两者均 `ON DELETE RESTRICT`；`source_id` 是可空通用来源标识，不建立多态外键。`source_type` 与 `reason` 均为 NOT NULL，因为第一版四种流水都有明确来源和稳定原因。完整内部 `idempotency_key` 使用 `VARCHAR(256)` 容纳服务端命名空间，客户端提交部分仍限 128 字符。

流水继承项目统一 `BaseModel`，因此物理表包含 `updated_at` 技术字段；业务层不提供流水更新/删除入口，API 不输出 `updated_at`。当前不下沉跨字段数据库 `CHECK`：数据库保证 FK、NOT NULL、容量和幂等唯一性，Model 保证单字段数量边界与非零变化量，Service 保证算术等式、类型/source 组合和余额/流水同事务。

## 8. 幂等契约

自动事件的幂等键由服务端生成并由数据库 UNIQUE 约束：

```text
inventory:order:{order_id}:deduct:product:{product_id}
inventory:order:{order_id}:restore:product:{product_id}
inventory:opening:product:{product_id}
```

管理员调整必须携带 `Idempotency-Key` 请求头，值为去除首尾空白后的 1 至 128 个可打印 ASCII 字符；不得写入响应或日志。其持久化身份包含操作类别与该键，避免与自动事件命名空间冲突。

- 相同管理员、相同 key、相同 Product/change/reason 的重试返回首次已提交结果，不再次改变余额或写流水/Audit。
- 相同 key 对应不同操作者或不同规范化 payload 时返回 `InventoryTransactionConflict`。
- 事务回滚不会消耗 key；调用方可以用同一 key 安全重试。
- Order 状态机与 Inventory 唯一约束共同防止重复恢复，形成纵深防御。

## 9. 并发、锁与事务所有权

采用“稳定顺序行锁 + 锁后校验 + 原子更新 + 同事务流水”：

1. 写用例开启事务；
2. 将所有 Kit Product ID 去重并按升序排序；
3. 依次 `SELECT ... FOR UPDATE` 锁定对应 ProductKit；
4. 锁后重新校验可售性、余额和幂等记录；
5. 更新余额并写流水；
6. 在同一事务中完成 Order/Items/Audit 或管理员 Audit；
7. 使用同一连接重载响应后提交。

Order 创建与取消 Service 拥有包含 Inventory 写入在内的外层事务；它们直接协调 Inventory Repository，不调用 Inventory Service。管理员调整事务由 Inventory Service 拥有。Repository 只执行锁、查询和持久化，不判断业务状态或抛业务异常。

### 9.1 Order 创建事务顺序

为使自动流水能引用数据库 `Order.id`，冻结顺序为：事务外批量读取并构造候选快照；事务内先创建 Pending Order 取得 ID，再按 Product ID 升序锁定全部 ProductKit、锁后重检并扣减、写以 Order ID 派生的扣减流水、批量写 OrderItem、写 `CREATE_ORDER` Audit、使用同一连接重载响应，最后提交。库存不足或后续任一步失败时，先创建的 Order 也随事务回滚。

订单号唯一冲突发生在任何库存锁/写之前；退出失败事务并确认属于订单号冲突后，才以新订单号和全新事务重试。这样既保留现有最多 3 次的订单号重试契约，也不会让一次编号冲突产生库存副作用。

### 9.2 Order 取消事务顺序

取消先锁定当前用户可见的 Order 并重检 Pending 状态，再加载 Items、按 Product ID 升序锁定全部 Kit、确认恢复幂等键尚未提交、增加余额并写恢复流水，然后更新 Order 为 Cancelled、写 `CANCEL_ORDER` Audit、重载响应并提交。发现自动恢复幂等键与 Pending 状态矛盾时按 `InventoryTransactionConflict` 失败，不通过跳过库存变化来掩盖数据不一致。

MySQL 错误 `1213`（deadlock）和 `1205`（lock wait timeout）只允许对整个、尚无外部副作用的用例做有限重试；最多 3 次（含首次），每次使用全新事务。其他数据库错误不重试。稳定锁顺序仍是主要预防措施，重试不是正确加锁的替代品。

### 9.3 Repository 实现边界

Phase 4.3.5 的 `InventoryRepository` 已提供：

- 单 ProductKit 的 `SELECT ... FOR UPDATE`；
- 多 Product ID 去重后，一次 `WHERE ... IN (...) ORDER BY product_id SELECT ... FOR UPDATE`；
- 调用方已计算最终余额的持久化，不在 Repository 判断库存是否充足；
- 管理调整单条流水写入，以及多 Kit 自动事件的一次 `bulk_create`；
- 使用调用方连接的幂等键读取和详情重载；
- Product/type/source/UTC 时间范围组合筛选与 `created_at DESC, id DESC` 分页；
- operator 关系预加载，以及一次批量 Order 查询补齐安全 `source_order_no`。

Repository 不开启事务、不拥有重试、不判断 Product 状态/可售性/余额边界、不解释幂等 payload，也不抛业务异常。多 Kit 锁使用单条排序 SQL，而不是循环逐条 `await`；自动流水使用批量 INSERT。SQLite 测试只能证明连接传播、回滚和查询形状，MySQL 的真实阻塞/死锁/超卖语义仍由 4.3.11 发布硬门槛验证。

### 9.4 管理员调整 Service 实现边界

Phase 4.3.6 的 `InventoryService.adjust_stock()` 已实现管理调整写用例：

- 构造 `inventory:admin:adjust:{client_key}` 内部身份；客户端 key 最长 128 字符，完整身份仍不超过数据库 256 字符容量；
- 在 Service 自有事务中先锁定 ProductKit，再验证 Product 存在、未删除、类型为 Kit 且扩展记录存在；
- 在锁内比较同一内部 key 的 Product/change/reason/operator，完全一致时返回首次已提交流水的原始 `after_quantity`，不把后来发生的库存变化误报为首次结果；
- 首次执行计算闭区间余额，原子保存余额、`admin_adjustment` 流水和 Product 目标的 `ADJUST_INVENTORY` Audit，并使用同一连接重载详情；
- 唯一键并发冲突退出失败事务后读取已提交记录：相同请求转为幂等重放，不同请求转为 `40933`，无对应记录则保留原始数据库异常；
- 仅对 MySQL 1205/1213 重试整个用例，每次进入全新事务，最多 3 次；日志不包含原因或幂等键；
- 返回不可变领域结果及 `is_replay`，供后续 Router 选择首次 HTTP 201 或重放 HTTP 200，Service 本身不依赖 HTTP。

该阶段没有注册组合根、Mapper 或路由，也没有修改旧库存端点及 Order 行为。SQLite 集成测试证明事务传播、回滚、幂等与边界；后续 Phase 4.3.11 已完成真实 MySQL 管理调整/下单竞争门槛。

### 9.5 Kit/混合订单扣减实现边界

Phase 4.3.7 已将 Order 创建切换到库存感知实现：

- `OrderItemCreate.experience_option_id` 对 Kit 可省略或为 `null`，对 Experience 仍由 Service 要求有效 Option；同一 Kit 的 `(product_id, null)` 重复组合在 Schema 层拒绝；
- 事务外分别批量加载 Product、非空 Option ID 和 Kit 扩展，构造数据库权威名称/配置/价格候选快照，不在 Item 循环中查询；
- 事务内先创建 Pending Order 取得 ID；订单号 UNIQUE 冲突因此发生在任何库存锁/写之前，归因后才使用新编号和全新事务重试；
- 一次按 Product ID 升序锁定全部 Kit 后，使用同一连接重读 Product 并按请求 Item 顺序检查可售性、Kit 扩展和库存，首个不足只返回 Product ID 与请求数量；
- 多 Kit 最终余额通过一次 `bulk_update` 保存，所有 `order_deduction` 流水通过一次 `bulk_create` 保存；每条流水使用 `inventory:order:{order_id}:deduct:product:{product_id}`、Order source、下单用户 operator 和稳定原因；
- Order、余额、流水、Items、`CREATE_ORDER` Audit 与详情重载共享事务，库存不足或任一后置失败时全部回滚；纯 Experience 订单不执行库存 Repository 调用；
- MySQL 1205/1213 只重试完整创建写事务，使用同一候选快照和订单号、每次新事务、最多 3 次；`IntegrityError` 先保留给既有订单号冲突归因。

Order Request/Response Schema、Mapper、组合根和既有 POST 路由已经同步支持 Kit null Option 快照；阶段门禁 `40922 KitOrderingRequiresInventory` 已移除。真实 MySQL 最后一件库存、交叉锁序及管理调整竞争已由 Phase 4.3.11 验证通过。

### 9.6 Pending 取消恢复实现边界

Phase 4.3.8 已将现有 owner cancel 用例切换为库存感知事务：

- 先用 `(order_id, user_id)` 锁定可见 Order 并重检 Pending；不存在与他人订单继续统一隐藏为 `OrderNotFound`，Paid/Cancelled/Completed 继续优先返回 `OrderStatusConflict`，不会触碰库存；
- 锁后通过 OrderRepository 只读取 `product_id`、`experience_option_id`、`quantity` 最小 Item 快照；Experience Item 被跳过，Kit 数量按 Product 聚合，然后用一次 Product ID 升序集合锁取得全部余额行；
- 恢复不重新要求 Product Online，也不使用当前目录价格；库存归还以不可变 OrderItem 数量快照为准。Kit 扩展缺失视为数据一致性冲突，不允许只取消 Order 而跳过库存；
- 一次批量查询确认全部 `inventory:order:{order_id}:restore:product:{product_id}` 尚未存在；Pending 与任一已提交 restore 身份矛盾时抛 `40933 InventoryTransactionConflict`，不静默当作成功；
- 多 Kit 最终余额通过一次 `bulk_update` 保存，恢复流水通过一次 `bulk_create` 保存；流水固定使用 `order_cancellation_restore`、Order source、取消用户 operator 与 `Order cancellation stock restore` 原因；
- 恢复后余额仍必须位于 `0..999999`，越界使用 `40932 InventoryBalanceExceeded`；余额、恢复流水、Cancelled 状态、`CANCEL_ORDER` Audit 与轻量响应重载共享一个事务，任一步失败全部回滚；
- 重复取消先在 Order 行锁后的状态重检处返回 `40921`，不会写第二组恢复流水。MySQL 1205/1213 仅重试完整取消用例，每次使用全新事务，最多 3 次；其他数据库错误不重试。

Order 状态机是正常重复请求的第一道保护，Inventory restore UNIQUE 是事务重放与未来自动取消的数据库兜底；两者共同构成纵深防御。真实 MySQL 同单取消竞争已由 Phase 4.3.11 验证只恢复一次。

### 9.7 查询 Service 与 Mapper 实现边界

Phase 4.3.9 已完成两类只读用例与 Inventory API 映射边界：

- `InventoryService.list_product_transactions()` 先读取包含逻辑删除记录的 Product，按 Product 不存在、已删除、类型不符、Kit 扩展缺失的稳定优先级校验，再把冻结筛选条件委托给 Repository；
- `InventoryService.list_transactions()` 把可选 Product ID 仅解释为全局流水筛选条件，不额外验证 Product 身份；未知 ID 返回元数据完整的空 `Page`；
- 两类用例均不创建事务、不加锁、不重复实现 Repository 的筛选、稳定排序或分页，并原样转发类型、source 和 UTC 包含下界/排除上界时间范围；
- `app/api/mappers/inventory.py` 同步构造流水、分页和调整响应的显式字段白名单，并立即通过严格 Out Schema 校验余额等式、类型/source/operator 组合及调整结果一致性；
- Mapper 只消费 Repository 已预加载的 operator 和已批量补齐的 `source_order_no`，执行期间零 SQL、零 ORM 修改；不输出内部幂等键、技术更新时间、用户名、手机号、密码、Token 或订单备注；
- 调整 Mapper 接受领域值与流水，不导入 Service DTO；`is_replay` 仍由后续 Router 用于选择 HTTP 201/200。

该阶段尚未注册 Inventory 组合根或管理路由，也未移除 Product 旧库存端点；这些边界现已由 Phase 4.3.10 完成。真实 MySQL 查询计划和完整 HTTP/并发矩阵仍属于 4.3.11 发布门槛。

### 9.8 Inventory API 实现边界

Phase 4.3.10 已将现有领域能力接入 HTTP：

- `get_inventory_service()` 只在组合根组装 InventoryRepository、ProductRepository 与共享 `AuditLogService(AuditLogRepository)`；Router 不导入业务 Repository 或持久化 Model；
- `POST .../inventory-adjustments` 要求 ADMIN+、严格 body 与必填 `Idempotency-Key` Header；首次提交返回 HTTP 201，完全相同的已提交重放根据 `is_replay` 返回 HTTP 200，响应体均为首次不可变流水及其 after 余额；
- 两个 GET 端点把严格 Query Schema 的分页、`type`、source、Product 和 UTC 时间范围显式转交查询 Service，并统一通过 Inventory Mapper 输出 `Page[InventoryTransactionListItem]`；
- 三个端点均声明精确成功信封及 400/401/403/404/409/422 错误信封，由全局中间件转换异常；客户端不能伪造 operator、余额、source、流水类型或内部幂等身份；
- Product 旧 `PATCH .../stock` 路由、`KitStockUpdate`、`KitStockOut`、stock Mapper 和 ProductService 最终值写用例已移除；Kit 创建 Schema 不再接受 `stock`，ProductService 固定使用 Repository 的零库存默认值；
- 真实 SQLite HTTP 流程已覆盖零库存创建、首次调整、幂等重放、指定/全局查询、单流水/Audit、字段隔离以及旧写入口拒绝。

本阶段没有修改物理 Schema 或迁移，也没有执行持久环境数据库操作。真实 MySQL 竞争、EXPLAIN 与完整权限/异常/边界矩阵已由 4.3.11 收口。

### 9.9 真实 MySQL 与 HTTP 发布门槛

Phase 4.3.11 在独立临时数据目录、`127.0.0.1:13306` 的 MySQL Community Server 8.0.46 上执行真实 Aerich 0 → 1 → 2 迁移链，并运行可重复的 `tests/inventory/mysql/` 门槛：

- 不同 key 并发调整同一 Kit 均提交且余额累加，无丢失更新；相同 key 并发仅创建一条流水/Audit，另一请求返回原提交结果；
- 两个订单争抢最后一件库存时只有一个完整提交，失败方的 Order、Item、流水和 Audit 全部回滚；反向排列两个 Kit 的并发订单均按 Product ID 稳定锁序完成，无死锁或部分扣减；
- 同一 Pending Order 并发取消只有一个成功，库存只恢复一次；管理员持有 Kit 行锁时，下单事务可在 `performance_schema.data_lock_waits` 中观测到真实等待，释放后读取已提交的新余额；
- 通过 1 秒会话锁等待门槛触发真实 MySQL `1205`，asyncmy/Tortoise 错误码被 Service 正确识别，第二个全新事务成功且只写一个余额变化、流水和 Audit；真实 `1213` 分类仍由隔离重试单元契约覆盖，而稳定锁序测试证明正常多 Kit 业务路径不制造交叉死锁；
- `EXPLAIN` 在有代表性的选择性和 5,000 条合法流水基数下分别使用 ProductKit `product_id` 唯一索引、`idx_inventory_product_created_id` 与 `idx_inventory_created_id`；
- 真实 MySQL FastAPI 并发相同 POST 返回一组 `{201, 200}`，共享同一不可变响应，两个 GET 可读回同一流水；SQLite 完整 HTTP 矩阵另覆盖三个端点的无凭据/无效 Token/USER、资源错误优先级、余额上下界、幂等冲突、严格 Body/Header/Path/Query 422、分页、Order source、UTC 时间与隐私字段隔离。

该门槛没有修改业务实现、物理 Schema、迁移或依赖；测试安全护栏只允许显式启用的 `127.0.0.1`、非 3306 端口和 `pinkdoohub_inventory_4311` 前缀 Schema。fixture 在跨 SQLite/MySQL 前后清理 Tortoise 1.1.7 不区分后端的 Executor SQL 缓存，使两套测试可在同一 pytest 进程中稳定共存。隔离实例验证后销毁，现有 `MySQL80` 服务和所有持久数据库未被访问或修改。

## 10. 错误与优先级

Inventory 特有错误：

| 命名异常 | code | HTTP | message | data |
|----------|------|------|---------|------|
| `InsufficientStock` | `40931` | 409 | `Insufficient stock` | 用户下单仅含 `product_id`, `requested_quantity` |
| `InventoryBalanceExceeded` | `40932` | 409 | `Inventory balance exceeds the allowed range` | 管理调整或取消恢复含 `product_id`, `before_quantity`, `change_quantity`, `minimum`, `maximum` |
| `InventoryTransactionConflict` | `40933` | 409 | `Inventory idempotency key conflicts with another request` | `null` |

Product 不存在/删除/类型/Kit 扩展缺失复用 Product 的 `40401`、`40903`、`40001`、`40404`；Order 状态错误继续复用 `40921`。`change`、reason、Idempotency-Key 和查询形状错误使用全局 HTTP 422 / code `422`。

用户下单的 `InsufficientStock` 不暴露精确可用量，避免库存探测；管理调整成功响应和余额越界错误可以返回当前安全余额。多个 Kit 同时不足时，在锁定全部 Kit 后按请求 Item 顺序返回第一个不足项，避免扩大错误结构并保持与现有 Order “首个稳定错误”契约一致。

创建订单的稳定优先级：

1. Schema 请求形状；
2. Product 不存在、删除或未上架；
3. Product 类型与 Option 形状不匹配；
4. Experience Option 无效；
5. Kit 扩展缺失；
6. Kit 库存不足；
7. 持久化完整性错误。

## 11. API、查询与权限范围

Phase 4.3 最小管理 API 已全部注册：

```text
POST /api/v1/admin/products/kit/{product_id}/inventory-adjustments
GET  /api/v1/admin/products/kit/{product_id}/inventory-transactions
GET  /api/v1/admin/inventory-transactions
```

全部为 ADMIN+。Product 管理详情已经返回当前 stock，因此不增加单独余额端点。流水支持 Product、类型、Order source 和 UTC 时间范围筛选，使用 `created_at DESC, id DESC` 稳定分页。用户不访问流水，只通过 Product 详情读取当前 stock/available，并通过 Order API 间接触发库存变化。

查询 Schema 固定 `source_id` 只可与 `source_type=order` 组合；`created_from` / `created_to` 必须为 UTC 且使用包含下界、排除上界语义。响应 Schema 对余额等式、流水类型与增减方向、source/operator 元数据组合和调整结果进行交叉校验，并只接受内部 UTC aware `datetime`。这些约束现已由三个 HTTP 端点统一执行。

## 12. 发布与验证门槛

- Phase 4.3 完成后的代码候选已收口为 v0.6.0；这不代表 tag、Release 或部署。
- 静态 `select_for_update()`、SQLite 原子回滚和 MySQL 8+ 真实并发测试均已通过。
- MySQL “最后一件库存”、交叉多 Kit 锁序、取消竞争、管理员调整与下单竞争均已通过。
- MySQL `EXPLAIN` 已验证锁定和 Product/全局流水分页索引。
- 未经明确授权不执行迁移、不重建开发数据库、不 push/tag/release/deploy。

## 13. 后续实施顺序

已完成 4.3.2 领域语言与 Schema → 4.3.3 Model/数据库设计 → 4.3.4 离线迁移 → 4.3.5 Repository → 4.3.6 管理调整 → 4.3.7 Kit/混合下单 → 4.3.8 取消恢复 → 4.3.9 查询/Mapper → 4.3.10 API → 4.3.11 并发与 HTTP 矩阵 → 4.3.12 最终 Review 与 v0.6.0 候选收口。后续业务阶段需另行冻结范围。
