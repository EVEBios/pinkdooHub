# 站内提醒 API（P1.1/P1.2）

> 2026-09-14；预约基础需 M12；订单/桌台扩展需 M13。原预约 API 响应与排序不变。
> 业务权威：[提醒需求](../01_requirements/attention_module.md)。

所有路径带 `/api/v1`，使用现有 Bearer 认证、`success()` 信封和统一错误响应。顾客端仅普通 USER，管理端 ADMIN+；目标接收者由认证推导，客户端不能传入 user_id 或 read_by_id。

| 方法 | 顾客路径 | 管理路径 | 用途 |
|---|---|---|---|
| GET | `/attention` | `/admin/attention` | 汇总 |
| GET | `/attention/reservations` | `/admin/attention/reservations` | 专用分页视图 |
| GET | `/attention/reservations/{reservation_id}` | `/admin/attention/reservations/{reservation_id}` | 预约版本与未读事件快照 |
| POST | `/attention/read` | `/admin/attention/acknowledge` | 精确阅读／共享知悉 |

## 汇总

`data` 为 `AttentionSummaryOut`：`server_now` 是 UTC 时间；`reservation_actionable`、`reservation_unread`、`reservation_overdue`、`reservation_total` 为非负整数。未读数量按预约去重。管理 total 为 actionable + unread；顾客 actionable/overdue 为 0，total 等于 unread。过时判定包含等于开始时间的边界，统计包含未来日期预约，不限今天。

## 分页视图

通用 `page` / `page_size` 使用 [通用分页契约](api_design_conventions.md)。仅接受声明字段。顾客 `view` 只能为 `unread`（默认）；管理员默认 `actionable`，另支持 `unread`、`overdue`。顾客传管理视图或额外过滤参数返回 422。

返回 `Page[ReservationOut]` 或 `Page[AdminReservationListItemOut]`，复用原预约安全映射及业务快照。待审核/过时按 `scheduled_start_at, id` 升序；未读按预约最新事件 ID 降序、预约 ID 降序。读取不产生阅读回执。

## 快照与精确已读

`reservation_id` 必须为正整数。顾客只能读取本人预约；不存在和非本人均返回原预约 40451。`data` 包含：

- `reservation_id`、`reservation_updated_at`、`server_now`。
- `events`：本接收目标仍未读的事件，按 ID 升序，每项含正整数 `id`、`event_type`、安全展示用 `label` 和 UTC `occurred_at`。事件枚举以 `app/common/enums/attention.py` 和生成的 OpenAPI 为准。

读取快照与业务转态共用预约锁，保证版本和事件集合一致。客户端须确认已显示业务详情的 updated_at 与快照一致，再确认该集合，不能直接把拉取快照当作已读。

POST 请求形如 `{"event_ids":[12,15]}`：仅此字段，1–100 个严格正整数，不接受字符串、布尔值、重复值或额外字段。成功 `data: null`。只修改明确 IDs 的未读行；重复请求成功，首次 read_at/read_by 保留。任一 ID 不存在或不属于目标接收者时返回 HTTP 404 / 40471，整批无更新；不泄露是哪一条越权。

## 错误与兼容

422 为协议校验；401 为无有效认证；403 为不符角色；账号禁用等沿用现有认证错误（例如 400 / 1005），不能按号段推断状态码。40471 的含义为“提醒不存在或不可访问”。轮询或已读失败不修改预约业务事实。新客户端应将提醒失败作为可恢复区域错误，保留原预约列表与详情入口。

P1.1 的预约字段保持兼容。P1.2 订单/桌台增量见下节；P1.3 资金结果见后文，微信投递及订阅字段仍未接入。旧客户端仍使用原业务接口，但其读取不会自动消除新站内提醒。

## P1.2 增量协议：订单与桌台

本节取代上文“当前不返回订单字段”的 P1.1 范围说明；需 M13。汇总在同一数据库事务读取，沿用同一 `server_now`，增加：

| 字段 | 含义 |
|---|---|
| order_pending | 普通 pending 订单，排除有效占台订单 |
| order_fulfillment | 管理员 paid 且无 pending/succeeded Refund 的订单数；顾客为 0 |
| order_unread | 顾客按订单去重的新结果；管理员为 0 |
| order_total | 管理员 pending + fulfillment；顾客 pending ∪ unread |
| table_pending | 付款截止时刻仍有效的待付款会话数 |
| table_unread | 顾客独立结束结果按会话去重；管理员为 0 |
| table_total | pending + unread；两者分别为待付款与已结束会话，不重叠 |

新增 GET `/attention/commerce/{scope}` 与 `/admin/attention/commerce/{scope}`，scope 为 orders/tables；view 为 all（默认）、pending、fulfillment、unread，带标准分页，仅接受声明字段。订单 fulfillment 为履约查询；顾客界面只提供 all/pending/unread。管理员 tables 固定为有效待付款队列。记录按 created_at、id 降序，先筛选/去重再分页。返回 Page[CommerceAttentionItemOut]：id、scope、reference、title、status_label、order_id、session_no、unread、created_at、payment_deadline_at。关联字段显式可空，桌台条目必须有精确 session_no；不会返回顾客手机号、内部释放备注或二维码 Token。列表读取不标已读。

新增顾客 GET `/attention/orders/{order_id}`、`/attention/tables/{session_no}`。仅 owner，非本人/不存在分别沿用 40411（订单）、40462（桌台）；ADMIN+ 不可访问顾客接口。返回 CommerceAttentionSnapshotOut：server_now、events；每条含原事件 id/type/label/occurred_at，加完整不可变 message、精确关联 session_no 和 read。返回本事项已读及未读结果，允许已读后继续核对历史；桌台可展示本次付款合并事件，但不会因此另增桌台主角标。

顾客将确切显示的未读事件 ID 交给已有 POST `/attention/read`；不支持批量“最新全部”。管理员不会接收新的订单/桌台结果事件，处理待办仍调用既有业务 API。查看、轮询、微信投递不改变业务待办。

新汇总字段为必填非负整数，旧客户端可以忽略新增字段；新客户端不得用缺失字段伪造 0。事件类型以 Enum/OpenAPI 为权威。新代码依赖 M13 结构，新增列不回填历史结果；发生结构兼容问题必须保留数据处理，不删结果回滚。

## 顾客完整开台记录（2026-09-14）

GET `/attention/table-sessions`：仅认证普通 USER，返回本人的全部开台记录，供会员中心固定“我的桌台”入口使用。标准 page/page_size 分页，默认第 1 页、20 条，上限遵循通用分页契约。接收者由认证身份推导，不提供跨用户筛选。

响应复用 `Page[CommerceAttentionItemOut]`，scope 固定 tables，按 created_at、id 降序。包含尚未付款、已经付款使用中及已结束记录；付款结果已读不会使条目消失。status_label 在有效付款窗口内为“待付款”，active 且 now < table_release_at 为“体验中”（具体计时阶段见详情），否则为“本次桌台已结束”。列表不标已读、不写事件，unread 仅代表该会话独立未读结果，原订单／桌台汇总数字不变。

未登录 401，ADMIN+ 访问顾客接口 403，非法页码/页大小 422；没有本人的记录时返回空分页。输出不含二维码 Token、内部备注、其他顾客资料。原 `/attention/commerce/tables?view=all` 继续只返回提醒集合；新接口为增量兼容，无需数据库迁移。前后端应同步更新，新客户端完整列表依赖此新端点。


## P1.3 增量协议：余额调整及订单资金结果

汇总新增 `wallet_unread` 非负整数，顾客为本人未读余额调整事件数，管理员恒为 0。会员 Tab 合计 `order_total + table_total + wallet_unread`。该字段服务端始终输出，新客户端缺失时报告契约错误，不假定为零。

- GET `/attention/wallet`：认证普通 USER；`view=unread`（默认）或 `all`，标准 page/page_size。按 occurred_at DESC、id DESC 稳定分页，返回 `Page[CommerceAttentionItemOut]`，scope 固定 wallet、id 为精确事件 ID，order_id/session_no/payment_deadline_at 为 null。只包含新启用后的调整结果，不回填旧账本；all 包含已读记录。GET 不修改已读。
- GET `/attention/wallet/{event_id}`：正整数事件编号；仅本人，事件或原始流水不存在／不归属本人均返回 HTTP 404 / 40471。管理员 403，未登录 401，禁用账号沿用 400/1005；不接受收件用户参数。
- 详情复用 `CommerceAttentionSnapshotOut`，wallet scope 精确返回一条事件。新增可空 `wallet_transaction`，只含 `id`、`change_amount`、`before_balance`、`after_balance`、`reason`。金额为精确两位小数字符串，调整非零、前后余额符合变化公式；原因完整 1–256 字。无钱包账户 ID、操作者、幂等键或内部备注。
- 订单与桌台事件的 wallet_transaction 为 null。代客下单和两种退款新增事件类型以 Enum/OpenAPI 为准，仍通过原 `/attention/orders/{order_id}` 返回完整安全结果，不增加第二个钱包或桌台主事项。
- 阅读使用原 POST `/attention/read` 的明确事件集合协议，列表、预加载、失败或后台响应不得自动清除结果。

兼容性：新增两个只读端点、汇总字段、可空事件字段和事件类型；依赖已有 M13 列，不需新迁移。先部署支持新类型的后端再使用新客户端；旧客户端资金业务操作继续可用，但旧事件解析器可能提示结果暂不可用，需同步升级展示。新事件生成后，回滚后端必须保留对新 Enum 值的读取兼容，不能直接回到不识别这些事件的旧代码，更不能删事件或修改账本。

## P2 管理预约跟进

全部端点使用 `/api/v1/admin/reservation-followups`，仅 ADMIN+，遵循原停用/删除身份拒绝规则。

| 方法与后缀 | 行为 |
|---|---|
| GET `/summary` | `server_now`, `contact_pending`, `overdue_pending`；独立于 P1 汇总 |
| GET `?kind=contact\|overdue&view=pending\|completed&page=1&page_size=20` | 按预约时间、ID 分页；含预约 ID、快照商品名、顾客昵称、时间、当前跟进版本/结果 |
| GET `/{reservation_id}/{kind}` | `eligible`, `completed`, `revision`, `latest`, `server_now`；无记录时 revision=0/latest=null |
| GET `/{reservation_id}/{kind}/history?page=1&page_size=20` | 版本倒序分页返回操作人 ID、时间、结果及说明 |
| POST `/{reservation_id}/{kind}` | JSON：`expected_revision` 非负严格整数、`request_key` UUID、`outcome`、`note`（去空白 1–500 字） |

outcome 的业务意义与可用范围以 [提醒需求](../01_requirements/attention_module.md#p21--p22-门店预约跟进2026-09-15) 为准。成功返回最新快照；相同请求重放可返回后来更新的最新快照，不重复写历史。版本过期、同键不同内容、已完成、业务条件不再成立或过期跟进使用 contacted，返回 HTTP 409 / code 40972，要求核对最新记录。不存在的预约沿用 40451。字段非法/多余字段返回 422。

读接口无完成副作用；此 API 不修改预约状态、不确认顾客已读、不证明微信送达。结果未知时前端保留原请求并重试，同一操作不换键。无新顾客端点。新增结构化 Out Schema 已同步 OpenAPI 与前端生成类型。
