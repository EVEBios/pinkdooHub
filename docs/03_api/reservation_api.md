# Reservation API v1.0（N1）

> **Status:** N1/M7 implemented and verified；M5/M7 present in current Gate A M7；other environments and real-client acceptance pending
>
> **Last Updated:** 2026-09-09
>
> **Base URL:** `/api/v1`

---

## 1. 契约说明

Reservation API 提供独立体验预约。创建预约不会创建 Order、Payment、WalletTransaction，也不要求客户端提交金额或联系方式。业务规则以 [Reservation Module](../01_requirements/reservation_module.md) 为准。

所有端点都需要 Bearer Token：

```http
Authorization: Bearer <access_token>
```

- `/reservations/*` 只允许状态正常的普通 `USER`。
- `/admin/*` 只允许 `ADMIN` / `SUPER_ADMIN`。
- 权限不足使用现有认证/授权错误；业务错误由全局异常中间件转换。
- 所有成功响应使用统一信封；列表数据在 `data` 内使用统一 Page。
- 所有 datetime 是 UTC ISO 8601；`reservation_date` / `start_time` / `end_time` 是 `Asia/Shanghai` 的当地展示字段。

成功信封：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

失败信封：

```json
{
  "code": 42253,
  "message": "Reservation schedule is unavailable",
  "data": {
    "reason": "minimum_lead_time"
  }
}
```

## 2. 端点总览

### 2.1 顾客端

| Method | Path | 用途 | 成功 HTTP |
|--------|------|------|-----------|
| GET | `/reservations/booking-options` | 获取一个 Option 未来第 0–30 日的合法日期与时段 | 200 |
| POST | `/reservations` | 创建 `pending` 独立预约 | 201 |
| GET | `/reservations` | 分页查看自己的预约历史 | 200 |
| GET | `/reservations/{reservation_id}` | 查看自己的预约详情 | 200 |
| PATCH | `/reservations/{reservation_id}/cancel` | 在截止时间前取消自己的预约 | 200 |

### 2.2 管理端

| Method | Path | 用途 | 成功 HTTP |
|--------|------|------|-----------|
| GET | `/admin/reservations` | 分页、组合筛选全部预约 | 200 |
| GET | `/admin/reservations/{reservation_id}` | 详情与当前完整手机号 | 200 |
| GET | `/admin/reservations/{reservation_id}/audit-logs` | 预约操作历史 | 200 |
| PATCH | `/admin/reservations/{reservation_id}/confirm` | 确认 `pending` 预约 | 200 |
| PATCH | `/admin/reservations/{reservation_id}/reject` | 以固定 `no_capacity` 拒绝 `pending` 预约 | 200 |
| GET | `/admin/store-closures` | 分页查询营业日记录；默认只返回自定义店休 | 200 |
| PUT | `/admin/store-closures/{business_date}` | 设置自定义店休并原子取消尚未开始的活跃预约 | 首次 201 / 重放 200 |
| DELETE | `/admin/store-closures/{business_date}` | 恢复营业，不复活已取消预约 | 200 |

## 3. 公共数据结构

### 3.1 Enum + Label

状态和原因使用对象，业务判断只使用 `value`：

```json
{
  "value": "pending",
  "label": "待门店确认"
}
```

| 类型 | value | label |
|------|-------|-------|
| ReservationStatus | `pending` | 待门店确认 |
| ReservationStatus | `confirmed` | 已确认 |
| ReservationStatus | `rejected` | 未能确认 |
| ReservationStatus | `cancelled` | 已取消 |
| ReservationRejectionReason | `no_capacity` | 当前时段无空位 |
| ReservationCancellationReason | `customer_request` | 顾客取消 |
| ReservationCancellationReason | `store_closed` | 门店店休 |
| DayType | `weekday` | 工作日 |
| DayType | `holiday` | 节假日 |

`rejection_reason` 和 `cancellation_reason` 在不适用时是 null，绝不同时非 null。

### 3.2 `ReservationOut`

用户列表、用户详情，以及用户/管理员状态 mutation 都返回同一安全预约结构：

```json
{
  "id": 1001,
  "product_id": 21,
  "experience_option_id": 42,
  "product_name": "拼豆双人体验",
  "duration_minutes": 120,
  "participants": 2,
  "day_type": {
    "value": "holiday",
    "label": "节假日"
  },
  "price": "399.00",
  "status": {
    "value": "pending",
    "label": "待门店确认"
  },
  "rejection_reason": null,
  "cancellation_reason": null,
  "customer_message": "预约已提交，正在等待门店确认。",
  "reservation_date": "2026-09-12",
  "start_time": "14:30",
  "end_time": "16:30",
  "scheduled_start_at": "2026-09-12T06:30:00Z",
  "scheduled_end_at": "2026-09-12T08:30:00Z",
  "cancellation_deadline_at": "2026-09-12T03:30:00Z",
  "confirmed_at": null,
  "rejected_at": null,
  "cancelled_at": null,
  "created_at": "2026-09-06T02:00:00Z",
  "updated_at": "2026-09-06T02:00:00Z"
}
```

字段语义：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | positive integer | Reservation ID |
| `product_id` | positive integer | 创建时关联 Product ID |
| `experience_option_id` | positive integer | 创建时关联 Option ID |
| `product_name` | string | 创建时名称快照 |
| `duration_minutes` | positive integer | 创建时 Option 时长快照 |
| `participants` | positive integer | 创建时人数快照 |
| `day_type` | Enum object | 创建时 Option 日期类型快照 |
| `price` | fixed two-decimal string | 创建时 Option 价格快照；不得转 float 作为权威金额 |
| `status` | Enum object | 当前预约状态 |
| `rejection_reason` | Enum object / null | 仅 rejected 时为 `no_capacity` |
| `cancellation_reason` | Enum object / null | 仅 cancelled 时为两种取消原因之一 |
| `customer_message` | string | 与状态/原因一致的服务端顾客文案 |
| `reservation_date` | date | 上海当地预约日期 |
| `start_time` / `end_time` | string | 上海当地时间；开始始终 `HH:00` / `HH:30`，结束可为任意分钟 |
| `scheduled_start_at` / `scheduled_end_at` | UTC datetime | 权威 UTC 时间范围 |
| `cancellation_deadline_at` | UTC datetime | 精确等于开始时间减 3 小时 |
| 状态时间 | UTC datetime / null | `confirmed_at`、`rejected_at`、`cancelled_at` |
| `created_at` / `updated_at` | UTC datetime | 技术时间 |

`ReservationOut` 不包含用户资料、手机号、订单、支付或管理员信息。

### 3.3 Page

所有列表端点使用：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

`page >= 1`，`page_size` 为 1–100，默认 20。未知 query 字段返回通用 422。

## 4. 顾客端接口

### 4.1 获取可预约日期与时段

```http
GET /api/v1/reservations/booking-options?experience_option_id=42
```

Query：

| 参数 | 必填 | 规则 |
|------|------|------|
| `experience_option_id` | 是 | 正整数；字符串 query 必须是 ASCII 十进制正整数 |

成功 `data`：

```json
{
  "experience_option_id": 42,
  "product_id": 21,
  "product_name": "拼豆双人体验",
  "duration_minutes": 120,
  "participants": 2,
  "day_type": { "value": "holiday", "label": "节假日" },
  "price": "399.00",
  "timezone": "Asia/Shanghai",
  "server_now": "2026-09-06T02:00:00Z",
  "booking_window_end_date": "2026-10-06",
  "minimum_lead_hours": 3,
  "slot_interval_minutes": 30,
  "booking_window_days": 30,
  "opens_at": "11:00",
  "closes_at": "20:00",
  "dates": [
    {
      "date": "2026-09-12",
      "day_type": { "value": "holiday", "label": "节假日" },
      "start_times": ["11:00", "11:30", "12:00", "12:30"]
    }
  ]
}
```

`dates` 一次覆盖上海当地今天到第 30 日；只保留至少一个合法时段的日期，允许返回空数组。响应以 `weekly_closed_weekday: {value,label}` 返回当前固定店休日。该接口排除当前固定店休日、单日店休、不匹配 Option `day_type`、不满 3 小时和无法在 20:00 前完成的时段，但不检查空位。

业务错误：`42251` / `42252`。页面停留后创建仍会重新校验，不能把此响应当作预留座位。

### 4.2 创建预约

```http
POST /api/v1/reservations
Content-Type: application/json
```

严格请求体：

```json
{
  "experience_option_id": 42,
  "reservation_date": "2026-09-12",
  "start_time": "14:30"
}
```

| 字段 | 规则 |
|------|------|
| `experience_option_id` | JSON integer，严格正整数；不接受字符串和 boolean |
| `reservation_date` | 上海当地有效日历日，严格 `YYYY-MM-DD` |
| `start_time` | 严格 24 小时制 `HH:00` 或 `HH:30` |

不允许额外字段。客户端不得提交 user、手机号、Product、价格、时长、人数、状态或原因；全部由服务端当前数据生成并保存快照。

成功：HTTP 201，`message="Reservation submitted for store confirmation"`，`data=ReservationOut` 且状态为 `pending`。

主要失败：

- `42251` Product 不可预约；
- `42252` Option 不可预约；
- `42253` 日期/时段不可用；
- `42254` 当前用户没有手机号。

POST 当前没有幂等键。网络、超时、HTTP 5xx 或成功响应契约损坏后结果未知，不自动重试；跳转“我的预约”查询权威结果。

同一用户对同一 Option 和同一时段可以有多条 Reservation；每次已被服务端接受的 POST 都返回新的 ID。N1 没有自动容量、占座或同槽去重语义，门店逐条人工确认/拒绝。客户端应合并一次点击的进行中 Promise，但不得把这种 UI 防双击描述为服务端唯一约束。

### 4.3 我的预约列表

```http
GET /api/v1/reservations?page=1&page_size=20&status=pending
```

可选 `status` 只允许四个 ReservationStatus。返回 `Page[ReservationOut]`，排序固定为 `scheduled_start_at DESC, id DESC`。

### 4.4 我的预约详情

```http
GET /api/v1/reservations/{reservation_id}
```

成功返回 `ReservationOut`。不存在或不属于当前用户统一返回 `40451`。

### 4.5 取消预约

```http
PATCH /api/v1/reservations/{reservation_id}/cancel
```

请求必须没有 body，连 `{}` 也不发送。

允许条件：

- Owner 可见；
- 当前状态是 `pending` 或 `confirmed`；
- 服务端 `now <= cancellation_deadline_at`。

成功返回 `ReservationOut`，状态为 `cancelled`，`cancellation_reason.value=customer_request`，`message="Reservation cancelled"`。从 confirmed 取消时历史 `confirmed_at` 保留。

失败：

- `40451` 不存在或非 Owner；
- `40951` 状态不允许取消；
- `40952` 已晚于截止时间。

重复取消不是 200 replay，而是 `40951`。结果未知时先 GET 详情收敛状态。

## 5. 管理端预约接口

### 5.1 列表与筛选

```http
GET /api/v1/admin/reservations?page=1&page_size=20&status=pending&business_date=2026-09-12&user_id=7&product_id=21
```

所有筛选均可选并可组合：

| 参数 | 规则 |
|------|------|
| `status` | 四状态之一 |
| `business_date` | 严格 `YYYY-MM-DD`，按上海营业日 |
| `user_id` | ASCII 十进制正整数 |
| `product_id` | ASCII 十进制正整数 |

排序为 `scheduled_start_at DESC, id DESC`。每项为 `AdminReservationListItemOut`，即 `ReservationOut` 加：

```json
{
  "user_id": 7,
  "user_nickname": "小粉",
  "user_phone_masked": "138****8000"
}
```

手机号缺失时 `user_phone_masked=null`。掩码必须由服务端生成，客户端不能先接收完整手机号再自行遮盖。

### 5.2 管理详情

```http
GET /api/v1/admin/reservations/{reservation_id}
```

返回 `AdminReservationDetailOut`，即 `ReservationOut` 加：

```json
{
  "user_id": 7,
  "user_nickname": "小粉",
  "user_phone": "13812348000"
}
```

`user_phone` 是当前 User 数据，不是创建快照，可为 null。完整号码仅在详情按需展示，不写日志或审计描述，也不能持久化到客户端列表缓存。

### 5.3 预约审计

```http
GET /api/v1/admin/reservations/{reservation_id}/audit-logs?page=1&page_size=20
```

服务端先确认 Reservation 存在，再按共享 AuditLog Page 返回。目标为 `target_type=reservation`、`target_id={reservation_id}`。可能动作包括：

- `CREATE_RESERVATION`
- `CONFIRM_RESERVATION`
- `REJECT_RESERVATION`
- `CANCEL_RESERVATION`

描述只使用稳定原因，例如 `reason=no_capacity` / `reason=store_closed` / `reason=customer_request`，不得包含手机号或自由文本。

### 5.4 确认预约

```http
PATCH /api/v1/admin/reservations/{reservation_id}/confirm
```

请求无 body。仅 `pending` 且服务端当前时间严格早于开始时间时允许。成功返回 `ReservationOut`，状态为 `confirmed`，`confirmed_at` 非 null，`message="Reservation confirmed"`。

失败：`40451`、`40951` 或 `40953`。

### 5.5 拒绝预约

```http
PATCH /api/v1/admin/reservations/{reservation_id}/reject
```

请求无 body，不接受客户端原因。仅 `pending` 且尚未开始时允许。成功返回：

```json
{
  "status": { "value": "rejected", "label": "未能确认" },
  "rejection_reason": {
    "value": "no_capacity",
    "label": "当前时段无空位"
  },
  "customer_message": "很抱歉，您选择的时段当前已无空位，本次预约未能确认。您可以选择其他日期或时段重新预约。"
}
```

以上仅展示相关字段；实际 `data` 是完整 `ReservationOut`。成功 message 为 `Reservation rejected because no capacity is available`。失败：`40451`、`40951` 或 `40953`。

## 6. 自定义店休接口

### 6.1 查询营业日记录

```http
GET /api/v1/admin/store-closures?page=1&page_size=20&date_from=2026-09-06&date_to=2026-10-06&is_closed=true
```

| 参数 | 默认 | 规则 |
|------|------|------|
| `date_from` | null | 可选严格日期，包含边界 |
| `date_to` | null | 可选严格日期，包含边界；不得早于 `date_from` |
| `is_closed` | true | `true` 仅店休、`false` 仅当前营业；不传时按 true，HTTP 契约不提供“一次返回全部状态”的 null 值 |

返回 `Page[StoreBusinessDayOut]`，按 `business_date ASC, id ASC`：

```json
{
  "id": 301,
  "business_date": "2026-09-12",
  "is_closed": true,
  "created_at": "2026-09-06T02:00:00Z",
  "updated_at": "2026-09-06T02:00:00Z"
}
```

注意：该表是一日一行的并发锁点，不是完整自然日历。预约创建过的日期也可能有 `is_closed=false` 行。当前配置的每周固定店休日不依赖此表，因此不会因为每周规则自动出现在列表中。

### 6.2 设置店休

```http
PUT /api/v1/admin/store-closures/2026-09-12
```

请求无 body。路径日期按上海当地日期解释，仅允许今天或未来、且不能是当前每周固定店休日。

### 管理每周固定店休

- `GET /api/v1/admin/reservation-settings`：返回当前 `weekly_closed_weekday` 与更新时间。
- `PUT /api/v1/admin/reservation-settings/weekly-closed-day`：严格请求体 `{"weekly_closed_weekday":"tuesday"}`，仅 ADMIN+ 可用。
- 更换立即生效，并原子取消未来 30 天内命中新星期、尚未开始的 pending/confirmed 预约；响应返回旧/新星期、分状态取消数与 `is_replay`。同值重放不写审计、不重复取消。旧星期恢复可预约，单日店休和历史预约不改写。

首次成功 HTTP 201：

```json
{
  "code": 0,
  "message": "Store closure applied",
  "data": {
    "id": 301,
    "business_date": "2026-09-12",
    "is_closed": true,
    "created_at": "2026-09-06T02:00:00Z",
    "updated_at": "2026-09-06T02:00:00Z",
    "newly_cancelled_count": 3,
    "cancelled_pending_count": 2,
    "cancelled_confirmed_count": 1,
    "is_replay": false
  }
}
```

同一日期已经自定义关闭时返回 HTTP 200，三个计数均为 0，`is_replay=true`；不重复取消、不重复写店休审计。

首次关闭在同一事务中只取消该日 `scheduled_start_at > server_now` 且状态为 `pending/confirmed` 的预约，统一写 `cancelled/store_closed`。管理员提交成功后应展示计数，并通过预约列表/详情确认；N1 不承诺主动通知。

非法日期返回 `42255`：

```json
{
  "code": 42255,
  "message": "Store closure date is unavailable",
  "data": { "reason": "past_date" }
}
```

或 `data.reason=weekly_closed`。

### 6.3 恢复营业

```http
DELETE /api/v1/admin/store-closures/2026-09-12
```

请求无 body。成功 HTTP 200，返回同一 `StoreClosureMutationOut`，其中 `is_closed=false`、所有取消计数为 0、`is_replay=false`，message：

```text
Store reopened; previously cancelled reservations remain cancelled
```

恢复只改变未来创建是否可用，不复活任何历史预约。日期没有自定义店休、已经恢复或从未关闭时返回：

```json
{
  "code": 40452,
  "message": "Store closure not found",
  "data": null
}
```

过去日期和周一仍先返回 `42255`，不进入恢复查询。

## 7. Reservation 业务错误码

| code | HTTP | message | data |
|------|------|---------|------|
| `40451` | 404 | `Reservation not found` | null |
| `40452` | 404 | `Store closure not found` | null |
| `40951` | 409 | `Reservation status does not allow this operation` | `operation`, `current_status`, `allowed_statuses[]` |
| `40952` | 409 | `Reservation cancellation window is closed` | null |
| `40953` | 409 | `Reservation operation is no longer available` | null |
| `42251` | 422 | `Reservation product is unavailable` | `product_id` |
| `42252` | 422 | `Reservation experience option is unavailable` | `experience_option_id` |
| `42253` | 422 | `Reservation schedule is unavailable` | `reason` |
| `42254` | 422 | `A current phone number is required to create a reservation` | null |
| `42255` | 422 | `Store closure date is unavailable` | `reason` |

`40951.data.operation` 只会是 `confirm`、`reject` 或 `cancel`。`allowed_statuses` 是允许状态 value 列表。

`42253.data.reason`：

| reason | 含义 |
|--------|------|
| `minimum_lead_time` | 开始时间早于服务端当前时间加 3 小时 |
| `outside_booking_window` | 日期早于上海当地今天或晚于第 30 日 |
| `invalid_slot_increment` | 不是半小时开始粒度 |
| `outside_business_hours` | 开始早于 11:00、结束晚于 20:00 或跨日 |
| `weekly_closed` | 命中当前配置的每周固定店休日（首次部署默认周一） |
| `store_closed` | 管理员已将日期设为自定义店休 |
| `option_day_type_mismatch` | Option 工作日/节假日类型与日期不匹配 |

`42255.data.reason`：

| reason | 含义 |
|--------|------|
| `past_date` | 目标日期早于上海当地今天 |
| `weekly_closed` | 命中当前配置的每周固定店休日，不能再作为单日店休设置或恢复 |

请求 Schema、Path 或 Query 形状错误使用通用 HTTP 422 / code `422`，`data.errors` 遵循项目统一格式。

## 8. 客户端状态收敛

Reservation 的 mutation 除店休 PUT replay 外都不提供幂等重放成功语义。客户端必须区分：

- 明确 4xx 业务拒绝：进入 failed，按 code 展示或重取权威状态；
- network / timeout / cancel / 5xx / 成功响应形状损坏：进入 unknown；
- unknown 后先查询预约详情、预约列表或店休日列表，不自动重复写请求；
- `40951` / `40953` 后重新 GET 详情，处理顾客与门店并发状态变化；
- 店休 PUT 未收到结果时，可先 GET `/admin/store-closures` 核对；若仍需用户确认重试，重复 PUT 会安全返回 200 replay；
- 店休 DELETE 未收到结果时先 GET，不能盲目重复 DELETE，因为成功后的第二次会稳定返回 `40452`。

前端必须使用后端 `customer_message` 展示拒绝和店休说明；N1 不得显示“微信消息已发送”或其他未实现通知结果。

## 9. 发布状态

仓库已完成 M5 离线迁移与 N1 后端实现。2026-09-06 的一次性 MySQL 8.0.46 验证真实执行 Aerich 0→5，并通过 Reservation `7` 项并发、回滚、1205/1213 与 EXPLAIN 专项；与 Inventory 联合门槛共 `16 passed`。该次隔离结果在当时不代表任何持久环境已应用 M5；2026-09-08 的后续受控执行已将 M5/M7 应用到当前持久 Gate A M7。共享、预发布和生产数据库不因此自动迁移，运行时是否可用仍必须同时以各目标环境迁移版本、OpenAPI、客户端验收和发布记录为准；开发 SQLite 的 `generate_schemas` 不能作为持久迁移证据。
