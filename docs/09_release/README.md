# pinkdooHub 发布文档

> **Current Phase:** Wallet 扩展 MySQL 已远端通过；Gate A 运维候选待新 CI，持久升级/回填、色板、RC 与外部条件仍阻断 — Gate A/Gate B 均保持 No-Go
> **Phase 9.1 Status:** Complete — Yijie Shen 于 2026-08-29 完成 Review
> **Last Updated:** 2026-09-07
> **Release Scope:** 微信小程序内部测试版（Gate A）

本目录保存可以直接用于后续 CI、演练和发布决策的操作文档。长期路线与公开发布门槛仍以 [Phase 9 微信小程序发布规划](../08_frontend/phase9_wechat_release_plan.md) 为总纲；本目录负责记录当前版本的决定、证据、责任和可执行清单。

## 0. 当前候选覆盖层（2026-09-07）

2026-09-02 以前的 Phase 9.2/9.3/9.4 报告仍是有效的**历史证据**，但它们绑定旧 SHA、
旧 OpenAPI、Aerich M0–M2 和旧微信产物，不能证明当前 M7 候选可发布。审计起点
`c6778e79...` 的 [Run 34104680282](https://github.com/EVEBios/pinkdooHub/actions/runs/34104680282)
保留为 7/8 失败记录；M7 gate 修复随后进入当前 PR head
`4d6430c1bf9532d644bd7039ed7603fe9ee2c2bf`。新的
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349)
已在 merge-ref `ccbbe9dcb675a99369867814386051befc5922f2` 的干净 checkout 上取得 8/8，
保存 7 组带 merge-ref、Run ID 和 digest 的 artifact；不能再把旧 Run 的 7 个成功项
与新结果拼接使用。

本地提交 `58d8435d76022db41e625e3cdb7704a37943c94d` 已修复该 M7 gate；提交前的
同内容 dirty 工作树在一次性 MySQL 8.0.46 完成 0→7、M0–M6 七个历史起点→M7、
M6/M7 snapshot 和联合 MySQL `21 passed`，资源最终清理。执行时不是干净提交且通用
cleanup checker 有已解释的 `--rm` inspect 假失败，因此这只是本地证据，详见
[M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)。远端后续验证为
SQLite `2000 passed, 2 skipped`、MySQL `21 passed`，完整身份、Job 与 artifact 清单见
[M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

当前仓库功能基线已经包含：M4 Wallet/Payment/Refund、M5 Reservation N1、M6
自选颜色 Kit、M7 可配置固定店休、代客钱包订单多颜色界面和会员缺省头像居中修复。
当前完整本地回归为后端 `2000 passed, 30 skipped in 113.05s`；30 项为三类显式
MySQL-only 门槛，已由一次性 MySQL 联合 `30 passed` 覆盖。既有前端基线为
`83 suites / 562 tests`，且前端 typecheck、ESLint、Stylelint 和 17 项 CI policy
均通过。这些结果只绑定本地候选，不是远端 Runner、Gate A 或 RC 证据。
当前微信 production-mode 代码检查产物为 141 个文件、主包 649,739 bytes、分包
407,624 bytes、总计 1,057,363 bytes，manifest SHA-256 为
`693fb673df044e03c2865af2827e39ac7a5d6de86dbb1b3214f0b4237eeb69b4`，且明确
`release_eligible=false`。这些数值是本地候选证据，不是远端 8/8、真实 HTTPS RC、
微信体验版或真机证据。

Wallet 扩展门槛随后在一次性 MySQL 8.0.46 完成专项 `9 passed` 与 Inventory +
Reservation + Wallet 联合 `30 passed`，并已接入本地候选 workflow；并发调账/余额支付/
退款、真实 1205、1213 整事务重试、可观测跨资金库存锁等待和关键 `EXPLAIN` 均通过。
容器/端口已清理，详见
[Wallet 扩展 MySQL 报告](reports/wallet_mysql_release_gate_2026-09-07.md)。受测 head
`62f807a...` 随后由 [Run 34134341829](https://github.com/EVEBios/pinkdooHub/actions/runs/34134341829)
在干净 Runner 取得 8/8，三域联合、cleanup 和 artifact 步骤全部成功；详见
[Wallet 远端 CI 报告](reports/wallet_remote_ci_2026-09-07.md)。其后的 Gate A 运维与
MARD 提交不属于该 Run，仍须由新 CI 验证。

发布状态必须继续按以下边界解释：

- M4 已有仓库实现、扩展一次性 MySQL 与远端 8/8 证据；Gate A 仍未执行 M4、钱包
  backfill、legacy settlement backfill 或 reconcile。
- M5 曾在一次性 MySQL 8.0.46 完成 0→5 与 16 项 Inventory + Reservation 门槛，
  但未应用 Gate A 持久库。
- M6 的本地 SQLite 升级、221 色来源清单和确定性图片导入仅属于开发数据；Gate A
  MySQL、持久图片存储、商品颜色启用与库存均未完成。
- M7 的仓库实现和离线迁移已存在；本地一次性 MySQL 0→7、七个历史升级起点、
  snapshot 和 21 项联合门槛已完成；同一修复已随当前候选在远端干净 checkout 通过
  8/8。M7 仍未应用 Gate A、共享、预发布或生产数据库。
- Gate A 在 2026-09-02 的最后记录是 M2。写入前必须重新只读查询真实 Aerich 状态；
  不得把这条历史记录当作当前数据库事实。仓库尚无经批准的既有非空库升级入口；
  只支持空库的 `gatea_operations initial-migrate` 不能用于最后留证的 M2→M7 场景。
- 本轮本地 SQLite Schema 修复和综合 seed 已完成，但只产生开发数据与本地
  回归证据，不改变 Gate A 的任何发布勾选项。

因此当前结论仍是 **No-Go / Not Authorized**。下一次 Gate A 决策至少还要关闭：
持久 Gate A 的只读实际起点、备份/独立恢复及经批准的既有库升级入口（若仍为 M2，
依次应用 M3–M7）、钱包补齐/对账、221 色持久数据与图片、
真实 HTTPS Origin、微信合法域名、release-eligible RC，以及 iOS/Android 全矩阵。

## 1. Phase 9.1 交付物

| 交付物 | 文件 | 状态 |
|--------|------|------|
| Release Decision Record | [release_decision_record.md](release_decision_record.md) | Gate A 决策已冻结；Gate B 未授权 |
| 当前基线审计 | [baseline_audit_2026-08-29.md](baseline_audit_2026-08-29.md) | 已采集本地证据；MySQL/真机/外部环境未执行 |
| Environment Matrix + Secret Inventory | [environment_and_secrets.md](environment_and_secrets.md) | Gate A 文件 Secret、轮换、备份密钥和日志策略已落地；真实域名待备案 |
| CI Gate Matrix | [ci_gate_matrix.md](ci_gate_matrix.md) | Phase 9.2 历史基线完成；Wallet-expanded 候选 Run 34134341829 为 8/8，后续运维 SHA 与持久 Gate 仍阻断 |
| M7 一次性 MySQL 报告 | [reports/m7_mysql_release_gate_2026-09-07.md](reports/m7_mysql_release_gate_2026-09-07.md) | 本地 dirty-tree M0–M7/历史矩阵/21 项通过，并已补记远端后续结果 |
| M7 当前候选远端 CI 报告 | [reports/m7_remote_ci_2026-09-07.md](reports/m7_remote_ci_2026-09-07.md) | Head `4d6430c...` / merge-ref `ccbbe9d...` / Run 34129910349 / 8/8 / 7 artifacts |
| Wallet 扩展远端 CI 报告 | [reports/wallet_remote_ci_2026-09-07.md](reports/wallet_remote_ci_2026-09-07.md) | Head `62f807a...` / merge-ref `6675b4f...` / Run 34134341829 / 8/8 / 7 artifacts |
| Phase 9.5 公开安全基线 | [phase95_public_security_baseline.md](phase95_public_security_baseline.md) | 仓库实现完成；真实微信/Secret/监控/对象存储/隐私平台证据待办 |
| Release Drill Runbook | [release_drill_runbook.md](release_drill_runbook.md) | 历史 M2 的 DR-01～DR-07、DR-09 服务端部分通过；当前 M4–M7 持久升级与重演未执行 |
| 9.3 演练环境 | [rehearsal_environment_2026-08-31.md](rehearsal_environment_2026-08-31.md) | 双 MySQL/Redis/HTTPS/图片恢复拓扑已真实执行并清理 |
| 9.3 演练报告 | [reports/phase93_rehearsal_2026-08-31.md](reports/phase93_rehearsal_2026-08-31.md) | SHA `136a8bd...` / Run 33408135841 / DR 服务端范围 PASS |
| 9.4 Gate A Loopback 报告 | [reports/phase94_gatea_loopback_2026-09-02.md](reports/phase94_gatea_loopback_2026-09-02.md) | Runtime `51ad315...` / Operations `17114d7...` / 持久主机 lifecycle PASS |
| 9.4 Gate A 备份恢复报告 | [reports/phase94_gatea_backup_restore_2026-09-02.md](reports/phase94_gatea_backup_restore_2026-09-02.md) | Backup `20260901t232740z` / Operations `d1f3379...` / 空数据独立恢复 PASS |
| 9.4 Gate A Bootstrap 报告 | [reports/phase94_gatea_bootstrap_2026-09-02.md](reports/phase94_gatea_bootstrap_2026-09-02.md) | Runtime `51ad315...` / Operations `0ebe25a...` / 首次、重放、轮换与清理 PASS |
| 9.4 Gate A 代表性数据二次恢复报告 | [reports/phase94_gatea_representative_restore_2026-09-02.md](reports/phase94_gatea_representative_restore_2026-09-02.md) | Backup `20260902t014211z` / Operations `3511491...` / 非空数据与三图片独立恢复 PASS |
| 9.4 备案前收口报告 | [reports/phase94_pre_icp_completion_2026-09-02.md](reports/phase94_pre_icp_completion_2026-09-02.md) | 加密异机副本、持久故障/重启、日志、预 RC 与开发者工具 PASS；域名/真机待完成 |
| Gate A 内部测试运维规则 | [gatea_test_operations.md](gatea_test_operations.md) | 测试人员、反馈、14 日窗口、停用、数据清理与事故职责已冻结 |
| Functional/Smoke/E2E Matrix | [wechat_acceptance_matrix.md](wechat_acceptance_matrix.md) | 已扩展到 Wallet、颜色 Kit、Reservation、M7 与最新界面；当前 RC 真机结果待填 |
| Risk Register | [risk_register.md](risk_register.md) | 已登记当前 M7 CI、持久升级、钱包、色板和 RC 重验风险 |
| Go/No-Go Checklist | [go_no_go_checklist.md](go_no_go_checklist.md) | 当前候选 CI 已关闭；Wallet/持久迁移/RC/真机仍未关闭，未授权发布 |

## 2. 当前结论

- 本版唯一发布平台是微信小程序 `weapp`。
- 当前目标是受控内部测试版，不是公开发布。
- Phase 9.1 已完成仓库级证据采集、交付物建档、责任人映射和项目负责人 Review，状态为 `Complete`。
- Phase 9.2 **历史基线**的 CI 与可重复构建已完成：Draft PR #2 的 Run 33355935212 在真实干净 checkout 上 8/8 Job 通过并保存 7 组 artifact。该结果不覆盖当前 M7 候选，也不授权微信后台变更、持久迁移、上传、提审或发布。
- Phase 9.3 **历史 M2 演练**已完成：候选 SHA `136a8bd...` 的 GitHub Actions Run 33408135841 为 8/8 success；Run ID `20260831t221625` 在可销毁双 MySQL/Redis/Nginx/App/图片卷环境完成当时的 DR-01～DR-07 与 DR-09 服务端部分，53 项发布工具契约通过，全部任务资源已清理。详见[演练报告](reports/phase93_rehearsal_2026-08-31.md)。当前 M7 必须新建演练证据；当前仍未授权上传、分发、提审或发布。
- Phase 9.4 **历史 M2 持久主机** loopback 首次部署已通过：Runtime `51ad315...` 的 Run 33568184860 与 Operations `17114d7...` 的 Run 33568983950 均为 8/8 success；真实腾讯云主机完成空库 Aerich 0→1→2、10 表核验、持久 MySQL/Redis/图片卷、非 root App、只读根文件系统、Healthy Nginx 和 liveness/readiness。MySQL/Redis/App 不发布宿主端口，唯一边界是 `127.0.0.1:18080`，公网 18080 不可达。完整脱敏证据见 [9.4 Loopback 报告](reports/phase94_gatea_loopback_2026-09-02.md)。当前实际版本只可重新只读确认；既有库升级、DNS/证书、微信合法域名、真实 RC 和 iOS/Android 真机仍未执行，Gate A 保持 No-Go。
- Phase 9.4 **历史 M2 空数据**持久备份/隔离恢复已通过：Operations `d1f3379...` 的 Run 33570862787 为 8/8 success；Backup `20260901t232740z` 在停写窗口生成 `0600` MySQL/图片 Artifact，独立无端口 Restore project 完成数据库摘要、图片 manifest、空 Redis 和 Restore App readiness 验证，并删除全部临时容器/网络/卷。该记录由后续非空恢复证据补充，详见[备份恢复报告](reports/phase94_gatea_backup_restore_2026-09-02.md)。
- Phase 9.4 **历史 M2 持久 Bootstrap** 已真实通过：Runtime `51ad315...`、Operations `0ebe25a...` 和 Run 33574718103 绑定；唯一 SUPER_ADMIN 首次创建、严格重放、唯一 Audit、初始/最终登录、密码轮换、旧密码拒绝、两个 Refresh 会话撤销和临时 Secret/容器/投放文件清理均为 PASS。成功 Record 为 `root:root 0644` 且不含 PII、密码、Token 或 hash；完整脱敏证据见 [9.4 Bootstrap 报告](reports/phase94_gatea_bootstrap_2026-09-02.md)。
- Phase 9.4 **历史 M2 代表性数据与二次隔离恢复**已真实通过：Operations `3511491...` 的 Run 33576453364 为 8/8 success；工具经 loopback 正式 API 创建最终禁用的合成 USER、两个 Online Product、三张图片、两种终态订单和完整库存流水，管理员/合成用户 Refresh 均撤销。非空 Backup `20260902t014211z` 在独立无端口 project 中完成数据库、三图片、空 Redis 和 Restore App 验证，临时 Docker 资源归零且来源服务 Healthy。完整脱敏证据见[代表性数据二次恢复报告](reports/phase94_gatea_representative_restore_2026-09-02.md)；当前 M4–M7 数据必须新建 Backup/Restore 证据。
- Phase 9.4 **历史 M2 备案前运维和自动化范围**已真实通过：Backup `20260902t014211z` 已形成经解密复核的 AES-256-GCM/RSA-OAEP-SHA256 异机副本；MySQL/Redis 故障和 App 重启证明 readiness 摘流量、liveness、数据/三图片保持、四容器日志轮转及 24 小时脱敏聚合查询。实现 `b69ee74...` Run 33584388085 和恢复修复 `c4d27a8...` Run 33584789525 均为 8/8 success；首次演练工具假失败、修复和重跑均留有证据。Node 24.13.0/npm 11.6.2 的备案前微信预 RC 为 97 文件/603,624 bytes/0 source map，manifest `aeb81ef...` 明确不可发布。开发者工具 Stable 2.02.2608060 已加载/编译并修正本机 `urlCheck` 覆盖，域名校验按预期拒绝保留 Origin。完整证据见[备案前收口报告](reports/phase94_pre_icp_completion_2026-09-02.md)。当前 M7 的备案/DNS/HTTPS、微信合法域名、真实 RC、iOS/Android 真机和上传授权仍未执行，Gate A 保持 No-Go。
- Phase 9.5 不依赖备案的仓库实现已完成：微信身份/绑定、Refresh 轮换、认证限流、注销匿名化、HMAC 标识最小化、安全事件、Secret 注入边界、存储端口和迁移均有自动化；真实微信 AppID、集中 Secret Manager、告警送达、对象存储和隐私平台材料仍未执行，Gate B 保持 No-Go。详见 [9.5 基线](phase95_public_security_baseline.md)。

## 3. 状态词

| 状态 | 含义 |
|------|------|
| `verified` | 本次 9.1 已执行并保留可复核结果 |
| `historical` | 过去执行过，但未绑定当前 RC 和环境 |
| `planned` | 输入、步骤和退出条件已定义，尚未实现 |
| `blocked` | 缺少 Gate 必需能力或外部配置，当前不能通过 |
| `deferred` | 明确不属于当前 Gate，未来单独冻结 |
| `not-authorized` | 需要项目负责人明确批准，当前不得执行 |

## 4. 责任角色

本版所有责任角色统一由 **Yijie Shen** 承担：

| 角色 | 责任人 | 职责 |
|------|--------|------|
| 项目负责人 | Yijie Shen | 业务范围、风险接受、Go/No-Go 和外部发布授权 |
| 前端负责人 | Yijie Shen | 微信构建、配置、包体、真机和客户端缺陷 |
| 后端负责人 | Yijie Shen | API、认证、迁移、数据、Redis、图片和管理员初始化 |
| CI/发布负责人 | Yijie Shen | 流水线、artifact、环境、备份恢复、部署和回滚 |
| 测试负责人 | Yijie Shen | 矩阵、测试数据、设备、证据与缺陷分级 |
| 安全/合规负责人 | Yijie Shen | 依赖、Secret、日志、隐私、平台规则和审核材料 |

同一人承担多个角色不合并证据步骤：实施、复核、风险接受和发布授权仍须分别记录时间与结论。涉及持久数据恢复、正式提审或公开发布时，可在当次 Gate 决策中追加独立复核人，但不改变 Yijie Shen 的默认责任归属。
