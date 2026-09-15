# 用户模块（User Module）

---

## 1. 模块目标

负责平台用户注册、密码/微信身份登录、会话安全、个人资料和账号生命周期管理。普通客户的钱包创建、余额与资金生命周期由 [会员钱包、支付与退款模块](wallet_module.md) 承接。

---

## 2. 用户角色

| 角色 | 说明 |
|------|------|
| 游客 | 未登录，可浏览公开内容 |
| 普通用户 | 已登录，可操作个人数据 |
| 管理员 | 已登录，可管理所有用户 |

---

## 3. 功能矩阵

### 游客

| 功能 | 说明 |
|------|------|
| 注册 | 创建账号 |
| 登录 | 用户名 + 密码 |
| 微信登录 | `wx.login` code 仅由后端向微信换取身份；首次登录创建普通用户 |
| 浏览商品 | 查看商品列表和详情 |

### 普通用户

| 功能 | 说明 |
|------|------|
| 查看个人信息 | 获取个人资料 |
| 修改个人信息 | 修改昵称、手机号 |
| 修改密码 | 验证旧密码后更新 |
| 微信绑定/解绑 | 既有密码账号可显式绑定；解绑必须保留密码这一备用登录方式 |
| 注销账号 | 二次验证，且无待支付/已支付订单、未来活跃预约、处理中资金、可退款钱包敞口或非零钱包余额时匿名化并撤销全部会话 |
| 体验预约 | 正常普通用户以当前手机号独立预约，不要求先下单；查看/取消自己的预约 |
| 头像 URL | 可随个人资料保存；头像文件上传尚未实现 |
| 查看订单 | 查看自己的订单记录 |
| 会员钱包 | 查看自己的会员资料、权威余额和不可变资金流水 |
| 余额支付 | 在余额充足时支付自己的 Pending 订单；微信支付当前关闭 |

### 管理员

| 功能 | 说明 |
|------|------|
| 查看用户列表 | 分页浏览所有用户 |
| 禁用用户 | 将用户状态设为禁用 |
| 客户资金管理 | ADMIN/SUPER_ADMIN 均可查询并增减普通 USER 余额、查看其流水 |
| 客户代客下单 | ADMIN/SUPER_ADMIN 均可为状态正常的普通 USER 按商品创建钱包订单并直接扣款 |
| 客户退款 | ADMIN/SUPER_ADMIN 均可对普通 USER 的 PAID/COMPLETED 已结算订单执行全额退款 |

用户详情、启用和头像文件上传仍属于后续范围。资金管理只允许以普通 `USER` 为目标：ADMIN 和 SUPER_ADMIN 自身不创建钱包，不能操作自己、其他 ADMIN 或 SUPER_ADMIN。disabled 普通客户不能主动充值/消费，且 ADMIN+ 代客钱包订单也必须拒绝；ADMIN+ 人工余额纠错与法定义务退款仍允许。deleted 用户禁止新的资金写入。`ADMIN` / `SUPER_ADMIN` 不允许通过公众微信链路自动创建、绑定、解绑或自助注销。

---

## 4. 登录方式

### 当前实现

| 方式 | 说明 |
|------|------|
| 用户名 + 密码 | 主要登录方式 |
| 微信小程序 | Phase 9.5 已实现服务端 `code2Session` 适配器；正式启用仍需 AppID/AppSecret、集中 Secret、备案后真机验证 |

公开版规则：

- 首次微信登录自动创建 `USER`，系统生成不可修改用户名，密码/手机号为空，昵称使用通用值；不依据手机号、昵称或头像自动合并账号。
- 既有密码账号必须在已登录状态下显式绑定微信；同一 App 的 OpenID 只能属于一个账号，UnionID（若微信返回）在同一 provider 下只能属于一个账号。
- 数据库只保存以独立 `EXTERNAL_IDENTITY_PEPPER` 生成的 HMAC 键，不保存原始 OpenID/UnionID，也不保存 `session_key`。
- Gate B 小程序界面使用微信登录；密码登录保留给 Gate A、既有账号和管理人员。公开密码注册由 `PASSWORD_REGISTRATION_ENABLED` 显式关闭。

### 后续计划

| 方式 | 计划版本 |
|------|----------|
| 手机验证码 | v0.2 |
| OAuth 登录 | v1.0 |

---

## 5. 权限模型

| 角色 | 权限范围 |
|------|----------|
| 游客 | 浏览商品、注册、登录 |
| 普通用户 | 游客权限 + 个人资料管理 + 创建/查看自己的订单和预约 + 自己的钱包与余额支付 |
| 管理员 | 管理用户、商品、订单、预约和普通客户钱包；不继承普通客户的钱包能力 |

---

## 6. 用户数据

| 字段 | 说明 |
|------|------|
| 登录账号 | 唯一标识，用于登录 |
| 密码 | 加密存储 |
| 昵称 | 显示名称 |
| 手机号 | 可选，用于联系；微信首次登录用户为空 |
| 头像 | 可选，个人头像图片 |
| 角色 | 普通用户 / 管理员 |
| 状态 | 正常 / 禁用 / 已注销 |
| auth_version | 密码、解绑、注销等安全变化后递增，使旧 access token 失效 |
| deleted_at | 账号完成匿名化的 UTC 时间 |

外部身份单独存储 provider、AppID、平台主体 HMAC、可空 UnionID HMAC 和用户外键；任何用户响应、日志和审计描述不得暴露原始平台标识、一次性 code、`session_key` 或 Pepper。

WalletAccount 也与 User 分表保存。新创建的普通 `USER` 拥有且恰好拥有一个钱包；ADMIN/SUPER_ADMIN 不建钱包。新密码注册和微信首次登录在创建 User 的同一事务内创建 `0.00` 钱包。历史普通用户先运行 `python -m app.tasks.wallet_account_backfill` 预览并记录输出的 `through_user_id=N`，apply 必须显式复用该冻结上界：`python -m app.tasks.wallet_account_backfill --through-user-id N --apply`。每批按 User ID 升序锁定并在事务内复验 `role=user` 且 `status=normal/disabled`，再重查钱包存在性；DELETED/staff 或已有钱包者跳过，只为仍合格且缺失者补齐 `0.00` 钱包，不生成零元流水。apply 后用同一 `--through-user-id N` 复查至 `would_create=0`。正式顺序固定为 M4 → wallet backfill → legacy manual settlement backfill → 只读 `python -m app.tasks.wallet_reconcile`/发布门槛 → 启用；reconcile 稳定核验钱包余额与不可变流水的净额、逐行算术/范围、链和终值，无流水钱包只能为零。任一差异或 blocker 必须阻断启用并由人工调查，命令绝不自动改账。

---

## 7. Phase 9.5 安全与用户权利规则

- 每次成功登录创建独立 refresh family；刷新同时轮换 access/refresh，旧 refresh 再次出现时撤销整个 family。密码修改、微信解绑、禁用和注销使相应旧会话失效。
- 密码登录在首次凭据校验后进入数据库事务，锁定 User 行并重新检查当前密码与状态；微信既有身份登录及首次注册 `IntegrityError` 收敛到既有身份时也必须锁定并复验当前 User。`last_login_at` 与对应 `LOGIN` / `WECHAT_LOGIN` Audit 使用同一事务连接顺序提交，审计完成前不得签发会话。
- Token 与新 refresh family 签发后，服务端再次锁定 User 并确认 `status=normal` 且 `auth_version` 与签发版本一致；若期间发生改密、解绑、禁用或注销，本次登录的收口逻辑只精确撤销尚未交付的新 family 并拒绝登录，不得以“撤销该用户全部 family”代替精确清理，也不得留下可用的 Redis refresh 会话。改密、解绑和注销用例自身既有的全会话撤销语义不变。
- 登录按 IP 与“IP + 账号”双维度限流；注册、refresh、微信登录和绑定有独立 Redis 原子限流。Redis 不可用时身份敏感端点 fail closed，超限统一返回 429，不回显账号或 Token。
- 密码登录对不存在账号、错误密码和没有密码的微信-only 账号统一返回 1003；不存在/无密码账号也执行 bcrypt dummy verify。只有密码正确后才返回禁用状态，避免通过响应或明显计算时差枚举账号。
- 注销只允许普通用户，必须提交固定确认词并使用当前密码或当前微信 code 二次验证；Pending/Paid 订单、未来 `pending/confirmed` 且 `scheduled_end_at > now_utc` 的预约、处理中 Payment/RechargeOrder/Refund、尚可全额退款的钱包结算敞口或非零钱包余额存在时均拒绝。可退款敞口包括未成功退款的 PAID 钱包结算，以及完成未满 30 天的 COMPLETED 钱包结算；因此即使当前余额为 `0.00` 也不得关闭钱包。
- 注销保留 User 主键、钱包、资金流水、Payment、Refund、订单、预约、库存流水和审计外键，但删除外部身份并匿名化 username/nickname/phone/avatar/password，状态改为 deleted；已有钱包同步改为 closed。Reservation 不快照手机号，因此匿名化后管理端历史预约的当前联系方式为 null。该处理是为履约、财务与安全审计保留最小必要记录，不等于物理删除全部历史业务数据。
- 注销的数据库 commit 是权威成功点。commit 后的 Redis refresh-family 清理为 best-effort 纵深撤销；若 Redis 故障，注销 API 仍返回成功，已提交的 `status=deleted` 和递增后 `auth_version` 会阻止旧 access/refresh 会话继续使用。失败只记录固定 scope/result 与内部 user ID 的高优先级安全事件，不得记录 Token/JTI；运维收到该事件后必须重试对该 User 的 refresh-family 清理。
- 订单与预约创建事务都锁定并重检用户行，与注销共用锁序，禁止注销后补写新订单或新预约。
- 安全日志只输出固定 `security_event`、结果、内部 user ID 和 scope；禁止输出密码、Token、code、OpenID/UnionID、AppSecret、Pepper 或带凭据 URL。

---

## 8. 后续扩展

| 版本 | 计划内容 |
|------|----------|
| v0.2 | 手机验证码登录、找回密码、手机号绑定 |
| v0.3 | 用户收藏、用户评价 |
| v1.0 | 真实微信支付 Provider、后台管理系统、完整隐私同意/撤回界面 |
