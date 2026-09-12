# 预约店休取消的微信订阅消息主动通知规划（N2）

> **Document Version:** v0.1
>
> **Status:** Deferred design — 当前选择 N1；N2 未实现、未启用、未授权
>
> **Last Updated:** 2026-09-06
>
> **Implementation Phase:** Unassigned（Reservation follow-up N2）
>
> **Database Migration:** TBD，不预占迁移编号
>
> **Target Gate:** 仅在另行批准后进入 Gate B；当前不是 Gate B 必选门槛
>
> **External Changes:** None — 未修改微信后台、未申请模板、未写入 Secret、未启动 Worker、未迁移数据库、未上传或发布小程序

本文记录 Reservation N1 之后未来可选的 N2 主动通知扩展，供后续产品、架构、安全、隐私、运维与发布评审使用。它不是当前实现契约，也不表示仓库或微信公众平台已经具备相应能力。N1 权威业务与 HTTP 契约分别见 [Reservation Module](reservation_module.md) 和 [Reservation API](../03_api/reservation_api.md)。

当前决策是 **N1：顾客在“我的预约/预约详情”查看权威状态和文案，门店通过当前用户手机号人工联系**。N2 不阻塞 N1 的设计、实现或验收；只有在产品负责人另行批准范围、微信模板可行性、个人信息处理目的、正式 Secret、Worker、监控和 Gate B 验收后，才可以进入实现与启用流程。

---

## 0. 决策摘要

### 0.1 当前冻结事实

- N1 是当前交付选择；N2 是延期的可选增强。
- N2 首个且唯一纳入本规划的业务事件是 `reservation_cancelled_store_closed`，即管理员设置店休后，尚未开始的 `pending` / `confirmed` 预约被门店批量取消。
- 店休取消的预约业务状态是 `cancelled`，取消原因是 `store_closed`。它与管理员因满座执行的 `rejected/no_capacity` 是两个不同事实，不能复用原因、模板或顾客文案。
- “我的预约”和预约详情中的数据库状态始终是权威事实。微信订阅消息只是尽力而为的补充渠道，不能替代站内状态，也不能成为预约取消是否生效的判断依据。
- 微信通知失败、延迟、重复、无授权或不可投递，不得回滚已经提交的店休和预约取消。
- 恢复营业只恢复该日期的可预约性，不恢复历史预约，不生成新的补偿通知。
- N2 启用前已经因店休取消的历史预约默认不追溯补发。
- 联系电话继续采用 N1 已选择的方案：读取当前 `User.phone`，预约表、订阅表和通知表都不保存手机号快照。
- 顾客在没有未来 `pending/confirmed` 且尚未结束的预约后才可以注销账号；注销匿名化可能使当前手机号消失。N1 管理端此时返回 `user_phone=null`，客户端展示“联系方式不可用”。如果业务不能接受这个结果，必须重新评审联系方式保留规则，不能由 N2 静默增加手机号快照。

### 0.2 三类状态必须分离

```text
Reservation 业务状态
    cancelled / store_closed
              │
              ├── 与用户是否订阅无关
              │
Notification subscription 用户意愿
    available / reserved / consumed / withdrawn / invalidated
              │
              ├── 不等于消息已发送或已送达
              │
Notification delivery 投递状态
    pending / processing / retry_wait / delivery_unknown
    provider_accepted / dead / suppressed
```

例如，一条预约可以已经是 `cancelled/store_closed`，顾客却没有订阅；也可以已经订阅，但投递仍在 `retry_wait`。任何通知状态变化都不得改变 Reservation 的取消事实。

### 0.3 顾客文案基线

站内页面的权威文案建议保持为：

> 门店当天休息，本次预约已由门店取消。给您带来不便，敬请谅解；您可以选择其他日期重新预约，如需帮助请联系门店。

微信模板消息使用更短、受模板字段限制的版本，但语义必须一致，不得写成“无空位”或“预约被拒绝”。具体字段和长度在 N2 实施时根据目标账号可用模板重新确认。

---

## 1. 背景与当前仓库差距

### 1.1 当前已有基础

仓库已经具备以下可复用边界：

- Reservation N1 已冻结四状态、`no_capacity`、`customer_request/store_closed`、自定义店休、原子批量取消、逐预约审计、管理详情当前手机号与 M5 两表；M5/M7 已进入当前持久 Gate A M7，N1 站内状态不依赖任何通知设施；
- 后端存在微信小程序 `code2Session` Provider 适配器、HTTP 超时和平台错误映射；
- 微信 AppID/AppSecret 已有配置和 Secret 文件注入边界；
- 用户与微信身份通过 `ExternalIdentity` 绑定；
- Redis 已用于认证与限流，可以在未来承担 Access Token 短期缓存或 Worker 唤醒，但不能成为不可丢通知的唯一存储；
- `AuditLogService` 可以加入调用方事务，适合记录店休和批量取消审计，但 AuditLog 不是消息 Outbox；
- 现有任务脚本提供批次与游标处理参考，但不是实时、可靠、可恢复的通知 Worker。

### 1.2 当前明确缺失

当前仓库没有：

- 小程序 `requestSubscribeMessage` 授权交互和相应平台端口；
- 可用于主动投递的 OpenID。现有 `external_identities.subject_id` 只保存 Pepper-HMAC，HMAC 不可逆；
- 用途隔离、可逆加密的微信消息收件地址；
- 订阅模板标识、字段映射和合法详情页配置；
- 微信 Access Token 的获取、缓存、刷新和并发抑制；
- Durable Outbox、投递状态、租约、重试和 Dead-letter；
- 常驻通知 Worker、健康检查、优雅停机和部署单元；
- 通知积压、失败、Token 刷新和人工兜底的生产监控与告警；
- 目标小程序正式账号、类目、模板、iOS/Android 真机和正式环境验收证据。

因此，N2 不是在店休接口后追加一次微信 HTTP 请求，而是一个独立的可靠通知扩展。

### 1.3 与当前发布范围的关系

[RDR-001](../09_release/release_decision_record.md) 已明确把订阅消息排除在 Gate A 之外；[Phase 9 微信发布规划](../08_frontend/phase9_wechat_release_plan.md) 中的 Phase 9.6 已用于微信交易闭环。本规划不会修改这两个事实，也不使用“Phase 9.6”命名。

N2 只有在未来另行批准后才进入 Gate B 范围，而且当前并不是 Gate B 的强制能力。正式采纳时应新增独立决策记录或明确的决策附录，不应改写 RDR-001 的历史结论。

---

## 2. 目标、成功标准与非目标

### 2.1 目标

N2 的目标是：顾客自愿订阅后，当门店设置某日店休并批量取消其尚未开始的预约时，系统在不影响预约事务正确性的前提下，异步尝试发送语义明确的微信订阅消息；无法主动通知时，为管理员提供可执行的电话兜底状态。

### 2.2 成功标准

未来实现只有同时满足以下条件才算完成：

1. 顾客只能在预约创建成功后的明确点击动作中选择是否订阅，拒绝、不支持或调用失败均不影响预约成功。
2. 后端不信任客户端提供的 OpenID、模板 ID、页面路径或消息字段；平台身份由后端用短期 `wx.login` code 换取并复验。
3. 管理员设置店休时，预约取消、`store_closed` 原因、审计和符合条件的 Outbox 在同一数据库事务内提交。
4. 事务内不调用微信；独立 Worker 在提交后投递，外部失败不回滚业务事实。
5. 无授权、无投递地址、已撤回、账号已注销或最终投递失败的预约进入人工电话兜底视图。
6. 站内页面始终展示权威取消状态与文案，不依赖微信消息是否发送。
7. API、日志、审计、指标和管理页面不泄露 OpenID 明文或密文、Nonce、密钥版本、Access Token、AppSecret、一次性 code 或完整 Provider 响应。
8. 多 Worker、进程崩溃、网络超时、重复请求、Token 失效、解绑和注销竞态有可验证的稳定结果。
9. 正式账号模板、合法页面、iOS/Android 真机、生产 Secret、告警送达和隐私材料形成 Gate B 证据后，发送开关才允许启用。

### 2.3 范围内

- 顾客显式微信订阅授权；
- 当前账号与本次微信身份匹配；
- 通知专用、版本化 AEAD 加密的 OpenID 投递地址；
- Reservation 级的一次通知意愿记录；
- 店休批量取消事务内写 MySQL Durable Outbox；
- 独立微信订阅消息 Provider；
- Access Token 缓存、提前刷新和 Single-flight；
- 独立 Worker、批量认领、租约、重试、Dead-letter 与崩溃恢复；
- 管理端投递摘要、人工电话兜底和必要的运营筛选；
- 功能开关、Secret、密钥轮换、可观测性、真机与发布验收。

### 2.4 明确不在范围内

- 营销群发、活动运营、广告或增长消息；
- 微信支付、退款或交易通知；
- 短信、邮件、公众号或其他通知渠道；
- 通用 Campaign、Workflow 或全渠道通知平台；
- 强迫顾客授权，或把拒绝授权当作预约失败；
- 保证微信消息必达或 Exactly-once；
- 历史店休取消消息补发；
- 管理员自由输入通知正文；
- 使用 `no_capacity` 原因或模板冒充 `store_closed`；
- 手机号快照；
- 在店休数据库事务内同步请求微信；
- 默认提供人工“重新发送”按钮；
- 自动通知预约确认、满座拒绝或顾客自行取消。它们只能作为后续独立扩展重新评审，不能消耗本规划为店休取消保留的一次订阅机会。

---

## 3. 平台前置条件与实施时核验

微信平台的模板、类目、授权和接口规则可能变化。本规划只冻结项目自身边界，不把当前平台细节写成永久契约。

N2.0 必须通过目标小程序正式账号或被批准的测试账号重新确认：

- 目标主体与服务类目允许使用语义匹配的预约取消订阅模板；
- 模板能够准确表达“门店店休导致预约取消”，且字段类型、数量、长度满足业务数据；
- `requestSubscribeMessage` 的当前触发条件、一次性或长期订阅规则、用户设置行为及错误语义；
- 服务端发送接口当前要求的身份、Access Token、请求字段、合法 Page 和环境限制；
- 接口成功结果究竟只表示 Provider 接受，还是存在可用的最终投递回执；
- 是否存在可依赖的消息 ID、结果回调或查询接口；
- Developer、Trial、Formal 环境之间的模板和 Page 跳转行为；
- 正式 AppID、合法域名、隐私保护指引和审核材料要求。

实施与每个 RC 应优先核对以下官方入口：

- [微信小程序订阅消息能力](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/subscribe-message.html)
- [`wx.requestSubscribeMessage`](https://developers.weixin.qq.com/miniprogram/dev/api/open-api/subscribe-message/wx.requestSubscribeMessage.html)
- [订阅消息服务端发送接口](https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/mp-message-management/subscribe-message/sendMessage.html)

只有目标账号后台和当时官方文档共同验证过的模板与规则，才能进入实现契约和发布证据。

---

## 4. 总体架构与依赖方向

### 4.1 端到端流程

```text
顾客预约成功
  │
  └─→ 明确点击“接收店休取消通知”
         │
         ├─→ 小程序 requestSubscribeMessage
         │       └─拒绝/失败→ 不影响预约，标记电话兜底候选
         │
         └─接受→ 新 wx.login code
                   └─→ 后端 code2Session + HMAC 身份复验
                          └─→ 加密 Recipient + Reservation Subscription

管理员设置店休
  │
  └─→ 同一 MySQL 事务
         ├─锁营业日
         ├─锁并批量取消符合条件的 Reservation
         ├─写 store_closed 审计
         └─批量写 eligible Notification Outbox
                      │
                    Commit
                      │
                      └─→ 独立 Worker 认领
                              ├─复验 Recipient/账号/Reservation
                              ├─获取 Access Token
                              ├─事务外调用微信 Provider
                              ├─provider_accepted
                              └─retry / dead / suppressed
                                      └─→ 管理员电话兜底
```

### 4.2 分层约束

沿用项目现有调用链：

```text
API → Service → Repository → Model → MySQL
          │
          ├─→ Validator
          └─→ Integration Provider（仅事务外）
```

建议职责如下：

| 层 | N2 职责 | 禁止事项 |
|----|---------|----------|
| Reservation API | 严格输入、认证/权限、调用 Service、Out Schema 和统一响应 | 不查 Model，不组装微信消息，不判断投递错误 |
| Reservation Service | 店休与批量取消事务，筛选符合资格的 Subscription，协调 Outbox Repository | 不在事务内调用微信，不直接操作 Model |
| Notification Subscription Service | Owner-only 授权登记、身份匹配、Recipient 加密、撤回 | 不接受客户端 OpenID/任意模板 |
| Notification Delivery Service / Worker | 认领任务、复验、解密、调用 Provider、错误分类和状态收敛 | 不修改 Reservation 业务状态 |
| Repository | 锁、查询、批量写、租约与状态更新 | 不做平台调用，不抛业务规则异常 |
| Provider | Access Token 与微信 HTTP 协议适配、响应最小化映射 | 不拥有业务事务，不记录敏感数据 |
| Redis | Access Token 缓存、刷新协调、可选 Worker 唤醒 | 不作为不可丢通知事件的唯一事实来源 |
| MySQL Outbox | 通知事件和投递状态的持久权威来源 | 不保存 OpenID 或手机号副本 |

`ReservationService` 不应调用另一个普通业务 Service。可通过稳定端口或 Repository 写 Outbox；Worker 则作为独立组合根编排 Delivery Service 和 Provider。

---

## 5. 顾客授权与身份校验

### 5.1 推荐授权时机

预约创建成功后展示独立按钮：

> 接收店休取消微信通知

该按钮必须由顾客主动点击。不能在页面加载、后台任务或管理员设置店休时临时弹出授权；事件发生后再索取授权已经无法保证本次通知。

顾客拒绝、设备不支持、平台调用失败或暂时跳过时：

- 预约仍保持创建成功；
- 页面继续说明可以在“我的预约”查看状态；
- 管理端将该预约归入无订阅的电话兜底候选；
- 不反复弹窗或通过误导性按钮强迫授权。

默认只为顾客明确接受的结果创建服务端 Subscription 和加密 Recipient。拒绝、封禁或失败不应为了统计而先保存 OpenID；是否保存一个不含 Recipient 的“本次不再提醒”偏好，须在 N2.0 结合跨设备 UX 和最小化原则单独决定。

### 5.2 推荐登记流程

1. 小程序在明确点击中，以当前发布配置白名单中的模板 ID 调用 `requestSubscribeMessage`；模板 ID 虽不是 Secret，也不能由任意业务数据或管理员输入决定。
2. 顾客接受后，小程序再取得新的短期 `wx.login` code。
3. 小程序把 login code 和服务端允许的 `template_key` 发送给当前预约的 Owner-only API。
4. 后端调用 `code2Session`，取得本次原始 OpenID，并立即排除 `session_key`。
5. 后端使用现有 External Identity Pepper 计算 OpenID HMAC。
6. 在事务中锁定当前 User 与 ExternalIdentity，确认 provider、app_id、HMAC 均属于当前认证用户。
7. 使用通知专用 AEAD 密钥加密原始 OpenID，写入或更新隔离 Recipient。
8. 写入该 Reservation 的订阅意愿；原始 OpenID、login code 和 `session_key` 在请求结束前从业务对象中丢弃。

### 5.3 信任边界

- 客户端上报的 `accept` 只是客户端观察结果，不是平台签发的可信授权票据。最终是否可发送以 Provider 响应为准。
- 客户端不得提交 OpenID、UnionID、任意模板 ID、任意 Page Path、任意消息字段、用户 ID、Recipient ID 或密钥版本。
- 后端只接受短期 login code 和服务端枚举的 `template_key`。
- 新 code 换出的 HMAC 必须与当前已绑定身份匹配；登记通知不得隐式创建、绑定、合并或切换账号。
- UnionID 不用于本次小程序订阅消息投递，不为 N2 新增可逆加密 UnionID。
- 密码登录且没有微信身份绑定的用户不能登记微信订阅，继续使用 N1 电话兜底。
- 预约 Owner、当前用户、ExternalIdentity 与 Recipient 的关联必须在锁后复验，避免解绑、注销或转态并发绕过。
- 现有 HMAC 数据无法通过迁移还原 OpenID。既有用户必须再次进入小程序、主动授权并提供新的 login code，才能创建加密 Recipient。

### 5.4 撤回语义

用户侧撤回只影响尚未开始投递的未来任务：

- Subscription 标记 `withdrawn`；
- 尚未认领的对应 Outbox 转为 `suppressed/consent_withdrawn`；
- 已经提交给微信的请求无法召回；
- 如果 Provider 请求已经开始但结果未知，页面不能声称撤回已经阻止该条消息；
- 微信客户端自身的订阅设置由微信管理，应用只记录本系统的发送意愿。

---

## 6. 身份、隐私与密钥边界

### 6.1 当前契约冲突

[Phase 9.5 公开身份、安全与隐私基线](../09_release/phase95_public_security_baseline.md) 当前明确要求原始 OpenID/UnionID 不入库，只保存 HMAC。该规则非常适合身份查找，但 HMAC 不可逆，不能作为订阅消息投递地址。

N2 真正获批实施时，必须正式把边界修订为：

```text
身份查找用途：
原始 OpenID → External Identity Pepper HMAC → external_identities

消息投递用途：
原始 OpenID → 通知专用、版本化 AEAD 加密 → wechat_notification_recipients
```

延期规划阶段不得先修改 Phase 9.5 当前事实，否则会把尚未实现的数据处理能力误报为现状。

### 6.2 加密要求

- 使用具备机密性和完整性保护的 AEAD 方案；具体算法由实现时安全评审冻结。
- 每条 Recipient 使用安全随机 Nonce/IV，不采用确定性加密。
- 认证 Tag 必须与密文一并保存或包含在明确的密文封装格式中；任何 Tag 校验失败都要 Fail Closed。
- Associated Data 至少绑定 provider、app_id、user_id、external_identity_id、数据格式版本和 key version，防止跨行或跨用途替换密文。
- OpenID 加密密钥必须独立于微信 AppSecret、JWT Secret、数据库凭据和 External Identity Pepper。
- 密钥只通过正式 Secret Manager 或项目批准的 Secret 文件边界提供，不能进入源码、迁移、普通环境文件、日志、测试夹具或发布产物。
- App 与 Worker 只获得其运行所需的最小密钥读取权限；不需要解密的管理 API 不应获得解密能力。
- 数据库备份虽然只含密文，仍属于个人信息处理范围；备份与加密密钥必须分离保存和授权。

### 6.3 密钥轮换

轮换必须支持：

1. 新写入只使用最新 key version；
2. Worker 在受控期间可读取当前和有限数量的旧版本；
3. 后台受控批次重新加密旧 Recipient，记录数量与失败但不记录内容；
4. 抽样或全量验证新密文可解密且 HMAC 仍匹配对应身份；
5. 所有活动 Recipient 完成重加密、备份策略确认并经过回滚窗口后，才撤销旧密钥；
6. 轮换中断可以从游标恢复，不产生明文中间文件。

不得直接替换密钥后让历史 Recipient 永久不可用。

### 6.4 最小化与删除

- Outbox 不复制 OpenID 明文或密文，只引用 Recipient。
- Outbox Payload 不包含手机号、昵称、头像、管理员自由文本或 Provider 完整响应。
- 用户解绑微信时撤回相关 Subscription、抑制尚未开始的任务并删除 Recipient。
- 用户注销时执行同样处理。预约已经因店休取消，不再阻止注销；手机号匿名化后，人工兜底显示 `contact_unavailable`。
- 已开始的 Provider 请求无法可靠召回。实现必须记录这一竞态语义，并确保注销提交后不会启动新的发送；不得为了等待网络请求而长时间持有数据库事务。
- Recipient、Subscription、Outbox 元数据和日志的精确保留期限必须在 N2.0 由产品/隐私负责人批准。本规划不凭空指定天数。
- 数据导出、删除、备份过期与事故响应都要覆盖新表和密钥用途。
- Worker 解密 OpenID 后必须重新计算现有 ExternalIdentity HMAC，并与关联身份记录比较；不匹配时停止投递、进入安全终态并触发高优先级告警。

---

## 7. 业务事件与消息契约

### 7.1 首个事件

| 字段 | 冻结值 |
|------|--------|
| Event Type | `reservation_cancelled_store_closed` |
| Aggregate | `reservation` |
| 触发条件 | `pending/confirmed` 且尚未开始的预约在设置店休事务中实际转为 `cancelled/store_closed` |
| 不触发 | 已取消、已拒绝、已经开始、重复设置店休、恢复营业、N2 启用前历史记录；N1 没有 `completed` 状态 |
| 权威事实 | Reservation 状态、取消原因和时间 |
| 投递渠道 | `wechat_subscription` |
| 兜底渠道 | 当前 `User.phone` 的人工电话；不保存快照 |

同一 Reservation 只有一次该业务事件。唯一键不得因模板版本变化而重新生成同一取消通知。

### 7.2 唯一业务键

建议 Outbox 唯一业务键覆盖：

```text
(event_type, aggregate_type, aggregate_id, channel)
```

其中 `aggregate_id` 是 Reservation ID。`template_version` 是事件发生时的发送快照，不进入唯一键；否则模板升级可能让同一取消事实重复通知。

如未来同一事件需要多个微信 App 或接收主体，应在重新评审后将明确的 destination scope 加入唯一键，不能直接放宽现有唯一约束。

### 7.3 最小消息快照

Outbox Payload 可以保存：

- Reservation ID 或对外预约编号；
- 上海当地预约日期；
- 上海当地开始与结束时间；
- 固定原因 `store_closed`；
- 服务端白名单中的预约详情 Page Key；
- 业务文案版本和模板版本；
- 事件发生时间。

Payload 不保存：

- OpenID 明文或密文；
- 手机号、昵称、头像；
- Access Token、AppSecret、login code 或 session_key；
- 管理员自由输入、内部备注或操作者身份；
- 任意客户端 Page Path 或模板字段；
- 微信完整响应体。

### 7.4 文案和模板映射

- 数据库只保存机器原因和最小快照，不持久化任意顾客文案。
- Mapper/Provider 通过版本化服务端映射构造模板字段。
- 模板字段只允许白名单值，并按实施时官方规则验证类型与长度。
- 详情 Page 由固定 Key 映射到受支持的线上路径，不能把客户端或数据库任意字符串直接交给微信。
- 模板或文案版本升级只影响之后新产生的事件，不重写已提交 Outbox，不补发历史事件。

---

## 8. 数据模型候选

以下全部是 N2 通知扩展的设计候选，不是已经存在的通知表。Reservation N1 的 `store_business_days` / `reservations`、字段、外键、索引和 Enum 已由主契约与已实施的 M5 冻结；N2 表的最终字段长度、数据库类型、外键动作、索引顺序和 Enum 表示仍必须结合 N1 Tortoise Model、MySQL 8 DDL 与查询计划另行评审。

### 8.1 `wechat_notification_recipients`

| 字段 | 用途 |
|------|------|
| `id` | 主键 |
| `user_id` | 当前普通用户 |
| `external_identity_id` | 被复验的微信身份绑定 |
| `provider` | 固定服务端 Enum，例如 `wechat_miniprogram` |
| `app_id` | 区分具体小程序 App，非客户端输入 |
| `openid_ciphertext` | AEAD 密文 |
| `openid_nonce` | 随机 Nonce/IV |
| `openid_auth_tag` | 若密文封装未包含 Tag，则单独保存认证 Tag |
| `encryption_format_version` | 密文封装/算法格式版本 |
| `encryption_key_version` | Secret key version 引用，不是密钥值 |
| `status` | `active/revoked` 等最小内部状态 |
| `verified_at` | 最近一次用新 code 服务端复验时间 |
| `revoked_at` | 解绑/注销/撤回后的时间 |
| `created_at/updated_at` | 审计时间 |

候选约束：

- `(user_id, provider, app_id)` 唯一；
- `(external_identity_id, provider, app_id)` 唯一或等价约束；
- 推荐由 Recipient 到 ExternalIdentity 使用 `RESTRICT`，让解绑/注销在遗漏显式密文清理时直接失败，而不是留下孤儿投递地址；
- Recipient 不保存手机号；
- 普通管理查询不得读取密文字段；
- 解绑/注销最终删除 Recipient。若短期保留撤销行用于事务收敛，保留窗口和物理删除任务必须由隐私评审冻结。

### 8.2 `reservation_notification_subscriptions`

| 字段 | 用途 |
|------|------|
| `id` | 主键 |
| `reservation_id` | Owner 的预约 |
| `recipient_id` | 当前可投递 Recipient |
| `notification_kind` | `reservation_cancelled_store_closed` |
| `channel` | `wechat_subscription` |
| `template_key` | 服务端稳定能力键，不是客户端任意 Template ID |
| `template_id_snapshot/template_version` | 本次用户授权所针对的准确模板绑定 |
| `consent_notice_version` | 顾客点击时看到的通知用途说明版本 |
| `status` | `available/reserved/consumed/withdrawn/invalidated` |
| `accepted_at` | 顾客接受时间 |
| `reserved_at` | 店休事务把这次意愿保留给本业务事件的时间 |
| `withdrawn_at` | 本系统撤回时间 |
| `consumed_at` | 某次发送尝试已消费该意愿的内部时间；具体语义实施时按平台规则冻结 |
| `created_at/updated_at` | 审计时间 |

候选约束：

- `(reservation_id, notification_kind, channel, template_key)` 唯一；
- Reservation 与当前 User 的 Owner 关系必须由 Service 锁后复验；
- 客户端观察到 `accept` 不等于服务端承诺一定可投递；
- 只有明确接受才创建 `available` 记录；`available → reserved` 只能在店休取消事务中发生，Provider 明确接受后才进入 `consumed`；
- 模板实际 ID/版本由服务端配置快照，不允许客户端指定；模板切换后旧授权不能自动用于新模板；
- 如果目标账号支持的订阅形式与上述模型不兼容，必须在 N2.0 重新修订，不能强行套用。

### 8.3 `notification_outbox`

| 字段 | 用途 |
|------|------|
| `id` | 单调主键，用于稳定批次顺序 |
| `event_id` | 内部逻辑事件标识 |
| `event_type` | `reservation_cancelled_store_closed` |
| `aggregate_type` | `reservation` |
| `aggregate_id` | Reservation ID |
| `user_id` | 业务 Owner，用于权限、删除和运营筛选 |
| `subscription_id` | 事件发生时符合条件的订阅引用 |
| `channel` | `wechat_subscription` |
| `template_key/template_version` | 服务端模板快照 |
| `payload` | 版本化最小 JSON 快照 |
| `status` | `pending/processing/retry_wait/delivery_unknown/provider_accepted/dead/suppressed` |
| `attempt_count` | 已开始的 Provider 尝试次数 |
| `next_attempt_at` | 下次可认领时间 |
| `lease_owner` | Worker 实例的脱敏随机 ID，不含主机敏感信息 |
| `lease_token/lease_generation` | Fencing Token，阻止过期 Worker 覆盖新一代认领结果 |
| `lease_expires_at` | 崩溃恢复租约 |
| `dispatch_started_at` | 已经准备进入 Provider 网络调用的边界标记 |
| `last_error_category` | 稳定、脱敏内部分类 |
| `last_provider_error_code` | 仅在安全评审允许时保存最小错误码 |
| `provider_accepted_at` | 微信接口确认接受请求的时间 |
| `delivery_unknown_at` | 请求可能已到达 Provider、但本地无可信结果的时间 |
| `dead_at/suppressed_at` | 终态时间 |
| `created_at/updated_at` | 审计时间 |

不要预设一定存在 `provider_message_id`。只有实施时确认微信当前接口可靠返回且确有收敛价值时，才增加可空字段。

候选索引：

- UNIQUE：`(event_type, aggregate_type, aggregate_id, channel)`；
- Claim：`(status, next_attempt_at, id)`；
- Lease 回收：`(status, lease_expires_at, id)`；
- 用户/人工兜底：`(user_id, status, created_at, id)`；
- 业务追踪：`(aggregate_type, aggregate_id, created_at)`。

索引顺序必须用最终查询和 MySQL `EXPLAIN` 验证，不以本草案替代证据。

### 8.4 外键与删除候选

- Outbox 不得通过 FK 阻止账号注销或微信解绑。
- Recipient 删除后，Outbox 应保留非敏感业务/投递审计，但 Recipient/Subscription 引用可以置空或转为不可投递终态。
- 用户注销前，在同一受控流程中先撤回订阅并把未开始任务转为 `suppressed/account_deleted`，再删除 Recipient 和执行 User 匿名化。
- 已经 `processing` 的任务必须按第 12 节竞态策略处理；不得持有数据库事务等待微信网络调用。
- 最终 FK 的 `RESTRICT/SET NULL` 组合必须通过真实 MySQL 删除、回滚和并发测试确认。

---

## 9. 店休事务与 Transactional Outbox

### 9.1 事务顺序

启用 N2 后，设置店休的完整事务建议为：

1. 在一次用例入口读取一次 `now`；营业日判断使用 `Asia/Shanghai`。
2. 锁定目标 `StoreBusinessDay` 权威行，锁后确认是否已经店休。
3. 首次关闭时写入店休事实。
4. 按 Reservation ID 升序锁定该营业日内、尚未开始且状态为 `pending/confirmed` 的预约。
5. 锁后重检范围和状态，批量更新为 `cancelled/store_closed`。
6. 批量写 Reservation 取消审计和店休审计。
7. 对本次实际发生状态迁移且具备有效 Subscription 与 Recipient 的预约，把 Subscription 从 `available` 原子转为 `reserved`，并批量写 Outbox。
8. 整体提交。

任一步失败时，营业日、预约、审计和 Outbox 全部回滚。

### 9.2 原子性与幂等

- 事务内只访问 MySQL，不获取 Access Token，不请求微信。
- 重复设置同一天店休是业务幂等重放：`newly_cancelled_count=0`、`notification_enqueued_count=0`，不重复审计和入队。
- Outbox UNIQUE 是并发兜底，不替代锁后业务判断。
- MySQL 1205/1213 只能用全新事务重试整个店休用例，不能只重放最后一次批量写。
- 创建预约与设置店休必须锁同一营业日权威行，并遵循一致锁序，防止“店休和新预约同时成功”。
- 大批预约要批量查询、更新、审计和插入 Outbox，禁止循环逐条 `await`。
- 如单日预约规模超过单事务安全阈值，必须重新评审关闭策略和上限；不能把一个逻辑店休日拆成可观察的半完成状态。

### 9.3 接口同步可返回的计数

店休接口可以在提交后返回：

- `newly_cancelled_count`；
- `notification_enqueued_count`；
- `immediate_manual_contact_count`：提交时已经确定没有订阅或投递地址的数量。

店休接口不能同步返回：

- `provider_accepted_count`；
- `delivered_count`；
- `final_manual_contact_count`。

发送发生在事务提交之后，稍后进入 `dead/suppressed` 的预约会继续加入人工兜底清单。

### 9.4 功能开关行为

- N2 总开关默认关闭。
- 开关关闭时，店休与批量取消照常成功，不创建通知 Outbox，所有受影响预约走 N1 页面状态和电话兜底。
- 开关开启且数据库 Outbox 写失败时，店休事务整体回滚，避免出现“系统承诺已启用通知但业务事件没有可靠记录”。
- Worker 暂时不可用不会阻止店休提交；Outbox 持久积压并触发告警。
- 订阅登记 Provider 不可用时，登记接口返回稳定 503 且零写入，但已经创建的预约不受影响。

---

## 10. API 与前端交互候选

以下路径和字段是评审候选。Reservation 主 API 契约存在后再冻结最终命名。

### 10.1 用户侧 API

```text
POST   /api/v1/reservations/{reservation_id}/notification-subscriptions/wechat
GET    /api/v1/reservations/{reservation_id}/notification-subscription
DELETE /api/v1/reservations/{reservation_id}/notification-subscription
```

`POST` 请求只允许：

- 短期 `wx.login` code；
- 服务端枚举的 `template_key`。

`POST` 请求禁止：

- OpenID/UnionID；
- user_id/recipient_id；
- 任意微信 Template ID；
- 任意 Page Path；
- 任意消息正文或模板字段；
- `accepted_at`、key version 或投递状态。

所有接口严格 Owner-only。不存在或不属于当前用户的 Reservation 采用项目统一资源隐藏语义。Reservation 已经开始或进入终态后是否允许新登记，应在主契约中固定；本规划推荐拒绝，因为已发生事件不能依赖事后授权补发。

登记接口还需要独立的 IP + User + Reservation 维度限流；Redis 故障遵循身份敏感操作的 Fail Closed 语义。客户端在响应未知时先查询当前 Subscription 状态，不能盲目重复弹出平台授权或重复创建记录。

`GET` 只返回业务级信息，例如：

```text
capability: available | unavailable
subscription_status: not_requested | enabled | reserved | withdrawn | consumed | unavailable
delivery_status: not_applicable | queued | retrying | delivery_unknown | provider_accepted | dead | suppressed
manual_contact_required: boolean
```

不得返回内部 Outbox ID、OpenID、密文、Nonce、Key Version、Access Token、平台原始错误或 Worker 信息。

默认最小化方案不向服务端写入 `client_rejected` 记录；顾客没有接受时，服务端只表现为没有可用 Subscription。若未来为了跨设备 UX 保存“本次不再提示”，必须另行评审该偏好的用途和保留期限。

`DELETE` 表示撤回本系统未来发送意愿，不代表修改微信客户端全局设置，也不能召回已经交给 Provider 的请求。

### 10.2 Reservation 响应扩展

顾客 Reservation 列表/详情仍以业务状态为主，可增加一个可空、非权威的通知摘要：

```text
notification:
  channel: wechat_subscription
  subscription_status: ...
  delivery_status: ...
  manual_contact_required: true | false
```

即便通知摘要加载失败，Reservation 的 `cancelled/store_closed` 状态和站内文案也必须正常展示。

### 10.3 管理侧能力

管理端可展示或筛选：

```text
no_consent
no_recipient
queued
retrying
delivery_unknown
provider_accepted
dead
suppressed
contact_unavailable
```

其中：

- `no_consent/no_recipient` 是业务投递资格摘要，不要求创建无意义 Outbox；
- `provider_accepted` 只表示微信接口确认接受请求，不表示顾客已查看或最终送达；
- `delivery_unknown/dead/suppressed/no_consent/no_recipient` 进入电话兜底候选；
- 电话只读取当前 `User.phone`。列表显示掩码，ADMIN+ 详情按 N1 规则显示完整号码；为空时显示 `contact_unavailable`。

管理 API 不返回 OpenID、密文、模板原始字段、Access Token、完整 Provider 响应或客户端授权明细。

首版不提供通用“重新发送”按钮。网络结果未知、一次订阅是否已消费和重复消息风险无法通过一个无约束按钮安全解决。运维重放必须通过受控 Runbook、明确任务 ID、状态前置条件和审计执行。

### 10.4 小程序 UX

- 预约成功和通知授权是两个独立反馈，不能让授权弹窗掩盖预约结果。
- 按钮说明仅承诺“尝试通过微信提醒”，不承诺必达。
- 拒绝后不循环弹窗，可保留“在我的预约查看状态”的固定提示。
- 非微信环境、基础库不支持或配置关闭时隐藏/禁用微信授权入口，但不影响预约功能。
- 顾客回到详情页时，以后端 Reservation 和通知摘要为准，不使用本地授权结果推断已经发送。
- 店休消息跳转到受 Owner 鉴权保护的预约详情；登录失效时先正常恢复会话，再校验归属。

---

## 11. Provider 与 Access Token 管理

### 11.1 Provider 边界

新增独立的微信订阅消息 Provider，不把发送职责塞进现有 `code2Session` 适配器。Provider 接受经过业务层白名单化的 DTO，并只返回最小标准结果，例如：

```text
accepted
retryable_failure(category, safe_code)
permanent_failure(category, safe_code)
unknown_outcome(category)
```

Provider 负责：

- 复用有明确生命周期的 HTTP Client，并在 Worker 关闭时释放连接；
- 构造并校验微信协议请求；
- 获取 Access Token；
- 应用统一超时；
- 映射 HTTP、JSON、平台错误和未知结果；
- 对 Token 明确失效执行至多一次强制刷新；
- 输出脱敏结构化事件。

Provider 不负责：

- 修改 Reservation；
- 决定顾客是否有权限；
- 写业务审计；
- 无限重试；
- 记录完整请求或响应；
- 把平台错误直接暴露给用户。

### 11.2 Access Token

- Access Token 是应用级短期凭据，不保存到业务表。
- Redis 可作为共享短期缓存；缓存值必须有安全 TTL，并在平台到期前提前刷新。
- 多 Worker 使用 Single-flight 或等价协调，避免同时刷新造成惊群。
- 获取失败时不能退回日志中的旧 Token，也不能把 Token 放进 URL 日志、指标标签或异常正文。
- Redis 故障时的策略必须明确。推荐发送链路暂缓并重试，不能每个 Worker 无限制直连刷新。
- Token 明确失效时清除缓存、强制刷新一次；再次失败按错误分类进入 Retry 或 Dead，不形成刷新循环。
- AppSecret 继续通过受控 Secret 边界读取；App 与 Worker 的访问权限和轮换必须有独立审计。

---

## 12. Worker、租约与投递语义

### 12.1 独立 Worker

Worker 应是独立进程/容器和组合根，不使用 FastAPI 进程内 BackgroundTasks 作为可靠投递机制。原因是 Web 进程重启、扩缩容和请求生命周期都不能保证任务持久执行。

首版建议直接轮询 MySQL Outbox，不为单个事件引入 Celery、RQ 等新队列依赖。若未来吞吐量证明需要消息队列，再通过 ADR 扩展；MySQL Outbox 仍是业务事件的持久权威来源。

### 12.2 认领流程

1. 按 `(next_attempt_at, id)` 稳定顺序选取到期的 `pending/retry_wait`。
2. 在短事务中使用 MySQL 8 支持且经真实测试的行锁/跳锁策略认领，设置 `processing`、lease owner、随机 lease token、递增 generation 和 expiry。
3. 提交认领事务后再进行解密、Token 获取和微信 HTTP 调用。
4. 在真正发起网络请求前持久标记 `dispatch_started_at`；该标记用于区分“安全重试”和“可能已经发送”。
5. 在新事务中使用 `WHERE id + lease_token + lease_generation + status` 的条件更新，收敛为 `provider_accepted/retry_wait/delivery_unknown/dead/suppressed`。
6. Worker 崩溃后，过期 lease 可由其他 Worker 回收；未过期 lease 不重复认领。旧 Worker 的迟到结果因 Fencing Token 不匹配而被拒绝。

批次大小、Lease 时长、轮询间隔、最大并发和最大重试次数全部通过配置提供合理上下限，不能写成不可调 Magic Number。

### 12.3 发送前复验

每次发送前至少复验：

- Outbox 仍由当前 Worker 持有有效 Lease；
- Reservation 确实是 `cancelled/store_closed`；
- 该事件没有被 Provider 接受或终止；
- Subscription 仍为当前事件保留、没有撤回且符合当前发送语义；
- User 仍为 `NORMAL USER`，微信 ExternalIdentity 仍属于该 User；
- Recipient 存在、状态有效、AppID 匹配且密文可解；
- 解密所得 OpenID 的 HMAC 与当前 ExternalIdentity subject 再次匹配；
- 模板配置和目标 Page 仍在服务端白名单中。

复验失败时进入明确的 `suppressed` 原因，不调用微信。

### 12.4 投递保证

本地 UNIQUE、Lease 和 Fencing Token 可以避免大部分应用内部重复，却无法消除“微信已经接受请求，Worker 在收到响应前网络超时”的不确定结果。如果平台没有业务幂等键或可靠查询，Exactly-once 不可实现。

实施前必须从以下两种策略中明确选择并获批：

| 策略 | 网络结果未知后的处理 | 代价 |
|------|----------------------|------|
| 保守 At-most-once | 转 `delivery_unknown` 并进入电话兜底，不自动再次发送 | 更少重复消息，但微信实际未接受时会漏发 |
| 有界 At-least-once | 在明确次数/时窗内自动重试 | 更少漏发，但微信已接受而响应丢失时可能重复 |

考虑 N1 电话兜底始终存在，本文建议 N2 首次启用默认采用保守策略：`delivery_unknown → manual_contact_required`。只有项目负责人书面接受潜在重复后，才把 Unknown 纳入有界自动重试。

无论最终选择哪种策略，都遵循：

- 确认平台成功时记录 `provider_accepted`，不用 `delivered` 或“顾客已收到”；
- 明确且可以证明请求尚未被 Provider 接受的临时失败，按退避策略重试；
- 明确永久失败进入 `dead` 或 `suppressed`；
- Worker 在 `dispatch_started_at` 之前崩溃可以安全恢复；在该时间之后且没有可信结果时必须先进入 `delivery_unknown`，不能当作普通 Retry；
- 固定文案具备幂等语义，不制造新的业务承诺；
- 如果实施时确认平台提供可靠 Message ID、结果事件或查询能力，可以用于状态收敛，但不得未经验证预设存在。

### 12.5 解绑/注销竞态

数据库事务不能跨微信 HTTP 调用持锁，因此已经开始的外部请求无法完全召回。实现必须冻结并测试以下边界：

- 解绑/注销提交后，尚未开始 Provider 调用的任务不得再发送；
- 注销流程锁定 User 后撤回 Subscription、抑制未开始任务并删除 Recipient；
- Worker 在外部调用前尽可能晚地复验 Recipient 和账号状态；
- 已经进入网络调用的任务可能在注销提交后获得 Provider 接受结果，系统必须如实记录，不声称能够召回；
- 不为了等待未知网络结果而阻塞账号注销或长时间持有数据库锁；
- 对该竞态的用户说明、隐私记录和运维处置必须在 Gate B 前完成 Review。

---

## 13. 错误分类、重试与 Dead-letter

具体微信 errcode 必须在实施时依据当时官方文档和目标账号验证；项目只冻结稳定的内部类别。

| 内部类别 | 示例 | 默认处理 |
|----------|------|----------|
| `network_transient_before_dispatch` | 能证明请求尚未发出的连接失败、临时 DNS/出口故障 | 指数退避 + Jitter，有限重试 |
| `provider_transient` | 5xx、平台繁忙、明确限流 | 尊重平台策略，有限重试 |
| `access_token_invalid` | 平台明确指出 Token 失效 | Single-flight 强刷一次，再按结果收敛 |
| `unknown_outcome` | 写入/响应超时等导致请求可能已被接受 | 先转 `delivery_unknown`；按 N2.0 批准策略走电话兜底或有界重试 |
| `no_consent` | 没有用户订阅意愿 | 不入可发送 Outbox；电话兜底 |
| `consent_withdrawn` | 发送前已撤回 | `suppressed`；电话兜底 |
| `no_recipient` | 无加密 OpenID 或已删除 | `suppressed`；电话兜底 |
| `account_deleted` | 用户已注销 | `suppressed`；手机号也可能不可用 |
| `identity_mismatch` | Recipient 与绑定不一致 | `dead` + 高优先级安全事件，不发送 |
| `decrypt_failed` | 密文损坏或 key version 不可读 | `dead` + Critical 运维告警，不记录内容 |
| `template_invalid` | 模板、字段或 Page 配置错误 | `dead` + 配置告警，禁止无限重试 |
| `provider_rejected_permanent` | 无订阅次数、接收方或权限被平台永久拒绝 | `dead`；电话兜底 |

重试策略要求：

- 指数退避加随机 Jitter；
- 最大尝试数与最大年龄都有上限；
- 明确区分连接前失败和发送后结果未知，不能把所有 Timeout 都当作安全重试；
- Retry 不延长或改变 Reservation 取消状态；
- 到达上限后持久进入 `dead`，不能静默丢弃；
- 运维修复配置后只允许通过受控命令重放明确的 Retry/Dead 集合；
- 重放保留原事件唯一键、尝试历史和审计，不创建“新业务事件”；
- 日志和错误字段只保存稳定分类、允许的错误码、attempt 和 trace ID，不保存请求体、OpenID 或完整响应。

---

## 14. 人工电话兜底

N2 上线后仍必须保留 N1 电话兜底，因为以下情况无法通过微信可靠覆盖：

- 顾客未绑定微信；
- 顾客拒绝、跳过或无法请求订阅；
- 既有用户尚未重新提供 login code，只有不可逆 HMAC；
- Recipient 已撤销、解绑或删除；
- 微信永久拒绝或 Outbox 进入 Dead；
- 网络结果长期未知；
- 模板或平台临时不可用；
- 顾客已注销，且当前手机号也已匿名化。

建议管理列表以 Reservation 为单位展示：

| 兜底状态 | 含义 |
|----------|------|
| `not_required_yet` | 仍在正常队列或重试窗口内 |
| `manual_contact_required` | 无授权、无 Recipient、Dead 或明确 Suppressed |
| `contact_available` | 当前 `User.phone` 存在；列表掩码、详情可查看 |
| `contact_unavailable` | 当前手机号为空或账号已注销 |

首版不把“已拨打/未接通/已确认”塞进 Reservation 状态或 Notification 状态。如果门店确实需要联系过程追踪，应另行设计最小 Contact Attempt 模型、权限、审计和保留期限。

---

## 15. 配置、Secret 与部署

### 15.1 非 Secret 配置候选

- `WECHAT_RESERVATION_NOTIFICATIONS_ENABLED=false`；
- 服务端 `template_key → template_id/template_version` 映射；
- 预约详情 Page Key 映射；
- Provider HTTP timeout；
- Worker batch size、poll interval、lease duration、concurrency；
- Retry base/max interval、Jitter 和 max attempts；
- Token 提前刷新窗口；
- Payload/schema version。

所有配置必须有安全默认值和范围校验。Template ID 虽通常不是 Secret，也不能接受客户端任意覆盖。

### 15.2 Secret 候选

- 微信 AppSecret：沿用现有 Secret 边界，授权给需要换取 Token/身份的进程；
- `WECHAT_NOTIFICATION_OPENID_ENCRYPTION_KEY`：新增独立、版本化 Secret；
- Redis/数据库凭据：沿用现有正式运行边界；
- 监控平台凭据：若新增，纳入 Secret Inventory。

Secret 的标识与版本可以进入 Release Record，值不能进入 Git、普通文档、Compose 参数、日志或测试报告。

### 15.3 部署单元

未来至少需要：

- API/App 服务；
- 独立 Notification Worker；
- MySQL 8；
- Redis（Token 缓存/协调，可故障恢复）；
- Secret 注入；
- 集中日志、指标和告警接入。

Worker 需要：

- Liveness：进程和事件循环存活；
- Readiness：数据库、必要 Secret 和基本配置可用；
- 不把微信平台短期故障错误标成进程死亡；
- SIGTERM 优雅停止认领新任务，并在有限时间内完成或释放当前 Lease；
- 明确的单实例/多实例扩容语义；
- 与 App 相同版本的消息 Payload 与模板映射兼容策略。

部署安全边界还应包括：

- App 与 Worker 使用非 Root、只读根文件系统和最小文件/网络权限；
- Worker 只能读取微信 AppSecret、通知加密密钥及必要的 DB/Redis 凭据，不得读取 DB Root、JWT、管理员初始化或图片存储管理凭据；
- 数据库迁移 Job 不获得 AppSecret 或 Recipient 解密密钥；
- 如基础设施支持，Worker 只允许访问必要的 MySQL、Redis、Secret/监控端点和 `api.weixin.qq.com:443`；
- App Readiness 不因微信平台短期故障而失败，预约核心功能继续可用；通知退化由 Worker Readiness、队列指标和告警独立表达。

---

## 16. 可观测性与告警

### 16.1 指标

至少采集：

- Outbox `pending/retry_wait/processing/delivery_unknown/dead/suppressed/provider_accepted` 数量；
- 最老 Pending/Retry Wait 年龄；
- Worker claim 数、Lease 过期与回收数；
- 投递尝试延迟和 Provider 调用耗时；
- Access Token 缓存命中、正常刷新、强制刷新和失败数；
- Provider 错误类别与允许的脱敏错误码；
- Recipient 解密失败和身份复验失败；
- 每次店休的取消数、入队数、Provider 接受数、Dead 数；
- 无授权、无 Recipient、需电话和电话不可用数量。

指标标签不得包含 user_id、Reservation 编号、手机号、OpenID、密文、Template 原始内容或高基数错误正文。

### 16.2 结构化日志与安全事件

实施时按现有 Allowlist 机制新增必要的稳定事件，例如：

- `wechat_notification_subscription`；
- `wechat_notification_delivery`；
- `wechat_notification_token`；
- `wechat_notification_recipient_decrypt`；
- `notification_outbox_lease_recovered`。

事件名和 outcome 必须在实现时同步代码、文档与测试；当前仓库并不具备这些事件，不能在本规划中标记为已实现。

日志只包含最小操作上下文和不可逆/内部 trace 标识。禁止记录 OpenID、login code、Access Token、AppSecret、密文、Nonce、手机号、请求/响应体或带凭据 URL。

### 16.3 业务审计与投递尝试记录

现有 AuditLog 只记录有业务或权限意义的动作，例如：

- 顾客启用或撤回该 Reservation 的微信通知；
- 管理员设置/恢复店休；
- Reservation 被门店批量取消；
- 有权限的运维人员执行受控 Dead 重放或取消投递；
- 密钥轮换批次的版本 ID、数量和结果摘要。

高频自动认领、正常发送和每次自动重试不逐条写现有人工 AuditLog，避免噪声和写放大。Outbox 本身保存当前投递事实；如果事故调查或 SLA 需要逐次历史，可以新增有限保留期的 `notification_delivery_attempts`，只记录 outbox_id、attempt_no、lease_generation、开始/结束时间、结果、稳定错误类别、允许的错误码、HTTP 状态和延迟，不保存 OpenID、请求/响应体或凭据。

Audit description 只允许内部 ID、稳定状态/原因、计数和 Secret version ID，不得包含手机号、OpenID/HMAC、密文、Nonce、模板数据、Provider errmsg、Access Token 或 login code。批量店休若要求每条预约留审计，必须提供批量写边界，不能循环逐条 `await`。

### 16.4 告警证据

告警至少覆盖：

- Pending/Retry Wait 积压或最老任务超出目标；
- Dead 持续出现或单次店休异常增长；
- Worker 不再认领；
- Lease 大量过期；
- Access Token 连续刷新失败；
- Recipient 解密失败或身份不一致；
- 模板配置类永久错误；
- 人工电话兜底积压。

阈值必须基于试运行容量和运营 SLA 冻结，本规划不虚构具体数值。正式 Gate B 证据需要证明：信号真实产生、平台收到、责任人收到、升级链生效、恢复后清除，以及全过程日志脱敏。结构化日志格式本身不是告警送达证据。

---

## 17. 测试与验收矩阵

### 17.1 单元测试

- Subscription、Recipient、Outbox 输入和输出 Schema 严格字段；
- 状态机与非法转移；
- Event Key 稳定性和模板版本不造成重复事件；
- AEAD 加解密、Associated Data 篡改、错误 key version 与轮换双读；
- Provider DTO 白名单、模板字段和 Page Key 映射；
- 平台响应到内部错误类别的映射；
- 指数退避、Jitter 上下界、最大次数和最大年龄；
- 日志/异常/指标不包含敏感字段；
- Mapper 零 SQL、零 ORM 修改与字段投影。

### 17.2 Service 与事务测试

- Owner-only 授权登记，未知字段和非法 Template Key 拒绝；
- code2Session 身份与当前 ExternalIdentity 匹配；
- 客户端不能伪造 OpenID、Recipient 或其他用户 Reservation；
- 加密 Recipient、Subscription 和相关审计原子提交；
- 任一步失败全部回滚，原始身份不落库/日志；
- 店休、批量取消、审计和 eligible Outbox 同事务提交；
- Outbox 失败时店休完整回滚；
- 店休提交后 Provider 失败不回滚 Reservation；
- 重复设置店休不重复入队；
- 无授权/无 Recipient 不创建可发送 Outbox并进入电话候选；
- 恢复营业不恢复预约、不生成通知；
- N2 开启前历史取消不补发；
- 解绑/注销撤回订阅、抑制任务、删除 Recipient；
- 账号注销后手机号为空时展示 `contact_unavailable`。

### 17.3 Worker 与故障测试

- 单 Worker 稳定顺序认领；
- 多 Worker 并发下同一任务不会被同时正常处理；
- 认领后崩溃、Lease 过期和其他 Worker 恢复；
- Provider 成功、明确临时失败、永久失败与未知结果；
- Token 缓存命中、Single-flight、提前刷新和明确失效后单次强刷；
- Redis 不可用、微信 5xx、限流、超时和畸形 JSON；
- 达到最大尝试后进入 Dead 并进入电话清单；
- 进程 SIGTERM 停止认领、完成或释放 Lease；
- Payload/模板版本兼容和滚动部署；
- 解绑/注销与 Worker 发送前复验的竞态；
- 已进入网络调用后注销的明确不可召回语义；
- 受控重放不创建新业务事件、不绕过唯一键和审计。

### 17.4 真实 MySQL 门槛

在一次性 MySQL 8.0.46 或项目当时冻结的 MySQL 8 版本中验证：

- 从实际最新 Aerich 版本完整升级到 N2 迁移；
- UNIQUE、FK、NULL、索引、JSON/文本类型和降级风险；
- 店休与创建预约并发；
- 两个店休日、反向日期和大量 Reservation 的稳定锁序；
- 多 Worker Claim、跳锁/Lease 和崩溃恢复；
- 1205/1213 全事务重试；
- 账号注销/解绑与 Outbox 认领并发；
- 核心 Claim、人工兜底和业务追踪查询的 `EXPLAIN` 命中预期索引；
- 大批量写入没有 N+1 或循环单条 `await`。

SQLite 行为测试不能替代 MySQL 锁、索引和类型兼容证据。

### 17.5 小程序与真实微信验收

- 明确点击触发授权；
- Accept、Reject、Ban、Fail、取消弹窗和重复进入；
- 非微信端或不支持环境的降级；
- 预约成功与授权失败的独立反馈；
- 正式 Template ID 和字段类型/长度；
- Developer/Trial/Formal 环境；
- iOS/Android 真机；
- 微信登录过期与详情 Page 跳转；
- 账号不匹配、解绑、注销、拒收和订阅机会不可用；
- Provider 接受后页面仍以 Reservation 状态为权威；
- 弱网、前后台切换和重复点击；
- 隐私指引、同意/撤回文案和客服联系方式。

### 17.6 安全与隐私验收

- 数据库、备份抽样、日志、审计、错误响应、指标和前端存储中无 OpenID 明文；
- 普通 API 和管理 API 均不返回密文、Nonce、Key Version 或 Provider 原始响应；
- 加密密钥与 AppSecret/JWT/Pepper 独立；
- 密钥轮换、新写旧读、重加密、回滚和旧 key 撤销演练；
- 最小权限证明 App/Worker/管理查询的读取边界；
- 解绑、注销、数据导出、删除和备份过期覆盖新数据；
- 保留期限、处理目的、隐私材料和用户权利获得批准；
- Secret/PII 扫描覆盖源码、构建产物、容器配置和测试报告。

---

## 18. 分阶段实施建议

不要把 N2 命名为现有 Phase 9.6，也不要提前写死数据库迁移号。

| 阶段 | 工作范围 | 退出条件 |
|------|----------|----------|
| N2.0 决策与平台可行性 | 产品批准、首个事件、模板/类目、订阅形式、投递语义、隐私目的、保留期限、RDR | 所有开放决策有 Owner 和书面结论；目标账号验证可行 |
| N2.1 数据保护与 Schema | Recipient、Subscription、Outbox、AEAD、密钥生命周期、迁移与回滚设计 | 安全/隐私/数据库 Review 通过；迁移编号按实际链确定 |
| N2.2 授权与身份 | 小程序明确点击、Owner-only API、code2Session/HMAC 匹配、Recipient 加密 | 单元/HTTP/隐私测试通过；拒绝不影响预约 |
| N2.3 事务 Outbox | 店休批量取消与 eligible Outbox 原子写入、唯一键、人工兜底摘要 | 事务回滚、幂等、MySQL 并发和 EXPLAIN 通过 |
| N2.4 Provider 与 Worker | Token Manager、Provider、Lease、Retry、Dead、优雅停机 | 故障矩阵、崩溃恢复、多 Worker 与敏感信息测试通过 |
| N2.5 产品界面 | 顾客订阅状态、站内权威状态、管理投递摘要和电话清单 | UX、权限、可访问性和跨端降级验收通过 |
| N2.6 运维与安全 | 部署、Secret、轮换、监控、告警、Runbook、数据权利 | 生产相似环境演练与告警真实送达证据完成 |
| N2.7 Gate B RC | 正式 AppID/模板、合法 Page、iOS/Android 真机、隐私材料和单独启用授权 | 当前 SHA/配置/模板/Secret/证据绑定；负责人明确 Go |

仓库实现完成不能自动勾选外部 Gate B 证据，也不能自动授权修改微信后台、部署、迁移或发布。

---

## 19. 迁移、上线与回滚

### 19.1 数据库迁移

- 迁移编号写 `TBD`，实施时基于当时最新迁移链生成；
- MySQL DDL 隐式提交，迁移需离线审查并按项目迁移 Runbook 执行；
- 不回填或伪造既有 OpenID，因为现有 HMAC 不可逆；
- 既有用户在新授权时渐进创建 Recipient；
- 迁移先创建表、约束和索引，应用保持发送开关关闭；
- 降级会丢失订阅/投递历史和加密 Recipient，属于数据破坏性回退，必须在 Runbook 中显式处理；
- 未经授权不得应用持久、共享或生产数据库。

### 19.2 推荐上线顺序

1. 业务/隐私/RDR/模板可行性批准；
2. 备份并验证恢复；
3. 应用数据库迁移，核验 Schema 和索引；
4. 部署兼容新表但总开关关闭的 App/Worker；
5. 验证 Worker 不发送、N1 仍完整工作；
6. 在批准环境开启订阅登记，渐进收集新 Recipient；
7. 用测试账号和隔离业务事件验证完整投递与电话兜底；
8. 验证监控、告警、Secret 轮换和故障恢复；
9. 绑定当前 RC 的正式模板、AppID、Page、真机与隐私证据；
10. 获得单独 Go 授权后开启发送；
11. 观察积压、错误、重复和电话兜底量，达到停止条件立即关闭发送。

### 19.3 回滚原则

- 首选关闭发送开关，不回滚 Reservation 业务状态；
- 关闭发送后保留 Outbox，不静默删除，明确是暂停、抑制还是待修复；
- 暂停 Worker 时告警仍监控积压；
- 配置或模板错误修复后，仅按受控条件重放；
- App 代码回滚必须保持对新 Schema 和 Payload 版本的兼容；
- 数据库 downgrade 不是普通应用回滚，必须先导出必要审计、处理 Recipient 个人信息并确认恢复路径；
- 密钥事故时立即关闭发送、限制密文读取、轮换/撤销密钥、评估备份和日志影响，并走安全事件流程；
- 回滚不恢复已因店休取消的预约，也不把 `store_closed` 改成 `no_capacity`。

---

## 20. Go / No-Go 清单

### 20.1 Go 条件

- [ ] 产品负责人书面批准 N2 范围和首个事件；
- [ ] 新 RDR 或明确附录确认 N2 进入哪个 Gate，且不改写 Gate A 历史；
- [ ] 目标账号类目与模板可行，字段和 Page 已冻结；
- [ ] 顾客明确授权、拒绝和撤回 UX 通过 Review；
- [ ] 处理目的、保留期限、隐私指引和用户权利获得批准；
- [ ] 通知专用 AEAD 密钥、版本、轮换和撤销演练完成；
- [ ] Recipient/Subscription/Outbox 迁移和完整 MySQL 链通过；
- [ ] 店休事务、唯一键、并发和批量性能门槛通过；
- [ ] Worker、多实例、崩溃恢复、Retry/Dead 和未知结果策略通过；
- [ ] AppSecret、加密密钥、数据库、Redis 和监控凭据均使用正式 Secret 边界；
- [ ] iOS/Android 真机在当前 RC、正式 AppID/模板和合法域名中通过；
- [ ] 告警真实送达、升级、恢复和脱敏证据完成；
- [ ] 人工电话兜底清单、权限和运营负责人确认可执行；
- [ ] 当前 SHA、配置、迁移、模板、证据和回滚 Runbook 绑定；
- [ ] 获得明确启用授权。

### 20.2 任一项成立即 No-Go

- 模板语义不能准确表达 `store_closed`；
- 需要用 `no_capacity` 或自由文本冒充店休；
- 无法确认授权触发和发送规则；
- 计划保存 OpenID 明文或复用 AppSecret/JWT/Pepper 加密；
- 事务内直接调用微信；
- 只有 Redis 队列、没有 Durable Outbox；
- 声称 Exactly-once 或“已送达”但没有平台证据；
- 无 Worker 崩溃恢复、Dead 和人工兜底；
- 日志、API、管理页或指标可能泄露平台标识/凭据；
- 未完成解绑/注销/密钥轮换和数据保留评审；
- 没有真实微信、MySQL、监控告警或正式 Secret 证据；
- 未经授权修改微信后台、持久环境或公开发布。

---

## 21. 实施时的文档联动

N2 仍是 Deferred 规划时，只新增本文，不修改现有数据库/API/发布事实。真正获批实施时必须检查并同步：

- Reservation 主需求与 API 文档；
- [数据库设计](../02_database/database_design.md) 与 `docs/02_database/er_diagram.dbml`；
- `docs/03_api/api_design_conventions.md` 的 Enum、错误码和状态映射；
- [项目架构](../04_architecture/architecture.md) 的 Recipient、Outbox、Worker、Provider 与依赖方向；
- [用户模块](user_module.md) 的微信绑定、解绑、注销、活跃预约阻断和个人信息边界；
- [Phase 9.5 基线](../09_release/phase95_public_security_baseline.md) 的“身份 HMAC + 通知专表可逆密文”新边界；
- 新的发布决策记录、[Phase 9 微信发布规划](../08_frontend/phase9_wechat_release_plan.md) 与 [Go/No-Go Checklist](../09_release/go_no_go_checklist.md)；
- `docs/09_release/risk_register.md`、环境/Secret Inventory、CI、部署、验收矩阵和运维 Runbook；
- 小程序 API 集成契约、架构、测试策略和隐私交互；
- `docs/06_ai/AI_CONTEXT.md` 与 `docs/05_development/changelog.md`；
- Product 中“预约日期/时间段尚未纳入”的旧边界已经由 Reservation N1 主契约修订；N2 只能补充通知，不拥有排期或价格规则。

---

## 22. 实施前开放决策

以下问题必须在 N2.0 指定 Owner 和截止时间，并形成书面结论：

1. N2 是否正式进入产品范围，以及对应 Gate 和发布日期；
2. 目标小程序账号的类目、可用 Template ID、字段和 Page；
3. 账号实际支持的一次性/长期订阅形式，以及一次意愿与一次消息的准确生命周期；
4. 是否接受本文建议的保守 Unknown 处理，还是批准有界 At-least-once 并接受极端重复风险；
5. 微信接口当前是否存在可靠 Message ID、结果回调或查询能力；
6. Recipient、Subscription、Outbox 元数据、日志和备份的保留期限；
7. AEAD 算法/库、Secret Manager、key version 格式和轮换执行者；
8. Worker 的运行平台、资源限制、扩容策略与运营 SLA；
9. 积压、Dead、Token、解密失败和电话兜底的告警阈值与负责人；
10. 注销时已经开始 Provider 请求的用户说明和隐私处置；
11. 电话兜底是否需要进一步记录联系尝试；如需要，另开范围；
12. 是否在 `store_closed` 稳定上线后扩展 `reservation_confirmed` 或 `reservation_rejected_no_capacity`。扩展必须重新评估模板、授权消耗、唯一键、文案和人工兜底，不自动纳入 N2 首版。

---

## 23. 相关事实来源

- [RDR-001：微信小程序发布目标](../09_release/release_decision_record.md)
- [Phase 9 微信小程序发布规划](../08_frontend/phase9_wechat_release_plan.md)
- [Phase 9.5 公开身份、安全与隐私基线](../09_release/phase95_public_security_baseline.md)
- [Go/No-Go Checklist](../09_release/go_no_go_checklist.md)
- [用户模块需求](user_module.md)
- [数据库设计](../02_database/database_design.md)
- [项目架构](../04_architecture/architecture.md)
- `app/integrations/wechat.py`：当前仅有 `code2Session` Provider
- `app/models/external_identity.py`：当前仅保存平台标识 HMAC
- `app/core/config.py`：当前微信登录配置边界
- `miniapp/src/platform/wechat_identity.ts`：当前仅有 `Taro.login` 平台封装
- `requirements.txt` 与 `app/tasks/`：当前没有可靠通知 Worker/队列依赖

本文没有把任何 N2 候选误报为现状。Reservation N1/M7 已完成仓库实现与 MySQL 门槛，M5/M7 也已进入当前持久 Gate A M7；共享、预发布和生产环境仍未因此自动迁移。本期仍以站内状态为权威、管理员使用当前手机号人工联系。微信订阅消息、通知 Outbox、Worker、重试与主动送达均不在 N1，也未实现、未启用、未授权。
