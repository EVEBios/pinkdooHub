# 微信 Gate A Functional / Smoke / E2E 验收矩阵

> **Status:** Current M7 server data A passed；M8 baseline CI passed，later upgrade candidate/new RC/M evidence blocked
> **Last Updated:** 2026-09-09
> **Scope:** 微信小程序内部测试版（Gate A）

本矩阵冻结“必须证明什么”和证据等级。2026-08-29 的本地自动化基线证明当前源码质量，但不等于未来 RC 在真实 HTTPS、MySQL、Redis 和微信真机上已经通过。

## 1. 证据等级与结果

| 标记 | 含义 |
|------|------|
| `A` | CI 自动化；结果绑定 Git SHA、锁文件和运行时版本 |
| `M` | RC 人工验证；记录设备、基础库、网络、环境、人员和结果 |
| `A+M` | CI 与真实设备都必须通过 |
| `N/A` | 当前 Gate 不适用；必须写明理由 |
| `GAP` | 当前无覆盖；必须关联风险、负责人和最晚关闭 Gate |

结果只能使用 `PASS`、`FAIL`、`BLOCKED`、`NOT RUN`。开发者工具关闭域名校验、历史截图、未绑定 SHA 的口头结果不能填 `PASS`。

历史自动化参考证据：Operations `c4d27a8...` 的 Run 33584789525 从干净 checkout
完成 8/8 Job，但只覆盖当时的 Aerich M0→M2、前端 61 suites/387 tests 和旧业务面。
持久 Gate A 的代表数据、异机加密备份、依赖故障、重启、数据/图片保持和日志脱敏也
绑定该旧基线。历史表项中的 `A PASS` 不得解释为后续 M7/M8 候选已经通过。

当时的审计起点 `c6778e7...` 的 Run 34104680282 保留为 7/8 失败记录；随后 M7 PR head
`4d6430c...` 的 [Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349)
已在干净 merge-ref checkout 上取得 8/8。远端后端为 `2000 passed, 2 skipped`、MySQL
为 `21 passed`，前端 typecheck、ESLint、Stylelint、`83 suites / 562 tests` 和 17 项
CI policy 均通过。当时本地完整后端为 `2000 passed, 30 skipped in 113.05s`，三类
MySQL-only 门槛另以一次性 MySQL 联合 `30 passed` 覆盖。该 M7
自动化覆盖已经包含 M4 Wallet、M5 Reservation、M6 自选颜色、M7 固定店休、代客多颜色
和头像布局；其中仓库 CI 已绑定该 Run，但仍不是 RC 真机结果。微信
production-mode 代码检查产物为 141 个文件、主包 649,739 bytes、分包 407,624 bytes、
总计 1,057,363 bytes，manifest SHA-256 为
`693fb673df044e03c2865af2827e39ac7a5d6de86dbb1b3214f0b4237eeb69b4`，但仍为
`release_eligible=false`。该 M7 候选的仓库 CI `A` 已通过，但 release-eligible RC 与
完整功能矩阵仍为 `BLOCKED`；下面各功能的自动化证据也不能替代真实 HTTPS、微信合法域名和
iOS/Android 的 `M` 证据。

Wallet-expanded head `62f807a...` 随后由
[Run 34134341829](https://github.com/EVEBios/pinkdooHub/actions/runs/34134341829) 再次取得
8/8，三域联合、cleanup 和 artifact 步骤全部 success；详见
[Wallet 扩展门槛远端 CI 报告](reports/wallet_remote_ci_2026-09-07.md)。这关闭 Wallet
自动化的“新远端 SHA”缺口，但不覆盖其后 Gate A 运维/MARD 提交，也不改变任何
`M BLOCKED`、持久迁移或真实 RC 状态。

补充的 [M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md) 已在提交前
dirty 工作树完成 MySQL 0→7、M0–M6→M7 历史矩阵、M6/M7 snapshot 和联合
`21 passed`；同内容随后记录为提交 `58d8435...`，并由该 M7 Run 远端复现 workflow
门槛。精确证据见 [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。这不把
任何当前 RC 的 `M BLOCKED`、Wallet 扩展门槛或持久环境项目改为 PASS。

2026-09-08 的当前检查点替代上述“后续 Operations/持久环境未留证”边界：
Operations `353455bb...` 的
[Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663) 已在干净
merge-ref checkout 完成 8/8；Runtime `73dca350...` 的持久 Gate A 已完成
M2→M7、Wallet/MARD、候选韧性、82 个 loopback API 请求的综合数据和数据后
Backup `20260908t021224z`/独立 Restore/加密异机副本。因此下表与源码、
MySQL、持久数据、图片、日志和服务端生命周期相关的 `A` 部分均可按当前报告
解释为 `PASS`；所有 `M`、真实 HTTPS Origin、微信合法域名和 release-eligible RC
仍为 `BLOCKED`。详见
[Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。

M8 基线 head `4e745848...` 随后由
[Run 34242753255](https://github.com/EVEBios/pinkdooHub/actions/runs/34242753255) 在干净
checkout 完成 8/8；首轮 7/8、修复和 artifact 见
[M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。其后新增的显式 M7→M8 入口与
Online exact no-op publisher 与 M7→M8 内容保护已有本轮本地 `tests/release` `229 passed`；
完整后端为 `2317 passed, 33 skipped in 125.31s`，均不在该 Run 中。
因此 M7 服务端数据项可继续使用既有 `A PASS`，但 M8 持久迁移、HEX/gzip Runtime、
新候选 CI、真实 RC 和所有 `M` 证据仍为 `BLOCKED`/`NOT RUN`。

## 2. 身份、角色与权限

| ID | 场景 | 期望 | Gate A 证据 | 当前状态 |
|----|------|------|-------------|----------|
| ID-01 | Guest 冷启动与公共浏览 | 不要求登录；可浏览 Online Product；无管理入口 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-02 | 普通用户账号密码登录 | 建立 Session，恢复用户态，错误信封可解释 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-03 | 注册、登出、再次登录 | 状态与 Storage 一致；登出后敏感页面不可用 | `A+M` | 当前 `A PASS`；长期注册已关闭；`M BLOCKED` |
| ID-04 | access 过期、refresh 有效 | single-flight 刷新并安全重放允许的请求 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-05 | access/refresh 都失效 | 清理 Session、回到登录、不形成刷新循环 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-06 | ADMIN | 可进入获授权管理能力；普通用户不可调用 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-07 | SUPER_ADMIN | 首次初始化、登录及高权限边界正确 | `A+M` | 当前 Bootstrap/login/Seed 会话 `A PASS`；`M BLOCKED` |
| ID-08 | 被禁用用户 | 新登录失败；已有 access/refresh 均不能继续 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-09 | 资源与权限隐藏 | owner-only、ADMIN+、不存在资源语义符合 API 契约 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| ID-10 | 微信身份 | Gate A 不启用微信登录，界面明确为内部测试 | `M` | `N/A`（Gate B） |

## 3. 用户业务链路

| ID | 领域 | 场景与关键断言 | 证据 | 当前 RC |
|----|------|----------------|------|---------|
| US-01 | Product | Experience/fixed/color-selectable Kit 列表、详情、Option/221 色、图片与空/错/加载态 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-02 | Product | Offline/Draft/删除对象不向普通用户错误暴露 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-03 | Cart | 增删改、数量/条目上限、Option/颜色隔离、v1→v2 Storage 恢复与坏缓存 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-04 | Cart | fixed/颜色库存不足、登录/登出、Product/颜色启用变化后的收敛行为 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-05 | Order create | Experience、fixed Kit、每色 10g 的 color Kit、混合订单成功；快照、重量与金额正确 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| US-06 | Order create | 最后一件、库存不足、并发/重复点击只产生预期结果 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-07 | Order create | 弱网/断网/服务端已成功但客户端 unknown 时安全恢复，不盲重发 | `A+M` | 当前客户端 `A PASS`；`M BLOCKED`；Gate B 仍需服务端幂等 |
| US-08 | My Orders | 分页、筛选、详情、历史快照、owner-only | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-09 | Cancel | Pending 取消恢复库存；终态不可取消；重复/40921 正确收敛 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-10 | Session | 登录后 Cart/页面恢复，登出后缓存和敏感数据策略一致 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-11 | Wallet | 会员余额与流水分页、金额格式、空/错/加载态；staff/disabled/deleted 边界 | `A+M` | 当前 CI/Gate A 对账 `A PASS`；`M BLOCKED` |
| US-12 | Wallet payment | 合成余额支付 Pending Order；余额/Payment/Settlement/Order/Audit 一致，失败零写入 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| US-13 | Recharge | Gate A 不进行真实充值；微信 provider 返回 503 且零写入，界面不误导为充值成功 | `A+M` | 当前 503/零写入 `A PASS`；`M BLOCKED` |
| US-14 | Reservation | 当前固定店休日、未来 0–30 日合法日期/半小时时段、手机号补录和创建 pending | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| US-15 | Reservation | 我的预约分页/详情、pending/confirmed/rejected/cancelled 文案与提前三小时取消 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| US-16 | Reservation | 无空位/店休结果可从权威状态收敛；首版不声称主动微信通知或自动容量 | `A+M` | 当前 `A PASS`；`M BLOCKED`；N2 `N/A` |
| US-17 | Color swatch | M8 公开颜色返回规范 HEX；小程序用 `backgroundColor` 直绘且不为数字色块请求兼容 PNG | `A+M` | 基线 CI/本地模拟器 `A PASS`；持久 M8/真实 RC `NOT RUN`；`M BLOCKED` |

## 4. 管理业务链路

| ID | 领域 | 场景与关键断言 | 证据 | 当前 RC |
|----|------|----------------|------|---------|
| AD-01 | Order | 组合筛选、分页、详情与历史快照 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-02 | Order | Pending→Paid→Completed；非法前置条件；库存不变化 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-03 | Order | 网络 unknown、竞态和重复点击不盲目重发 mutation | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-04 | Product | 创建/编辑/删除、Experience Option 恢复原 ID、fixed/color Kit 类型与统一 10g 价格 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-05 | Product | Draft/Online/Offline readiness 与 Validator 错误展示 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-06 | Image | jpg/png/webp、2 MiB、预览、删除、失败补偿、HTTPS 读取 | `A+M` | 图片上传/持久/恢复 `A PASS`；HTTPS `M BLOCKED` |
| AD-07 | Inventory | fixed/颜色库存调整首次 201/重放 200、同 key 冲突、正负边界与 40932 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-08 | Inventory | Product/颜色/全局流水、筛选/分页、Order source、隐私字段不输出 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-09 | Audit | Product/Order/Inventory/User 敏感操作顺序、主体与时间正确 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-10 | User Admin | 列表筛选、禁用事务/审计、角色层级和旧 Token 阻断 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| AD-11 | Wallet Admin | 查询普通客户钱包/流水；staff、disabled、deleted 与不存在用户的稳定边界 | `A+M` | 当前 CI/Gate A 对账 `A PASS`；`M BLOCKED` |
| AD-12 | Wallet adjustment | 正负调账、余额/退款敞口上限、Idempotency-Key 首次/重放/冲突和 Audit | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-13 | Assisted wallet order | 为 NORMAL USER 创建 fixed/多颜色订单并直接 Paid；库存/余额/资金事实/双 Audit 原子一致 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-14 | Refund | manual/wallet 一次全额退款；PAID Kit 恢复、COMPLETED 不恢复、重复与窗口边界 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-15 | Color catalog | 221 色分页/搜索/全局启停、商品颜色启停、零库存与上架校验、M8 HEX/可选色样读取 | `A+M` | Gate A M7 的 221 色/图片/三启用色/库存 `A PASS`；持久 HEX `NOT RUN`；`M BLOCKED` |
| AD-16 | Reservation Admin | 组合筛选/详情、当前手机号隐私投影、pending 确认与 `no_capacity` 拒绝 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-17 | Store day closure | 单日关闭原子取消活跃预约、重放、恢复营业但不复活历史预约 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |
| AD-18 | Weekly closure | M7 读取/更换固定店休、旧星期恢复、新星期未来预约原子取消、单日店休保持 | `A+M` | 当前 CI/MySQL/Gate A 数据 `A PASS`；`M BLOCKED` |

## 5. 运行时、设备、网络与生命周期

| ID | 场景 | 最低覆盖 | 证据 | 当前 RC |
|----|------|----------|------|---------|
| RT-01 | iOS 真机 | 一台支持设备；记录系统、微信、基础库、机型 | `M` | `BLOCKED`（备案/HTTPS/体验版） |
| RT-02 | Android 真机 | 一台支持设备；记录系统、微信、基础库、机型 | `M` | `BLOCKED`（备案/HTTPS/体验版） |
| RT-03 | 布局可用性 | 小屏/常见屏/大字体、键盘、安全区域、长文本 | `M` | `BLOCKED`（真实 RC） |
| RT-04 | 网络切换 | Wi-Fi、移动网络、弱网、断网、恢复 | `M` | `BLOCKED`（真实 RC） |
| RT-05 | 生命周期 | 冷/热启动、前后台、锁屏、请求中断、分包首次加载 | `M` | `BLOCKED`（真实 RC） |
| RT-06 | request 域名 | 真实 HTTPS、证书、微信后台白名单；真机成功 | `M` | Origin `BLOCKED` |
| RT-07 | upload 域名 | 图片上传中断/恢复、大小/类型错误、unknown | `A+M` | 域名 `BLOCKED` |
| RT-08 | download 域名 | 商品图片加载、失败占位、缓存和恢复 | `M` | 域名 `BLOCKED` |
| RT-09 | Redis/DB 故障 | readiness 摘流量；客户端错误可恢复且不泄密 | `A+M` | 当前 M7 Runtime 依赖故障/恢复 `A PASS`；客户端 `M BLOCKED` |
| RT-10 | 后端重启 | 连接恢复、Token/Cart/订单结果一致，不丢图片 | `A+M` | 当前 M7 Runtime 数据/225 图片保持 `A PASS`；`M BLOCKED` |
| RT-11 | 快速操作 | 双击、连点、重复进入、返回前台不会重复 mutation | `A+M` | 当前客户端 `A PASS`；`M BLOCKED` |
| RT-12 | 版本来源 | 体验版 artifact、Git SHA、OpenAPI、环境和版本记录一致 | `A+M` | 历史 M2 预 RC `A PASS`；当前真实 RC/体验版 `BLOCKED` |
| RT-13 | 最新界面回归 | 会员缺省头像在小屏/大字体双轴居中；代客多颜色手机六列/宽屏十列可读可操作 | `A+M` | 本地 `PASS`；真实设备 `BLOCKED` |
| RT-14 | 文本压缩 | ≥1 KiB 文本按协商只 gzip 一次、可解码且 `Vary` 正确；小响应和 PNG/JPEG/WebP 不压缩 | `A+M` | 基线自动化 `A PASS`；Gate A M8 Runtime/HTTPS `NOT RUN`；`M BLOCKED` |

## 6. 安全、隐私与可观测性

| ID | 场景 | Gate A 断言 | 证据 | 当前 RC |
|----|------|-------------|------|---------|
| SE-01 | Secret 扫描 | 源码、日志、artifact、source map 无 Secret/私钥/连接串 | `A` | M8 基线 Run 34242753255 与 M7 持久日志 `PASS`；后续候选/真实 RC 待重验 |
| SE-02 | 产物 Origin | 无 `.example.invalid`、开发 Origin 或意外主机 | `A` | 预 RC 保留 `.test` Origin `PASS` 且不可发布；真实 Origin `BLOCKED` |
| SE-03 | 权限 | UI 隐藏不替代后端 ADMIN+/owner 校验 | `A+M` | 当前 `A PASS`；`M BLOCKED` |
| SE-04 | 日志脱敏 | 无密码、Token、完整 Redis URL、reason/key 和个人敏感信息 | `A+M` | 当前 M7 日志精确 Secret/高置信模式 0 命中 `A PASS`；`M BLOCKED` |
| SE-05 | 依赖 | 微信运行时可达高风险均关闭或获有期限例外 | `A` | M8 基线 Run 34242753255 `PASS`；现有例外 2026-11-30 到期 |
| SE-06 | 内部声明 | 体验版明确受邀、不可公开、无微信支付/登录误导 | `M` | 规则已冻结；体验版 `BLOCKED` |
| SE-07 | 隐私 | Gate A 使用合成/受控账号，数据保留、反馈和停用日期明确 | `M` | 治理已冻结；实际体验版 `BLOCKED` |

## 7. Gate A 最小验收数据集

Gate A 已通过 M7 后端 API/受控任务在**升级后的 Gate A MySQL 与持久图片存储**
中建立合成数据，并保存不含密码、Token、手机号或请求/响应正文的成功摘要。
开发机 `db.sqlite3` 中的数据仍只是本地功能测试资产，没有被复制为 Gate A 证据。

当前 Gate A 综合数据覆盖 3 个合成普通用户、3 Wallet/7 WalletTransaction、1 个 221 色
商品/三启用色、6 笔预留订单、5 Payment/Settlement、2 Refund、6 条预约和 1 个单日店休；
数据后 `wallet_reconcile=4/0/0`，Backup/Restore 与 225 图片通过。合成凭据与脱敏 Record
分离保管，不在本矩阵中记录任何凭据值。

| 数据域 | 最低样本 | 必须证明 |
|--------|----------|----------|
| 身份 | NORMAL USER、DISABLED USER、ADMIN、SUPER_ADMIN；需要时使用不可登录的历史 DELETED 事实 | 角色/状态/权限/Token 边界，全部使用合成身份 |
| Product | Online/Draft/Offline Experience 与 weekday/holiday Option；fixed Kit；color-selectable Kit | 公共隐藏、管理查询、价格/快照、上架校验 |
| 颜色与图片 | 全部 221 个来源槽和持久图片；至少若干启用有货色、启用零库存色、禁用色；M8 后再验 HEX 直绘 | M7 DB 的 slot/code/name/URL、manifest 的 HEX/RGB/checksum、按商品独立库存；M8 DB/API 的逐槽 HEX、零色块 PNG 请求 |
| Order/Inventory | Pending/Cancelled/Paid/Completed；Experience/fixed/color/mixed；admin adjustment/order deduction/cancel restore/refund restore | 状态机、金额/重量快照、扣减/恢复、流水/Audit 和幂等 |
| Wallet/Payment/Refund | 零余额与非零余额、调账、wallet/manual settlement、可退款和已退款样本 | 权威余额链、资金关联、上限/敞口、真实微信 provider 仍 503 零写入 |
| Reservation | pending/confirmed/rejected/cancelled，`no_capacity`、customer/store_closed，单日店休和当前固定店休 | 用户/管理员投影、提前三小时、M7 更换与历史不复活 |

M7 数据创建后的只读一致性检查、非空 Backup/Restore 和加密异机副本已完成；M8 应用后
必须重新完成数据后 Backup/Restore，域名可用后再以同一不漂移数据开始真机矩阵。
任何为了凑状态而直接改表的数据都不能作为验收样本。

## 8. Gate B 追加域（本次不执行）

公开版必须另行扩充并通过：微信登录及账号绑定/冲突/禁用、登录/注册限流、refresh
轮换、Order create 服务端幂等、微信支付/回调/查单/退款/对账、Reservation N2 订阅
授权与 durable outbox/worker/重试/监控、正式监控告警、隐私保护指引、用户权利和平台
提审。Gate A 的账号密码、合成钱包余额、ADMIN 人工 Paid 和合成数据不能作为这些项目的证据。

## 9. RC 验收报告模板

```text
RC / Git SHA / CI run / artifact checksum：
后端、前端、OpenAPI 版本：
环境 / API Origin / 数据集：
设备、系统、微信、基础库、网络：
执行人 / 日期：Yijie Shen（实际执行时填写日期）
矩阵 ID：
结果：PASS / FAIL / BLOCKED / NOT RUN
证据链接：
缺陷 ID、严重性、复现与处置：
风险例外 ID 与到期日（如有）：
```

测试账号只记录角色和受控标识，不在文档中记录密码、Token、OpenID 或个人信息。
