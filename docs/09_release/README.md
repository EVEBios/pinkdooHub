# pinkdooHub 发布文档

> **Current Phase:** 9.4 外部条件阻断中；9.5 仓库可实施范围已完成 — Gate A/Gate B 均保持 No-Go
> **Phase 9.1 Status:** Complete — Yijie Shen 于 2026-08-29 完成 Review
> **Last Updated:** 2026-09-02
> **Release Scope:** 微信小程序内部测试版（Gate A）

本目录保存可以直接用于后续 CI、演练和发布决策的操作文档。长期路线与公开发布门槛仍以 [Phase 9 微信小程序发布规划](../08_frontend/phase9_wechat_release_plan.md) 为总纲；本目录负责记录当前版本的决定、证据、责任和可执行清单。

## 1. Phase 9.1 交付物

| 交付物 | 文件 | 状态 |
|--------|------|------|
| Release Decision Record | [release_decision_record.md](release_decision_record.md) | Gate A 决策已冻结；Gate B 未授权 |
| 当前基线审计 | [baseline_audit_2026-08-29.md](baseline_audit_2026-08-29.md) | 已采集本地证据；MySQL/真机/外部环境未执行 |
| Environment Matrix + Secret Inventory | [environment_and_secrets.md](environment_and_secrets.md) | Gate A 文件 Secret、轮换、备份密钥和日志策略已落地；真实域名待备案 |
| CI Gate Matrix | [ci_gate_matrix.md](ci_gate_matrix.md) | Phase 9.2 Complete；PR #2 Run 33355935212 的 8 个 Job 全部通过 |
| Phase 9.5 公开安全基线 | [phase95_public_security_baseline.md](phase95_public_security_baseline.md) | 仓库实现完成；真实微信/Secret/监控/对象存储/隐私平台证据待办 |
| Release Drill Runbook | [release_drill_runbook.md](release_drill_runbook.md) | DR-01～DR-07、DR-09 服务端部分已执行通过；DR-08 留到 9.4 |
| 9.3 演练环境 | [rehearsal_environment_2026-08-31.md](rehearsal_environment_2026-08-31.md) | 双 MySQL/Redis/HTTPS/图片恢复拓扑已真实执行并清理 |
| 9.3 演练报告 | [reports/phase93_rehearsal_2026-08-31.md](reports/phase93_rehearsal_2026-08-31.md) | SHA `136a8bd...` / Run 33408135841 / DR 服务端范围 PASS |
| 9.4 Gate A Loopback 报告 | [reports/phase94_gatea_loopback_2026-09-02.md](reports/phase94_gatea_loopback_2026-09-02.md) | Runtime `51ad315...` / Operations `17114d7...` / 持久主机 lifecycle PASS |
| 9.4 Gate A 备份恢复报告 | [reports/phase94_gatea_backup_restore_2026-09-02.md](reports/phase94_gatea_backup_restore_2026-09-02.md) | Backup `20260901t232740z` / Operations `d1f3379...` / 空数据独立恢复 PASS |
| 9.4 Gate A Bootstrap 报告 | [reports/phase94_gatea_bootstrap_2026-09-02.md](reports/phase94_gatea_bootstrap_2026-09-02.md) | Runtime `51ad315...` / Operations `0ebe25a...` / 首次、重放、轮换与清理 PASS |
| 9.4 Gate A 代表性数据二次恢复报告 | [reports/phase94_gatea_representative_restore_2026-09-02.md](reports/phase94_gatea_representative_restore_2026-09-02.md) | Backup `20260902t014211z` / Operations `3511491...` / 非空数据与三图片独立恢复 PASS |
| 9.4 备案前收口报告 | [reports/phase94_pre_icp_completion_2026-09-02.md](reports/phase94_pre_icp_completion_2026-09-02.md) | 加密异机副本、持久故障/重启、日志、预 RC 与开发者工具 PASS；域名/真机待完成 |
| Gate A 内部测试运维规则 | [gatea_test_operations.md](gatea_test_operations.md) | 测试人员、反馈、14 日窗口、停用、数据清理与事故职责已冻结 |
| Functional/Smoke/E2E Matrix | [wechat_acceptance_matrix.md](wechat_acceptance_matrix.md) | 场景与证据等级已冻结；RC 真机结果待填 |
| Risk Register | [risk_register.md](risk_register.md) | 已登记并分配责任角色/关闭 Gate |
| Go/No-Go Checklist | [go_no_go_checklist.md](go_no_go_checklist.md) | Gate A/Gate B 清单已建立；未授权发布 |

## 2. 当前结论

- 本版唯一发布平台是微信小程序 `weapp`。
- 当前目标是受控内部测试版，不是公开发布。
- Phase 9.1 已完成仓库级证据采集、交付物建档、责任人映射和项目负责人 Review，状态为 `Complete`。
- Phase 9.2 CI 与可重复构建已完成：Draft PR #2 的 Run 33355935212 在真实干净 checkout 上 8/8 Job 通过并保存 7 组 artifact。该结果不授权微信后台变更、持久迁移、上传、提审或发布。
- Phase 9.3 已完成：候选 SHA `136a8bd...` 的 GitHub Actions Run 33408135841 为 8/8 success；Run ID `20260831t221625` 在可销毁双 MySQL/Redis/Nginx/App/图片卷环境完成 DR-01～DR-07 与 DR-09 服务端部分，53 项发布工具契约通过，全部任务资源已清理。详见[演练报告](reports/phase93_rehearsal_2026-08-31.md)。微信合法域名、真实 RC、iOS/Android 真机 DR-08 和 Gate A 决策保持 Phase 9.4；当前仍未授权上传、分发、提审或发布。
- Phase 9.4 持久主机 loopback 首次部署已通过：Runtime `51ad315...` 的 Run 33568184860 与 Operations `17114d7...` 的 Run 33568983950 均为 8/8 success；真实腾讯云主机完成空库 Aerich 0→1→2、10 表核验、持久 MySQL/Redis/图片卷、非 root App、只读根文件系统、Healthy Nginx 和 liveness/readiness。MySQL/Redis/App 不发布宿主端口，唯一边界是 `127.0.0.1:18080`，公网 18080 不可达。完整脱敏证据见 [9.4 Loopback 报告](reports/phase94_gatea_loopback_2026-09-02.md)。DNS/证书、微信合法域名、真实 RC 和 iOS/Android 真机仍未执行，Gate A 保持 No-Go。
- Phase 9.4 空数据持久备份/隔离恢复已通过：Operations `d1f3379...` 的 Run 33570862787 为 8/8 success；Backup `20260901t232740z` 在停写窗口生成 `0600` MySQL/图片 Artifact，独立无端口 Restore project 完成数据库摘要、图片 manifest、空 Redis 和 Restore App readiness 验证，并删除全部临时容器/网络/卷。当前备份仍在同机，Bootstrap 后含代表性数据的复验、保留期和加密异机副本仍未完成，详见[备份恢复报告](reports/phase94_gatea_backup_restore_2026-09-02.md)。
- Phase 9.4 持久 Bootstrap 已真实通过：Runtime `51ad315...`、Operations `0ebe25a...` 和 Run 33574718103 绑定；唯一 SUPER_ADMIN 首次创建、严格重放、唯一 Audit、初始/最终登录、密码轮换、旧密码拒绝、两个 Refresh 会话撤销和临时 Secret/容器/投放文件清理均为 PASS。成功 Record 为 `root:root 0644` 且不含 PII、密码、Token 或 hash；完整脱敏证据见 [9.4 Bootstrap 报告](reports/phase94_gatea_bootstrap_2026-09-02.md)。
- Phase 9.4 代表性数据与二次隔离恢复已真实通过：Operations `3511491...` 的 Run 33576453364 为 8/8 success；工具经 loopback 正式 API 创建最终禁用的合成 USER、两个 Online Product、三张图片、两种终态订单和完整库存流水，管理员/合成用户 Refresh 均撤销。非空 Backup `20260902t014211z` 在独立无端口 project 中完成数据库、三图片、空 Redis 和 Restore App 验证，临时 Docker 资源归零且来源服务 Healthy。完整脱敏证据见[代表性数据二次恢复报告](reports/phase94_gatea_representative_restore_2026-09-02.md)；备份保留期、加密异机副本、DNS/HTTPS、微信合法域名、真实 RC 和真机仍待完成。
- Phase 9.4 备案前运维和自动化范围已真实通过：Backup `20260902t014211z` 已形成经解密复核的 AES-256-GCM/RSA-OAEP-SHA256 异机副本；MySQL/Redis 故障和 App 重启证明 readiness 摘流量、liveness、数据/三图片保持、四容器日志轮转及 24 小时脱敏聚合查询。实现 `b69ee74...` Run 33584388085 和恢复修复 `c4d27a8...` Run 33584789525 均为 8/8 success；首次演练工具假失败、修复和重跑均留有证据。Node 24.13.0/npm 11.6.2 的备案前微信预 RC 为 97 文件/603,624 bytes/0 source map，manifest `aeb81ef...` 明确不可发布。开发者工具 Stable 2.02.2608060 已加载/编译并修正本机 `urlCheck` 覆盖，域名校验按预期拒绝保留 Origin。完整证据见[备案前收口报告](reports/phase94_pre_icp_completion_2026-09-02.md)。备案/DNS/HTTPS、微信合法域名、真实 RC、iOS/Android 真机和上传授权仍未执行，Gate A 保持 No-Go。
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
