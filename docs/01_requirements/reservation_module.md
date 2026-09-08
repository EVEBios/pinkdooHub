# 预约模块（Reservation Module）

> **Contract Version:** v1.0（N1）
>
> **Status:** N1/M7 repository and MySQL gates complete；M5/M7 present in current Gate A M7；other environments and real-client acceptance pending
>
> **Last Updated:** 2026-09-09

---

## 1. 目标与权威边界

Reservation 为顾客提供独立于 Order、Payment 和 Wallet 的拼豆体验预约，并为门店提供人工确认、因无空位拒绝、设置自定义店休和查看顾客当前联系方式的能力。

本文件是 N1 预约业务行为的权威来源；HTTP 契约见 [Reservation API](../03_api/reservation_api.md)，数据结构见 [Database Design](../02_database/database_design.md)。微信订阅消息、Outbox、Worker、重试与主动通知不属于 N1，见独立的 [N2 微信店休通知规划](reservation_wechat_notification_plan.md)。

N1 的核心取舍：

- 预约不要求先下单，也不创建订单、支付或钱包流水；顾客到店后付款或仅登记。
- 每次创建先进入 `pending`，由 ADMIN+ 人工判断并确认或拒绝。
- 首版不维护座位容量，不承诺自动防超额；`booking-options` 只表达时间、营业日和 Option 合法性，不表达空位。
- N1 不把“同一用户 + 同一 Option + 同一开始时间”设为唯一业务身份；同一时段允许重复提交并分别生成 Reservation，是否确认为人工容量判断。客户端仍不得在结果未知时自动重发。
- 顾客以“我的预约 / 预约详情”中的服务端状态和文案为权威；N1 不主动推送微信通知。
- Product 继续维护体验 Option 与当前价格，Reservation 负责具体日期、时段、营业日历和不可变创建快照。

## 2. 角色与权限

| 角色 | 能力 |
|------|------|
| 游客 | 不能读取预约选项、创建或查询预约 |
| 正常普通用户 `USER` | 查询一个可用 ExperienceOption 的可预约日期/时段；创建预约；分页查看自己的预约；查看自己的详情；在取消截止时间前取消自己的 `pending/confirmed` 预约 |
| `ADMIN` / `SUPER_ADMIN` | 分页筛选全部预约；查看详情和当前完整手机号；确认或以固定原因拒绝 `pending` 预约；查看预约审计；查询、设置和恢复自定义店休 |
| disabled / deleted 用户 | 不能调用顾客预约入口，也不能创建新的预约；历史记录继续保留 |

用户详情按 Owner-only 查询。不存在和不属于当前用户的预约统一表现为 `40451`，不得暴露资源是否属于他人。ADMIN+ 权限只由后端认证依赖裁决，前端角色守卫不是安全边界。

## 3. 时间、营业日与价格分类

### 3.1 时区与表示

- 营业规则统一使用 `Asia/Shanghai`。
- 创建请求使用上海当地 `reservation_date`（严格 `YYYY-MM-DD`）和 `start_time`（严格 `HH:00` 或 `HH:30`）。
- 服务端把当地日期/时间转换为 UTC aware datetime，数据库保存 `scheduled_start_at` / `scheduled_end_at`，API 的 datetime 字段也返回 UTC ISO 8601。
- 顾客响应同时返回服务端计算的当地 `reservation_date`、`start_time` 和 `end_time`。前端不得自行从设备时区重建权威预约时刻。
- 所有“当前时间”判断使用服务端时钟。客户端倒计时和按钮只能改善体验，最终以写请求时的服务端锁后校验为准。

### 3.2 营业时间与预约窗口

| 规则 | 冻结值 |
|------|--------|
| 营业时间 | 每个营业日 `11:00–20:00` |
| 开始时间粒度 | 每 30 分钟一个候选开始时段 |
| 最短提前量 | 开始时间必须大于等于服务端当前时间加 3 小时 |
| 最远可预约日期 | 上海当地今天起第 30 个自然日，包含第 0 日和第 30 日 |
| 完整体验 | `scheduled_end_at` 必须不晚于当地当天 `20:00`，不能跨日 |
| 每周店休 | 默认周一；ADMIN+ 可更换为任一星期 |

边界采用精确比较：创建时 `scheduled_start_at == now + 3h` 合法；早于该时刻非法。用户取消时 `now == scheduled_start_at - 3h` 仍合法，只有 `now` 严格晚于截止时间才返回 `40952`。

### 3.3 工作日 / 节假日 MVP

- 周一至周五使用 `weekday` Option；当前配置为每周店休日的日期会被独立禁用，不改变日期类型。
- 周六、周日使用 `holiday` Option。
- 当前配置的每周固定店休日不进入任何可预约日期；首次部署默认周一。
- 更换固定店休日立即生效：预约窗口内命中新星期、尚未开始的 `pending/confirmed` 预约在同一事务中以 `store_closed` 取消；旧星期恢复可预约，已有单日店休保持不变，历史取消预约不恢复。
- N1 不接入法定节假日、调休或第三方日历。因此周一至周五即使是法定节假日仍按 `weekday`，周末调班仍按 `holiday`。
- 创建时所选 Option 的 `day_type` 必须与预约日期分类一致，否则返回 `42253`，`data.reason=option_day_type_mismatch`。

## 4. ExperienceOption 可预约性与不可变快照

查询 `booking-options` 和创建预约均要求：

1. Option 存在且未逻辑删除；
2. 关联 Product 存在、未逻辑删除；
3. Product 类型为 `experience`；
4. Product 状态为 `online`；
5. Option 的 `day_type` 与预约日期分类一致。

创建事务在锁内重新读取 Product 与 Option 并复验，不能信任此前页面或 `booking-options` 的结果。Option 不存在/已删除使用 `42252`；关联 Product 不可预约使用 `42251`。

成功创建时保存完整 Option 展示和计价快照：

- `product_name`
- `option_duration_minutes`
- `option_participants`
- `option_day_type`
- `option_price`

历史列表、详情和到店价格均读取 Reservation 快照。Product/Option 后续改名、改价、下架或逻辑删除不覆盖既有预约。N1 不把手机号写入快照：管理端始终读取 User 当前手机号，避免历史个人信息在预约表内额外复制。

## 5. `booking-options` 服务端日历

顾客按一个 `experience_option_id` 一次查询完整创建选项。响应包含：

- 当前 Option/Product 摘要与价格；
- `timezone=Asia/Shanghai`、UTC `server_now`；
- `booking_window_end_date`；
- 冻结规则 `minimum_lead_hours=3`、`slot_interval_minutes=30`、`booking_window_days=30`、`opens_at=11:00`、`closes_at=20:00`；
- `dates[]`：未来第 0–30 日中至少存在一个合法开始时段的日期、日期类型和 `start_times[]`。

服务端会排除：周一、自定义店休日、Option 日期类型不匹配的日期、已经错过最短提前量的开始时段，以及会使体验结束晚于 `20:00` 的时段。`dates` 可以为空，这是“该 Option 在当前窗口无合法时段”，不是系统错误。

该接口不读取座位容量，也不保证返回的时段最终可确认。创建时必须再次校验全部规则，以覆盖页面停留、管理员临时店休和 Product/Option 变化。

## 6. 预约状态机

### 6.1 状态

| value | 展示文案 | 进入方式 | 允许后续动作 |
|-------|----------|----------|--------------|
| `pending` | 待门店确认 | 顾客创建 | 门店确认、门店拒绝、顾客取消、店休批量取消 |
| `confirmed` | 已确认 | ADMIN+ 确认 `pending` | 顾客取消、店休批量取消 |
| `rejected` | 未能确认 | ADMIN+ 以 `no_capacity` 拒绝 `pending` | 无 |
| `cancelled` | 已取消 | 顾客取消或店休批量取消 | 无 |

N1 不设 `completed`、`expired`、`no_show` 或付款状态。预约开始后历史状态保持原值；是否到店、收款和履约不由本模块推断。

### 6.2 原因与状态时间不变量

| 状态 | `rejection_reason` | `cancellation_reason` | 状态时间 |
|------|--------------------|-----------------------|----------|
| `pending` | null | null | `confirmed_at/rejected_at/cancelled_at` 全 null |
| `confirmed` | null | null | `confirmed_at` 非 null，其余终态时间 null |
| `rejected` | `no_capacity` | null | `rejected_at` 非 null，其余状态时间 null |
| `cancelled` | null | `customer_request` 或 `store_closed` | `cancelled_at` 非 null；从 `confirmed` 取消时保留原 `confirmed_at` |

拒绝原因只允许 `no_capacity`。店休取消必须使用独立 `store_closed`，绝不能以“无空位”冒充店休。

### 6.3 顾客文案 Registry

| 情况 | 服务端 `customer_message` |
|------|---------------------------|
| `pending` | 预约已提交，正在等待门店确认。 |
| `confirmed` | 预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。 |
| `rejected/no_capacity` | 很抱歉，您选择的时段当前已无空位，本次预约未能确认。您可以选择其他日期或时段重新预约。 |
| `cancelled/customer_request` | 本次预约已取消。您可以选择其他日期或时段重新预约。 |
| `cancelled/store_closed` | 门店当天休息，本次预约已由门店取消。给您带来不便，敬请谅解；您可以选择其他日期重新预约，如需帮助请联系门店。 |

前端应直接展示 `customer_message`，并按 `status.value` / 原因 `value` 决定交互；不得只用本地文案推断状态。未知 Enum 必须保留可诊断性并安全降级。

## 7. 创建预约

请求只包含：

```json
{
  "experience_option_id": 42,
  "reservation_date": "2026-09-12",
  "start_time": "14:30"
}
```

创建要求当前正常普通用户存在有效手机号；缺少手机号返回 `42254`，零写入。手机号仅作为当前联系资料读取，不进入请求，也不复制到 Reservation。

创建事务的关键顺序：

```text
锁 User 并复验 role/status/phone
→ 按日期确保并锁定 StoreBusinessDay
→ 锁 Product 与 ExperienceOption
→ 复验当前可预约性、店休和完整时间窗口
→ 写 pending Reservation 与完整快照
→ 写 CREATE_RESERVATION Audit
→ 同事务连接重载响应
```

任一步失败时 Reservation 与 Audit 全部回滚。`StoreBusinessDay` 是创建与设置店休共用的一日一行锁点，用来防止“同一天被关店”和“新预约”并发同时成功。

N1 的创建接口没有客户端幂等键。网络超时、5xx 或成功信封损坏时结果未知，客户端不得自动重复 POST；应先查询“我的预约”核对服务端权威结果。

同一用户、同一 ExperienceOption、同一 `scheduled_start_at` 的多次成功请求会创建多条独立记录；数据库和 Service 都不做去重，也不把重叠记录自动视为超额。该规则支持多人同行、代为登记或顾客明确追加预约，但前端必须合并同一次点击产生的并发 Promise，避免把一次操作误发为多次。门店逐条人工确认或以 `no_capacity` 拒绝。

## 8. 用户查询、取消与改期

- 用户列表按 `scheduled_start_at DESC, id DESC` 分页，可选按四状态之一筛选。
- 用户详情只允许 Owner；用户响应不包含 User、手机号或管理员信息。
- 只有 `pending` / `confirmed` 可由 Owner 取消；其他状态返回 `40951`，并返回稳定的 operation/current_status/allowed_statuses。
- 取消必须在开始前精确至少 3 小时；晚于截止时间返回 `40952`。
- 取消成功进入 `cancelled/customer_request` 并写 `CANCEL_RESERVATION` Audit。
- 改期不是原行更新：先取消旧预约，再按当前 Product/Option、价格、日历和手机号规则创建新预约。旧记录、原快照和审计历史保留。

取消 PATCH 必须是空请求体，连 `{}` 也不发送。当前接口不是幂等命令：第一次成功后再次取消返回 `40951`。请求结果未知时先 GET 详情，不盲目重发。

## 9. 门店确认与拒绝

- 只有 ADMIN+ 可以操作。
- 确认和拒绝都只允许从 `pending` 进入目标状态；否则 `40951`。
- 当服务端 `now >= scheduled_start_at` 时，即使仍为 `pending` 也不能确认或拒绝，返回 `40953`。
- 拒绝请求没有原因 body，服务端固定写入 `rejection_reason=no_capacity`，避免客户端伪造自由文本或未来原因。
- 确认写 `confirmed_at` 和 `CONFIRM_RESERVATION` Audit；拒绝写 `rejected_at`、固定原因和 `REJECT_RESERVATION` Audit。
- 首版容量由店员人工判断。系统不统计座位、不占座、不根据重叠预约自动拒绝。

## 10. 自定义店休与批量取消

### 10.1 设置限制

- 自定义店休只允许上海当地今天或未来日期。
- 当前配置的每周固定店休日不能通过单日店休 PUT/DELETE 重复管理；返回 `42255`，`data.reason=weekly_closed`。
- 过去日期不能设置或恢复；返回 `42255`，`data.reason=past_date`。
- `PUT /admin/store-closures/{business_date}` 是按日期幂等：首次关闭返回 HTTP 201；日期已经自定义关闭时返回 HTTP 200、`is_replay=true`，不重复取消或审计。

### 10.2 原子批量取消

首次关闭日期时，在单一事务内：

```text
锁该 StoreBusinessDay
→ is_closed=true
→ 按 Reservation ID 升序锁定该日 scheduled_start_at > now 且 pending/confirmed 的预约
→ 批量改为 cancelled/store_closed
→ 批量写每条 CANCEL_RESERVATION Audit
→ 写 CLOSE_STORE_BUSINESS_DAY Audit 和取消计数
```

只有尚未开始（`scheduled_start_at > now`）的活跃预约被取消；已经开始、`rejected` 或已 `cancelled` 的历史不变。响应返回本次取消总数以及 pending/confirmed 分项计数。营业日、全部预约和全部审计必须一起提交或一起回滚；禁止循环逐条独立事务产生半完成店休。

N1 主动通知未实现。顾客可在“我的预约/详情”看到 `cancelled/store_closed` 和独立文案；门店通过管理详情读取当前手机号进行人工联系。N2 才会加入显式订阅授权、Outbox、Worker、重试和人工兜底队列。

### 10.3 恢复营业

- `DELETE /admin/store-closures/{business_date}` 把现有自定义店休日恢复为营业日并写审计。
- 恢复营业绝不复活此前因店休取消的预约；顾客需要重新创建，获得新的 Reservation ID 和当前价格快照。
- 目标日期没有自定义店休（包括已经恢复）时返回 `40452`。重复 DELETE 不伪装成功。

`store_business_days` 行不会因为恢复而删除，`is_closed=false` 仍保留并发锁点和历史审计关联。

## 11. 管理查询、手机号与隐私

- 管理预约列表按 `scheduled_start_at DESC, id DESC` 分页，可组合筛选 `status/business_date/user_id/product_id`。
- 列表返回当前用户昵称和后端生成的 `user_phone_masked`；标准 11 位手机号形如 `138****8000`。
- 管理详情返回当前 `user_phone` 完整值，用于履约联系；不是预约快照。用户后续修改手机号后，详情读取新号码。
- 因历史迁移或账号匿名化导致当前号码不可用时，管理列表/详情分别返回 null。客户端必须展示“联系方式不可用”，不得展示旧缓存号码。
- 顾客列表和详情永不返回手机号。Audit description 不得包含手机号、昵称、请求 body、Token 或其他敏感信息。

## 12. 账号注销联动

普通用户存在满足以下条件的预约时，账号注销沿用 User 模块 `1015` 阻断：

```text
status IN (pending, confirmed)
AND scheduled_end_at > now_utc
```

该查询必须在注销事务内、锁定 User 后使用同一数据库连接完成。以 `scheduled_end_at` 而不是开始时间判断，避免体验已经开始但尚未结束时匿名化当前联系方式。`rejected/cancelled` 或结束时间已过的预约不阻断，但 Reservation、快照、外键和审计仍作为最小必要历史保留。

## 13. 并发、事务与审计

- Service 拥有所有写事务；Repository 只做查询和原子 CRUD；Validator 只判断时间规则，不查库。
- 创建、设置店休和恢复营业对同一 `StoreBusinessDay` 使用一致锁边界；店休批量预约按 ID 升序锁定。
- 单预约状态变迁先 `SELECT ... FOR UPDATE`，锁后重新检查状态与服务端时间。
- 仅 MySQL 1205/1213 对整个用例使用全新事务最多 3 次；其他数据库错误不重试。
- 并发首次创建营业日的命名唯一冲突只有在确认权威行已存在时才允许完整事务重试，不能吞掉不相关 IntegrityError。
- 审计动作：`CREATE_RESERVATION`、`CONFIRM_RESERVATION`、`REJECT_RESERVATION`、`CANCEL_RESERVATION`、`CLOSE_STORE_BUSINESS_DAY`、`REOPEN_STORE_BUSINESS_DAY`。
- 店休批量取消必须批量写 Audit，禁止 N+1。

## 14. 错误语义

Reservation 使用冻结错误段：

| code | HTTP | 含义 |
|------|------|------|
| `40451` | 404 | 预约不存在或对当前顾客不可见 |
| `40452` | 404 | 目标日期没有可恢复的自定义店休 |
| `40951` | 409 | 当前预约状态不允许该操作 |
| `40952` | 409 | 顾客已错过开始前至少 3 小时的取消窗口 |
| `40953` | 409 | 预约已经开始，门店不能再确认或拒绝 |
| `42251` | 422 | 关联 Product 当前不可预约 |
| `42252` | 422 | ExperienceOption 不存在、已删除或不可预约 |
| `42253` | 422 | 日期/时段不可用；具体原因见 API 文档 |
| `42254` | 422 | 当前账号没有手机号，不能创建预约 |
| `42255` | 422 | 自定义店休日期不可操作 |

Pydantic 请求形状错误继续使用通用 HTTP 422 / code `422`，不能与稳定业务错误 `42251–42255` 混淆。

## 15. 发布与验证门槛

仓库已有 N1 Model、Repository、Validator、Service、Mapper、FastAPI Router、离线 M5 迁移和自动化测试。2026-09-06 已在一次性 MySQL 8.0.46 专用 Schema 真实执行 Aerich 0→5；Reservation MySQL 专项 `7 passed`，与既有 Inventory 门槛联合运行 `16 passed`。已覆盖创建/店休两个锁等待方向、并发重复店休、批量取消与审计回滚、真实 1205、1213 全事务重试，以及营业日唯一索引和五个 Reservation 查询索引的 EXPLAIN。容器、端口和临时报告均已清理，未触碰持久数据库。

正式部署/启用前，必须在当前候选 SHA 与目标发布流水线重新执行下列门槛并留存证据；上面的可销毁 MySQL 记录只满足本地核心验证，不代替目标环境发布证据：

1. 相关单元、Schema、Repository、Mapper、Service 和真实 HTTP 矩阵；
2. 在目标发布流水线重新执行并留存隔离 MySQL 8.0.x 的 Aerich `0 → 1 → 2 → 3 → 4 → 5` 证据；
3. 验证四个 `RESTRICT` 外键、命名唯一索引、五个 Reservation 查询索引、UTC datetime 和字符串 Enum 持久化；
4. 验证创建与店休、重复店休、相反日期店休、同一预约状态变迁的真实并发；
5. 验证同一用户/Option/时段的两次明确创建生成两个不同 Reservation ID，不被错误去重或自动判满；
6. 注入 1205/1213，证明每次重试使用全新完整事务且不重复写状态或 Audit；
7. 对用户列表、活跃预约注销阻断、管理组合筛选和店休日批量取消运行 `EXPLAIN`；
8. 迁移后核对 `store_business_days` / `reservations` 行数与约束，并保留回滚或前向修复方案。

上述一次性验证本身不等于目标环境迁移。M5/M7 后续已随当前持久 Gate A 的 M2→M7 受控升级应用；本地持久 SQLite、共享、预发布和生产数据库不因该证据自动迁移。开发环境 `generate_schemas` 只能补建缺失表，不能 ALTER 既有表，也不会写 Aerich 版本；它不是发布迁移证据。MySQL DDL 会隐式提交，因此任何新目标执行 M5/M7 都不能承诺整份 DDL 原子回滚，执行前必须备份、停写并准备按实际完成步骤恢复。

## 16. 明确不在 N1

- 自动容量、座位数、排队或超额保护；
- 预约与订单/支付绑定、预付款、到店收款记录；
- 微信订阅消息、短信、邮件、Outbox、Worker、重试与送达回执；
- 法定节假日、调休、临时营业时段或单日特殊营业时间；
- 直接修改原预约时间、恢复被取消预约；
- 到店、爽约、完成、评价或核销状态；
- 顾客自由填写拒绝/取消原因或管理员自由文本拒绝原因。
