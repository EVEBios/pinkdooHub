# 微信发布 Go/No-Go Checklist

> **Status:** No-Go / Not Authorized — GitHub-hosted disposable M7→M8 完整 updater 与最终 9/9 CI 已通过；持久 Gate A 仍为 M7，5Mbps 容量失败处置、持久升级、真实 HTTPS RC 与真机仍阻断
> **Last Updated:** 2026-09-09
> **Current Scope:** 微信小程序内部测试版（Gate A）

本清单是发布决策索引，不替代 CI、演练或验收证据。勾选项必须附证据链接、执行时间和责任人；“本机试过”“历史通过”“应该没问题”不能勾选。Phase 9.1 只建立清单，不授权微信上传、体验版分发、提审或公开发布。

2026-09-07 候选覆盖说明：历史 Phase 9.2/9.3/9.4 的勾选项绑定 M0–M2 和旧 SHA，
只说明当时的流程或基础设施能力，不自动满足当前 M7 RC。审计起点 `c6778e7...` 的
[Run 34104680282](https://github.com/EVEBios/pinkdooHub/actions/runs/34104680282)
保留为 7/8 失败记录；修复后的历史 M7 PR head `4d6430c...` 已由
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349)
在 merge-ref `ccbbe9d...` 的干净 checkout 上完整重跑并取得 8/8。任何标记为“历史”
的 `[x]` 仍不能用于跳过持久环境、RC 或真机项目。

本地提交 `58d8435...` 包含 M7 CI gate 修复；提交前同内容 dirty 工作树的一次性
MySQL 报告完成 0→7、M0–M6→M7 和联合 `21 passed`。该 M7 远端 Run 已独立复现
workflow 覆盖并保存证据，详见
[M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

2026-09-08 当前覆盖说明：持久 Gate A 已从只读确认的 M2 起点升级到 M7，
完成 Wallet/legacy settlement 补齐与对账、221 色与持久图片、候选韧性、综合合成
数据以及数据后 Backup `20260908t021224z`/独立 Restore。Operations head
`353455bb...` 由 [Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663)
在干净 PR checkout 完成 8/8。详细证据见
[Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。
该报告是当前持久 M7 检查点，不是 M8 证据。M8 head
`4e745848315aab56805a872ecf5b9f5e3c10135b`、merge-ref `3ddda81...` 已由
[Run 34242753255](https://github.com/EVEBios/pinkdooHub/actions/runs/34242753255) 完整
取得 8/8；首轮 Run 34242022911 的 7/8 与 Reservation 迁移清单漏 M8 修复均保留在
[M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。其后新增的 M7→M8/Online no-op
保护现已收口为 head `fa6fce05...`、merge-ref `b2f02ebc...`，并由
[Run 34281512196](https://github.com/EVEBios/pinkdooHub/actions/runs/34281512196) 在干净
PR checkout 完成 8/8；详见
[M8 发布加固远端 CI 报告](reports/m8_hardening_remote_ci_2026-09-09.md)。M8 尚未应用
Gate A；下方除 HTTPS/微信平台/真机/签署外，还保留持久 M7→M8、
HEX/gzip、M8 数据后恢复等未勾选项。

2026-09-09，仓库新增第 9 个必需 CI Job，在 GitHub-hosted disposable Linux
上从冻结 M7 source 完整执行代表数据、221 PNG、M7 Backup/同 ID Restore、
M7→M8 plan/apply/replay、M8 Runtime 的 221 HEX/gzip/PNG 和 M8 Backup/同 ID Restore。
Head `62b1b15...` / merge-ref `a9ff3d2...` 的
[Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) 最终 9/9
Success；首次 OpenAPI Job 在还未执行契约检查时遭遇一次性 `pip`
TLS/truststore 异常，同一 clean checkout 原样重跑后 51 秒通过。Gate A Job
14/14 阶段、artifact 脱敏扫描和零残留均通过，详见
[Gate A M7→M8 完整更新器远程 CI 演练报告](reports/gatea_m7_m8_updater_remote_ci_2026-09-09.md)。
这关闭了一次性完整 updater 门槛，不关闭持久 Gate A 的当次只读预检、
新 Backup/Restore、写授权、Runtime 切换和数据后恢复。

## 1. Gate A：内部微信测试版

### 1.1 范围、候选与可追溯性

- [x] RDR-001 冻结为微信单平台、受邀内部测试、不可公开；
- [x] Phase 9.1 当前基线审计和八类交付物已建档；
- [x] 所有责任角色已映射为 Yijie Shen；
- [x] 项目负责人 Yijie Shen 已于 2026-08-29 Review 并确认 Phase 9.1 Complete；
- [ ] Gate A RC 建立前填写计划窗口和当次审批时间；
- [ ] RC Git SHA 工作树干净，后端/前端/微信版本映射明确；
- [x] M7 CI gate 修复已形成独立本地提交 `58d8435...`；该项只证明提交边界；
- [x] M7 持久检查点 Operations 已绑定 PR head `353455bb...`、merge-ref `92649bac...` 和 Run 34178908663；
- [x] 后端与 `weapp` artifact 均来自同一已通过 Run，并记录 GitHub digest；
- [x] M8 基线已绑定 PR head `4e745848...`、merge-ref `3ddda81...` 和 Run 34242753255；该项只关闭该 SHA 的仓库 CI；
- [x] M8 Run 的后端、前端与非发布 `weapp` artifact 来自同一 merge-ref，7 组大小与 GitHub digest 已记录；
- [x] M7→M8/Online no-op 保护已绑定干净 head `fa6fce05...`、merge-ref `b2f02ebc...` 与 Run 34281512196；后端、前端、OpenAPI、非发布 `weapp`、依赖审计和仓库卫生均来自同一完整 8/8；
- [x] 完整 updater 已绑定 head `62b1b15...`、实际 checkout `a9ff3d2...` 和 Run 34288613644；最终 9/9，并单独保留 OpenAPI 依赖安装瞬时失败/重跑边界；
- [ ] OpenAPI 摘要、运行时版本、微信开发者工具/上传工具版本已记录；
- [ ] 体验版名称、界面和测试说明明确标识“内部测试”，无公开承诺。
- [x] 备案前预 RC 已绑定 `c4d27a8...`、Node 24.13.0/npm 11.6.2、开发者工具 Stable 2.02.2608060、不可发布 `.test` Origin、97 文件/603,624 bytes、0 source map 和 manifest `aeb81ef...`；该项不替代上面的真实 RC；

### 1.2 CI 与代码质量

- [x] 历史 Phase 9.2/9.3：M0–M2 候选曾从干净 checkout 完成 8/8；仅作为流水线基础能力证据；
- [x] M7 持久检查点 Operations 在同一干净 PR checkout 完成 8/8；Run 34178908663 success；
- [x] 该 M7 Run 的 `backend-sqlite` 成功并保存 JUnit；当时本地完整套件为 `2039 passed, 31 skipped`；
- [x] 该 M7 Run 的 `backend-mysql-release` 在专用 MySQL 8.0.46 验证 M0–M7、M5→M6→M7 历史重放、M6/M7 快照和三域联合门槛；
- [x] Wallet 扩展 MySQL 门槛已在一次性 MySQL 8.0.46 覆盖并发调账/余额支付/退款、真实 1205、1213 全事务重试、锁序、`EXPLAIN` 与 Inventory 联合回归；Wallet `9 passed`、三域联合 `30 passed`；
- [x] 包含 Wallet-expanded workflow 的 head `62f807a...` 已由 Run 34134341829 在远端
  Runner 完成 8/8；三域联合、JUnit/cleanup artifact 上传步骤均 success；
- [x] 该 M7 `frontend-quality` 远端结果覆盖 TypeScript、ESLint、Stylelint、`83 suites / 562 tests` 和 17 项 CI policy；
- [x] 该 M7 `openapi-contract`、`weapp-build`、repository hygiene 与双依赖审计均在同一 Run 通过；
- [x] 包含 Gate A Operations 及 loopback 快速复用修复的 Run 34178908663 再次 8/8，保留 7 组绑定 merge-ref/Run 的 artifact；
- [x] 本轮完整本地后端结果为 `2039 passed, 31 skipped in 112.21s`；31 项为三类显式 MySQL-only 门槛，对应集合由远端 `backend-mysql-release` 覆盖，该项不是 RC 证据；
- [x] 当时前端本地结果为 `83 suites / 562 tests`；该项不是远端或 RC 证据；
- [x] M8 Run 34242753255 的 8 个 Job 全部 success；`backend-mysql-release` 的 M6→M7→M8、联合 MySQL gate 与 cleanup 均 success；
- [x] M8 本地完整后端为 `2069 passed, 31 skipped`，前端为 `84 suites / 573 tests`，并通过 TypeScript、ESLint、Stylelint、OpenAPI drift、compileall、pip check 与 17 项 CI policy；本地计数不冒充远端日志；
- [x] 后续 M7→M8/Online no-op 候选的完整 `tests/release` 为 `229 passed`，覆盖显式 source、Record 组合、版本化 21 表内容摘要/Restore、停写 raw 预检、live replay、图片不漂移与事务内 no-op；
- [x] 本轮本地候选的完整后端为 `2317 passed, 33 skipped in 125.31s`，编译检查通过；该本地计数已收口进 `fa6fce05...`，但不冒充远端日志、完整 updater 或 Gate A 证据；
- [x] 2026-09-09 本地 2 核/4GiB 容器包络/共享 5Mbps 探索轮已完整采集 A/B/C/D、5/10 VU 共 12/12 个 Profile，150 个写旅程、最终对账、日志/statement 和资源清理均有独立报告；
- [ ] 上述探索轮的全部冻结容量门槛通过，或已对 10 VU 持续未压缩色板的 P95/428 drops 形成有时限、可监控且由风险接受人签署的处置；其余 11 项通过不能覆盖整轮 `FAIL`；
- [x] 上述后续候选已由新干净 head `fa6fce05...` / merge-ref `b2f02ebc...` 的 Run 34281512196 完整远端 8/8 复现并保存 7 组 artifact；
- [x] 同一干净候选在 GitHub-hosted disposable Linux/MySQL 完整执行 M7→M8 updater；Run 34288613644 的 14/14 阶段、M7/M8 双 Backup/Restore、Runtime 和脱敏 artifact 已保存；
- [x] Node/npm/Python/Taro 支持版本由仓库和 CI 固定。

### 1.3 环境、HTTPS 与 Secret

- [ ] 测试 API Origin、DNS、证书、续期责任和目标 AppID 已冻结；
- [ ] 微信后台 request/upload/download 合法域名与实际调用一致；
- [x] 生产语义演练启动强制 `APP_DEBUG=false`、MySQL、随机 JWT 和必要配置；
- [x] Phase 9.3 MySQL、Redis 和图片存储均为专用/受控资源；
- [x] Gate A Secret inventory 已映射到 Root 文件边界、精确权限/读取主体、轮换/泄漏触发和责任人；Gate B 集中 Secret Manager 单独延期；
- [x] 2026-09-08 当前 M7 持久主机 24 小时日志重跑，精确 Secret 和高置信敏感模式命中均为 0，成功结果不保存原始日志；
- [x] Gate A source map 策略已批准为不生成、不上传；项目配置和 2026-09-02 历史预 RC 均为 0 source map；当前 RC 仍须重验；
- [x] 当前 M7 日志无密码、Token、完整 Redis/MySQL URL、AppSecret、私钥或高置信敏感模式命中，扫描只输出聚合；

### 1.4 迁移、备份与恢复

- [x] 历史 M2：空 MySQL 8+ 0→2、M0/M1 代表数据升级、部分失败处置和资源清理曾通过；
- [x] 历史 M2：持久 Gate A 的代表性 User/Product/图片/Order/Inventory/Audit 非空备份、无端口独立恢复与加密异机副本曾通过；
- [x] 写前只读查询并记录 Gate A 真实 Aerich M0–M2、Schema/数据摘要、图片 manifest 和运行镜像；没有以 2026-09-02 历史记录替代查询；
- [x] 当前干净 PR checkout 在 CI MySQL 8.0.46 完成空库 0→7、M5→M6→M7 workflow 重放、M6/M7 snapshot 与远端 cleanup artifact；0/1/2/3/4/5/6→7 完整历史矩阵已在一次性 MySQL 执行，持久 Gate A 还额外真实执行 M2→M7；
- [x] 非空 Gate A 在停写窗口创建新 MySQL/图片一致 Backup `20260908t000731z`，并在独立无端口实例恢复经只读确认的 M2 数据通过；
- [x] 批准的非空 M2→M7 升级入口已实现并完成单测/一次性 MySQL 8.0.46 验证；它绑定
  source/target SHA、24 小时内 Backup/Restore、停写快照、逐步迁移、Wallet、MARD 与
  成功 Record，失败保持停止并阻断盲目重跑；现有 `initial-migrate` 仍只接受空库；
- [x] 按只读确认的 M2 起点依次应用 M3→M4→M5→M6→M7，成功 Record 绑定 DDL/Aerich、镜像、前后摘要与零漂移断言；
- [x] M4 后按同一冻结上界执行 wallet account preview/apply/二次 preview、legacy settlement preview/apply 和只读 `wallet_reconcile`，待补齐和差异均为零；
- [x] M6 后在 Gate A MySQL 导入 221 色 slot/code/name/URL，按冻结 manifest/checksum 发布 221 张持久图片，综合测试商品启用 3 色并设置库存；本地 `db.sqlite3` 没有被当作此证据；
- [x] M7 后核验 `reservation_settings` 只有一条 `singleton_key=1`、默认/当前周一、CHECK/UNIQUE 存在，已有数据不漂移；
- [x] 部署 Runtime `73dca350...`并写入匹配的受控升级 Record；综合数据后新 Backup `20260908t021224z`/独立 Restore 与 loopback 纵向数据链路通过；
- [x] 保留期、删除审批、恢复授权、RPO/RTO 和周期演练频率已冻结；当前 M7 数据后 Backup/Restore Record 已生成；
- [ ] M8 写前重新只读确认当前 Gate A 精确为 M0–M7，数据库/225 图片与 M7 Record 一致，并冻结目标 SHA/Image、停写窗口、执行/复核人与明确写授权；
- [ ] 为当次 M7→M8 创建新的同点 MySQL/图片 Backup；M7/M8 Record 必须包含 `m7-preserved-business-v1`，对 20 个非 `bead_colors` 表和该表 M7 投影（共 21 个业务表）做内容 SHA-256，独立无端口 Restore 必须重算并精确匹配，同时验证 Schema、225 图片、空 Redis 和 Restore App；不得仅复用 `20260908t021224z` 或只比较聚合计数；
- [x] 受保护的 M7→M8 仓库候选已经实现：必须显式 `--source-version 7`，只执行 M8，比较版本化 21 表内容摘要、Aerich 精确链与完整图片 manifest，并要求三次 MARD 结果精确 no-op；旧调用默认 M2 且误用时在写前 fail closed；
- [x] M8 原语前的停写 source preflight 已实现：`swatch_hex` 列必须为 0，221 条 M7 slot/code/name/URL/sort/active 必须逐项等于冻结 manifest，221 张预期 PNG 必须为普通非软链接文件、SHA-256 精确且权限 `0644`；任一失败不得调用迁移任务；
- [x] 独立只读代码审查发现成功重放没有重新证明 App/Nginx 仍停服；修复并补齐服务状态 fail-closed 矩阵后复核无未解决 P0–P3，且已绑定 `fa6fce05...` / Run 34281512196；
- [x] M7→M8 加固已形成最终干净 head `fa6fce05...`，并完成该 SHA 的完整远端 CI；
- [x] 候选在 GitHub-hosted disposable Linux/MySQL 完整执行 updater 并保存独立 evidence；source 为真实 M7 Runtime/代表数据而非伪造 Record，且未拆跑内部原语；
- [x] 一次性完整 updater 的 M8 列形状、221 槽逐项 HEX/唯一性、`m7-preserved-business-v1` 内容零迁移漂移和 225 图片 manifest 通过；
- [ ] 持久 Gate A 的 M8 `swatch_hex` 列形状、221 槽逐项 HEX/唯一性通过，且颜色 code/name/URL/active/sort、商品颜色库存、订单快照和 `m7-preserved-business-v1` 保护的其他业务内容不漂移；
- [x] publisher 候选已允许已有 Online 自选色商品在事务锁定后仍为精确 no-op 时通过，并在任何数据库/图片漂移时写前拒绝；本地自动化覆盖 221 张全部复用、零数据库/图片写入；
- [ ] 在持久 Gate A 受控 M7→M8 编排内取得精确 no-op 证据；不得脱离编排直接运行 publisher、临时改商品状态或把 PNG 转 WebP；
- [ ] 持久 Gate A 成功升级后继续保持 App/Nginx 停止，以完全相同的 source version/SHA/Backup ID 紧邻重放 upgrade plan；只有 live DB、完整图片 manifest、21 表内容摘要和只读 MARD preview 均匹配且输出 `already_current=true` 才可 `app-up`。不得误认为 `app-up` 自身会执行这些 live 检查；
- [ ] 整个 Backup→升级→replay→`app-up` 维护窗口已证明没有直接 SQL、其他迁移进程或宿主图片旁路写入；不能把 DB 锁/内容摘要/图片原子替换描述为跨 DB/文件系统绝对原子事务；
- [ ] M8 数据后创建新的 Backup/独立 Restore/加密异机副本，并把 Runtime、Operations、upgrade、backup 与 restore Record 精确绑定。

### 1.5 运行时与运维

- [x] FastAPI/Uvicorn 可启动、优雅停止、重启，错误不泄露配置；
- [x] liveness 与 DB/Redis readiness 分离，依赖故障时不接业务流量；
- [x] Redis 认证/网络边界和故障行为验证通过；
- [x] 图片上传、HTTPS 读取、持久化、备份和恢复通过；
- [x] SUPER_ADMIN bootstrap 一次性、严格重放、可审计，初始凭据已安全处置；
- [x] 日志可按精确 Compose project 查询；24 小时请求/4xx/5xx/时延聚合、MySQL/Redis 摘流量与恢复、App 重启和敏感扫描已真实通过；
- [x] 初始测试人员、allowlist、反馈入口、14 日窗口/停用规则、数据清理和事故联系人已冻结。
- [x] 当前 M7 镜像在升级后 Gate A 重新验证 liveness/readiness、MySQL/Redis 故障恢复、图片持久化、日志脱敏与 App 重启，并生成候选 SHA 级不可覆盖 Record；
- [x] 一次性 M8 Runtime 已实测 221 HEX、identity 63,445 bytes 与 gzip 10,948 bytes（减少 52,497 bytes）、正确 `Vary`、小响应不压缩和 PNG 不重复压缩；
- [ ] M8 Runtime 在 Gate A 启动后重新验证 liveness/readiness、数据库/图片无漂移、日志脱敏、故障恢复与重启；
- [ ] Gate A 实测协商 gzip：大于等于 1 KiB 的文本只压缩一次且可解码/含正确 `Vary`，小响应和 PNG/JPEG/WebP 不压缩；

### 1.6 微信与业务验收

- [ ] iOS 和 Android 真机记录设备、系统、微信、基础库和网络；
- [ ] request/upload/download、HTTPS 和合法域名在真机通过；
- [x] 历史 M2：Guest、普通用户、ADMIN、SUPER_ADMIN、禁用用户服务端 loopback 纵向链路曾通过；
- [x] 当前本地自动化覆盖 Product、Cart、Order、Wallet/Payment/Refund、颜色 Kit、Reservation、M7 固定店休、代客多颜色与头像布局；该项不替代当前远端 CI、Gate A HTTPS 或真机；
- [ ] Product、Cart、创建订单、用户订单/取消、管理订单通过；
- [ ] Product 管理、图片、Inventory、Audit、用户禁用通过；
- [ ] 用户钱包余额/流水、余额支付、不可用真实微信充值、管理员客户钱包/调账、代客钱包订单和全额退款通过；
- [ ] fixed/color-selectable Kit 的 221 色搜索、每色 10g 数量、购物车/快照、颜色库存扣减/取消/PAID 退款恢复及流水通过；
- [ ] M8 公开 221 色全部返回规范 HEX，小程序以 `backgroundColor` 直绘且数字色块零 PNG 请求；兼容 PNG 仍可作为旧客户端回退；
- [ ] 用户预约创建/列表/详情/取消，管理员列表/确认/无空位拒绝，缺手机号补录和隐私投影通过；
- [ ] M7 固定店休读取/更换、命中新星期的未来预约原子取消、旧星期恢复，以及单日店休关闭/恢复且历史预约不复活通过；
- [ ] 会员缺省头像在小屏/大字体双轴居中，代客扣款手机六列/宽屏十列多颜色布局可用；
- [ ] access/refresh 失效、权限、资源隐藏和错误信封通过；
- [ ] 弱网、断网、网络恢复、前后台、锁屏、分包首次加载通过；
- [ ] 重复点击、上传中断和服务端成功/客户端未知有安全收敛证据；
- [ ] 所有 `FAIL/BLOCKED/GAP` 已关闭、延期到非当前 Gate或进入明确风险例外。

### 1.7 Gate A 决策

- [ ] 没有越权、Secret 泄漏、数据破坏、重复订单/库存错误或无法恢复的阻断缺陷；
- [ ] [risk_register.md](risk_register.md) 中所有 Gate A P0/P1 已关闭或满足例外规则；
- [ ] Yijie Shen 分别以测试负责人、技术负责人和项目负责人角色记录 Go 结论与时间；
- [ ] 上传/分发体验版已取得单独外部操作授权；
- [ ] 明确 Gate A 不授权提审或公开发布。

任一必需项未勾选，结论即为 **No-Go**。

## 2. Gate B：对外公开微信小程序追加门槛

Gate A 全部重新绑定公开 RC 后，还必须：

- [ ] 微信登录 code2Session、OpenID/UnionID、账号绑定/冲突/禁用/恢复通过；
- [ ] 登录/注册限流、refresh token 轮换/撤销/重放检测通过；
- [ ] Order create 服务端幂等及并发/unknown 结果通过；
- [ ] 若在线收款：微信支付下单、调起、验签、金额核对、通知幂等、查单、关闭、退款、对账和告警通过；
- [ ] 若不在线收款：用户文案、履约和订单状态不暗示已提供在线支付；
- [ ] 正式 MySQL/Redis/图片、Secret、备份恢复、监控告警和事故流程通过；
- [ ] 隐私保护指引、同意/撤回、账号注销/删除、数据保留和联系方式完成 Review；
- [ ] 小程序主体、类目、备案/适用要求、审核材料、审核账号与服务内容一致；
- [ ] 管理分包公开发布决策完成；
- [ ] 发布观察窗口、回滚/停写/恢复权限和联系人冻结；
- [ ] 取得提审和正式发布的分别授权。

2026-09-02 注：身份与 refresh/限流项的仓库实现与自动化已完成，但真实 AppID/真机和正式监控证据尚缺，因此复选框保持未勾选；Secret、存储和隐私项同样只完成设计/代码边界，不以本地结果替代外部 Gate B 证据。证据索引见 [Phase 9.5 基线](phase95_public_security_baseline.md)。

## 3. 自动 No-Go 条件

以下任一情况无需等待表决，直接 No-Go：

- artifact、Git SHA、OpenAPI 或环境来源不能证明一致；
- CI 必需 Job 未运行、被无批准跳过或结果不可复核；
- 连接目标身份不明、备份未恢复验证或迁移状态无法解释；
- 当前数据库为 M7 却省略显式 `--source-version 7`、新 Backup/Restore 缺少或不匹配 `m7-preserved-business-v1`、raw M7 色板/schema/PNG 预检失败、所绑定候选未通过完整 updater 隔离 MySQL 门槛，或绕过编排直接执行 M8 内部原语/独立 publisher；
- 成功 Record 后未在同一停写窗口紧邻完成 live replay verification、把 `app-up` 的 Record 校验误当实时 DB/图片/MARD 校验，或存在不能排除的直接 SQL/宿主图片旁路写入；
- 存在越权、Secret/个人敏感信息泄漏、数据破坏或不可恢复风险；
- 订单/库存/支付出现重复、伪造、金额不一致或 unknown 无安全处置；
- 真机 HTTPS、合法域名、request/upload/download 不通；
- Gate A 试图公开分发，或 Gate B 缺少登录/支付（适用时）/安全/隐私硬门槛；
- 实际包与已测试包不同，或在开发者电脑手工修改后上传。

## 4. 决策记录模板

```text
Decision ID：
Gate：A / B
RC / Git SHA / CI run / artifact checksum：
目标环境 / 微信版本：
Checklist 证据索引：
未关闭风险与例外：
决定：GO / NO-GO
决定理由：
测试负责人：Yijie Shen（待签署）
技术负责人：Yijie Shen（待签署）
项目负责人：Yijie Shen（待签署）
外部操作授权范围：无 / 上传体验版 / 提审 / 正式发布
决定时间与观察窗口：
停止、回滚或恢复触发条件：
```

GO 只授权记录中写明的 Gate、RC、环境和外部操作；不能自动延伸到下一 Gate、另一个 SHA、提审或正式发布。
