# 微信发布 Go/No-Go Checklist

> **Status:** No-Go / Not Authorized — M7 服务端/持久数据已关闭；域名/HTTPS、真实 RC 与真机仍阻断
> **Last Updated:** 2026-09-08
> **Current Scope:** 微信小程序内部测试版（Gate A）

本清单是发布决策索引，不替代 CI、演练或验收证据。勾选项必须附证据链接、执行时间和责任人；“本机试过”“历史通过”“应该没问题”不能勾选。Phase 9.1 只建立清单，不授权微信上传、体验版分发、提审或公开发布。

2026-09-07 候选覆盖说明：历史 Phase 9.2/9.3/9.4 的勾选项绑定 M0–M2 和旧 SHA，
只说明当时的流程或基础设施能力，不自动满足当前 M7 RC。审计起点 `c6778e7...` 的
[Run 34104680282](https://github.com/EVEBios/pinkdooHub/actions/runs/34104680282)
保留为 7/8 失败记录；修复后的当前 PR head `4d6430c...` 已由
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349)
在 merge-ref `ccbbe9d...` 的干净 checkout 上完整重跑并取得 8/8。任何标记为“历史”
的 `[x]` 仍不能用于跳过持久环境、RC 或真机项目。

本地提交 `58d8435...` 包含 M7 CI gate 修复；提交前同内容 dirty 工作树的一次性
MySQL 报告完成 0→7、M0–M6→M7 和联合 `21 passed`。当前远端 Run 已独立复现
workflow 覆盖并保存证据，详见
[M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

2026-09-08 当前覆盖说明：持久 Gate A 已从只读确认的 M2 起点升级到 M7，
完成 Wallet/legacy settlement 补齐与对账、221 色与持久图片、候选韧性、综合合成
数据以及数据后 Backup `20260908t021224z`/独立 Restore。Operations head
`353455bb...` 由 [Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663)
在干净 PR checkout 完成 8/8。详细证据见
[Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。
下方仍未勾选的当前 Gate A 主链项均依赖真实 HTTPS/微信平台/真机或最终签署。

## 1. Gate A：内部微信测试版

### 1.1 范围、候选与可追溯性

- [x] RDR-001 冻结为微信单平台、受邀内部测试、不可公开；
- [x] Phase 9.1 当前基线审计和八类交付物已建档；
- [x] 所有责任角色已映射为 Yijie Shen；
- [x] 项目负责人 Yijie Shen 已于 2026-08-29 Review 并确认 Phase 9.1 Complete；
- [ ] Gate A RC 建立前填写计划窗口和当次审批时间；
- [ ] RC Git SHA 工作树干净，后端/前端/微信版本映射明确；
- [x] M7 CI gate 修复已形成独立本地提交 `58d8435...`；该项只证明提交边界；
- [x] 当前 Operations 候选已绑定 PR head `353455bb...`、merge-ref `92649bac...` 和 Run 34178908663；
- [x] 后端与 `weapp` artifact 均来自同一已通过 Run，并记录 GitHub digest；
- [ ] OpenAPI 摘要、运行时版本、微信开发者工具/上传工具版本已记录；
- [ ] 体验版名称、界面和测试说明明确标识“内部测试”，无公开承诺。
- [x] 备案前预 RC 已绑定 `c4d27a8...`、Node 24.13.0/npm 11.6.2、开发者工具 Stable 2.02.2608060、不可发布 `.test` Origin、97 文件/603,624 bytes、0 source map 和 manifest `aeb81ef...`；该项不替代上面的真实 RC；

### 1.2 CI 与代码质量

- [x] 历史 Phase 9.2/9.3：M0–M2 候选曾从干净 checkout 完成 8/8；仅作为流水线基础能力证据；
- [x] 当前 Operations 候选在同一干净 PR checkout 完成 8/8；Run 34178908663 success；
- [x] 当前 Run 34178908663 的 `backend-sqlite` 成功并保存 JUnit；本地完整套件为 `2039 passed, 31 skipped`；
- [x] 当前 Run 34178908663 的 `backend-mysql-release` 在专用 MySQL 8.0.46 验证 M0–M7、M5→M6→M7 历史重放、M6/M7 快照和三域联合门槛；
- [x] Wallet 扩展 MySQL 门槛已在一次性 MySQL 8.0.46 覆盖并发调账/余额支付/退款、真实 1205、1213 全事务重试、锁序、`EXPLAIN` 与 Inventory 联合回归；Wallet `9 passed`、三域联合 `30 passed`；
- [x] 包含 Wallet-expanded workflow 的 head `62f807a...` 已由 Run 34134341829 在远端
  Runner 完成 8/8；三域联合、JUnit/cleanup artifact 上传步骤均 success；
- [x] 当前 `frontend-quality` 远端结果覆盖 TypeScript、ESLint、Stylelint、`83 suites / 562 tests` 和 17 项 CI policy；
- [x] 当前 `openapi-contract`、`weapp-build`、repository hygiene 与双依赖审计均在同一 Run 通过；
- [x] 包含 Gate A Operations 及 loopback 快速复用修复的 Run 34178908663 再次 8/8，保留 7 组绑定 merge-ref/Run 的 artifact；
- [x] 本轮完整本地后端结果为 `2039 passed, 31 skipped in 112.21s`；31 项为三类显式 MySQL-only 门槛，对应集合由远端 `backend-mysql-release` 覆盖，该项不是 RC 证据；
- [x] 当前前端本地结果为 `83 suites / 562 tests`；该项不是远端或 RC 证据；
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
- [x] 保留期、删除审批、恢复授权、RPO/RTO 和周期演练频率已冻结；当前数据后 Backup/Restore Record 已生成。

### 1.5 运行时与运维

- [x] FastAPI/Uvicorn 可启动、优雅停止、重启，错误不泄露配置；
- [x] liveness 与 DB/Redis readiness 分离，依赖故障时不接业务流量；
- [x] Redis 认证/网络边界和故障行为验证通过；
- [x] 图片上传、HTTPS 读取、持久化、备份和恢复通过；
- [x] SUPER_ADMIN bootstrap 一次性、严格重放、可审计，初始凭据已安全处置；
- [x] 日志可按精确 Compose project 查询；24 小时请求/4xx/5xx/时延聚合、MySQL/Redis 摘流量与恢复、App 重启和敏感扫描已真实通过；
- [x] 初始测试人员、allowlist、反馈入口、14 日窗口/停用规则、数据清理和事故联系人已冻结。
- [x] 当前 M7 镜像在升级后 Gate A 重新验证 liveness/readiness、MySQL/Redis 故障恢复、图片持久化、日志脱敏与 App 重启，并生成候选 SHA 级不可覆盖 Record；

### 1.6 微信与业务验收

- [ ] iOS 和 Android 真机记录设备、系统、微信、基础库和网络；
- [ ] request/upload/download、HTTPS 和合法域名在真机通过；
- [x] 历史 M2：Guest、普通用户、ADMIN、SUPER_ADMIN、禁用用户服务端 loopback 纵向链路曾通过；
- [x] 当前本地自动化覆盖 Product、Cart、Order、Wallet/Payment/Refund、颜色 Kit、Reservation、M7 固定店休、代客多颜色与头像布局；该项不替代当前远端 CI、Gate A HTTPS 或真机；
- [ ] Product、Cart、创建订单、用户订单/取消、管理订单通过；
- [ ] Product 管理、图片、Inventory、Audit、用户禁用通过；
- [ ] 用户钱包余额/流水、余额支付、不可用真实微信充值、管理员客户钱包/调账、代客钱包订单和全额退款通过；
- [ ] fixed/color-selectable Kit 的 221 色搜索、每色 10g 数量、购物车/快照、颜色库存扣减/取消/PAID 退款恢复及流水通过；
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
