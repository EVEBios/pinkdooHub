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
`51ad315...` 的 M2 Schema、Operations `c4d27a8...` 和 GitHub Actions Run 33584789525；详细证据见
[`reports/phase94_pre_icp_completion_2026-09-02.md`](reports/phase94_pre_icp_completion_2026-09-02.md)。

该检查点不是 RC 或 Go 决定。微信开发者工具已完成预 RC 加载/编译并验证域名校验
fail closed；备案、DNS/HTTPS、微信合法域名、release-eligible artifact、iOS/Android
真机和独立上传授权仍未完成。Gate A 因此继续为 **No-Go / Not Authorized**。

### 0.2 M7 候选检查点（2026-09-07）

当时的仓库已经新增 M4 Wallet/Payment/Refund、M5 Reservation N1、M6 自选颜色 Kit、
M7 可配置固定店休，以及代客钱包订单多颜色和会员头像布局修复。该扩展没有自动改变
Gate A 的身份、资金或分发决定：仍使用账号密码；只有 M4 迁移、历史补齐、只读对账
和扩展 MySQL 门槛全部关闭后，才可用合成钱包余额/人工结算验证。Gate A 不接真实微信
充值、支付或退款，也不向公众开放。

审计起点 `c6778e7...` 的远端 Run 34104680282 为 7/8，旧 MySQL gate 没有正确纳入 M7。
本地提交 `58d8435...` 修复该 gate，提交前 dirty-tree 一次性 MySQL 报告完成 0→7、
历史矩阵、snapshot 和 21 项联合门槛。包含该修复的当时 PR head `4d6430c...` 随后在
Run 34129910349 的干净 merge-ref checkout 上取得 8/8，并保存 7 组 artifact；旧失败
Run 仍保留为历史回归依据。
该历史检查点的 Gate A 最后留证版本仍是 M2，当时真实状态只能重新只读确认；仓库没有获批的非空
M2→M7 升级入口。钱包 backfill/reconcile、221 色持久发布、真实 RC 与真机均未执行。
本检查点只更新 No-Go 依据，不授予持久迁移、微信后台修改、上传、
分发、提审或发布权限。完整当前门槛见
[Go/No-Go Checklist](go_no_go_checklist.md)，本地证据边界见
[M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)与
[M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

### 0.3 Gate A M7 持久服务端检查点（2026-09-08）

当次授权窗口内，真实只读起点确认为 M2；在新 Backup/独立 Restore 后，
持久 Gate A 已受控完成 M3→M4→M5→M6→M7、Wallet account/legacy settlement
补齐与零差异对账、221 色与持久图片发布、M7 结构核验、当前 Runtime
韧性和脱敏扫描。Runtime 为 `73dca350...`，Image ID 为 `sha256:d508e9d9...`。

综合数据经 82 个正式 loopback API 请求建立，覆盖 M3–M7 新业务链路；数据后
`wallet_reconcile` 为 `4/0/0`。Backup `20260908t021224z` 已完成数据库/
225 图片的独立无端口 Restore，并在管理电脑形成立即解密复核通过的
AES-256-GCM/RSA-OAEP-SHA256 异机副本。合成密码只保留在服务器上
`root:root 0600` 凭据文件，密码注册已重新关闭，真实充值/微信 Provider 仍关闭。

数据后备份工具的快速 loopback 端口复用修复位于 Operations `353455bb...`，
[Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663) 已 8/8。
完整脱敏证据见
[Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。

该检查点关闭所有不依赖域名的当前 Gate A 服务端 P0/P1 项，但仍不是 RC
或 Go 决定。真实 HTTPS Origin、微信 request/upload/download 合法域名、
`release_eligible=true` RC、体验版上传授权、iOS/Android 真机和最终签署仍未完成；
Gate A 继续为 **No-Go / Not Authorized**。

### 0.4 M8 HEX/gzip 候选检查点（2026-09-08）

M8 候选将 MARD 221 色的规范 `swatch_hex` 纳入正式 Schema/API/销售就绪规则，让小程序
直接绘制数字色块，并为 App 与 Nginx 增加协商式 gzip。首轮 head `06b5502...` 的
[Run 34242022911](https://github.com/EVEBios/pinkdooHub/actions/runs/34242022911) 为 7/8：
Reservation MySQL 门槛仍按 M0–M7 枚举迁移文件，漏列已经应用的 M8。修复提交
`4e745848315aab56805a872ecf5b9f5e3c10135b` 把 M8 纳入该测试的存在性和顺序断言；
对应 merge-ref `3ddda81...` 的
[Run 34242753255](https://github.com/EVEBios/pinkdooHub/actions/runs/34242753255) 已重新执行
全部八类 Job并取得 8/8。完整身份、Job 与 artifact 见
[M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。

该检查点只批准把 M8 作为下一发布候选继续准备，不批准任何持久写入。Gate A 的当前
权威状态仍是 §0.3 的 M7；M8 migration、目标 Runtime、HEX/gzip 现场验收及 M8 数据后
Backup/Restore 尚未执行。`4e745848...` 之后的仓库候选已新增显式 M7→M8 编排：只执行
M8；以 `m7-preserved-business-v1` 对 20 个非 `bead_colors` 表和该表 M7 投影（共 21 个
业务表）做内容级摘要，另绑定 Aerich 精确链与完整图片 manifest。停写后、M8 原语前，
raw preflight 必须确认没有 `swatch_hex` 列、221 条 M7 色卡元数据逐槽等于冻结 manifest，
以及 221 张预期 PNG 为普通非软链接文件、内容 SHA-256 精确且权限 `0644`。随后 MARD
preview/apply/replay 必须为精确 221 项 no-op；publisher 只允许已有 Online 引用在事务
锁定后仍完全一致时零写通过。成功 Record 生成后还必须保持停写，在 `app-up` 前用相同
参数完成 live replay verification；`app-up` 自身只验证 Record/候选身份，不复核 live
DB、图片或 MARD。本轮本地 `tests/release` 为 `229 passed`，完整后端为
`2317 passed, 33 skipped in 125.31s`。独立只读代码审查曾发现成功重放没有重新证明
App/Nginx 仍停服；修复并补齐服务状态 fail-closed 矩阵后复核无未解决 P0–P3。该新增
路径现已收口为 head `fa6fce05...`、merge-ref `b2f02ebc...`，并由
[Run 34281512196](https://github.com/EVEBios/pinkdooHub/actions/runs/34281512196) 在干净
PR checkout 完成 8/8；最终干净 SHA/远端 CI 已关闭，完整 updater 隔离 MySQL 仍未执行。
身份、Job 和 artifact 见
[M8 发布加固远端 CI 报告](reports/m8_hardening_remote_ci_2026-09-09.md)。

上述“完整 updater 隔离 MySQL 仍未执行”是该检查点当时的边界；该一次性证据缺口现已由
§0.5 的 Run 34288613644 关闭，但不改变持久 Gate A 仍为 M7 的结论。

2026-09-09 的本地 2 核/4GiB 容器包络/共享 5Mbps 探索轮已经完成 12/12 个 A/B/C/D
Profile：gzip 色板、认证浏览、兼容 PNG 冷/热页和 150 个真实本地写旅程在 5/10 VU
均通过，最终业务对账、日志/statement 与资源清理也通过；但 10 VU 持续请求未压缩的
51,063-byte 色板产生 428 个 qdisc drops，P95/P99 为 1,510/2,442ms。因此整轮严格为
`FAIL`，只能说明正常压缩客户端路径有余量，不能关闭容量 Gate。该单轮 dirty-tree ARM64
Docker 证据也不替代干净 SHA candidate-pre、独立 Linux 主机、TLS/公网或真机验收。详见
[M8 本地容量报告](reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md)。

进入 Gate A 前还必须绑定新 Backup/独立 Restore、目标 SHA/Image、停写窗口和当次明确
写授权；文档、CI 或本地测试均不构成授权。禁止用默认 M2 路径处理 M7、拆跑内部原语、
手工改表、临时改变商品状态或使用 `--fake`。同样不授权 Runtime 切换、DNS、微信后台、
体验版上传、分发、提审或公开发布。上述保护依赖 App/Nginx 停止且没有直接 SQL、其他
迁移或宿主图片旁路写入，不构成跨数据库/文件系统绝对原子事务。Gate A 继续为
**No-Go / Not Authorized**。

### 0.5 M7→M8 完整更新器一次性检查点（2026-09-09）

候选 head `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、实际 PR checkout
`a9ff3d246c61a4aeede062596c32817a69834d7a` 的
[Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644)
已将 `gatea-m7-m8-updater` 作为第 9 个 CI Job 在 GitHub-hosted disposable
Linux/Unix-socket Docker 中完整执行。Source 为冻结 M7
`73dca350505d43775fb1ff1158ccf6aabc221998`，不是手工伪造的 Schema 或 Record。

演练 14/14 阶段通过：建立 M7 代表数据/221 纯色 PNG/Online 三色商品，
完成 M7 Backup `20260908t230214z` 与同 ID 独立 Restore，再执行
M7→M8 plan/apply/停服 replay/app-up。升级成功点的 21 表内容摘要和
225 图片 manifest 与 source 一致；MARD 在已有 Online 引用下为 221 项
exact no-op。Runtime 又验证 221 个规范 HEX、identity JSON 63,445 bytes
与 gzip 10,948 bytes（减少 52,497 bytes）、正确 `Vary`、小响应不压缩和
PNG 兼容回退，最后完成 M8 Backup `20260908t230329z` 与同 ID 独立
Restore。上传的 20 个演练文件通过白名单和 Secret 扫描，有界清理第 2 次
成功并确认容器、网络、卷、镜像、端口和 workspace 全部零残留。

Run attempt 1 的其余 8 个 Job 通过，`openapi-contract` 在契约命令执行前
遭遇 `pip` TLS/truststore 一次性异常；同一 clean checkout 原样重跑后 51 秒通过，
Run 最终为 9/9 Success。这是依赖安装失败，不是 OpenAPI Schema 漂移。
完整证据见
[Gate A M7→M8 完整更新器远程 CI 演练报告](reports/gatea_m7_m8_updater_remote_ci_2026-09-09.md)。

该检查点关闭了一次性完整 updater 复现缺口，不改变 §0.3 的持久环境事实。
当次运行明确记录 `persistent_gatea_authorized=false` 和
`production_secrets_used=false`；持久 Gate A 仍为 M7，仍须冻结精确目标、当次
只读预检、新 Backup/Restore、source/target SHA 和 Image ID、停写窗口与明确
写授权。真实 HTTPS Origin、微信合法域名、`release_eligible=true` RC、上传/
灰度授权与 iOS/Android 真机也仍未完成，故 Gate A 继续为
**No-Go / Not Authorized**。

### 0.6 M9 失败验收与受控前滚检查点（2026-09-11）

§0.3–§0.5 保留的是各自日期的历史事实，不能作为当前操作指令。旧候选 A
`d6c09482ee0f5583d79bd847e995746c9c6ee1a3` 此后已将 live Gate A 配置、数据库和五项
常驻服务带到 M9；但 `current` 仍指向 finalized lineage S
`73dca350505d43775fb1ff1158ccf6aabc221998`。A 的 admin-assisted acceptance 在
`order_created` 后读取 T01 bootstrap identity 时绕过 Entrypoint Secret 加载而安全失败。
补偿已取消订单、恢复 Kit 库存、下线 fixture、撤销会话，且没有资金或桌台会话数据；
canonical schema v3 failure pending 必须保留，A 不得原地重跑。

B `ad2ac8c...` 已 stage，但 retirement 只到 `prepared`。随后候选 C head
`e909c42cebaf59931536ddc2c82a43f19a29925c` / merge target
`c709d6252a07d65eb1457b23e7036ecb736f18b8` 已由 Run 34616037853 完成 9/9；真实 Gate A
schema v3 stage 却在任何 C pending/Image/Release 写入前安全失败，因为隔离 launcher 的
pre-install predecessor validation 误调用只适用于已安装 Release 的 `_runtime_modules()`。
清理后 A/B/S、三份受保护 digest 与五服务均不变，C 无现场残留且不得复用。

当前只授权全新候选 D 在自身同一 SHA 的全新 9/9 required Jobs 后，按受控链执行：schema v3
stage 绑定 A failure 与 B stage/prepared digest，八阶段退休并归档两份失败证据，新建 A/M9
Backup/Restore，执行 A→D 的 M9→M9 零迁移 adoption/replay，随后重新完成 D acceptance、
resilience、数据后 Backup/Restore 与 finalize。D stage 必须在完整 provenance 后完成第二次
blocker scan，再 stable no-follow exact-bytes 加载归档内标准库限定 validator；不得使用
`PYTHONPATH`、`current`、A/B Release 或现场工作树 fallback。禁止手工
删除 pending、临时注入 Secret、数据库降级或重跑 M7→M9；任一步失败都保持 **No-Go** 并
停止。该恢复授权不扩展到真实微信支付、正式微信小程序码、微信后台上传/分发、提审或公开发布。

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
| 支付 | 不接真实微信支付；默认由 ADMIN+ 人工确认 Paid。当前 M7 检查点已关闭 M4/backfill/reconcile，可继续用无现金价值的合成钱包余额验证余额支付/代客扣款/退款 |
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
- 微信登录、真实微信支付/退款、订阅消息或分享增长能力；
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
