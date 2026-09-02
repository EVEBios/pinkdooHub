# Phase 9.5 公开身份、安全与隐私基线

> **Status:** Repository implementation complete; external Gate B evidence pending
> **Last Updated:** 2026-09-02
> **External Changes:** None — 未启用微信登录、未创建付费云资源、未迁移 Gate A、未配置正式 Secret/监控/对象存储

## 1. 本阶段结论边界

Phase 9.5 在仓库内完成了可独立于备案实施的身份、安全和隐私基础能力：微信 `code2Session` 服务端适配器、明确的账号绑定规则、refresh family 轮换/重放撤销、Redis 限流、账号注销匿名化、外部身份 HMAC 最小化、结构化安全事件、生产存储端口及集中 Secret 文件注入边界。

这不是 Gate B 通过。以下证据仍依赖备案、正式小程序账号或外部资源，保持阻断：

- 真实 AppID/AppSecret 的 `wx.login → code2Session` iOS/Android 真机链路；
- 正式集中 Secret Manager 的版本、访问审计、轮换和撤销演练；
- 正式对象存储/CDN Bucket、最小权限、上传/读取/删除/恢复与成本策略；
- 生产监控平台的日志接入、告警送达、静默/升级和故障演练；
- 微信公众平台隐私保护指引、用户同意/撤回 UI、备案/主体/类目和公开审核材料 Review；
- 当前新迁移在受控持久环境的停写、备份、应用与回滚授权。

## 2. 身份与账号关联契约

### 2.1 微信首次登录

1. 客户端只提交 `wx.login` 一次性 code；AppSecret 只存在于后端 Secret 边界。
2. 后端向微信 `code2Session` 换取 OpenID、可选 UnionID 和 `session_key`，但只将最小身份 DTO 交给业务层，立即丢弃 `session_key`。
3. 首次身份自动创建普通用户：系统唯一 username、`password=NULL`、`phone=NULL`、通用 nickname；不依据手机号、昵称或头像自动合并。
4. OpenID/UnionID 使用独立稳定 Pepper 做 HMAC-SHA256 后存储。原始值、一次性 code、`session_key`、Pepper 和 AppSecret 均不得进入数据库、响应、审计 description 或日志。

### 2.2 绑定、冲突与解绑

- 既有密码用户只可在已登录状态显式绑定。Subject 唯一键和可选 Union 唯一键是并发兜底；属于其他用户时统一冲突，不泄露目标账号。
- 普通用户每个 provider/App 只保留一个绑定；重复绑定自己按幂等成功处理。
- `ADMIN` / `SUPER_ADMIN` 不能通过公众链路自动创建、绑定、解绑或注销。
- 解绑需要当前密码，且锁后再次验证密码；微信-only 用户不能移除唯一登录方式。成功后递增 `auth_version` 并撤销全部 refresh family。
- 公开小程序构建使用 `TARO_APP_AUTH_MODE=wechat`；Gate A 与管理入口保留 `password`。公开密码注册必须显式设置 `PASSWORD_REGISTRATION_ENABLED=false`。

## 3. 会话与限流

每次登录创建一个独立 `sid` family。Redis 保存 active JTI、已消费 JTI、family 当前 JTI 与 user→families 索引；成功刷新在一条 Lua 脚本内消费旧 JTI、记录 used、发布新 JTI。旧 refresh 重放时删除 family 当前 active token 并标记 revoked。客户端收到刷新响应后原子替换 access/refresh，不能继续持有旧 refresh。

默认策略如下，正式 RC 可经安全 Review 收紧，但不得静默放宽：

| Scope | 默认阈值 | 窗口 | Principal |
|-------|----------|------|-----------|
| 密码登录 IP | 20 | 5 分钟 | HMAC(IP) |
| 密码登录账号 | 8 | 5 分钟 | HMAC(IP + 规范化 username) |
| 密码注册 | 5 | 1 小时 | HMAC(IP) |
| Refresh | 30 | 1 分钟 | HMAC(IP)；不能使用每次轮换都会变化的 Token 作为桶 |
| 微信登录 | 10 | 5 分钟 | HMAC(IP) |
| 微信绑定 | 5 | 10 分钟 | HMAC(IP + user ID) |

Redis 键不含明文 IP、账号或 Token。Redis 故障时身份敏感请求返回 503，不绕过限流；超限统一返回 HTTP 429/code 42901。

密码登录将不存在账号、错误密码和微信-only 账号统一为 code 1003，并对前两类不可核验记录执行 bcrypt dummy verify；只有凭据正确后才返回禁用状态。该规则与双维度限流共同降低账号枚举风险。

## 4. 账号注销、数据保留与用户权利

账号注销要求固定确认词，并以锁后当前密码或本次微信 code 二次验证。Pending/Paid 订单阻止注销；Cancelled/Completed 不阻止。订单创建与注销均先锁 User 行，确保注销后不会补写新订单。

注销执行以下最小化处理：

- 删除全部外部身份绑定；
- username 替换为随机匿名标识，nickname 固定为“已注销用户”；
- password、phone、avatar、last_login_at 置空；
- status=`deleted`，写 `deleted_at`，递增 `auth_version`；
- 撤销全部 refresh family；
- 保留 User 主键和 Order/Inventory/Audit 历史，以满足履约、库存追溯、财务与安全审计。

当前仓库 API 已实现注销和数据最小化；微信公众平台的隐私保护指引、首次同意/撤回界面、联系方式、正式保留期限与用户请求 SLA 必须在 Gate B RC 前由项目负责人 Review。没有该 Review 时不得把“已实现注销接口”描述为完整合规。

## 5. 安全事件、监控与告警基线

应用输出固定格式 `security_event=<event> outcome=<outcome> user_id=<id|none> scope=<scope|none>`。允许事件包括：

- `auth_rate_limit`: `blocked` / `unavailable`；
- `refresh_reuse`: `family_revoked`；
- `wechat_identity_exchange`: `rejected` / `unavailable`；
- `external_identity_login|bind|unbind`: `succeeded`；
- `account_deletion`: `blocked_active_order` / `anonymized`。

日志平台不得采集请求 body、Authorization、Set-Cookie、OpenID/UnionID、code、AppSecret、Pepper 或带凭据 URL。首个公开 RC 的推荐告警为：

| 信号 | 建议窗口/阈值 | 初始级别 | 处置 |
|------|---------------|----------|------|
| Refresh reuse | 任意 1 次 | High | 撤销已由应用完成；核查账号活动与来源版本 |
| Rate limiter unavailable | 连续 2 分钟或 3 次 | Critical | 身份流量已 fail closed；检查 Redis/readiness |
| 微信 exchange unavailable | 5 分钟内 ≥5 或失败率 ≥20% | High | 核查微信状态、出口网络与 Secret 版本 |
| 单 scope 限流 blocked | 5 分钟内 ≥20 | Medium | 判断攻击/客户端循环，禁止用日志枚举用户 |
| 注销异常增长 | 1 小时超过历史基线 3 倍 | Medium | 检查客户端引导和账号攻击，不阻止合法请求 |

真实监控平台上线时必须证明事件到达、阈值触发、责任人收到、恢复清除和记录脱敏。仓库内日志格式和 Runbook 不是送达证据。

## 6. Gate B Secret Manager 决策门

必须支持版本化 Secret、按运行身份最小读取、人工/机器访问审计、轮换与立即撤销、静态/传输加密以及恢复权限。至少管理 DB App/Root、Redis、JWT、微信 AppSecret、External Identity Pepper、对象存储和监控 ingest 凭据。

运行镜像支持从 `/run/secrets/wechat_app_secret` 与 `/run/secrets/external_identity_pepper` 可选读取，不要求把 Secret 放入 Compose 参数或常驻明文配置。Pepper 与 JWT Secret 必须独立；Pepper 的普通轮换会改变查找键，因此只能执行带双版本读取/离线重键和回滚计划的受控迁移，不能直接替换。

本阶段不指定腾讯云 SSM、Secrets Manager 或其他供应商，也未创建资源。选型完成后必须把 Secret ID/版本而非值写入 Release Record。

## 7. 生产图片存储决策门

业务上传边界只依赖 `ImageStorage` Protocol；现有 `LocalImageStorage` 继续服务开发/Gate A。Gate B 对象存储适配器必须满足：

- 复用 2 MiB、jpg/png/webp 内容/MIME 校验，不信任文件名；
- 服务端不可预测 key、禁止覆盖、HTTPS URL、私有写权限和最小 bucket/namespace 权限；
- DB 写失败时幂等补偿删除；逻辑删除后按截止时间、有效引用和命名空间安全清理；
- 上传/下载/删除的超时、重试、unknown outcome 和幂等语义有测试；
- 版本/生命周期、跨故障域备份、RPO/RTO、CDN 缓存失效、访问日志、成本与流量告警有 Review。

没有真实 Bucket、凭据和恢复演练前，R-024 不能关闭。

## 8. 数据库迁移与发布顺序

迁移 3 新增 `external_identities`，增加 `users.auth_version/deleted_at` 并让 password/phone 可空。MySQL DDL 隐式提交，`RUN_IN_TRANSACTION=False`；正式执行必须：停写 → 备份/独立恢复 → 只读扫描 → 迁移 0→3 或受支持起点→3 → 表/索引/NULL/版本核验 → App 切换。降级会删除全部外部绑定，并要求所有保留用户重新拥有非 NULL password/phone，属于破坏性恢复，不作为普通回滚。

Gate A 当前仍运行迁移 0→2。用户未授权对 Gate A 执行迁移 3，因此本阶段只做离线与可销毁 MySQL 验证。

## 9. 剩余 Gate B 验收

- [x] 身份/绑定/冲突/权限/注销业务契约和本地 HTTP 测试；
- [x] Refresh 轮换、并发单成功、重放撤销和客户端双 Token 替换；
- [x] Redis 原子限流、统一 429、依赖故障 fail closed；
- [x] 原始平台标识不入库/响应/结构化安全日志；
- [x] MySQL 迁移静态契约与可销毁 0→3 验证；
- [ ] 真实微信 AppID iOS/Android、禁用/冲突/解绑/注销真机矩阵；
- [ ] 正式 Secret Manager、监控告警、对象存储及各自故障/轮换/恢复演练；
- [ ] 隐私保护指引、同意/撤回、保留期限、联系方式和用户请求流程 Review；
- [ ] Gate B 当前 RC 的 CI、正式 Origin/合法域名、提审与发布授权。

## 10. 2026-09-02 本地验证证据

- 后端普通套件：`1693 passed, 9 skipped`；跳过项仅为必须显式启用隔离 MySQL 的 release gate。
- MySQL release gate：一次性 `mysql:8.0.46`、回环 `127.0.0.1:13307`、冻结 Schema `pinkdoohub_inventory_4311_ci`，真实执行 Aerich 0→1→2→3，9 项并发/事务/1205/EXPLAIN/HTTP 门槛全部通过；随后由 CI 同源清理程序删除 Schema、停止容器并确认端口关闭。
- 前端：61 套件/392 项 Jest、TypeScript、ESLint、Stylelint、OpenAPI 类型漂移和 17 项 CI Node 契约全部通过。
- 微信构建：以 `TARO_APP_AUTH_MODE=wechat` 和保留 CI HTTPS Origin 编译，97 文件、主包 427,289 bytes、分包 178,092 bytes、总计 605,381 bytes；产物扫描无占位 Origin/source map/H5 marker/Secret marker，并明确为 `release_eligible=false`。
- OpenAPI：从真实 FastAPI 应用重新导出为 50 paths / 124 component schemas，再生成只读 TypeScript 类型。

这些是功能提交 `94325fa...` 对应的本地证据。推送后仍须以当前分支头的远端干净 checkout CI 结果补齐远端证据；它们也不是正式微信、备案域名或 Gate B 发布证据。
