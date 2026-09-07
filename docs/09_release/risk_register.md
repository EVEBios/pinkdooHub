# Phase 9 微信发布风险登记

> **Status:** Active
> **Last Updated:** 2026-09-07
> **Current Gate:** Gate A — 内部微信测试版

风险状态使用 `open`、`mitigating`、`accepted-until`、`closed`、`deferred`。只有满足“关闭证据”才能标记 `closed`；降低优先级或口头接受不等于关闭。

2026-09-07 覆盖说明：R-001、R-004～R-006 等 `closed` 项绑定的是 Phase 9.2 PR head
`23a0f08...`、Phase 9.3 `136a8bd...`、Phase 9.4 Runtime `51ad315...` / Operations
`c4d27a8...` 等旧 SHA 与 Aerich M0–M2；它们证明对应流程曾有效，不自动关闭当前 M4–M7 候选的
后续风险。审计起点 `c6778e7...` 的远端 Run 34104680282 保留为 7/8 失败记录；当前
head `4d6430c...` 的 Run 34129910349 已 8/8 并关闭 R-026，但 Gate A 因其余风险仍是 No-Go。

## 1. 活跃风险

| ID | 级别 | 风险/信号 | 概率×影响 | 缓解与关闭证据 | 责任角色 | 最晚关闭 | 状态 |
|----|------|-----------|-----------|--------------|----------|----------|------|
| R-001 | P0 | Phase 9.2 的 8 个 CI Job 缺少真实 PR Run | 高×高 | PR #2 Run 33355935212 在当时的干净 checkout 8/8 通过，7 组 artifact 绑定 merge-ref/Run；仅关闭历史基线 | Yijie Shen | 9.2 | closed |
| R-002 | P0 | 当前微信构建只有保留 `.test` Origin 且 `release_eligible=false`，真实 Gate A Origin 未冻结 | 确定×高 | 冻结真实 HTTPS Origin；CI 语义扫描；request/upload/download 真机成功 | Yijie Shen | Gate A | open |
| R-003 | P0 | request/upload/download 合法域名、DNS、证书未冻结 | 高×高 | 微信后台配置、TLS 外部验证、iOS/Android 真机证据 | Yijie Shen | Gate A | open |
| R-004 | P0 | 备份恢复和迁移失败处置未实际演练 | 中×极高 | Run `20260831t221625` 的 DR-01–DR-05 全部通过：独立 DB/图片恢复、restore-app、耗时、数据断言和 MySQL DDL 部分提交恢复均有报告 | Yijie Shen | 9.3 | closed |
| R-005 | P0 | Phase 9.2 MySQL-only 门槛缺少当时 SHA 的远端 PR 证据 | 中×高 | Run 33355935212 使用专用 MySQL 8.0.46 完成 M0→M2、9 项并发/锁/重试/HTTP 门槛并保存 cleanup artifact；仅关闭历史基线 | Yijie Shen | 9.2 | closed |
| R-006 | P0 | 受控 SUPER_ADMIN bootstrap 已实现但尚未在隔离 MySQL 执行并处置初始凭据 | 中×高 | DR-07 在隔离 MySQL 完成首次/重放、登录、唯一用户/Audit 与凭据轮换；初始/轮换 Secret 随任务目录删除 | Yijie Shen | 9.3 | closed |
| R-007 | P0 | npm audit 仍报 10 个包/5 个叶子公告；Taro 当前版没有无破坏修复 | 中×高 | 已逐项证明为未启用 esbuild serve、H5-only 或当前微信源码/产物不可达；精确策略、新告警 fail-closed，2026-11-30 到期 | Yijie Shen | 2026-11-30/Gate A | accepted-until |
| R-008 | P0 | 对外公开微信身份缺口 | 中×极高 | 9.5 已实现 code2Session 适配、HMAC 身份、自动创建/显式绑定/冲突/禁用/解绑/注销和自动化；仍需真实 AppID iOS/Android 真机矩阵 | Yijie Shen | Gate B | mitigating |
| R-009 | P0 | Order create 无服务端幂等，弱网重试可能重复订单/扣库存 | 中×极高 | 冻结键/身份/冲突语义并实现并发、unknown、重放测试 | Yijie Shen | Gate B | deferred |
| R-010 | P0 | 若公开在线收款，缺微信支付可信闭环 | 高×极高 | 服务端下单、验签、金额核对、通知幂等、查单、退款、对账和告警 | Yijie Shen | Gate B（收款时） | deferred |
| R-011 | P1 | dependency-aware readiness 已实现但尚未在生产相似 MySQL/Redis 验证摘流量与恢复 | 中×高 | DR-06 分别中断 MySQL/Redis，Readiness 安全返回 503，恢复后重新 200；Liveness、优雅重启与脱敏均通过 | Yijie Shen | 9.3 | closed |
| R-012 | P1 | Redis 初始化日志可能泄露连接凭据 | 中×高 | Run 33355935212 的后端契约证明 username、password、query 不输出 | Yijie Shen | Gate A | closed |
| R-013 | P1 | production fail-fast 与 Secret 隐藏缺少干净 CI 证据 | 中×高 | Run 33355935212 覆盖 debug/MySQL/JWT/Redis/HTTPS 图片配置的接受与拒绝路径 | Yijie Shen | Gate A | closed |
| R-014 | P1 | Gate A 图片依赖本地卷，主机/系统盘故障可能同时损坏来源与同机备份 | 高×高 | 3 张真实图片已完成持久卷、`0600` 归档、checksum 和无端口独立恢复；Backup `20260902t014211z` 已生成管理电脑 FileVault 上的 AES-256-GCM/RSA-OAEP-SHA256 异机副本并立即完整解密复核，私钥与副本分离 | Yijie Shen | Gate A 保管 | closed |
| R-015 | P1 | Gate A Secret 的保管、读取主体、轮换和泄漏响应未落地 | 中×高 | Root 文件型 Secret 的路径、`0700/0400/0440` 权限、容器 UID/GID 读取边界、人工 TTY Bootstrap、轮换/泄漏触发、备份私钥隔离和日志零精确命中均已验证；详细证据见备案前收口报告 | Yijie Shen | Gate A（测试） | closed |
| R-016 | P1 | Python/Node/npm/pip 固定缺少远端干净 CI 证据 | 高×中 | Run 33355935212 验证版本文件、engines 和 CI 精确版本 | Yijie Shen | 9.2 | closed |
| R-017 | P1 | pip-audit 修复可升级项后只剩 ecdsa 无修复的 P-256 时序公告 | 中×高 | 固定 pip-audit 2.10.1；production HS256 不可达策略 fail-closed，算法/版本变化重审，2026-11-30 到期 | Yijie Shen | 2026-11-30 | accepted-until |
| R-018 | P1 | 当前候选只有 `release_eligible=false` 本地产物，尚缺同 SHA 的远端产物与真实 RC | 中×中 | 新 SHA 8/8 保存微信 artifact/checksum；真实 Origin 重建并复核 0 source map/上传入口 | Yijie Shen | Gate A | open |
| R-019 | P1 | 管理分包是否随公开包发布未决定 | 中×中 | Gate B 前评估包体、审核面、运营入口和后端授权 | Yijie Shen | Gate B | deferred |
| R-020 | P1 | 认证安全和监控告警缺口 | 中×高 | 9.5 已实现 refresh family 轮换/重放撤销、Redis 原子限流/fail-closed 和结构化安全事件；仍需正式监控接入、送达与恢复演练 | Yijie Shen | Gate B | mitigating |
| R-021 | P2 | OpenAPI CLI UTF-8/CP1252 回归缺少 CI 运行证据 | 高×低 | Run 33355935212 的 OpenAPI Job 完成 `--help`、真实导出、字节比较和类型漂移检查 | Yijie Shen | 9.2 | closed |
| R-022 | P2 | metadata/README 已收敛，artifact checker 拒绝 H5-only marker；当前 M7 RC 尚未复核 | 中×中 | 当前 SHA 的 CI artifact 与真实 RC 证明发布元数据只声明微信 | Yijie Shen | Gate A | mitigating |
| R-023 | P2 | Jest 重复提示 ReactDOMTestUtils.act deprecated | 高×低 | Taro 测试依赖升级窗口或有期限 warning 白名单 | Yijie Shen | Gate A 后可排期 | open |
| R-024 | P1 | Gate B 公开服务仍依赖单主机本地图片卷，缺少高可用存储/CDN | 高×高 | Phase 9.5 已冻结 `ImageStorage` 端口和对象存储验收门；仍需选型、真实 Bucket/CDN、最小权限和恢复演练 | Yijie Shen | Gate B | mitigating |
| R-025 | P1 | Gate B 缺少集中 Secret Manager、访问审计和自动轮换 | 中×高 | Phase 9.5 已冻结 Secret inventory、文件注入边界和 Pepper 轮换约束；仍需选择集中系统并验证最小权限、版本、轮换、撤销和审计 | Yijie Shen | Gate B | mitigating |
| R-026 | P0 | M7 修复前远端 CI 只有 7/8；失败 Run 的 MySQL Job 把 M6 当最新版本 | 确定×高 | `4d6430c...` / merge-ref `ccbbe9d...` 的 Run 34129910349 已 8/8；MySQL 21 项、cleanup 步骤和 7 组 artifact 可复核；旧 Run 保留 | Yijie Shen | 当前候选 / Gate A | closed |
| R-027 | P0 | M7 最初只有本地 dirty-tree 一次性 MySQL 完整证据，未绑定干净 commit/远端 Runner | 中×高 | [本地报告](reports/m7_mysql_release_gate_2026-09-07.md)保留完整历史矩阵；当前 [远端报告](reports/m7_remote_ci_2026-09-07.md)绑定 head/merge-ref，在干净 Runner 复现 workflow、21 项 MySQL 与 cleanup | Yijie Shen | 当前候选 / Gate A | closed |
| R-028 | P0 | 持久 Gate A 最后记录为 M2，但当前真实版本尚未重新读取；现有批准入口只允许空库，若实际仍为 M2，则不存在可安全执行的非空 M2→M7 路径 | 确定×极高 | 先只读确认真实版本；实现并测试经 Review 的既有库升级/候选 Record 入口；停写、备份/独立恢复，并从获批实际起点逐步升级（M2 时依次 M3–M7），再完成匹配镜像部署与失败前滚/恢复演练 | Yijie Shen | Gate A | open |
| R-029 | P1 | Wallet 曾只有有限 MySQL 关键闭环，缺少扩展并发/瞬态错误/查询计划与跨资金库存门槛 | 中×极高 | 一次性 MySQL 8.0.46 已完成 Wallet `9 passed`、三域联合 `30 passed`：并发调账/余额支付/退款、真实 1205、1213 整事务重试、可观测 Wallet/Inventory 锁等待和关键 `EXPLAIN`；远端复现作为后续 CI 证据跟踪，不回开已关闭的仓库缺口 | Yijie Shen | 2026-09-07 | closed |
| R-030 | P1 | 本地 SQLite 的 221 色与图片未发布到 Gate A MySQL/持久图片存储，商品颜色启用/库存也未配置 | 确定×高 | 来源 manifest 保留 HEX/RGB/checksum；Gate A MySQL 导入 221 个 slot/code/name/URL，发布图片并核验槽位/文件，为测试商品配置启用色和库存，HTTPS 真机读取通过 | Yijie Shen | Gate A | open |
| R-031 | P1 | 旧微信验收只覆盖 M2 业务面，M4–M7、代客多颜色和头像布局没有当前 RC 真机证据 | 确定×高 | 当前矩阵全部绑定同一 release-eligible RC，在至少一台 iOS 和 Android 完成 Wallet、颜色 Kit、Reservation、固定/单日店休和最新布局验收 | Yijie Shen | Gate A | open |
| R-032 | P1 | Gate A 的 Wallet 历史用户/legacy manual Order 尚未 backfill/reconcile，启用资金入口可能形成缺账户或矛盾结算 | 高×极高 | M4 后按冻结上界依次完成 wallet preview/apply/二次 preview、legacy settlement preview/apply 与只读 reconcile；所有差异为零后再启用 | Yijie Shen | Gate A | open |
| R-033 | P2 | Reservation N1 只在页面展示状态，店休取消没有主动微信通知 | 高×中 | Gate A 明确 N1 边界并保留人工电话兜底；若 Gate B 要求通知，完成订阅授权、加密投递地址、durable outbox/worker/重试/监控和真机验收 | Yijie Shen | Gate B / N2 | deferred |
| R-034 | P2 | MARD 网页 HEX/RGB 未经实体拼豆样本校色，图片是确定性纯色而非实物照片 | 中×中 | Gate A 内部说明来源限制；公开使用前按批准色样校准并更新 manifest/图片/checksum/验收记录 | Yijie Shen | Gate B 或正式销售前 | deferred |

## 2. 风险例外规则

P0 默认不能豁免。任何例外至少包含：

- 风险 ID、适用 Git SHA/环境/Gate 和明确的业务理由；
- 可验证的补偿控制，不使用“当前用户少”替代安全措施；
- 接受人、责任人、到期时间和自动失效条件；
- 发生后的停止、数据保护、沟通和恢复方案；
- Go/No-Go 记录中的显式引用。

当前默认例外建议人、风险接受人和责任人均为 Yijie Shen；同一人承担多个角色时，必须分别记录建议、接受决定和时间，不能用一次签名合并三个步骤。

Secret 泄漏、越权、数据破坏、无法恢复、artifact 来源不明、真实支付状态不可信等风险不得通过普通例外进入相应 Gate。

## 3. 更新规则

- CI、演练、RC 真机或外部平台检查发现新风险时先登记，再决定是否阻断。
- 每个 RC 冻结时复核概率、影响、状态、负责人和到期日。
- `closed` 必须给出 CI run、测试、演练报告、配置复核或 Review 链接；仅合并代码不算关闭。
- Gate A 的 `deferred` 项在 Gate B 立项时自动重新打开，不能沿用旧结论。
- 微信平台、依赖、证书和合规规则具有时效性，RC 冻结时重新检查官方规则和后台配置。
