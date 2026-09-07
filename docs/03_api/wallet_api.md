# Wallet / Payment / Refund API

> **API Version:** v1.0
>
> **Status:** Implemented in repository；M4 not applied to persistent databases；WeChat Provider disabled
>
> **Last Updated:** 2026-09-07

---

## 1. 通用约定

- Base URL：`/api/v1`
- 所有端点都要求 Bearer access token。
- 钱包只对普通 `USER` 存在；所有用户侧 wallet/payment 端点统一经过共享 customer 依赖，先校验当前 User 仍为 `status=normal` 且 access token 的 `auth_version` 匹配，再强制 `role=user`；ADMIN/SUPER_ADMIN 调用返回 403。ADMIN/SUPER_ADMIN 的钱包账户查询和资金写入只针对普通客户。管理端订单资金只读查询沿用既有订单权限，可读取任意管理端可见订单。
- disabled USER 不能主动充值或消费；ADMIN+ 仍可为 disabled 普通客户做人工余额纠错和法定义务退款，但代客钱包订单属于消费并拒绝 disabled 目标。deleted USER 禁止新的资金写入。
- 账号注销还会检查尚可全额退款的钱包结算敞口；即使余额为 `0.00`，未成功退款的 PAID 钱包结算或完成未满 30 天的 COMPLETED 钱包结算仍返回 `1015` 并保持钱包 active。
- 所有金额响应为固定两位小数字符串，例如 `"100.00"`。
- 资金写请求中的金额也必须是固定两位小数字符串；不接受 JSON number。
- 分页默认 `page=1&page_size=20`，`page_size` 范围 `1..100`。
- 需要幂等的写接口必须带 `Idempotency-Key`：trim 后 1–128 个可打印 ASCII 字符。四类持久资金 key（RechargeOrder、Payment、Refund、WalletTransaction）在 MySQL 均使用 ASCII / `ascii_bin`，按大小写敏感的逐字节语义比较；`Key-A` 与 `key-a` 不相同。
- 首次资金写成功为 HTTP 201；完全一致的幂等重放为 HTTP 200。
- 小程序必须冻结本次资金请求及其 key；network/timeout/HTTP 5xx 的结果未知态只能显式原样重放，不能读取修改后的表单并生成新 key。客户端收到成功响应后还要核对 URL 中的 Order/User、提交的变化量与规范化原因，以及代客订单的商品、Option、数量和备注。
- 用户取消与余额支付、管理端完成与退款属于互斥命令；客户端从确认弹窗开始同步加锁，任一请求处于提交中或结果未知时冻结另一命令，并以重新读取的 Order 与资金事实收敛状态。该 UI 门禁不替代服务端行锁、状态校验和唯一约束。
- 无请求体端点会拒绝任何 body，包括 `{}`。
- 响应使用项目统一信封；下文只展示 `data`。
- 一次性 MySQL 8.0.46 已完成 Wallet `9 passed` 与三域联合 `30 passed`，覆盖关键资金闭环、四个资金幂等列 `ascii_bin`、并发调账/余额支付/退款、真实 1205、1213 整事务重试、资金库存锁等待与关键 `EXPLAIN`；容器已清理且未触碰持久库。新的 Wallet-expanded workflow 尚待远端干净 SHA 复现。

## 2. 路由总览

| Method | Path | 能力 | 权限 | 当前状态 |
|--------|------|------|------|----------|
| GET | `/wallet` | 会员资料与钱包摘要 | USER | 可用；历史 NORMAL/DISABLED USER 需先 backfill，历史 DELETED 不补 |
| GET | `/wallet/transactions` | 我的钱包流水 | USER | 可用 |
| POST | `/wallet/recharges` | 创建微信充值意图 | USER | 固定 503、零写入 |
| GET | `/orders/{order_id}/financials` | 我的订单支付/退款事实 | owner USER | 可用 |
| POST | `/orders/{order_id}/payments/wallet` | 余额支付订单 | owner USER | 内部环境可演练；生产需开关 |
| POST | `/orders/{order_id}/payments/wechat` | 创建微信订单支付 | owner USER | 固定 503、零写入 |
| GET | `/admin/users/{user_id}/wallet` | 客户钱包摘要 | ADMIN+ | 仅普通 USER 目标 |
| GET | `/admin/users/{user_id}/wallet-transactions` | 客户钱包流水 | ADMIN+ | 仅普通 USER 目标 |
| POST | `/admin/users/{user_id}/wallet-adjustments` | 增减客户余额 | ADMIN+ | 内部环境可演练；生产需开关 |
| POST | `/admin/users/{user_id}/wallet-orders` | 按商品创建代客钱包订单并扣款 | ADMIN+ | 内部环境可演练；生产需管理写开关 |
| GET | `/admin/orders/{order_id}/financials` | 订单支付/退款事实 | ADMIN+ | 沿用管理端任意订单只读权限 |
| POST | `/admin/orders/{order_id}/refunds` | PAID/COMPLETED 全额退款 | ADMIN+ | 内部钱包/人工渠道；微信固定 503 |

## 3. 响应对象

### 3.1 WalletSummary

```json
{
  "wallet_id": 8,
  "user_id": 21,
  "balance": "200.00",
  "balance_limit": "1000.00",
  "status": "active",
  "capabilities": {
    "topup_enabled": false,
    "wallet_payment_enabled": true,
    "refund_enabled": true
  },
  "created_at": "2026-09-05T08:00:00Z",
  "updated_at": "2026-09-05T08:10:00Z"
}
```

`capabilities` 是当前服务端运行环境的能力提示，不能替代每次写接口的权限、状态和余额校验。

### 3.2 WalletTransaction

```json
{
  "id": 31,
  "transaction_type": "admin_adjustment",
  "direction": "income",
  "change_amount": "100.00",
  "before_balance": "100.00",
  "after_balance": "200.00",
  "source_type": "admin",
  "source_id": null,
  "source_order_no": null,
  "operator_id": 2,
  "operator_nickname": "店员",
  "reason": "线下充值",
  "created_at": "2026-09-05T08:10:00Z"
}
```

内部幂等键、手机号、Token、支付 Provider 凭据均不返回。

### 3.3 Payment / Refund

```json
{
  "order_id": 51,
  "order_status": {"value": "paid", "label": "已支付"},
  "payment": {
    "id": 61,
    "payment_no": "PY01K4ABCDE123456789ABCDEFG",
    "order_id": 51,
    "recharge_order_id": null,
    "purpose": "order",
    "method": "wallet",
    "amount": "88.00",
    "status": "succeeded",
    "created_at": "2026-09-05T08:20:00Z",
    "updated_at": "2026-09-05T08:20:00Z",
    "succeeded_at": "2026-09-05T08:20:00Z"
  },
  "refund": null
}
```

退款存在时 `refund` 为：

```json
{
  "id": 71,
  "refund_no": "RF01K4ABCDE123456789ABCDEFG",
  "order_id": 51,
  "method": "wallet",
  "amount": "88.00",
  "status": "succeeded",
  "reason": "客户协商退款",
  "operator_id": 2,
  "inventory_restored": true,
  "created_at": "2026-09-05T09:00:00Z",
  "updated_at": "2026-09-05T09:00:00Z",
  "succeeded_at": "2026-09-05T09:00:00Z"
}
```

以上对象不是宽松的 ORM 直出：Mapper 只投影白名单字段，Out Schema 要求 Payment/Refund 金额为正，Order 与 Recharge 用途各自只有一个对应关联，且 `status=succeeded` 时 `succeeded_at` 必须是 UTC 时间。`OrderFinancialOut` 进一步要求 Payment 与外层 `order_id` 一致、用途为 `order`、状态为 `succeeded`且订单为 `paid/completed`；Refund 存在时必须与该 Order/Payment 的渠道和全额一致。不一致数据不得作为成功响应输出。

## 4. 用户钱包

### 4.1 获取会员钱包

```http
GET /api/v1/wallet
Authorization: Bearer <access_token>
```

`data`：

```json
{
  "user": {
    "id": 21,
    "username": "member01",
    "nickname": "小粉",
    "phone": "13800000000",
    "avatar": null,
    "role": "user",
    "status": "normal",
    "last_login_at": null,
    "created_at": "2026-09-05T08:00:00Z",
    "updated_at": "2026-09-05T08:00:00Z"
  },
  "wallet": {"...": "WalletSummary"}
}
```

ADMIN/SUPER_ADMIN 调用返回 403；历史 NORMAL/DISABLED 普通 USER 尚未 backfill 时返回 `40441`。历史 DELETED USER 不属于 backfill 目标。

### 4.2 查询我的流水

```http
GET /api/v1/wallet/transactions?page=1&page_size=20
Authorization: Bearer <access_token>
```

返回统一 `Page[WalletTransaction]`，按 `created_at DESC, id DESC` 稳定排序。

### 4.3 创建充值意图

```http
POST /api/v1/wallet/recharges
Authorization: Bearer <access_token>
Idempotency-Key: recharge-20260905-001
Content-Type: application/json

{"amount":"100.00"}
```

金额必须位于闭区间 `1.00–1000.00`。当前真实 Provider 未接入，因此所有合法请求也返回：

```json
{
  "code": 503,
  "message": "Wallet top-up is not available until the supervised payment channel and WeChat merchant account are ready",
  "data": null
}
```

该 503 必须发生在任何数据库写入前；不创建充值单、Payment、钱包流水或 Audit。

## 5. 订单资金

### 5.1 获取我的订单资金事实

```http
GET /api/v1/orders/{order_id}/financials
Authorization: Bearer <access_token>
```

不存在和他人订单统一返回 `40411 OrderNotFound`。无成功结算时 `payment`、`refund` 均为 `null`。

### 5.2 使用余额支付

```http
POST /api/v1/orders/{order_id}/payments/wallet
Authorization: Bearer <access_token>
Idempotency-Key: wallet-pay-51-001
```

请求体：无；发送任意 body 返回 422。

仅允许订单 owner、普通 USER、正常账号、active Wallet 和 Pending Order。金额完全取自服务端订单总额。

首次 HTTP 201、重放 HTTP 200；`data`：

```json
{
  "order_id": 51,
  "order_no": "OD01K4ABCDE123456789ABCDEFG",
  "order_status": {"value": "paid", "label": "已支付"},
  "payment": {"...": "Payment"},
  "post_payment_balance": "112.00"
}
```

重放不会只比较 key：服务端还会复验 Order owner 与 PAID/COMPLETED 状态、成功 wallet Payment 的用户/订单/purpose/method/amount、空充值与 Provider 关联、Settlement 的订单/Payment/金额，以及扣款 WalletTransaction 的账户、类型、负向金额、余额算术、Order 来源、本人操作者和固定原因。任一缺失或矛盾返回资金冲突，不能把当前余额伪装为首次支付后的历史余额。

`WalletPaymentOut` 对成功响应再次验证：Order 必须为 `paid/completed`，Payment 必须关联外层 `order_id` 且为 `purpose=order/method=wallet/status=succeeded`；任一状态或关联字段矛盾都不会被序列化为 HTTP 成功结果。

### 5.3 创建微信订单支付

```http
POST /api/v1/orders/{order_id}/payments/wechat
Authorization: Bearer <access_token>
Idempotency-Key: wechat-pay-51-001
```

请求体：无。当前固定返回 HTTP 503 / code 503，且零数据库写入。客户端不得把微信收银台本地回调作为 Order Paid 的权威证据。

## 6. ADMIN+ 钱包管理

### 6.1 查询客户钱包

```http
GET /api/v1/admin/users/{user_id}/wallet
Authorization: Bearer <admin_access_token>
```

`data` 包含安全的 `UserListItem` 和 `WalletSummary`。目标不是普通 USER、目标是操作者本人或调用方非 ADMIN+ 时返回 403。

### 6.2 查询客户流水

```http
GET /api/v1/admin/users/{user_id}/wallet-transactions?page=1&page_size=20
Authorization: Bearer <admin_access_token>
```

返回 `Page[WalletTransaction]`，权限规则同上。

### 6.3 调整客户余额

```http
POST /api/v1/admin/users/{user_id}/wallet-adjustments
Authorization: Bearer <admin_access_token>
Idempotency-Key: adjust-user-21-001
Content-Type: application/json

{
  "change": "-20.00",
  "reason": "订单差额纠正"
}
```

- `change` 范围 `-1000.00–1000.00` 且不能为 `0.00`；调整后余额必须在 `0.00–1000.00`。
- 正向调账还必须满足 `调整后余额 + 尚可退款的钱包支付敞口 ≤ 1000.00`。敞口包括 PAID 钱包订单，以及完成未满 30 天的 COMPLETED 钱包订单；没有成功 Refund、Refund Pending 或 Failed 时继续占用，Refund succeeded 后释放。
- `reason` trim 后 1–256 字符。
- 首次 HTTP 201、完全一致重放 HTTP 200。重放必须同时核验既有流水的目标账户、`admin_adjustment` 类型、`admin` 来源、空 `source_id`、变化量、余额算术、操作者和规范化原因；任一事实矛盾均返回 `40943`。
- 返回 `{wallet, transaction}`；重放中的结果余额来自首次流水，不使用后来变化后的当前余额覆盖历史结果。
- disabled 普通客户允许通过该端点做人工余额纠错；deleted 客户禁止资金写入。reason 必须说明真实业务原因，不得把通用调账伪装成商品消费。

### 6.4 按商品创建代客钱包订单

```http
POST /api/v1/admin/users/{user_id}/wallet-orders
Authorization: Bearer <admin_access_token>
Idempotency-Key: assisted-order-user-21-001
Content-Type: application/json

{
  "items": [
    {
      "product_id": 8,
      "experience_option_id": null,
      "quantity": 2
    }
  ],
  "remark": "门店代客下单"
}
```

请求体复用 `OrderCreate`：1–10 个 Item，Experience 必须携带有效 Option，Kit 必须省略 `experience_option_id` 或传 `null`，每行数量 1–99，组合不得重复，remark 最长 500 字符。商品名称、配置、价格、小计、总额、支付金额、订单状态和客户角色均由服务端决定。

仅允许 ADMIN/SUPER_ADMIN 为状态正常的普通 USER 操作；管理员本人、ADMIN/SUPER_ADMIN 目标、disabled 或 deleted 目标均拒绝。该用例属于商品消费，与允许对 disabled 客户执行的人工余额纠错不是同一能力。

服务端在一个事务中创建真实 Order/OrderItem 权威快照、扣减 Kit 库存并写库存流水、扣减钱包并写 `order_payment` 流水、创建 succeeded wallet Payment 和唯一 Settlement、将订单直接置为 `paid`，再顺序写 `CREATE_ORDER` 与 `PAY_ORDER` 两条审计。余额不足、库存不足或任一步失败时全部回滚。

首次 HTTP 201，完全一致的幂等重放 HTTP 200；`data`：

```json
{
  "order": {
    "id": 52,
    "order_no": "OD01K4ABCDE123456789ABCDEFG",
    "user_id": 21,
    "user_nickname": "小粉",
    "total_amount": "50.00",
    "status": {"value": "paid", "label": "已支付"},
    "remark": "门店代客下单",
    "items": [
      {
        "id": 93,
        "product_id": 8,
        "experience_option_id": null,
        "product_name": "拼豆材料套装",
        "option_duration_minutes": null,
        "option_participants": null,
        "option_day_type": null,
        "product_price": "25.00",
        "quantity": 2,
        "subtotal": "50.00"
      }
    ],
    "created_at": "2026-09-05T08:30:00Z",
    "updated_at": "2026-09-05T08:30:00Z"
  },
  "payment": {"...": "Payment"},
  "post_payment_balance": "150.00"
}
```

幂等身份包含操作者、目标客户、Item 的顺序与内容和 remark；相同 key 绑定不同意图返回 `40943`。重放还会完整核验 Order owner/Items/remark/PAID、成功 wallet Payment 的用户/订单/purpose/method/amount/空充值与 Provider 关联、Settlement 的关联与金额，以及扣款 WalletTransaction 的账户、类型、金额、余额算术、来源、操作者和固定原因；任一事实矛盾都拒绝。合法重放返回首次历史扣款后的 `post_payment_balance`，不以当前钱包余额覆盖。该端点由 `WALLET_ADMIN_WRITE_ENABLED` 控制。

`AssistedWalletOrderOut` 会独立要求 Order 为 `paid`，Payment 关联该 Order、金额等于 `order.total_amount`，且为 `purpose=order/method=wallet/status=succeeded`；Mapper 或预加载事实出现交叉字段矛盾时不返回伪成功。

## 7. ADMIN+ 订单退款

### 7.1 查询订单资金事实

```http
GET /api/v1/admin/orders/{order_id}/financials
Authorization: Bearer <admin_access_token>
```

返回 `OrderFinancialOut`。该只读端点沿用管理端查看任意订单的既有权限，因此可以读取历史 staff order 的资金事实；这不赋予对 staff order 的资金写权限。退款 Service 仍只允许普通 USER 所属订单，ADMIN/SUPER_ADMIN 所属订单不能退款。

### 7.2 全额退款

```http
POST /api/v1/admin/orders/{order_id}/refunds
Authorization: Bearer <admin_access_token>
Idempotency-Key: refund-order-51-001
Content-Type: application/json

{"reason":"客户协商退款"}
```

规则：

- 订单必须是 `paid` 或 `completed`，且有金额一致的唯一成功 Settlement。
- Settlement 绑定的 Payment 必须同时满足：所属普通 USER 与 Order 一致、金额与 Order/Settlement 一致、`purpose=order`、`status=succeeded`、`recharge_order_id=null`；缺失或任一矛盾返回 `40443` 且零写入。
- Completed 必须在完成后 30 天内。
- 金额固定为 Settlement 全额，不接受 amount 字段。
- 每个 Order/Settlement 最多一次退款。
- PAID Kit/混合订单恢复 Kit；COMPLETED 不恢复；Experience 不操作库存。
- 钱包渠道原子退回钱包；人工渠道登记线下退款完成；微信渠道当前 503 且零写入。
- 首次 HTTP 201、完全一致重放 HTTP 200；`data` 为 `status=succeeded` 且带 UTC `succeeded_at` 的 Refund，金额必须为正并关联该 Order。退款重放会重新核验 Settlement、成功 Payment、Refund 的订单/用户/金额、purpose、method、状态/成功时间、空充值关联、Provider reference、操作者和规范化原因；钱包退款还核验入账 WalletTransaction 的账户、正向金额、余额算术、Refund 来源、操作者和固定原因。任一缺失或矛盾都拒绝重放。

## 8. 错误契约

| code | HTTP | 类型 | 说明 |
|------|------|------|------|
| `40441` | 404 | `WalletNotFound` | 钱包不存在或不可见，常见于历史 NORMAL/DISABLED USER 尚未 backfill |
| `40442` | 404 | `RechargeOrderNotFound` | 充值单不存在或不可见 |
| `40443` | 404 | `PaymentNotFound` | 支付/成功结算不存在或不可见 |
| `40444` | 404 | `RefundNotFound` | 退款不存在 |
| `40941` | 409 | `WalletBalanceExceeded` | 变化后余额超出 `0.00–1000.00` |
| `40942` | 409 | `InsufficientWalletBalance` | 钱包余额不足；不返回当前余额 |
| `40943` | 409 | `WalletTransactionConflict` | 幂等键绑定到不同资金意图 |
| `40944` | 409 | `PaymentStatusConflict` | Payment 状态不允许操作或重放事实不完整 |
| `40945` | 409 | `PaymentSettlementConflict` | Order/Payment 已有冲突结算 |
| `40946` | 409 | `RefundStatusConflict` | 订单/Refund 状态不允许退款或已有退款 |
| `40947` | 409 | `WalletRefundCapacityExceeded` | 正向入账会侵占尚可全额退款的钱包支付预留空间 |
| `40948` | 409 | `RefundWindowExpired` | Completed 订单超过 30 天退款窗口 |
| `42241` | 422 | `RechargeAmountOutOfRange` | 充值额超出 `1.00–1000.00` |
| `503` | 503 | `ServiceUnavailableException` | 能力开关关闭或微信 Provider 未接入 |

请求体、Header、Path 或 Query 的形状错误使用全局 HTTP 422 / code `422`。账号状态继续复用 `1005 UserDisabled`、`1009 UserDeleted`；订单资源和状态错误继续复用 `40411`、`40921`；库存创建/恢复错误继续复用 `40931`、`40932`、`40933`。

`40947` 的 `data` 固定返回两位小数字符串 `requested_balance`、`refundable_exposure` 和 `maximum`，用于说明余额本身虽未越界，但继续正向入账将无法保证后续全额原路退款。客户端不得通过拆分请求规避；未来真实充值成功入账也必须复用相同校验。

## 9. 503 零写入边界

以下请求当前必须在任何数据库写入之前稳定失败。微信退款需要先只读定位并锁定订单的 Payment method，允许进入只读事务，但不得创建或修改任何业务事实：

- `POST /wallet/recharges`
- `POST /orders/{order_id}/payments/wechat`
- 对 `method=wechat` 的退款
- production 中未开启对应钱包写 Feature Flag 的 ADMIN 调账、ADMIN 代客钱包订单、余额支付或退款

测试必须断言 WalletAccount 余额、RechargeOrder、Payment、Settlement、Refund、WalletTransaction、InventoryTransaction 和 AuditLog 均无变化。

## 10. 历史资金运维命令

M4 不为历史账号直接生成钱包，也不猜测历史订单的结算渠道。应用 M4 后、启用钱包能力前按受控发布流程执行：

```bash
python -m app.tasks.wallet_account_backfill
# 记录预览摘要中的 through_user_id=N，以下两步复用同一个 N：
python -m app.tasks.wallet_account_backfill --through-user-id N --apply
python -m app.tasks.wallet_account_backfill --through-user-id N
python -m app.tasks.legacy_manual_settlement_backfill
# 记录预览摘要中的 through_order_id=N，以下两步复用同一个 N：
python -m app.tasks.legacy_manual_settlement_backfill --through-order-id N --apply
python -m app.tasks.legacy_manual_settlement_backfill --through-order-id N
python -m app.tasks.wallet_reconcile
```

- legacy manual settlement backfill 仅扫描固定 Order ID 上界内的 PAID/COMPLETED，并只为仍归属普通 `USER`、恰好一条 `MARK_ORDER_PAID` Audit 的订单新增事实；disabled owner 允许补录停写前已经发生的历史收款，deleted owner 不得新增。它以 `payment:legacy-manual:order:{order_id}` 内部幂等身份原子创建 `manual/succeeded` Payment 与唯一同额 Settlement，并把 Audit 时间保存为 `succeeded_at`。`--apply` 必须显式复用预览上界；apply 前全量预检有 blocker 时全局零写入，写入批次按 User→Order 锁序执行，锁后复验若出现新 blocker 则当前批零写入并立即停止。deleted owner 已有完整一致事实可零写入计为 replay；非客户 owner、deleted owner 缺失事实、缺/重复 Audit、部分或矛盾 Payment/Settlement 都逐单报告 blocker，最终退出非零。
- wallet backfill 默认只预览，并输出本次冻结上界 `through_user_id`；apply 必须显式传入预览得到的 `--through-user-id N`，缺少时不连库直接拒绝。每个写批次在独立事务内按 User ID 升序锁定候选 User，锁后复验 `role=user` 且 `status=normal/disabled`，再重新检查钱包存在性，只为仍合格且仍缺失者创建 `0.00` WalletAccount。DELETED/staff 或已有钱包者跳过，且不生成零元流水。apply 后必须以同一 `through_user_id` 复查 `would_create=0`。
- reconcile 全程只读：按钱包 ID 及流水 `created_at ASC, id ASC` 稳定扫描，除核对 WalletAccount.balance 与 WalletTransaction 净额外，还检查非零变化、单行余额算术与范围、相邻余额链、末条余额，以及无流水钱包只能为 `0.00`。摘要要求 `mismatches=0 violations=0`；任一违规都退出非零，绝不自动改账、删除坏流水或补造流水。
- 这些命令都不是 Web API，也不替代迁移授权、备份、停写窗口、执行后 SQL 核验和真实 MySQL 发布门槛。应用模式必须分别复用预览输出的 `through_user_id` 与 `through_order_id`，且不得与新旧应用的 User/Order/Payment 写并行。

## 11. 发布验证状态

2026-09-07 已在一次性 MySQL 8.0.46 完成 Wallet 专项 `9 passed` 和 Inventory + Reservation + Wallet 联合 `30 passed`，覆盖并发调账、余额支付、退款、真实 1205、模拟 1213 整事务重试、Wallet/Inventory 行锁等待及关键资金查询 `EXPLAIN`。CI 候选已把 `tests/wallet/mysql` 接入统一 `backend-mysql-release` Job；在新的干净 SHA 远端复现前，本结果只属于本地候选证据。API 请求/响应、错误码与数据模型没有因该门槛发生变化；M4、两个历史 backfill、reconcile 和生产资金开关仍未应用任何持久环境。
