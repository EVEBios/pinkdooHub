# Phase 9 微信发布风险登记

> **Status:** Active
> **Last Updated:** 2026-09-09
> **Current Gate:** Gate A — 内部微信测试版

风险状态使用 `open`、`mitigating`、`accepted-until`、`closed`、`deferred`。只有满足“关闭证据”才能标记 `closed`；降低优先级或口头接受不等于关闭。

2026-09-07 覆盖说明：R-001、R-004～R-006 等 `closed` 项绑定的是 Phase 9.2 PR head
`23a0f08...`、Phase 9.3 `136a8bd...`、Phase 9.4 Runtime `51ad315...` / Operations
`c4d27a8...` 等旧 SHA 与 Aerich M0–M2；它们证明对应流程曾有效，不自动关闭后续候选的
后续风险。审计起点 `c6778e7...` 的远端 Run 34104680282 保留为 7/8 失败记录；历史 M7
head `4d6430c...` 的 Run 34129910349 已 8/8 并关闭 R-026。持久 Gate A 随后
在 Runtime `73dca350...` 上完成 M2→M7、Wallet/MARD、韧性、综合数据和
数据后 Backup/Restore；Operations `353455bb...` 的 Run 34178908663 为 8/8。M8 基线
head `4e745848...` 的 Run 34242753255 也已 8/8，但持久 Gate A 仍为 M7；其后新增的
M7→M8/Online no-op 保护已由 head `fa6fce05...` / Run 34281512196 在干净远端完成
8/8；head `62b1b15...` / merge-ref `a9ff3d2...` 的 Run 34288613644 又在
GitHub-hosted disposable Linux 中完成全链路 updater 14/14 阶段、M7/M8 双
Backup/Restore、221 HEX/gzip/PNG Runtime、artifact 扫描和零残留，最终 CI
9/9。完整 updater 的一次性证据缺口因此已关闭，但持久 Gate A 仍为 M7，
尚无精确目标/当次预检/新 Backup/Restore/窗口与写授权。因此 Gate A 同时受
持久 M8 升级、容量 Gate 处置、真实 HTTPS/微信合法域名、RC、真机与最终签署阻断。

## 1. 活跃风险

| ID | 级别 | 风险/信号 | 概率×影响 | 缓解与关闭证据 | 责任角色 | 最晚关闭 | 状态 |
|----|------|-----------|-----------|--------------|----------|----------|------|
| R-001 | P0 | Phase 9.2 的 8 个 CI Job 缺少真实 PR Run | 高×高 | PR #2 Run 33355935212 在当时的干净 checkout 8/8 通过，7 组 artifact 绑定 merge-ref/Run；仅关闭历史基线 | Yijie Shen | 9.2 | closed |
| R-002 | P0 | 当前微信构建只有保留 `.test` Origin 且 `release_eligible=false`，真实 Gate A Origin 未冻结 | 确定×高 | 冻结真实 HTTPS Origin；CI 语义扫描；request/upload/download 真机成功 | Yijie Shen | Gate A | open |
| R-003 | P0 | request/upload/download 合法域名、DNS、证书未冻结 | 高×高 | 微信后台配置、TLS 外部验证、iOS/Android 真机证据 | Yijie Shen | Gate A | open |
| R-004 | P0 | 备份恢复和迁移失败处置未实际演练 | 中×极高 | Run `20260831t221625` 的 DR-01–DR-05 全部通过：独立 DB/图片恢复、restore-app、耗时、数据断言和 MySQL DDL 部分提交恢复均有报告 | Yijie Shen | 9.3 | closed |
| R-005 | P0 | Phase 9.2 MySQL-only 门槛缺少当时 SHA 的远端 PR 证据 | 中×高 | Run 33355935212 使用专用 MySQL 8.0.46 完成 M0→M2、9 项并发/锁/重试/HTTP 门槛并保存 cleanup artifact；仅关闭历史基线 | Yijie Shen | 9.2 | closed |
| R-006 | P0 | 受控 SUPER_ADMIN bootstrap 已实现但尚未在隔离 MySQL 执行并处置初始凭据 | 中×高 | DR-07 在隔离 MySQL 完成首次/重放、登录、唯一用户/Audit 与凭据轮换；初始/轮换 Secret 随任务目录删除 | Yijie Shen | 9.3 | closed |
| R-007 | P0 | npm audit 仍报 10 个包/5 个叶子公告；Taro 当前版没有无破坏修复 | 中×高 | 已逐项证明为未启用 esbuild serve、H5-only 或当前微信源码/产物不可达；精确策略、新告警 fail-closed，2026-11-30 到期。本轮新出现的 Joi Low 已通过 `17.13.4→17.13.7` 消除，没有加入例外 | Yijie Shen | 2026-11-30/Gate A | accepted-until |
| R-008 | P0 | 对外公开微信身份缺口 | 中×极高 | 9.5 已实现 code2Session 适配、HMAC 身份、自动创建/显式绑定/冲突/禁用/解绑/注销和自动化；仍需真实 AppID iOS/Android 真机矩阵 | Yijie Shen | Gate B | mitigating |
| R-009 | P0 | Order create 无服务端幂等，弱网重试可能重复订单/扣库存 | 中×极高 | 冻结键/身份/冲突语义并实现并发、unknown、重放测试 | Yijie Shen | Gate B | deferred |
| R-010 | P0 | 若公开在线收款，缺微信支付可信闭环 | 高×极高 | 服务端下单、验签、金额核对、通知幂等、查单、退款、对账和告警 | Yijie Shen | Gate B（收款时） | deferred |
| R-011 | P1 | dependency-aware readiness 已实现但尚未在生产相似 MySQL/Redis 验证摘流量与恢复 | 中×高 | DR-06 分别中断 MySQL/Redis，Readiness 安全返回 503，恢复后重新 200；Liveness、优雅重启与脱敏均通过 | Yijie Shen | 9.3 | closed |
| R-012 | P1 | Redis 初始化日志可能泄露连接凭据 | 中×高 | Run 33355935212 的后端契约证明 username、password、query 不输出 | Yijie Shen | Gate A | closed |
| R-013 | P1 | production fail-fast 与 Secret 隐藏缺少干净 CI 证据 | 中×高 | Run 33355935212 覆盖 debug/MySQL/JWT/Redis/HTTPS 图片配置的接受与拒绝路径 | Yijie Shen | Gate A | closed |
| R-014 | P1 | Gate A 图片依赖本地卷，主机/系统盘故障可能同时损坏来源与同机备份 | 高×高 | 当前 225 图片的 Backup `20260908t021224z` 已完成 `0600` 归档、checksum、无端口独立恢复，并在管理电脑 FileVault 上形成 AES-256-GCM/RSA-OAEP-SHA256 异机副本后立即解密复核；私钥与副本分离 | Yijie Shen | Gate A 保管 | closed |
| R-015 | P1 | Gate A Secret 的保管、读取主体、轮换和泄漏响应未落地 | 中×高 | Root 文件型 Secret 的路径、`0700/0400/0440` 权限、容器 UID/GID 读取边界、人工 TTY Bootstrap、轮换/泄漏触发、备份私钥隔离和日志零精确命中均已验证；详细证据见备案前收口报告 | Yijie Shen | Gate A（测试） | closed |
| R-016 | P1 | Python/Node/npm/pip 固定缺少远端干净 CI 证据 | 高×中 | Run 33355935212 验证版本文件、engines 和 CI 精确版本 | Yijie Shen | 9.2 | closed |
| R-017 | P1 | pip-audit 修复可升级项后只剩 ecdsa 无修复的 P-256 时序公告 | 中×高 | 固定 pip-audit 2.10.1；production HS256 不可达策略 fail-closed，算法/版本变化重审，2026-11-30 到期 | Yijie Shen | 2026-11-30 | accepted-until |
| R-018 | P1 | 当前远端微信 artifact 仍为 `release_eligible=false`，尚缺真实 HTTPS Origin 的 RC | 中×中 | Run 34288613644 已保存当前干净 merge-ref 的微信 artifact/checksum；域名可用后以真实 Origin 重建并复核 `release_eligible=true`、0 source map 与上传入口 | Yijie Shen | Gate A | open |
| R-019 | P1 | 管理分包是否随公开包发布未决定 | 中×中 | Gate B 前评估包体、审核面、运营入口和后端授权 | Yijie Shen | Gate B | deferred |
| R-020 | P1 | 认证安全和监控告警缺口 | 中×高 | 9.5 已实现 refresh family 轮换/重放撤销、Redis 原子限流/fail-closed 和结构化安全事件；仍需正式监控接入、送达与恢复演练 | Yijie Shen | Gate B | mitigating |
| R-021 | P2 | OpenAPI CLI UTF-8/CP1252 回归缺少 CI 运行证据 | 高×低 | Run 33355935212 的 OpenAPI Job 完成 `--help`、真实导出、字节比较和类型漂移检查 | Yijie Shen | 9.2 | closed |
| R-022 | P2 | metadata/README 已收敛，artifact checker 拒绝 H5-only marker；当前 M8 RC 尚未复核 | 中×中 | 当前最终 SHA 的 CI artifact 与真实 RC 证明发布元数据只声明微信 | Yijie Shen | Gate A | mitigating |
| R-023 | P2 | Jest 重复提示 ReactDOMTestUtils.act deprecated | 高×低 | Taro 测试依赖升级窗口或有期限 warning 白名单 | Yijie Shen | Gate A 后可排期 | open |
| R-024 | P1 | Gate B 公开服务仍依赖单主机本地图片卷，缺少高可用存储/CDN | 高×高 | Phase 9.5 已冻结 `ImageStorage` 端口和对象存储验收门；仍需选型、真实 Bucket/CDN、最小权限和恢复演练 | Yijie Shen | Gate B | mitigating |
| R-025 | P1 | Gate B 缺少集中 Secret Manager、访问审计和自动轮换 | 中×高 | Phase 9.5 已冻结 Secret inventory、文件注入边界和 Pepper 轮换约束；仍需选择集中系统并验证最小权限、版本、轮换、撤销和审计 | Yijie Shen | Gate B | mitigating |
| R-026 | P0 | M7 修复前远端 CI 只有 7/8；失败 Run 的 MySQL Job 把 M6 当最新版本 | 确定×高 | `4d6430c...` / merge-ref `ccbbe9d...` 的 Run 34129910349 已 8/8；MySQL 21 项、cleanup 步骤和 7 组 artifact 可复核；旧 Run 保留 | Yijie Shen | 当前候选 / Gate A | closed |
| R-027 | P0 | M7 最初只有本地 dirty-tree 一次性 MySQL 完整证据，未绑定干净 commit/远端 Runner | 中×高 | [本地报告](reports/m7_mysql_release_gate_2026-09-07.md)保留完整历史矩阵；当前 [远端报告](reports/m7_remote_ci_2026-09-07.md)绑定 head/merge-ref，在干净 Runner 复现 workflow、21 项 MySQL 与 cleanup | Yijie Shen | 当前候选 / Gate A | closed |
| R-028 | P0 | 持久 Gate A 最后历史记录为 M2，错误起点或部分 DDL 失败可能造成不可发布状态 | 确定×极高 | 2026-09-08 写前只读确认真实 M2，Backup/Restore 后依次执行 M3–M7、Wallet/MARD 并生成绑定 Runtime `73dca350...` 的成功 Record；最终 22 表/217 列/83 约束/173 索引统计行及业务摘要通过 | Yijie Shen | Gate A | closed |
| R-029 | P1 | Wallet 曾只有有限 MySQL 关键闭环，缺少扩展并发/瞬态错误/查询计划与跨资金库存门槛 | 中×极高 | 一次性 MySQL 8.0.46 已完成 Wallet `9 passed`、三域联合 `30 passed`；head `62f807a...` 的 Run 34134341829 远端 8/8，三域联合、cleanup 和 artifact 步骤成功，覆盖并发、真实 1205/1213、锁等待与关键 `EXPLAIN` | Yijie Shen | 2026-09-07 | closed |
| R-030 | P1 | 本地 SQLite 的 221 色与图片不能作为 Gate A MySQL/持久图片证据 | 确定×高 | Gate A 已根据冻结 manifest 写入 221 色、原子发布/checksum 核验 221 张图片，并建立启用 3 色与库存 148 的测试商品；数据后 225 图片 Backup/Restore 通过。HTTPS/真机读取另由 R-002/R-003/R-031 跟踪 | Yijie Shen | Gate A | closed |
| R-031 | P1 | 旧微信验收只覆盖 M2 业务面，M4–M8、HEX 直绘、gzip、代客多颜色和头像布局没有当前 RC 真机证据 | 确定×高 | 当前矩阵全部绑定同一 release-eligible RC，在至少一台 iOS 和 Android 完成 Wallet、颜色 Kit/HEX、Reservation、固定/单日店休、压缩与最新布局验收 | Yijie Shen | Gate A | open |
| R-032 | P1 | Gate A 的 Wallet 历史用户/legacy manual Order 需要 backfill/reconcile，否则启用资金入口可能形成缺账户或矛盾结算 | 高×极高 | 按冻结上界完成 wallet `would_create=1 → created=1 → 0`、legacy settlement `would_create=1 → created=1 → 0`，升级对账 `1/0/0`；综合数据后二次对账为 `scanned=4, mismatches=0, violations=0`，真实充值/Provider 仍关闭 | Yijie Shen | Gate A | closed |
| R-033 | P2 | Reservation N1 只在页面展示状态，店休取消没有主动微信通知 | 高×中 | Gate A 明确 N1 边界并保留人工电话兜底；若 Gate B 要求通知，完成订阅授权、加密投递地址、durable outbox/worker/重试/监控和真机验收 | Yijie Shen | Gate B / N2 | deferred |
| R-034 | P2 | MARD 网页 HEX/RGB 未经实体拼豆样本校色，图片是确定性纯色而非实物照片 | 中×中 | Gate A 内部说明来源限制；公开使用前按批准色样校准并更新 manifest/图片/checksum/验收记录 | Yijie Shen | Gate B 或正式销售前 | deferred |
| R-035 | P0 | 持久 Gate A 已是 M7，而 M8 基线 Run 早于显式 M7→M8 入口；误用默认 M2、旧 Run/Record、缺少内容级恢复证明可能造成部分 DDL 和不可发布状态 | 确定×极高 | 显式 `--source-version 7`、M8-only、`m7-preserved-business-v1` 21 表、raw M7 目录/221 PNG 预检和启动前 live replay 已经 Review；head `62b1b15...` / Run 34288613644 又以真实 M7 source、双 Backup/Restore 和 14/14 阶段关闭一次性完整 updater 缺口。风险继续 mitigating，仅因持久 Gate A 仍缺当次只读盘点、新 Backup/Restore、精确 target SHA/Image、停写窗口、明确写授权和 M8 数据后恢复 | Yijie Shen | Gate A M8 前 | mitigating |
| R-036 | P1 | 已有 Online 自选色商品下的 exact no-op publisher 与 M8 HEX/gzip 尚未在持久 Runtime 现场验证；直接 SQL 或宿主图片旁路写入会越过应用锁边界 | 确定×高 | Run 34288613644 已在一次性 Runtime 实测 Online 221 项 exact no-op、启动前 replay、221 HEX、63,445→10,948 bytes gzip、正确 `Vary`、PNG 不压缩和 M8 Backup/Restore。这降低候选实现风险，但维护窗口仍必须停止 App/Nginx 并排除 DB/文件旁路 writer；关闭仍需持久 Gate A 的三次 no-op/紧邻 replay、221 HEX/API/零色块 PNG 请求、单次 gzip/图片不压缩和数据后 Backup/Restore | Yijie Shen | Gate A M8 前 | mitigating |
| R-037 | P1 | 共享 5Mbps 下，10 VU 持续请求未压缩 51,063-byte 色板 JSON 会形成出口队列和尾延迟 | 确定×高 | 本地完整探索矩阵已把该路径稳定复现为 428 qdisc drops、P95/P99 1,510/2,442ms；gzip 后 10,023 bytes、减少 80.371%，同一 10 VU 为 271/290ms 且零 drops。代码已由 `fa6fce05...` / Run 34281512196 关闭干净远端 CI，但该 Run 不执行容量矩阵；保持 App/Nginx gzip、客户端不禁用压缩并监控 gzip 命中/drops/尾延迟。关闭仍需基于干净候选的 candidate-pre 三轮和独立 2 vCPU/4GiB Linux/真实网络复现全部门槛，或由风险接受人签署有期限处置 | Yijie Shen | Gate A M8 前 | mitigating |

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
