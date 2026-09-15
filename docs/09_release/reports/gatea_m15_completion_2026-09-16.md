# Gate A M15 迁移完成报告

## 结论与范围

Gate A 已于 **2026-09-16T01:01:05.032583+08:00（北京时间）** 完成 M15 finalization，随后只读审计通过。数据库 M15、live 配置、运行镜像、current 和 finalized lineage 指向同一冻结候选，五服务 healthy，readiness/liveness 均为 HTTP 200，无 pending。现场完整数据与图片和验收后独立恢复的备份一致。

本报告是本轮 Gate A M9→M15 完成事实的权威入口；较早 A–G 恢复记录与执行计划中的“等待”状态属于对应时间的历史。此次完成不代表 Gate B、其他持久环境、正式微信资金、域名/HTTPS RC、真机或微信上传/公开发布已经通过；微信发布仍为 No-Go，具体未关闭项目见[发布清单](../go_no_go_checklist.md)。

## 冻结候选与来源

- 源 G/M9：`232919cc57efe4250195ab721104d62ae5e08d34`；源 finalized 摘要：`bdcf5314250ec45f3dc573e30529458939d57fc553908fc90f66b50a77aafc4e`。
- PR：[#6](https://github.com/EVEBios/pinkdooHub/pull/6)，冻结 head：`410ba10563981a2fd744bbe715dbcf37e5208565`。
- 实际安装 merge target：`ff125a322374d9cd34728798f89cf3d02904dca3`。
- 镜像：`sha256:a42d2f421a8a21e083c39efb1755b74cc810e4ed18469998a83dee5a4a62d1a3`。
- 当前指针：`/srv/pinkdoohub/gatea/releases/ff125a322374d9cd34728798f89cf3d02904dca3`。
- 当前候选自己的 [CI Run 34993499157](https://github.com/EVEBios/pinkdooHub/actions/runs/34993499157)，attempt 1，九项通过。
- 专用 updater ZIP SHA-256：`6256fb77628cff582f251733828427d1767b951d520cd607533af225152e33e5`。
- 源备份与独立恢复 ID：`20260915t161237z`；验收后备份与独立恢复 ID：`20260915t165831z`。

完成报告是运行后证据；文档提交不改变上述冻结源码、镜像或 CI 身份，也不冒充新的候选验收。

## 验证结果

| 阶段 | 结果与证据含义 |
|---|---|
| 升级前 | G/M9 新备份与同 ID 独立恢复通过；M15 stage 验证本候选制品、源码和快照 |
| M10–M15 | 六个迁移依次各执行一次；逐步验证固定 M9 列投影、版本链、结构、默认值与新表；只读 replay 通过 |
| 管理员验收 | 预约、提醒、跟进、库存读取及权限/整数校验通过；直接开台、同意图重放不重启、释放通过；管理员会话撤销 |
| 数据保护 | 221 色保持 packs=null/revision=0，库存批次为 0；保留旧资金、订单、库存和其他不应变化的业务内容；无开放会话和占用，reconcile 违规为 0 |
| 故障恢复 | MySQL、Redis 分别中断时 readiness=503、liveness=200；恢复后 readiness=200；应用重启通过；数据与图片不变 |
| 日志 | 五服务 24 小时扫描通过；精确敏感值命中 0、禁止模式命中 0，不保存原始日志 |
| 数据后恢复 | 完整 MySQL 内容（包含新增业务表和 Aerich）与图片一致；独立恢复应用 ready；Redis 空启动、旧刷新会话失效；不发布宿主端口 |
| 最终收口 | 停写再次比对备份，恢复五服务，再原子更新 current 并写 finalized；所有证据绑定同一候选和备份 ID |
| 最终审计 | current/live/database/finalized 一致；现场快照与独立恢复备份相同；历史保护归档不变；无 pending |

## 记录摘要

以下为服务器原始 JSON 文件的 SHA-256；没有改写历史记录或复用其他候选证据。

| 记录 | SHA-256 |
|---|---|
| Stage | `d0a0a1e38a5e2c003efd06893c0c768e43482497a3976308e2d1512e63381f89` |
| M9→M15 upgrade | `a21730782276a7ec8facfde5bf924e414fe751d71e4f29de27a733456f127cac` |
| 只读 replay | `abcb0f2cb2c148f76fdd723176a5f00c8395e4d5d58fb7fd809451b7d7f3408a` |
| Activation | `4ea7b43d17cd80e4c2c34ac248b56c79d63d1e4ac16e3d677236a6fe56bc1e7a` |
| 管理员验收 | `82592486f855a028ffcbcf050d9735b9b6f1006763d5825b389cec4415fcb276` |
| 故障恢复 | `caac30e4dee134d745d9d8138d879e75e6f9059b4cc59af0502da24e43da8d24` |
| 验收后备份 | `63db7e5ff4fd2d01c27c5ee100881741aa675e8870566d57f7f1c457528b8f19` |
| 同 ID 独立恢复 | `c48640b5c0d6d52b40101989c0e8495f92a8a511856182bdfe253390a6f422e2` |
| Finalization | `2ec3f77da46ca991b4659201428ba5b0110f05e9c828073a196016c82b8633e1` |

原始记录位于服务器 Gate A `records/releases`、`records/m15-acceptance`、`records/resilience`、`records/backups` 与 `records/restores`。本地核验副本与安全摘要保存在固定 `pinkdooHub-m15-migration-evidence/runtime/m15-finalized-audit.json`；它包含上述记录和来源路径，不包含凭据或业务原始行。

## 失败预防与资源控制

本轮管理员第一次交接在凭据输入前因缺少 `records/m15-acceptance` 目录失败。确认父目录和归属后使用既有受控工具创建 root:root/0755 目录，重新验证实际安装入口全部八项凭据前置检查后才交接。失败未登录或执行业务写入，未产生 pending；冻结代码和已有证据保持不变。今后交接检查必须覆盖实际环境中的新记录目录，不能仅凭 API 测试和迁移演练通过就交接。

本轮不重复已完成迁移，不重复已通过且代码未变的完整 CI 或业务测试。先前失败均按影响范围回归：历史 M9 夹具、MySQL M11 新外键检查、Taro 渲染等待分别定向处理；最终代码候选自己的九项 CI 全通过。过程、测试计数与失败原记录见[执行与验证计划](gatea_m10_m15_execution_plan_2026-09-15.md)。本次最终操作未改业务代码、迁移文件、依赖或版本号，仅记录验证结果；文档执行差异和链接检查。

## 资源回收与保留

- 独立恢复临时容器、网络、数据卷按该备份 ID 清理并由发布器和最终审计复核；只读快照一次性容器均退出并删除。
- 本地临时 Docker daemon、测试容器/数据卷、依赖链接和传输输入已回收；本次 SSH/执行会话全部结束。
- Gate A 五个持久服务、发布源码和镜像、SQL/图片备份、历史保护归档及证据按用途保留。Compose 的 image-init 已成功退出，是持久部署组成部分。
- 用户原开发 Redis、终端和浏览器不属于本次待回收临时资源，保持现状。

## Review

本次收尾只更新发布事实与导航，无 API、数据模型或依赖变更。报告以原始记录摘要和现场检查为依据，不记录 Secret、用户名、密码或令牌；历史证据保持原位。测试范围对应实际变更，未将文档提交冒充新的源码候选 CI。M15 数据库迁移与恢复已完成，本任务无剩余迁移步骤；微信发布及其他环境仍按各自清单推进。
