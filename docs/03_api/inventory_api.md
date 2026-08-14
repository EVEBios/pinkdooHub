# Inventory API

> **Document Version:** v0.6
>
> **Status:** Implemented and Final-Review Complete（Phase 4.3.12；v0.6.0 未发布候选；未应用持久环境）
>
> **Last Updated:** 2026-08-14
>
> 本文遵循 [API Design Conventions](api_design_conventions.md)，业务规则以 [Inventory Module](../01_requirements/inventory_module.md) 为准。

---

## 1. 概述

Base URL 为 `/api/v1`。Inventory 三个管理端点均已注册并要求 JWT Bearer Token 与 ADMIN+；普通用户不直接访问流水。领域类型、Schema、Model/数据库设计、MySQL 增量迁移、Repository、管理员调整与查询 Service、Mapper、组合根，以及 Order 创建扣减/取消恢复均已实现。完整迁移链、Repository smoke、真实 MySQL 竞争/1205 重试/EXPLAIN、真实 MySQL HTTP smoke、完整 SQLite HTTP 矩阵与 Phase 4.3.12 最终 Review 均已通过；代码收口为 v0.6.0 未发布候选，但未应用任何持久、共享或生产环境。

所有响应使用统一 `{code, message, data}` 信封。成功输出必须先经专用 Out Schema 显式投影；不得返回 ORM Model、内部幂等键、用户名、手机号、Token 或订单备注。

## 2. 数据对象

### 2.1 调整请求

| 字段/头 | 类型 | 必填 | 规则 |
|---------|------|------|------|
| `Idempotency-Key` header | string | 是 | 规范化后 1..128 个可打印 ASCII 字符 |
| `change` | integer | 是 | strict，`-999999..999999`，不得为 0 |
| `reason` | string | 是 | trim 后 1..256 字符 |

未知 body 字段一律拒绝。Product ID 来自 path；客户端不能提交 stock、before/after、operator、type、source 或内部幂等键。

### 2.2 流水对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 流水 ID |
| `product_id` | integer | Kit Product ID |
| `transaction_type` | string | `opening_balance` / `admin_adjustment` / `order_deduction` / `order_cancellation_restore` |
| `change_quantity` | integer | 正数增加、负数减少 |
| `before_quantity` | integer | 变化前余额 |
| `after_quantity` | integer | 变化后余额 |
| `reason` | string | 规范化原因或服务端标准原因 |
| `source_type` | string | `migration` / `admin` / `order` |
| `source_id` | integer/null | Order 来源时为 Order ID |
| `source_order_no` | string/null | 已预加载的安全订单号 |
| `operator_id` | integer/null | 触发用户/管理员 ID；迁移为空 |
| `operator_nickname` | string/null | 当前安全展示昵称 |
| `created_at` | datetime | UTC ISO 8601 |

调整响应包含本次流水对象以及当前 `stock`。内部 `idempotency_key` 永不输出。

### 2.3 Schema 注册表

| Schema/类型 | 方向 | 用途 |
|-------------|------|------|
| `InventoryIdempotencyKey` | Header | `Idempotency-Key` 严格字符串类型 |
| `InventoryAdjustmentCreate` | Request | `change + reason` 调整请求 |
| `InventoryProductTransactionQuery` | Query | path 已指定 Product 的流水筛选 |
| `InventoryTransactionQuery` | Query | 全局流水筛选，额外接受 Product ID |
| `InventoryBalanceOut` | Response | 当前权威余额 |
| `InventoryTransactionOut` | Response | 单条完整安全流水 |
| `InventoryTransactionListItem` | Response | 分页列表项 |
| `InventoryAdjustmentOut` | Response | 调整后的余额和本次流水 |

请求/查询 Schema 使用 `extra="forbid"`。`type` 是 HTTP 查询别名，内部字段名为 `transaction_type`；`source_id` 仅允许与 `source_type=order` 一起使用。响应 Schema 使用 `from_attributes=True`、额外字段白名单过滤和聚合一致性校验；时间必须是 Mapper 提供的 UTC aware `datetime`。

## 3. 错误契约

| 命名异常/来源 | code | HTTP | 说明 |
|---------------|------|------|------|
| `ProductNotFound` | `40401` | 404 | Product 不存在 |
| `ProductKitNotFound` | `40404` | 404 | Kit 扩展缺失 |
| `ProductTypeMismatch` | `40001` | 400 | Product 不是 Kit |
| `ProductIsDeleted` | `40903` | 409 | Product 已逻辑删除 |
| `InsufficientStock` | `40931` | 409 | 用户下单库存不足，不返回精确 available |
| `InventoryBalanceExceeded` | `40932` | 409 | 调整后小于 0 或大于 999999 |
| `InventoryTransactionConflict` | `40933` | 409 | 幂等键与已提交请求不一致 |
| 全局 Schema 校验 | `422` | 422 | 调整、header、分页、筛选或时间格式无效 |

HTTP 状态由异常类型决定，不根据 code 号段推断。认证失败使用全局 401，角色不足使用全局 403。

## 4. 端点列表

| Method | URI | 描述 | 角色 | 实现状态 |
|--------|-----|------|------|----------|
| POST | `/admin/products/kit/{product_id}/inventory-adjustments` | 调整 Kit 库存 | ADMIN+ | 已实现 |
| GET | `/admin/products/kit/{product_id}/inventory-transactions` | 指定 Kit 流水 | ADMIN+ | 已实现 |
| GET | `/admin/inventory-transactions` | 全局流水筛选 | ADMIN+ | 已实现 |

不新增单独余额端点；Product 管理详情继续承担当前余额读取。

## 5. 创建库存调整

```http
POST /api/v1/admin/products/kit/5/inventory-adjustments
Idempotency-Key: 54d63655-b6aa-4f91-b9ef-590602c6c5ec
Content-Type: application/json
```

```json
{
  "change": 20,
  "reason": "采购入库"
}
```

首次成功返回 HTTP 201：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "product_id": 5,
    "stock": 80,
    "transaction": {
      "id": 101,
      "product_id": 5,
      "transaction_type": "admin_adjustment",
      "change_quantity": 20,
      "before_quantity": 60,
      "after_quantity": 80,
      "reason": "采购入库",
      "source_type": "admin",
      "source_id": null,
      "source_order_no": null,
      "operator_id": 7,
      "operator_nickname": "店长",
      "created_at": "2026-08-13T10:30:00Z"
    }
  }
}
```

相同管理员、相同 key、相同规范化请求的已提交重试返回 HTTP 200 与原结果，不新增余额变化、流水或 Audit。相同 key 绑定不同请求返回 `40933`。失败并回滚的请求不占用 key。

Draft、Online、Offline 的未删除 Kit 均可调整。成功时余额、`admin_adjustment` 流水和 `ADJUST_INVENTORY` Audit 使用同一事务。

Router 根据 Phase 4.3.6 Service 返回的不可变 `is_replay` 选择首次 HTTP 201 或重放 HTTP 200；Service 本身不依赖 HTTP。两种成功响应均先通过 `InventoryAdjustmentOut`，且重放返回首次提交的流水与 after 余额。

## 6. 指定 Kit 流水

```http
GET /api/v1/admin/products/kit/5/inventory-transactions?page=1&page_size=20&type=admin_adjustment
```

先按 Product 契约区分不存在、删除、非 Kit 和 Kit 扩展缺失，再返回 `Page[InventoryTransactionOut]`。支持：

- `page`、`page_size`；
- `type`；
- `source_type`；
- `source_id`；
- `created_from`（UTC，包含）；
- `created_to`（UTC，不包含）。

排序固定为 `created_at DESC, id DESC`。

## 7. 全局流水

```http
GET /api/v1/admin/inventory-transactions?page=1&page_size=20&product_id=5&source_type=order&source_id=42
```

除指定 Kit 端点的查询参数外支持 `product_id`。筛选结果为空时返回空 Page，不把无结果解释为 Product 不存在；若需要验证 Product 身份，使用指定 Kit 端点。

Mapper 只能消费 Repository 已预加载或注解的 Product、Order 和 operator 展示字段，执行期间零 SQL、零 ORM 修改。

Phase 4.3.9 已实现指定 Kit 与全局查询 Service，以及流水/分页/调整响应 Mapper；Phase 4.3.10 已通过上述两个 GET 端点公开这些能力。指定 Kit 查询按 Product 不存在、删除、非 Kit、Kit 扩展缺失的顺序失败；全局 `product_id` 只参与筛选。Mapper 只投影上表字段并通过 Out Schema 校验，不读取内部幂等键或用户隐私字段。

## 8. Order API 联动

现有 `POST /api/v1/orders` 路径不变，Phase 4.3.7 已允许 Kit Item 省略 `experience_option_id` 或显式提交 `null`，并拒绝 Kit 携带正整数 Option ID。Kit 或混合订单创建扣减 Kit；Phase 4.3.8 已让现有 owner cancel 在 Pending 状态恢复全部 Kit，确认支付和完成继续不改变库存。完整矩阵以 [Inventory Module §4](../01_requirements/inventory_module.md#4-库存发生时点与-order-矩阵) 为准。

创建事务已按冻结顺序先写 Pending Order 取得 `Order.id`，再锁定和扣减 Kit，使流水 source 与幂等键引用稳定数据库 ID；任一步失败时该 Order 同样回滚。订单号唯一冲突发生在库存写之前，并沿用全新事务最多 3 次的既有重试契约。

取消事务先锁 owner 可见 Order，再读取 Item 数量快照并稳定锁定 Kit；每个 Product 使用 `inventory:order:{order_id}:restore:product:{product_id}`，写正数 `order_cancellation_restore` 流水。Pending 与已存在 restore 身份矛盾返回 `40933`，恢复余额越界返回 `40932`；重复取消由状态机返回 `40921`。余额、流水、Cancelled、Audit 和响应重载全事务原子，MySQL 1205/1213 对完整取消用例最多尝试 3 次。

库存不足响应示例：

```json
{
  "code": 40931,
  "message": "Insufficient stock",
  "data": {
    "product_id": 5,
    "requested_quantity": 3
  }
}
```

普通用户响应不提供 `available_quantity`。阶段门禁 `40922 KitOrderingRequiresInventory` 已随 Phase 4.3.7 创建切换从代码与当前错误注册表移除。

## 9. 兼容性

Phase 4.3.10 已移除：

```text
PATCH /api/v1/admin/products/kit/{product_id}/stock
```

同时已从 Kit 创建请求移除 `stock` 输入，新 Kit 从 0 开始并通过 adjustment 入库。两项均属于 v0.6.0 的已冻结破坏性变化，不提供语义混淆的兼容包装；旧请求现在分别得到 404 与 422。

## 10. Phase 4.3.11–4.3.12 验证与 Review 结果

- MySQL 8.0.46 隔离 Schema 使用真实 Aerich 0 → 1 → 2 迁移记录，没有 `--fake` 或运行时自动建表；
- 不同/相同管理员幂等键并发、最后一件库存、反向多 Kit、同单取消、管理员调整与下单竞争全部通过，且真实 `performance_schema.data_lock_waits` 证明行锁阻塞；
- 真实 `1205 Lock wait timeout` 被 asyncmy/Tortoise 传递并由 Service 识别，随后使用全新事务成功重试，未重复余额、流水或 Audit；
- ProductKit 锁查询、Product 流水分页和全局流水分页在代表性数据下分别命中 `product_id`、`idx_inventory_product_created_id` 和 `idx_inventory_created_id`；
- 完整 HTTP 矩阵覆盖三个端点的 401、既有无效 Token `1006`、403、400/404/409 资源与业务异常、Body/Header/Path/Query 422、分页/过滤/Order source/UTC 和隐私字段隔离；真实 MySQL 上的两个相同并发 POST 得到一组 201/200，并由两个 GET 读回唯一流水。
- 最终 Review 复核 API → Service → Repository → Model 依赖、事务/锁/重试与幂等边界、OpenAPI 双成功状态、Mapper 零 SQL/隐私白名单、迁移/索引和文档一致性；同时为 Product 用户/管理 Kit 详情响应补齐 `stock <= 999999`。

测试实例使用独立临时数据目录和 `127.0.0.1:13306`，验证后销毁；未连接现有 3306 `MySQL80` 服务，也未修改任何持久数据库。最终 Review 没有新增迁移或依赖；应用默认版本与示例环境已收口为 v0.6.0 未发布候选。
