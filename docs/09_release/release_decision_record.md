# RDR-001：微信小程序发布目标

> **Decision ID:** P9-RDR-001
> **Status:** Accepted for Gate A
> **Decision Date:** 2026-08-29
> **Decision Owner:** Yijie Shen
> **Public Release Authorization:** Not Granted

## 0. Phase 9.1 Review 记录

| 项目 | 记录 |
|------|------|
| Reviewer | Yijie Shen |
| Review Date | 2026-08-29 |
| Result | Phase 9.1 Complete；进入 Phase 9.2 |
| Gate A Readiness | No-Go；须由 9.2–9.4 的真实证据关闭 |
| External Operations | 未授权微信后台修改、上传、提审、公开发布、持久迁移、push、tag 或 release |

Yijie Shen 确认：本版唯一发布平台为微信小程序，当前只推进受邀内部测试版 Gate A；支付宝、抖音和 H5 不属于本版范围。Gate A 暂时使用用户名密码和 ADMIN+ 人工 Paid，不接微信登录、微信支付或真实资金。Gate A 使用 production 安全配置语义、真实测试 HTTPS Origin、独立 MySQL 8+、Redis 和持久图片存储，并依次完成 CI、迁移与备份恢复演练以及 iOS/Android 真机验收。所有责任角色均由 Yijie Shen 承担，但实施、复核、风险接受和发布授权分别记录。

### 0.1 Phase 9.4 备案前检查点（2026-09-02）

持久 Gate A 的迁移、Bootstrap、代表性数据、非空恢复、加密异机备份、MySQL/Redis
故障、App 重启、日志轮转/脱敏/查询，以及不可发布微信预 RC 已完成。结果绑定 Runtime
`51ad315...`、Operations `c4d27a8...` 和 GitHub Actions Run 33584789525；详细证据见
[`reports/phase94_pre_icp_completion_2026-09-02.md`](reports/phase94_pre_icp_completion_2026-09-02.md)。

该检查点不是 RC 或 Go 决定。微信开发者工具已完成预 RC 加载/编译并验证域名校验
fail closed；备案、DNS/HTTPS、微信合法域名、release-eligible artifact、iOS/Android
真机和独立上传授权仍未完成。Gate A 因此继续为 **No-Go / Not Authorized**。

## 1. 决策

本版发布目标冻结为微信小程序，不同时发布支付宝、抖音或 H5。发布采用两道门：

1. 先交付仅面向受邀人员的内部微信测试版 Gate A；
2. Gate A 通过后，再单独规划并授权对外公开版 Gate B。

Gate A 是当前唯一获准推进的发布目标。Gate B 的设计审计可以继续，但不得上传正式版、提交审核或向公众开放。

## 2. Gate A 产品形态

| 项目 | 决策 |
|------|------|
| 平台 | 微信小程序 `weapp` |
| 分发 | 微信开发版/体验版；仅受邀测试人员 |
| 普通用户身份 | 暂时沿用用户名密码 |
| 管理员身份 | 沿用用户名密码与后端 ADMIN+/SUPER_ADMIN 权限链 |
| 支付 | 不接微信支付；ADMIN+ 人工确认 Paid 仅用于测试业务闭环 |
| 数据 | 隔离、可恢复、非生产业务数据；不得复用开发者个人 SQLite 作为发布环境 |
| API | 真实 HTTPS 测试 Origin；微信合法域名开启校验 |
| 数据库 | 生产相似的隔离 MySQL 8+ |
| Redis | 生产相似的隔离 Redis |
| 图片 | Gate A 至少使用持久化、可备份且可通过 HTTPS 访问的存储 |
| 发布承诺 | 明确显示内部测试属性，不接受公众注册或商业收款承诺 |

账号密码和人工 Paid 不是正式微信身份或支付能力。体验版说明、测试账号和反馈入口必须明确这一点。

## 3. Gate B 前置决策

对外公开前必须另行冻结：

- 普通用户微信登录和现有账号关联/冲突/解绑/禁用规则；
- 是否允许公众继续使用用户名密码；
- 是否在线成交或收款；
- 在线收款时的微信支付、通知、查单、退款和对账；
- 管理分包是否随公开包发布；
- 生产基础设施、Secret Manager、对象存储/CDN、监控和告警供应商；
- 隐私保护指引、用户权利、平台类目和审核材料。

这些决定未完成前，Gate B 保持 `not-authorized`。

## 4. 明确不在 Gate A 内

- 支付宝、抖音、H5 的 Build、Smoke、Functional、CORS 或发布；
- 微信登录、微信支付、退款、订阅消息或分享增长能力；
- Order create 服务端幂等；
- 登录/注册限流、refresh token 轮换；
- 公开隐私审核与公众数据处理；
- 正式生产数据库迁移或真实商业数据导入；
- 自动上传微信、自动提审或自动发布。

这些非目标不影响 Gate A 内部测试，但其中标记为 Gate B blocker 的能力不能被永久豁免。

## 5. 版本与候选映射

当前三个版本维度不强制使用同一个编号：

| 维度 | 当前事实 | RC 要求 |
|------|----------|---------|
| 后端 | `APP_VERSION=0.6.0` 未发布候选 | 记录实际环境值 |
| 前端 npm | `miniapp@1.0.0` | 记录 `package.json` 值 |
| 微信上传版本 | 尚未创建 | 上传时记录版本号、备注和上传工具版本 |

每个 RC 使用 Release Record 映射 Git SHA、上述三个版本、OpenAPI 摘要、CI run 和 artifact checksum，不用改写历史来强行统一版本。

## 6. 决策后果

正面结果：

- CI、测试和运维精力只围绕当前微信目标；
- 内部测试与公开发布风险明确分离；
- 可以先验证基础设施和发布能力，不被登录/支付商业接入阻塞。

代价与限制：

- 现有支付宝、抖音、H5 构建记录不再是本版门槛；
- Gate A 不能作为商业上线或公众数据处理证据；
- Gate B 仍需要独立的身份、支付、安全与合规工作。

## 7. 变更规则

以下变化必须更新本 RDR 并由项目负责人 Yijie Shen 批准：

- 把 Gate A 改为公众可访问；
- 在 Gate A 收取真实资金；
- 增加支付宝、抖音或 H5；
- 接管一套现有持久数据库；
- 改变身份方式、支付方式或管理入口；
- 省略本记录列出的 Gate A/Gate B blocker。
