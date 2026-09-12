# 会员钱包、支付与退款模块（Wallet / Payment / Refund）

> **Contract Version:** v1.0
>
> **Status:** Repository implementation and Gate A M4/backfill/reconcile complete；WeChat Provider disabled；other persistent environments pending
>
> **Last Updated:** 2026-09-09

---

## 1. 目标与当前边界

本模块为 pinkdooHub 自营商品和体验服务提供封闭式会员钱包、余额支付、ADMIN+ 调账、支付结算事实与全额退款。钱包不是通用支付账户：余额不可转账、不可提现、不可兑换现金，也不能购买第三方商品或服务。

当前仓库已经实现 Wallet、Payment、PaymentSettlement、RechargeOrder 和 Refund 的领域、Model、Repository、Service、Mapper、FastAPI 路由及离线 MySQL 迁移 M4。2026-09-07 已在一次性 `mysql:8.0.46` 容器完成 Wallet 专项 `9 passed` 与 Inventory + Reservation + Wallet 联合 `30 passed`，覆盖关键资金/库存闭环、四个资金幂等列的 `ascii_bin`、并发调账/余额支付/退款、真实 1205、1213 整事务回滚重试、可观测资金库存锁等待和关键 `EXPLAIN`；该次隔离门槛本身未触碰持久库。后续 Wallet-expanded workflow 已远端通过，持久 Gate A 又于 2026-09-08 受控应用 M4、完成两个历史 backfill 与只读 reconcile。该事实不表示本地持久 `db.sqlite3` 已按 Aerich 应用 M4，也不自动迁移共享、预发布或生产数据库；真实资金 Provider 和生产开关仍须单独授权。

真实微信支付当前明确关闭。商户号、小程序 AppID 关联、HTTPS 通知域名、商户证书、API v3 Key、商户私钥以及经营主体进件资料均不写入仓库；正式接入时再通过受控 Secret 和发布记录填写真实值。在此之前，充值和微信订单支付/退款稳定返回 HTTP 503，且不得创建 RechargeOrder、Payment、Refund、流水或审计等任何数据库记录。

HTTP 契约见 [Wallet API](../03_api/wallet_api.md)，表结构见 [Database Design](../02_database/database_design.md)，订单主状态见 [Order Module](order_module.md)。

## 2. 角色与能力

| 角色 | 能力 |
|------|------|
| `USER` | 拥有一个钱包；查看自己的会员资料、余额和流水；用余额支付自己的 Pending 订单；查看自己的支付/退款事实 |
| `ADMIN` | 不创建钱包；仅可查询、调账、代客钱包下单和退款普通 `USER` 客户 |
| `SUPER_ADMIN` | 不创建钱包；与 `ADMIN` 相同，仅可操作普通 `USER` 客户 |

权限规则：

- 新注册/首次微信登录的 `role=user` 普通客户创建 WalletAccount；历史 backfill 只补 `status=normal/disabled` 的普通 USER。历史 `deleted` USER 不新建钱包；ADMIN、SUPER_ADMIN 始终不创建钱包。
- ADMIN/SUPER_ADMIN 均使用现有 ADMIN+ 认证边界，但 Service 必须再次确认目标用户是普通 `USER`。
- 用户侧 `/wallet`、`/wallet/transactions`、`/wallet/recharges` 以及 owner 范围的订单资金查询/支付端点统一经过共享 customer 认证依赖；它先校验当前 User 仍为 `status=normal` 且 access token 的 `auth_version` 匹配，再额外强制 `role=user`。ADMIN/SUPER_ADMIN 即使拥有历史订单也不能调用这些客户端入口。
- 管理员不得以目标用户身份给自己调账、代客下单或退款，也不得操作 ADMIN/SUPER_ADMIN 钱包。
- 管理端 `/admin/orders/{order_id}/financials` 是既有订单管理权限下的只读例外，可读取任意管理端可见订单的资金事实；所有调账、代客扣款和退款写入仍只能以普通 `USER` 为目标。
- disabled 用户不能主动充值或消费，且既有认证边界会阻断其用户侧访问；ADMIN+ 仍可为该普通客户执行人工余额纠错和法定义务退款。管理员代客钱包订单属于消费，因此必须拒绝 disabled 目标。
- deleted 用户是终态，禁止一切新的资金写入；已存在的钱包、资金、支付、退款、订单与审计事实继续保留。

## 3. 金额规则

所有金额使用 `Decimal` / `DECIMAL(10,2)`；资金写请求只接受固定两位小数字符串，不接受 JSON number、科学计数法、NaN、Infinity 或三位以上小数。

| 规则 | 冻结值 | 边界 |
|------|--------|------|
| 单笔充值 | `1.00–1000.00` 元 | 两端包含 |
| 钱包余额 | `0.00–1000.00` 元 | 两端包含 |
| 单次 ADMIN 调整变化量 | `-1000.00–1000.00` 元且不得为零 | 调整后仍须位于余额闭区间 |

余额支付金额来自服务端 Order.total_amount，客户端不能提交支付金额。全额退款金额来自成功 PaymentSettlement.amount，客户端不能提交退款金额。

钱包必须为尚可原路全额退款的 wallet Payment 预留空间。预留敞口包括所有未成功退款的 PAID 钱包订单，以及完成未满 30 天且未成功退款的 COMPLETED 钱包订单；Pending/Failed Refund 仍占用敞口，成功退款释放对应敞口。任何 ADMIN 正向调账必须同时满足：

```text
调整后余额 + 尚可退款的钱包支付敞口 ≤ 1000.00
```

余额本身超界返回 `40941`；余额合法但侵占退款预留空间返回 `40947`。钱包退款按 Settlement 全额入账，因此在上述不变量成立时不会突破余额硬上限。未来真实充值成功入账也必须在锁内复用同一预留校验，不允许通过充值挤占法定义务退款空间。超限请求整体失败，不允许截断、拆分或产生部分流水。

## 4. 钱包与不可变流水

采用“权威余额 + 不可变流水”模型：

```text
WalletAccount.balance = 当前权威余额
WalletTransaction     = 每一次已提交余额变化的不可变历史
```

- 余额与对应流水必须使用同一数据库连接、同一事务提交。
- 流水必须满足 `after_balance = before_balance + change_amount` 且 `change_amount != 0.00`。
- 同一钱包的流水按 `created_at ASC, id ASC` 形成确定顺序；相邻记录必须满足前一条 `after_balance =` 后一条 `before_balance`，末条 `after_balance` 必须等于 WalletAccount 权威余额。没有流水是合法的零余额初始状态，但此时权威余额必须为 `0.00`。
- 已提交流水没有更新/删除业务入口；纠错通过新的反向 ADMIN 调整。
- 内部幂等键永不通过 API 或日志返回。
- 当前类型为 `recharge`、`order_payment`、`admin_adjustment`、`refund`；真实充值成功路径尚未开放。
- 来源类型为 `recharge_order`、`order`、`admin`、`refund`。通用 `source_id` 不建多态外键。

## 5. 用户创建、历史 backfill 与注销

- 密码注册必须在一个事务内创建 `User + WalletAccount(0.00) + REGISTER Audit`。
- 首次微信登录必须在一个事务内创建 `User + WalletAccount(0.00) + ExternalIdentity + Audit`。
- 运行时合成数据只为 `USER` 创建钱包；SUPER_ADMIN Bootstrap 和 ADMIN/SUPER_ADMIN 合成账号不创建钱包。
- M4 不在迁移 SQL 中批量伪造 Wallet、零元期初流水或历史 Payment/Settlement。历史 `status=normal/disabled` 普通 USER 必须在停写/受控窗口通过可续跑 backfill 创建且仅创建一个 `0.00` 钱包；历史 `deleted` USER 可没有钱包且不得补建。启用任一钱包能力前，`users(role=user,status IN normal/disabled) LEFT JOIN wallet_accounts` 缺失数必须为零，ADMIN/SUPER_ADMIN 钱包数必须为零。
- `python -m app.tasks.wallet_account_backfill` 默认只预览，摘要同时输出冻结扫描范围的 `through_user_id=N`。写入时必须显式复用该上界：`python -m app.tasks.wallet_account_backfill --through-user-id N --apply`；缺少上界时在连接数据库前拒绝。每批在独立事务内按 User ID 升序锁定候选 User，锁后复验仍为 `role=user` 且 `status=normal/disabled`，然后重新检查钱包是否已存在并仅为仍缺失者创建 `0.00` WalletAccount；锁前候选已变为 DELETED/staff 或已有钱包时跳过。命令不创建零元 WalletTransaction，apply 后应对同一 `through_user_id` 再做 preview 并确认 `would_create=0`。
- M4 前已经处于 PAID/COMPLETED 的订单没有 PaymentSettlement，必须先运行 `python -m app.tasks.legacy_manual_settlement_backfill` 预览，再以相同 `through_order_id` 显式 `--apply`；apply 缺少该上界会直接拒绝。命令只为仍归属普通 `USER` 且恰好一条 `MARK_ORDER_PAID` Audit 的订单新增事实；disabled owner 可补录停写前已经发生的历史人工收款，但不能发起新的消费，deleted owner 不得新增事实。命令按该 Audit 时间重建 `method=manual/status=succeeded` 的 Payment 与同额 Settlement；deleted owner 已有完整一致事实可零写入计为 replay，非客户 owner、deleted owner 缺失事实、缺失/重复 Audit、部分或矛盾资金事实全部报告为 blocker 并以非零状态退出，不猜测支付渠道或静默修复。apply 会先对固定范围执行全量只读预检，存在 blocker 时全局零写入；分批按 User→Order 锁序复验若出现新 blocker，则当前批零写入并立即停止，先前已提交批次可安全重放。
- `python -m app.tasks.wallet_reconcile` 在 wallet 与 legacy settlement 两类 backfill 均收敛后执行。任务全程只读：钱包按 ID、流水按 `created_at ASC, id ASC` 稳定扫描；除比较每个钱包的权威余额与流水净额外，还检查每条流水变化量非零、`after = before + change`、前后余额均在 `0.00..1000.00`、相邻流水余额链连续，以及末条 `after_balance` 等于权威余额；无流水钱包的权威余额必须为 `0.00`。`mismatches` 统计至少一项违规的钱包数，`violations` 统计可重叠的具体规则命中数，同一钱包始终只计一个 mismatch；例如非零余额且无流水会同时命中净额与无流水规则。日志只报告内部钱包、用户、必要的流水 ID 和固定检查代码，不输出金额、reason、幂等键、来源/订单或人员展示字段。任一差异都以非零退出码失败，绝不自动改余额、删除坏流水或补造流水。

普通用户注销除原有 Pending/Paid 订单检查外，还必须在 User 行锁内确认：

- 不存在 Pending Payment、Pending RechargeOrder 或 Pending Refund；
- 不存在尚可全额退款的钱包支付敞口；即使当前余额为 `0.00`，任何未成功退款的 PAID 钱包结算或完成未满 30 天的 COMPLETED 钱包结算仍必须阻断注销；
- 钱包余额为 `0.00`；
- 钱包存在时随注销改为 `closed`，但 Wallet、Payment、Refund 和流水历史不物理删除。

注销事务的数据库 commit 是权威成功点：User 匿名化、`status=deleted`、`auth_version` 递增、外部身份删除、钱包关闭与 `DELETE_ACCOUNT` Audit 在同一事务提交后，Redis refresh-family 清理只是提交后的 best-effort 纵深撤销。清理失败不得将已提交的注销返回为失败；API 仍返回成功，`status/auth_version` 会阻断后续 access/refresh 会话。系统必须记录不含 Token/JTI 的高优先级安全事件，运维据此按内部 User ID 重试 family 清理。

## 6. ADMIN+ 调账

ADMIN/SUPER_ADMIN 可以对普通客户钱包增加或减少余额，必须提交 `change + reason + Idempotency-Key`。

事务顺序为：

```text
锁 target User
→ 校验目标角色
→ 锁 WalletAccount
→ 检查幂等身份
→ 校验余额闭区间与正向入账后的退款预留敞口
→ 更新余额并写 WalletTransaction
→ 写 ADJUST_WALLET Audit
→ 使用同一连接重载响应
```

同 key、同操作者、同目标钱包、同变化量和同规范化原因返回首次结果，不重复改余额；同 key 绑定不同意图返回冲突。调账重放还必须核验既有 WalletTransaction 的目标账户、`admin_adjustment` 类型、`admin` 来源、空 `source_id`、变化量、`before + change = after` 算术、操作者和规范化原因；任一事实缺失或矛盾都拒绝重放，不能用当前钱包余额拼装一次看似成功的历史结果。首次成功 HTTP 201，完全一致重放 HTTP 200。

负向调账只检查余额下界；正向调账还必须在相同 User/Wallet 锁与事务连接内汇总尚可退款的钱包 PaymentSettlement 敞口，并保持“调整后余额 + 敞口 ≤ 1000.00”。已成功退款的结算不再占用敞口，退款入账与释放敞口由同一退款事务提交。

通用调账只用于资金纠错或受控线下充值，不得通过 reason 文本伪造商品消费事实。针对特定商品扣款必须使用管理端代客钱包订单用例，由真实 Order、OrderItem 快照、Kit 库存流水、钱包流水、Payment、Settlement 和审计共同形成闭环。

## 7. ADMIN+ 代客钱包订单

ADMIN/SUPER_ADMIN 可以为状态正常的普通 USER 创建商品订单并直接使用该客户钱包付款。请求复用普通 `OrderCreate` 的 1–10 个 Item、Experience Option、Kit null Option、数量、重复组合和 remark 规则，并额外要求 `Idempotency-Key`。客户端仍不能提交用户 ID 以外的归属字段、价格、总额、支付金额或最终状态。

该用例使用一个数据库事务：

```text
锁 target User 并重检 role/status
→ 创建真实 Order 并取得 ID
→ 锁 WalletAccount 并检查 active/余额
→ 按 Product ID 升序锁定并扣减全部 Kit
→ 写 OrderItem 权威快照
→ 创建 succeeded wallet Payment
→ 扣减 WalletAccount 并写 order_payment WalletTransaction
→ 创建唯一 PaymentSettlement
→ 将 Order 直接保存为 paid
→ 顺序写 CREATE_ORDER、PAY_ORDER 两条 Audit
→ 使用同一连接重载响应
```

任一 Product/Option/Kit 不可用、库存不足、钱包余额不足、目标 disabled/deleted、唯一事实冲突、流水或 Audit 失败，都必须让订单、快照、库存、钱包、Payment、Settlement 与审计全部回滚。代客订单属于消费，因此 disabled 目标不能通过该入口扣款；这不影响 ADMIN+ 对 disabled 普通客户执行余额纠错或法定义务退款。

同 key、同操作者、同目标客户、同 Item 顺序和内容、同 remark 返回首次已提交的 Order/Payment 与首次历史扣款后余额；同 key 绑定不同意图返回冲突。重放时还必须完整核验 Order owner/Items/remark/PAID、Payment 的用户/订单/用途/钱包渠道/成功状态/金额/空充值与 Provider 关联、Settlement 的订单/Payment/金额，以及扣款 WalletTransaction 的账户、类型、金额、余额算术、来源、操作者和固定原因；任一矛盾都拒绝重放。首次成功 HTTP 201，完全一致重放 HTTP 200。该能力由 `WALLET_ADMIN_WRITE_ENABLED` 控制。

## 8. 订单支付与结算

余额支付只允许订单所属普通用户操作自己的 Pending 订单。一个成功订单结算由 `PaymentSettlement.order_id UNIQUE` 保证；不能仅依赖 Order.status 防止双扣。

事务锁序与写入顺序为：

```text
User
→ Order
→ Payment / PaymentSettlement 幂等与唯一事实
→ WalletAccount
→ Payment succeeded
→ WalletTransaction(order_payment)
→ PaymentSettlement
→ Order pending → paid
→ PAY_ORDER Audit
```

余额不足、订单状态冲突、结算冲突、流水失败或 Audit 失败都必须整体回滚。相同 key 重放必须复验 Order 归属与 PAID/COMPLETED 状态、成功 wallet Payment 的用户/订单/用途/金额/空充值与 Provider 关联、Settlement 的订单/Payment/金额，以及 `order_payment` WalletTransaction 的账户、金额、余额算术、来源、本人操作者和固定原因；任一事实缺失或矛盾都拒绝。合法重放返回首次资金流水的历史 `after_balance`，不能把之后变化过的当前余额伪装成首次结果。

现有 ADMIN+ 人工 `pending → paid` 路径在 M4 后先只读定位订单 owner，再按 `User → Order` 锁序锁定并复验；只有状态正常的普通 USER 订单可以同时写入 `method=manual` 的成功 Payment 和唯一 PaymentSettlement。staff、disabled 或 deleted owner 均拒绝，Order/Payment/Settlement/Audit 零写入。该路径只表示受控线下付款登记，不是微信支付。

## 9. 全额退款

退款与 Order 主状态分离。订单仍保持现有状态机：

```text
pending → paid → completed
   └──→ cancelled
```

Refund 使用独立 `pending / succeeded / failed` 状态。退款成功不把 Paid/Completed 改成 Cancelled，也不回退 Completed。

v1 规则：

- 仅 ADMIN/SUPER_ADMIN 可对普通客户发起退款；reason 与 Idempotency-Key 必填。
- 只允许有唯一成功 PaymentSettlement 的 `PAID` 或 `COMPLETED` 订单。
- 退款前必须锁定并验证 Settlement 关联的 Payment：`user_id`、`order_id`、`amount` 与订单/结算一致，`purpose=order`、`status=succeeded` 且 `recharge_order_id=null`；任何矛盾都拒绝且零写入。
- 每个 Order/Settlement 最多一条 Refund，金额固定为结算金额，即一次全额退款；不支持部分退款。
- Completed 订单退款窗口为完成后 30 天；以 Order.updated_at 的 UTC 时间判断。
- 钱包支付：Refund、钱包入账、WalletTransaction、退款预留敞口释放、可选库存恢复与 Audit 同事务成功。
- 人工付款：ADMIN 调用成功即登记线下全额退款已完成，不写钱包流水；真实线下资金动作及凭据由运营流程负责。
- 微信付款：当前返回 HTTP 503 且零写入；正式接入后必须在数据库事务外调用 Provider，再以可信通知/查单收敛状态。

退款重放必须重新核验 Settlement、成功 Payment 与 Refund 的完整关系和业务意图，包括订单/用户/金额、order purpose、支付渠道、空充值关联、成功时间、操作者、规范化原因和 Provider reference；钱包退款还必须核验 `refund` WalletTransaction 的账户、正向金额、余额算术、来源、操作者和固定原因。任一事实缺失、状态不完整或跨字段矛盾都拒绝重放，不得仅凭相同 key 返回成功。

库存规则：

- `PAID` Kit/混合订单退款：按 OrderItem 数量快照恢复全部 Kit，写 `order_refund_restore` 流水；多 Kit 按 Product ID 升序锁定。
- `PAID` 纯 Experience：不操作库存。
- `COMPLETED` 订单退款：无论 Kit 或 Experience 均不恢复库存。
- 退款库存恢复与资金退款必须原子提交；库存恢复越界时整笔退款失败，不允许只退款不记库存结果。

## 10. 幂等、重试与锁序

ADMIN 调账、ADMIN 代客钱包订单、余额支付、充值创建、微信支付创建和退款均要求 `Idempotency-Key`。客户端键去除首尾空白后必须为 1–128 个可打印 ASCII 字符；服务端加业务命名空间后持久化，数据库 UNIQUE 是并发最终兜底。`RechargeOrder.idempotency_key`、`Payment.idempotency_key`、`Refund.idempotency_key` 与 `WalletTransaction.idempotency_key` 在 MySQL 必须使用 ASCII 字符集和 `ascii_bin` 排序规则，按大小写敏感的逐字节语义比较；例如 `Key-A` 与 `key-a` 是两个不同的合法 key，不能依赖实例默认 collation。

- 同 key + 同完整业务意图：返回首次已提交结果。
- 同 key + 不同目标、金额、原因、操作者或业务类型：HTTP 409。
- 事务回滚不消耗 key。
- 并发唯一冲突必须退出失败事务后再读取已提交事实。
- 仅 MySQL 1205/1213 可对整个无外部网络副作用用例使用全新事务有限重试，最多 3 次。

资金响应在 Mapper 显式投影后还必须通过严格 Out Schema：Payment/Refund 金额必须为正，`purpose=order/recharge` 必须分别且仅关联 Order/RechargeOrder，`succeeded` 事实必须有 UTC `succeeded_at`；Order 资金详情中 Payment 必须与外层 Order 一致且已成功，Refund 必须与该 Order/Payment 的渠道和全额一致。余额支付成功响应还必须是同一 Order 的 `order/wallet/succeeded` Payment 且 Order 为 PAID/COMPLETED；代客钱包订单响应必须是 PAID Order，Payment 与该 Order 及其 `total_amount` 完全一致。任一交叉字段矛盾均视为服务端契约违反，不序列化为成功响应。

小程序资金客户端还必须把成功响应绑定到本次请求的 URL 资源和完整业务意图：人工调账核对目标用户、变化量和规范化原因，退款核对订单和原因，代客钱包订单核对目标用户、商品、Experience Option、数量和规范化备注。结果未知时保留原请求快照和原 `Idempotency-Key`，不得根据已经编辑的新表单生成第二笔资金命令。用户订单的取消/支付、管理订单的完成/退款必须共享同步互斥门禁；任一结果未知时先同时重读 Order 与资金事实，权威状态尚未收敛前不得开放另一命令。

跨域写统一遵循：

```text
User → Order/RechargeOrder → Payment/Settlement/Refund → WalletAccount → ProductKit（Product ID 升序）
```

外部 Provider 调用不得发生在持有数据库事务或行锁期间。

2026-09-07 的扩展 MySQL 候选门槛已在一次性 MySQL 8.0.46 上验证上述约束：Wallet 专项 9 项、Inventory + Reservation + Wallet 联合 30 项通过。覆盖并发调账/余额支付/退款、真实 1205、首轮已写后的 1213 整事务回滚重试、Wallet/Inventory 可观测行锁等待，以及钱包 owner/幂等/分页和 Payment 幂等/用户分页的 `EXPLAIN` 索引命中。该次结果只证明当时的隔离仓库候选且本身未写持久库；后续 workflow 已远端通过，持久 Gate A 已于 2026-09-08 完成 M4、两个 backfill 与 reconcile。共享、预发布和生产环境仍未因此自动迁移，任何生产资金开关也仍未获授权。

## 11. 功能开关与发布边界

| 配置 | production 默认 | 说明 |
|------|--------------------|------|
| `WALLET_ADMIN_WRITE_ENABLED` | `false` | 生产调账与 ADMIN+ 代客钱包订单开关；development/testing 默认可演练 |
| `WALLET_ORDER_PAYMENT_ENABLED` | `false` | 生产余额支付开关；development/testing 默认可演练 |
| `WALLET_REFUND_ENABLED` | `false` | 生产退款开关；development/testing 默认可演练 |
| `WALLET_TOPUP_ENABLED` | `false` | 当前禁止开启 |
| `PAYMENT_PROVIDER` | `disabled` | 当前只接受 `disabled` |

配置校验 fail closed：当前 `PAYMENT_PROVIDER != disabled` 或开启 `WALLET_TOPUP_ENABLED` 均拒绝启动。功能开关只控制能力，不改变固定金额上限。生产启用任何内部钱包写能力前，必须按 M4 → NORMAL/DISABLED 普通 USER wallet backfill → legacy manual settlement backfill → reconcile/发布门槛的顺序收敛；历史 DELETED USER 不补钱包，不得颠倒顺序或与应用写流量并行。

## 12. 当前未实现

- 真实微信充值、订单支付、退款、通知验签、查单、关单、证书轮换和对账。
- 钱包转账、提现、兑换现金、赠送余额或第三方消费。
- 混合支付、部分退款、用户自助退款。
- 动态资金配置中心及生产经营/商户进件资料。

## 13. M9 二维码开台联动（已实现）

M9 只把既有成功订单付款事实接入桌台计时，不改变钱包金额、Payment、Settlement、Refund 或 WalletTransaction 的计算规则：

- 钱包支付和管理员人工结算仍分别由现有事务所有者编排。
- 若订单绑定有效待支付 Table Session，唯一可信计时起点是该次成功 `Payment.succeeded_at`。
- Payment、Settlement、钱包扣款/流水、Order `pending -> paid`、Session `awaiting_payment -> active` 与全部 Timer 必须同事务提交或回滚。
- 桌台页面发起钱包付款时必须携带 `Table-Session-No`；指定 Session 过期/关闭/不属于当前用户或订单时资金零写入。
- 全额退款成功时，在现有 Refund 事务内关闭仍为 active 的 Session 并释放 Occupancy；PAID Kit 恢复与 COMPLETED 不恢复语义不变。
- 涉及 M9 时采用适用的 `User -> Order -> StoreTable -> TableSession/Occupancy -> Settlement/Payment/Refund -> WalletAccount -> Kit` 锁序。
- 真实微信支付仍是独立后续项目，不因 M9 内部钱包/人工验收而开启或模拟成功 Provider 事实。

完整规则见 [二维码开台需求](table_session_module.md) 与 [二维码开台 API](../03_api/table_session_api.md)。运行时代码、M9 迁移和内部钱包/人工验收路径已进入仓库；真实微信支付仍保持 Deferred，各持久环境须独立迁移和验收。
