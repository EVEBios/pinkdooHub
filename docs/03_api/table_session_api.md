# 二维码开台与计时 API

**版本**: v1.0（Implemented，仓库候选）
**最后更新**: 2026-09-10
**计划版本**: M9（必须位于 M8 之后）

---

## 1. 概述与状态

本文档定义桌台二维码解析、用户开台、待支付占台、计时查询和管理员释放的 HTTP 契约。

当前仓库已实现本文端点、Schema、Model、M9 迁移及小程序页面，并已同步 OpenAPI；是否已上线仍以目标环境迁移和验收记录为准。通用信封、认证、分页、错误格式、UTC 时间和 Enum 展示遵循 `api_design_conventions.md`。

业务规则以 `docs/01_requirements/table_session_module.md` 为准。

### 1.1 通用约定

- Base URL：`/api/v1`。
- JSON Schema 一律 `extra="forbid"`。
- 所有 ID 为 JSON integer；对外 Session 标识使用 `session_no` 字符串。
- `session_no` 固定为 `TS` + 26 位大写 Crockford Base32 ULID，匹配 `^TS[0-9A-HJKMNP-TV-Z]{26}$`；Path 与 `Table-Session-No` Header 共用该严格校验。
- 时间为带时区 UTC ISO 8601，例如 `2026-09-10T04:30:00Z`。
- 状态与原因使用 `{ "value": "...", "label": "..." }`。
- 分页默认 `page=1&page_size=20`，`page_size` 范围 `1..100`。
- 需要幂等的写接口必须带 `Idempotency-Key`：trim 后 1–128 个可打印 ASCII 字符，数据库使用 ASCII 大小写敏感逐字节语义。
- `qr_token` 固定 32 个 ASCII 字母数字字符，正则 `[A-Za-z0-9]{32}`，大小写敏感。当前内部占位二维码内容为 `PINKDOOHUB_TABLE:v1:<qr_token>`；客户端解析前缀后只把 Token 传给 API。后续微信官方小程序码的 `scene` 仍原样携带 Token，不添加字段名前缀。
- 客户端倒计时以响应的 `server_now` 与绝对截止时间为准，不上传或持久化剩余秒数。

### 1.2 角色

- `PUBLIC`：只可解析二维码；不返回当前占台者、订单或用户信息。
- `NORMAL USER`：查询本人可选订单、创建及读取本人会话。
- `ADMIN+`：查询全部桌台/会话、启停桌台、显式释放会话。
- `DISABLED`、`DELETED` 普通用户以及管理员账号不得执行用户开台接口。

---

## 2. 路由总览

### 2.1 公开与用户端

| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/table-codes/{qr_token}` | PUBLIC | 解析静态桌台二维码 |
| GET | `/table-sessions/eligible-orders` | NORMAL USER | 查询本人可用于开台的 Pending 订单 |
| POST | `/table-sessions` | NORMAL USER | 绑定桌台与订单，创建 15 分钟待支付会话 |
| GET | `/table-sessions/current` | NORMAL USER | 查询本人当前未关闭会话；没有时返回 null |
| GET | `/orders/{order_id}/table-session` | NORMAL USER | 查询本人订单最新一条桌台会话；没有时返回 null |

### 2.2 ADMIN+

| Method | Path | 说明 |
|--------|------|------|
| GET | `/admin/tables` | 查询固定 30 桌及当前占用摘要 |
| PATCH | `/admin/tables/{table_id}` | 启用或停用桌台 |
| GET | `/admin/table-sessions` | 分页查询历史与当前会话 |
| GET | `/admin/table-sessions/{session_no}` | 查询会话详情 |
| POST | `/admin/table-sessions/{session_no}/release` | 应急释放整张桌台 |

桌台种子与普通占位二维码由受控运维命令生成，不开放 HTTP 管理端点；Token 轮换和微信官方小程序码物料生成保持 Deferred，后续仍只能通过单独批准的受控运维流程提供。

---

## 3. 数据契约

### 3.1 TableSummary

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | StoreTable ID；只在认证后的用户/管理员响应出现 |
| `table_no` | string | `T01`–`T30` |
| `display_name` | string | 顾客可见名称，例如“T01号桌” |
| `is_enabled` | boolean | 是否允许创建新会话 |

公开二维码解析响应不返回 `id`，使用单独的 `PublicTableCodeOut`。

### 3.2 PublicTableCodeOut

| 字段 | 类型 | 说明 |
|------|------|------|
| `table_no` | string | 桌号 |
| `display_name` | string | 顾客可见名称 |
| `is_enabled` | boolean | 是否启用 |
| `is_available` | boolean | 当前是否可以尝试占台；只表达布尔值 |

不得返回 `table_id`、`qr_token`、Session、Order、用户信息、占台起止时间或冲突原因。`is_available=true` 不是预留承诺，最终结果以创建会话事务的锁后校验为准。

### 3.3 EligibleOrderListItemOut

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | Order ID |
| `order_no` | string | 订单号 |
| `total_amount` | string | 两位小数金额字符串 |
| `created_at` | datetime | 创建时间 |
| `experience_item_count` | integer | Experience 明细行数，不是 quantity 求和 |
| `kit_item_count` | integer | Kit 明细行数；仅作购买摘要 |
| `duration_groups` | array[`EligibleDurationGroupOut`] | 按分钟升序排列 |

`EligibleDurationGroupOut`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `duration_minutes` | integer | Experience 时长快照 |
| `buffer_minutes` | integer | 固定为 10 |
| `experience_item_count` | integer | 该时长下明细行数 |
| `total_quantity` | integer | 该时长下 quantity 求和，仅展示，不参与计时 |

查询必须基于 Order Item 历史快照，不读取 Product/Option 当前时长。纯 Kit、非 Pending、已有成功结算或已有未关闭 Table Session 的订单不进入列表。

### 3.4 TableSessionTimerOut

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | Timer ID |
| `duration_minutes` | integer | 分组后的 Experience 时长 |
| `buffer_minutes` | integer | 固定快照 10 |
| `started_at` | datetime | 等于可信付款成功时间 |
| `service_ends_at` | datetime | Experience 阶段结束 |
| `grace_ends_at` | datetime | 缓冲阶段结束 |
| `phase` | object | `EXPERIENCE` / `GRACE` / `ENDED` 的动态展示对象 |
| `ended_at` | datetime / null | 实际结束时间；自然结束为 `grace_ends_at`，父 Session 提前关闭时为更早的 `closed_at` |
| `experience_items` | array[`TimerExperienceItemOut`] | 属于该分钟组的不可变订单 Item 摘要 |

`TimerExperienceItemOut`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `order_item_id` | integer | Order Item ID |
| `product_id` | integer | 原 Product ID |
| `product_name` | string | 名称快照 |
| `quantity` | integer | 购买数量，仅展示 |
| `participants_per_unit` | integer / null | Option 人数快照；不参与计时 |
| `total_participants` | integer / null | `quantity × participants_per_unit` 的展示派生值 |

Kit Item 不得进入 `experience_items`。Timer Mapper 必须使用已经预加载的 Order Item 快照，不在循环中发 SQL。父 Session 为 `CLOSED` 时 `phase` 固定为 `ended`，`ended_at = min(grace_ends_at, session.closed_at)`；Session 未关闭但 Timer 已自然结束时 `ended_at=grace_ends_at`，其他情况为 null。

### 3.5 TableSessionOut

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_no` | string | `TS` + 26 位 Crockford ULID |
| `table` | `TableSummary` | 桌台摘要 |
| `order_id` | integer | 绑定订单 ID |
| `order_no` | string | 订单号 |
| `status` | object | `AWAITING_PAYMENT` / `ACTIVE` / `CLOSED` |
| `claimed_at` | datetime | 成功占台时间 |
| `payment_deadline_at` | datetime | `claimed_at + 15 分钟` |
| `started_at` | datetime / null | 未付款时 null；激活后等于 Payment.succeeded_at |
| `table_release_at` | datetime / null | 未付款时 null；激活后为最晚缓冲结束点 |
| `closed_at` | datetime / null | 未关闭时 null |
| `close_reason` | object / null | 关闭后返回稳定原因 |
| `timers` | array[`TableSessionTimerOut`] | 待支付时为空；激活/关闭后保留历史 Timer |
| `server_now` | datetime | Mapper 捕获的一致 UTC 当前时间 |

用户响应不返回 `user_id`、`payment_id`、`qr_token`、Idempotency-Key、管理员原因全文或操作者信息。

### 3.6 AdminTableOut

在 `TableSummary` 基础上增加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `state` | string | `available` / `awaiting_payment` / `active` / `disabled` |
| `current_session_no` | string / null | 当前 Occupancy 对应 Session |
| `current_status` | object / null | 当前会话状态 |
| `current_order_no` | string / null | 当前订单号 |
| `current_user_id` | integer / null | 当前顾客 ID |
| `claimed_at` | datetime / null | 当前占台时间 |
| `payment_deadline_at` | datetime / null | 待支付截止 |
| `table_release_at` | datetime / null | 激活后预计释放时间 |

固定最多 30 条，`GET /admin/tables` 返回 `AdminTableListOut`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | array[`AdminTableOut`] | 按 `table_no ASC` 排序的 30 桌摘要 |
| `server_now` | datetime | 全部桌台共用的一次 UTC 当前时间 |

该有界列表不使用分页。

### 3.7 AdminTableSessionOut

在 `TableSessionOut` 基础上增加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | integer | 顾客 ID |
| `user_nickname` | string | 当前安全展示昵称 |
| `payment_id` | integer / null | 激活关联 Payment |
| `closed_by_user_id` | integer / null | 人工关闭操作者；系统关闭为 null |
| `admin_close_reason` | string / null | 管理员显式释放原因，trim 后 1–200 字符 |

不返回用户名、手机号、Token、钱包余额、Idempotency-Key 或支付 Provider 原始数据。

### 3.8 Schema 注册表

| Schema | 方向 | 用途 |
|--------|------|------|
| `TableCodePath` | Path | QR Token 形状校验 |
| `EligibleOrderListQuery` | Query | 用户可选订单分页 |
| `TableSessionCreate` | Request | `qr_token` + `order_id` |
| `TableSessionOut` | Response | 用户会话详情 |
| `TableSessionTimerOut` | Response | 计时分组 |
| `TimerExperienceItemOut` | Response | Timer 下 Experience 快照摘要 |
| `AdminTableUpdate` | Request | `is_enabled` + `reason` |
| `AdminTableListOut` | Response | 固定 30 桌 + 单一 `server_now` |
| `AdminTableSessionListQuery` | Query | 管理会话组合筛选 |
| `AdminTableSessionListItemOut` | Response | 管理分页列表项 |
| `AdminTableSessionOut` | Response | 管理详情 |
| `AdminTableSessionRelease` | Request | 人工释放原因 |

运行时由 Mapper 显式投影并严格校验 Out Schema，再由 `success()` 包装。OpenAPI 使用精确的 `SuccessResponse[T]` / `ErrorResponse`，不得直接暴露 ORM Model。

---

## 4. 公开二维码解析

### 4.1 GET `/table-codes/{qr_token}`

不要求 Bearer Token。

成功（200）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "table_no": "T01",
    "display_name": "T01号桌",
    "is_enabled": true,
    "is_available": true
  }
}
```

行为：

- 读取前先对目标桌台的已到期待支付/计时会话执行安全的惰性收敛，或使用不延迟响应的一致可用性查询。
- 接口必须限流并允许短时间公共缓存，但缓存不得被当作占台授权。
- 无效 Token 返回 `40461`，停用桌台仍可返回 200 + `is_enabled=false`，不泄露停用原因。
- 新占台开关关闭时返回 HTTP 503，不把 `is_available=false` 伪装成普通桌台占用。

---

## 5. 用户接口

### 5.1 GET `/table-sessions/eligible-orders`

Query：

| 参数 | 类型 | 默认 | 规则 |
|------|------|------|------|
| `page` | integer | 1 | >= 1 |
| `page_size` | integer | 20 | 1..100 |

成功（200）返回 `Page[EligibleOrderListItemOut]`，按 `created_at DESC, id DESC` 稳定排序。

此列表是用户体验辅助，不构成开台资格承诺；创建接口必须在事务锁后重新校验。
若当前用户已经有未关闭 Session，接口先收敛时间状态；仍未关闭时返回 `40963`，客户端应跳转 `/table-sessions/current`，不再展示另一批可选订单。

### 5.2 POST `/table-sessions`

Headers：

```http
Authorization: Bearer <access_token>
Idempotency-Key: table-claim-20260910-001
Content-Type: application/json
```

Body：

```json
{
  "qr_token": "M9X7zF3Yv2qN8bKt4Rd6Wp1Hs5Lc0AaE",
  "order_id": 51
}
```

校验：

- `qr_token` 必填，精确匹配格式。
- `order_id` 必填且为正整数。
- 未知字段拒绝。
- Idempotency-Key 缺失、空白、过长或含不可打印字符返回全局 HTTP 422 / code `422`。

响应：

- 首次创建：HTTP 201，`TableSessionOut`，状态 `AWAITING_PAYMENT`。
- 完全相同重放：HTTP 200，返回原不可变创建结果的当前投影。
- 同 Key 不同规范化请求：`40965`。

创建成功示例：

```json
{
  "code": 0,
  "message": "Table session created",
  "data": {
    "session_no": "TS01K4FF7V3J5KQ0P2M9R8A6C1DE",
    "table": {
      "id": 1,
      "table_no": "T01",
      "display_name": "T01号桌",
      "is_enabled": true
    },
    "order_id": 51,
    "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
    "status": {"value": "awaiting_payment", "label": "待支付"},
    "claimed_at": "2026-09-10T04:30:00Z",
    "payment_deadline_at": "2026-09-10T04:45:00Z",
    "started_at": null,
    "table_release_at": null,
    "closed_at": null,
    "close_reason": null,
    "timers": [],
    "server_now": "2026-09-10T04:30:00Z"
  }
}
```

错误优先级固定为：认证角色/账号状态 → 已存在幂等事实（相同请求重放、不同请求 `40965`）→ 新占台开关 → QR Token 存在/桌台启用 → Owner 可见 Order → Order 开台资格 → 锁内时间收敛 → 用户已有 Session → Order 已有 Session → 桌台 Occupancy。这样既不让并发改变首个错误，也不因桌台占用泄露他人信息。

开关关闭时不创建新 Session；但完全相同的已提交幂等请求仍可返回 200 replay，因为它不产生新占用。桌台同时停用且被占用时，新的非重放请求稳定返回 `TableUnavailable.reason=disabled`。

### 5.3 GET `/table-sessions/current`

返回当前用户唯一一条未关闭会话。查询前执行惰性收敛。

有会话：HTTP 200 + `TableSessionOut`。
无会话：HTTP 200 + `data: null`，不返回 404。

### 5.4 GET `/orders/{order_id}/table-session`

返回当前用户该订单最新一条 Table Session，按 `claimed_at DESC, id DESC` 选择。存在未关闭会话时它必然是最新一条。查询前执行惰性收敛。

- 有历史或当前会话：HTTP 200 + `TableSessionOut`。
- 本人订单尚无会话：HTTP 200 + `data: null`。
- 订单不存在或不属于当前用户：复用 `40411 OrderNotFound`，不泄露所有者。

### 5.5 钱包付款的会话关联

现有 `POST /orders/{order_id}/payments/wallet` 在 M9 增加可选 Header：

```http
Table-Session-No: TS01K4FF7V3J5KQ0P2M9R8A6C1DE
```

规则：

1. 桌台计时页发起付款时必须携带该 Header。
2. Header 存在时，Session 必须属于当前用户和 Path 中的 Order，处于 `AWAITING_PAYMENT`，且可信付款时间 `succeeded_at <= payment_deadline_at`；否则资金零写入并返回稳定业务错误。
3. Header 不存在但 Order 当前有有效的唯一待支付 Session 时，后端自动关联并激活，兼容现有付款入口。
4. Header 不存在且没有未关闭 Session 时，保持现有普通订单付款行为，不创建 Timer。
5. Header 指向已经超时关闭的历史 Session 时返回 `40966`，不得退化为普通付款；桌台页应提示重新扫码绑定。
6. 付款成功响应继续使用现有 `PaymentOut`，客户端随后查询 `/orders/{order_id}/table-session` 获取计时详情，避免扩张资金响应契约。

现有 `PATCH /admin/orders/{order_id}/paid` 同样增加可选 `Table-Session-No` Header。管理桌台页发起人工结算时必须携带它并执行与钱包相同的 Session/Order/截止时间校验；现有普通订单管理页不携带 Header 时，后端在锁定订单后只自动关联唯一、未超时的待支付 Session，没有未关闭 Session 时保持普通人工结算。已经关闭的历史 Session 绝不自动启动计时。

---

## 6. ADMIN+ 接口

### 6.1 GET `/admin/tables`

返回 `AdminTableListOut`，精确最多 30 条，按 `table_no ASC`，并在顶层返回单一 `server_now`。读取前批量收敛到期待支付/计时会话；禁止循环逐桌查询。

### 6.2 PATCH `/admin/tables/{table_id}`

Headers：Bearer Token、JSON Content-Type。

Body：

```json
{
  "is_enabled": false,
  "reason": "桌面维修"
}
```

规则：

- `reason` trim 后 1–200 字符。
- 停用只阻止新 Session，不关闭当前 Session。
- 将 `is_enabled` PATCH 到当前相同值是安全 no-op 并返回 200；状态发生变化时写 `UPDATE_STORE_TABLE` Audit。
- 不允许修改 `table_no`、`display_name` 或 `qr_token`。
- 成功返回 HTTP 200 + `TableSummary`。

### 6.3 GET `/admin/table-sessions`

Query：

| 参数 | 类型 | 规则 |
|------|------|------|
| `page` | integer | 默认 1，>= 1 |
| `page_size` | integer | 默认 20，1..100 |
| `table_id` | integer | 可选，正整数；未知 ID 返回空 Page |
| `user_id` | integer | 可选，正整数 |
| `order_id` | integer | 可选，正整数 |
| `status` | string | 可选：`awaiting_payment` / `active` / `closed` |
| `close_reason` | string | 可选，稳定关闭原因 |
| `claimed_from` | datetime | 可选，UTC 含时区 |
| `claimed_to` | datetime | 可选，UTC 含时区，且不早于 from |

按 `claimed_at DESC, id DESC` 稳定排序，返回 `Page[AdminTableSessionListItemOut]`。列表项不得携带完整 Timer Item 数组；可返回 `timer_count`、最短/最长时长和关键时间。

### 6.4 GET `/admin/table-sessions/{session_no}`

成功返回 `AdminTableSessionOut`。不存在返回 `40462`。

### 6.5 POST `/admin/table-sessions/{session_no}/release`

Headers：Bearer Token、`Idempotency-Key`、JSON Content-Type。

Body：

```json
{
  "reason": "顾客已提前离店"
}
```

规则：

- `reason` trim 后 1–200 字符。
- 只允许 `AWAITING_PAYMENT` 或 `ACTIVE`。
- 关闭整个 Session、删除 Occupancy、设置 `close_reason=admin_released`，不修改 Order、Payment、Refund 或 Inventory。
- 首次成功 HTTP 200；完全相同重放返回同一关闭事实；同 Key 不同意图返回 `40965`。
- 已因其他原因关闭时返回 `40962`，不得改写 `closed_at`、`close_reason` 或原操作者。
- 写 `RELEASE_TABLE_SESSION` Audit，记录 Session、Table、Order 和规范化原因，不记录幂等键。

---

## 7. 状态与时间响应示例

120 分钟 Experience 已付款后的 `TableSessionOut` 关键部分：

```json
{
  "status": {"value": "active", "label": "计时中"},
  "started_at": "2026-09-10T04:35:00Z",
  "table_release_at": "2026-09-10T06:45:00Z",
  "timers": [
    {
      "id": 101,
      "duration_minutes": 120,
      "buffer_minutes": 10,
      "started_at": "2026-09-10T04:35:00Z",
      "service_ends_at": "2026-09-10T06:35:00Z",
      "grace_ends_at": "2026-09-10T06:45:00Z",
      "phase": {"value": "experience", "label": "体验中"},
      "ended_at": null,
      "experience_items": [
        {
          "order_item_id": 801,
          "product_id": 12,
          "product_name": "双人拼豆体验",
          "quantity": 2,
          "participants_per_unit": 2,
          "total_participants": 4
        }
      ]
    }
  ],
  "server_now": "2026-09-10T04:40:00Z"
}
```

60 与 120 分钟混合订单生成两个 Timer；两个 `started_at` 完全相同，`table_release_at` 等于 120 分钟 Timer 的 `grace_ends_at`。Kit 不出现在数组中。

---

## 8. 错误契约

HTTP 状态由异常类型决定，不根据 code 数字段推断。

| 命名异常 | code | HTTP | message | data |
|----------|------|------|---------|------|
| `TableCodeNotFound` | `40461` | 404 | `Table code not found` | null |
| `TableSessionNotFound` | `40462` | 404 | `Table session not found` | null |
| `StoreTableNotFound` | `40463` | 404 | `Store table not found` | null |
| `TableUnavailable` | `40961` | 409 | `Table is unavailable` | `table_no`, `reason=occupied|disabled`；不含占台者 |
| `TableSessionStatusConflict` | `40962` | 409 | `Table session status does not allow this operation` | `operation`, `current_status`, `required_status` |
| `UserTableSessionConflict` | `40963` | 409 | `User already has an open table session` | null |
| `OrderTableSessionConflict` | `40964` | 409 | `Order already has an open table session` | `order_id` |
| `TableIdempotencyConflict` | `40965` | 409 | `Table idempotency key conflicts with another request` | null |
| `TablePaymentWindowExpired` | `40966` | 409 | `Table payment window has expired` | `session_no`, `payment_deadline_at` |
| `TableOrderIneligible` | `42261` | 422 | `Order is not eligible to open a table` | `order_id`, `reason` |
| `TableRateLimitExceeded` | `42961` | 429 | `Too many table requests` | null |

`TableOrderIneligible.reason` 仅允许稳定白名单：

- `no_experience_item`
- `invalid_experience_duration_snapshot`
- `order_not_pending`
- `order_already_settled`

订单不存在/不属于当前用户复用 `40411 OrderNotFound`。账号状态复用 `1005 UserDisabled`、`1009 UserDeleted`。请求形状、Header、Path 或 Query 错误使用全局 HTTP 422 / code `422`，不新增业务码。

新占台开关 `TABLE_SESSION_CLAIMS_ENABLED=false`、目标环境尚未完成 M9 或开台前置条件未满足时，公开二维码解析、可选订单与创建 Session 返回 HTTP 503，并且不得创建 Session、Occupancy 或 AuditLog。该开关不得阻断已存在 Session 的查询、到期收敛、截止内付款、订单取消/完成/退款联动或管理员释放；紧急停用时必须允许安全排空现有会话。

---

## 9. 幂等、资源隐藏与审计

### 9.1 幂等

- 创建 Session 与管理员释放各自使用独立命名空间和持久幂等事实；桌台启停使用目标布尔状态的天然幂等 PATCH。
- 幂等比较至少覆盖业务动作、目标资源、规范化请求和真实操作者。
- 幂等重放不更新 `claimed_at`、`payment_deadline_at`、`started_at`、`closed_at` 或 Timer。
- 数据库 UNIQUE 冲突必须在失败事务退出后解析，不在 poisoned transaction 中继续读。

### 9.2 资源隐藏

- 用户读取他人 Order 或 Session 时返回对应 NotFound，不返回 403。
- 公开解析只返回布尔可用性，不返回占用用户、Session 或 Order。
- 管理列表只提供运营所需最小用户摘要。
- 应用和审计日志不记录完整 `qr_token` 或 Session Idempotency-Key；定位问题使用桌号、内部 ID、request ID 或 Token 有界摘要。公开 URL 中的 Token 仍按部署层访问日志脱敏规则处理。

### 9.3 Audit

人工动作至少记录：

- `CREATE_TABLE_SESSION`
- `UPDATE_STORE_TABLE`
- `ACTIVATE_TABLE_SESSION`（随钱包/人工付款的真实操作者）
- `RELEASE_TABLE_SESSION`
- 订单取消、完成与退款继续沿用其现有 Audit action，并在 details 中附加已关闭 Session 标识。

自动 `PAYMENT_TIMEOUT` / `TIME_EXPIRED` 不伪造 operator；Session 行本身是权威关闭记录。

### 9.4 限流

M9 首版默认阈值：

- 公开二维码解析：每 IP 每分钟 60 次。
- 创建 Session：每用户每 15 分钟 5 次，同时每 IP 每 15 分钟 20 次。
- 用户可选订单、当前 Session 与订单最新 Session：每用户每分钟各 60 次。

限流计数使用 Redis 原子操作；公开解析和创建 Session 在 Redis 不可用时 fail closed 为 HTTP 503，不能失去防滥用保护后继续占台。超过阈值返回 `42961 TableRateLimitExceeded`，响应不包含 IP、Token、用户、Order 或当前占台信息。阈值作为命名配置项暴露，生产调优必须保留上述多维约束，不能只依赖客户端节流。

---

## 10. 查询、Mapper 与性能约束

1. 所有列表数据库分页，唯有固定上限 30 的 `/admin/tables` 可返回有界数组。
2. 可选订单使用存在性过滤和聚合预取，不逐单查询 Items。
3. Session 详情一次预加载 Table、Order、Timer、Experience Item 快照和必要用户摘要。
4. API Mapper 在执行期间零 SQL、零 ORM 修改，并按用户/管理员白名单分别投影。
5. Timer `phase`、`ended_at` 与 `server_now` 在 Mapper 入口捕获一次 UTC 当前时间后统一派生；父 Session 已关闭时所有 Timer 立即 ended，避免提前释放后仍显示体验中。
6. 列表不加载大体量 Item 数组；详情才返回 Timer Item 摘要。
7. 自动收敛使用分页、稳定排序和短事务，不持有跨网络调用的数据库锁。

---

## 11. OpenAPI 与兼容性

- 所有新端点必须精确声明成功与错误信封，不能保留无约束 `object`。
- `/orders/{order_id}/payments/wallet` 与 `/admin/orders/{order_id}/paid` 新增的 `Table-Session-No` 是可选 Header，因此不破坏现有普通订单客户端；桌台计时/管理桌台页必须使用它绑定付款意图。
- 现有 Order 创建、取消、管理支付、完成、钱包付款和退款的成功对象保持原契约；Table Session 详情通过独立查询获得。
- OpenAPI 导出、前端类型生成、类型检查和严格请求体拒绝测试必须同步更新。

---

## 12. 发布前 API 门槛

1. 所有公开、用户和管理员端点的认证、权限、资源隐藏、严格 422 与错误信封矩阵通过。
2. 30 桌固定上限、排序、停用、冲突和惰性到期行为通过。
3. 钱包与人工付款的 `Payment.succeeded_at`、Timer 和事务回滚一致性通过。
4. 取消、完成、退款和管理员释放均原子删除 Occupancy。
5. 幂等首次/重放/冲突及 MySQL UNIQUE 竞态通过。
6. 真实 MySQL 8 同桌、同用户、同订单、付款/超时并发门槛通过。
7. OpenAPI、前端生成类型和小程序真机扫码通过。
8. 新占台开关关闭时解析、可选订单和创建 Session 稳定 503 零写入；既有 Session 仍可排空、查询和应急释放。
