# 微信 Gate A 隔离发布演练 Runbook

> **Status:** M2→M7 persistent/server drill passed；M7→M8 historical updater passed on GitHub-hosted disposable Linux；current M7→M8→M9 candidate and persistent M9 execution remain blocked pending the candidate's own CI
> **Last Updated:** 2026-09-11
> **Scope:** 微信小程序内部测试版（Gate A）

本文定义 Phase 9.3 的安全执行顺序、证据和失败处置。它不是生产操作授权，也不包含任何真实连接信息。首次实际演练必须在专用、可销毁、与共享环境隔离的 MySQL 8+、Redis 和图片存储中执行。

2026-08-31 的已执行报告只证明当时 M0–M2 候选。当前迁移链已经扩展到 M9，功能面
增加 M4 Wallet/Payment/Refund、M5 Reservation N1、M6 自选颜色 Kit 和 M7 可配置
固定店休；M8 又增加正式 HEX 与文本压缩，M9 增加 30 个固定桌台、开台会话、订单计时器
和当前占用。旧报告、旧工具输出和旧候选迁移 Record
不得重命名或复用为当前结果。持久 Gate A 已于 2026-09-08 从 M2 升级到 M7；这是当前
最后成功点，后续每次操作仍须以只读查询重新确认，不能退回使用 2026-09-02 的 M2 假设。

2026-09-08 的当前执行已遵循该顺序：只读确认 M2，新 Backup/独立 Restore 后
升级到 M7，再完成 Wallet/MARD、候选韧性、综合数据、数据后 Backup/Restore
和加密异机副本。本文保留操作规范；实际结果见
[Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。
M8 基线 head `4e745848...` 的 Run 34242753255 已 8/8；后续 M7→M8 加固 head
`fa6fce05...` 的 Run 34281512196 也已在干净远端完成 8/8。随后 head
`62b1b15...` / merge-ref `a9ff3d2...` 的 Run 34288613644 将完整 M7→M8 updater
作为第 9 个 CI Job，在 GitHub-hosted disposable Linux 完成 14/14 阶段、
M7/M8 双 Backup/Restore、221 HEX/gzip/PNG Runtime、artifact 扫描与零残留，
Run 在同一 clean checkout 重跑一次性 `pip` truststore 失败的 OpenAPI Job 后
最终 9/9。详见
[M8 发布加固远端 CI 报告](reports/m8_hardening_remote_ci_2026-09-09.md)与
[Gate A M7→M8 完整更新器远端 CI 演练报告](reports/gatea_m7_m8_updater_remote_ci_2026-09-09.md)。
上述历史 M8 一次性 updater 缺口已关闭。当前 M9 候选把编排扩展为
M7→M8→M9，并新增 30 桌 bootstrap/replay、桌台 reconcile/sweep、Runtime API 和
M9 数据后 Backup/Restore；它必须先用自己的干净 Git SHA 完成全部 required Jobs，
历史 Run 34288613644 不能替代。持久 Gate A M8/M9 仍未执行。

## 1. 安全边界

- 演练不得连接默认 `3306` 共享实例、生产资源、开发 SQLite 或来源不明的数据库；fixture 和人工预检都必须拒绝这些目标。
- 不使用 Aerich `--fake`，不依赖应用启动自动建表，不用手工 SQL 补版本或业务状态。
- 数据只使用合成数据；日志、截图和报告不得包含密码、Token、JWT、Redis URL、AppSecret 或连接串。
- 迁移前必须生成备份并在独立实例验证可恢复。仅“命令返回 0”不算备份验证。
- 每个进程、容器、端口、临时目录、快照和 artifact 都记录所有者及用途，成功、失败或放弃时走同一清理路径。
- MySQL DDL 可能隐式提交。不得假设迁移失败会整体事务回滚；发生部分失败时先停写并调查真实 Schema 状态。
- downgrade、恢复、覆盖数据、删除 Schema、切换 DNS、上传体验版等外部或破坏性操作均需当次明确授权。

## 2. 演练角色与输入

| 角色 | 责任人 | 责任 |
|------|--------|------|
| 演练负责人 | Yijie Shen | 冻结范围、窗口、目标、停止条件和最终结论 |
| 数据库执行人 | Yijie Shen | 预检、备份、迁移、Schema/数据核验和恢复 |
| 应用执行人 | Yijie Shen | 后端、Redis、图片、管理员初始化和 API Smoke |
| 微信验证人 | Yijie Shen | 构建来源、体验版、合法域名和真机 Smoke |
| 观察/复核人 | Yijie Shen | 分步骤复核目标、证据、失败决策和资源清理 |

当前项目由同一人承担所有角色，因此演练记录必须把“执行”和“复核”写成两个独立步骤，分别保存时间和检查结果；不得用一次笼统签字代替复核。

演练开始前必须冻结：

- Git SHA、后端版本、前端版本、OpenAPI 摘要和 CI run；
- 与该 SHA 绑定的后端/微信构建 artifact 及校验和；
- 专用 MySQL、Redis、HTTPS Origin、图片存储和合成账号清单；
- MySQL 当前版本、目标 Aerich 版本、备份目标和预计恢复时间；
- 演练负责人、执行人、Go/No-Go 决策人、回滚/恢复授权人；
- 维护或停写窗口、最长允许中断、终止阈值和沟通渠道。

缺少任一项时不得进入写操作。

## 3. 演练场景

| ID | 场景 | 核心断言 | 状态 |
|----|------|----------|------|
| DR-01 | 全新空库 0→当前 | 当前要求为精确 0→9，并核验 M3–M9 表/约束/索引/默认数据/HEX/30 桌 | M9 本地一次性 MySQL 0→9 PASS；当前 SHA 的远端 CI 与持久 Gate A 待执行 |
| DR-02 | 迁移 0 代表性数据升级 | 用户、Product、Audit 等数据保持；当前候选必须继续到 M9 | M9 本地一次性 0→9 PASS；持久 Gate A 的 M2→M7 历史 PASS，M7→M8→M9 NOT RUN |
| DR-03 | 历史版本代表性数据升级 | M5 fixed/Reservation 样本经 M6→M7→M8→M9，已有数据不漂移 | M9 本地迁移链与历史 M8 内容保护 PASS；当前 SHA 的完整远端 updater 与持久 M7→M8→M9 NOT RUN |
| DR-04 | 备份并恢复到新实例 | Schema、关键行数、抽样聚合、登录和启动均通过 | 持久 M7 Backup `20260908t021224z`/独立 Restore/加密异机副本 PASS；一次性 M7 `20260908t230214z` 和 M8 `20260908t230329z` 同 ID Restore PASS |
| DR-05 | 可控迁移失败 | 识别实际部分提交状态；按批准方案前滚或从已验证备份恢复 | 历史 M2 PASS；M8/M9 部分提交均须保持停写并按当次证据处置 |
| DR-06 | 应用与依赖 | FastAPI/Uvicorn、MySQL、Redis、图片、liveness/readiness、优雅重启通过 | 当前 M7 Runtime 候选级韧性 PASS |
| DR-07 | 管理员初始化 | 一次性、幂等、可审计地建立首个 SUPER_ADMIN；重复执行无第二账号 | 历史 Bootstrap PASS；当前账号登录、轮换密码和会话撤销在 M7 Seed 重验 PASS |
| DR-08 | 微信真机网络 | request/upload/download、证书、Token、图片和错误信封通过 | BLOCKED：备案/Origin/RC |
| DR-09 | Gate A 纵向 Smoke | 旧最小链路加 Wallet、颜色 Kit、Reservation、M7 和最新界面 | 当前服务端 82 请求及数据聚合 PASS；真机界面继续属于 DR-08 |
| DR-10 | M4 钱包补齐与对账 | wallet/legacy preview 与冻结上界 apply、二次 preview、只读 reconcile 全零差异 | 持久 Gate A PASS；综合数据后复核 `4/0/0` |
| DR-11 | M5 Reservation | 预约四状态、单日店休、隐私、并发/1205/1213/索引与历史数据 | MySQL 门槛与 Gate A 六预约聚合 PASS；真机待 DR-08 |
| DR-12 | M6 颜色目录与库存 | M5 fixed 重放到 M6/M7；221 槽/列/FK/索引；持久图、商品启用色/库存与 HTTPS | MySQL/持久图/三启用色/库存/Backup 已 PASS；HTTPS 真机待 DR-08 |
| DR-13 | M7 固定店休 | 单例/默认周一/唯一约束，历史预约/单日店休不漂移，更换的事务/锁序/批量取消 | 一次性/远端 MySQL 与持久 Gate A 结构/聚合 PASS；真机待 DR-08 |
| DR-14 | M8 HEX 与 gzip | `swatch_hex` 221 项精确/唯一，目录与图片零漂移；API/小程序直绘；文本只压缩一次、图片不压缩 | 一次性 updater Runtime 221 HEX、63,445→10,948 bytes gzip、PNG 不压缩 PASS；持久 M7→M8、Gate A HTTPS Runtime 与真机 NOT RUN |
| DR-15 | M9 二维码开台与计时 | 30 桌固定编号/随机 Token、15 分钟支付窗、按已付 Experience 时长分组计时并加 10 分钟、超时/取消/完成/退款释放、对账与清扫幂等 | 仓库实现与本地 SQLite/MySQL 门槛 PASS；当前 SHA 的远端 updater、持久 Gate A 与真机扫码 NOT RUN |

对当前最后留证为非空 M7 的 Gate A，以及未来任何需要接管的既有数据库，都必须先执行
只读审计，确认 Schema、Aerich 版本、数据质量、图片 manifest 和备份；未审计的库不
自动成为“受支持升级起点”。

历史 M2 执行的 SHA、CI、结果、耗时、修复项和资源清理记录见
[Phase 9.3 隔离发布演练报告](reports/phase93_rehearsal_2026-08-31.md)。该报告不修改，
当前候选的每次新执行必须另建独立报告并列出 DR-01～DR-15 的适用/不适用项。

M7 的本地可销毁迁移与联合门槛见
[M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)。该报告运行于提交前
dirty 工作树；同内容随后成为提交 `58d8435...`，并随 head `4d6430c...` 在
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 取得远端
8/8。远端证据见 [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)，但仍不包含
持久部署、备份恢复、应用/图片/Redis Smoke 或微信真机，因此不能把 DR-01～DR-14
整体标成 M8 候选 PASS。M8 的远端身份、首轮失败与修复、8 Job/artifact 见
[M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。

### 3.1 当前 M4–M9 证据分层

| 版本 | 仓库/历史事实 | 当前候选一次性 MySQL | 持久 Gate A 必需动作 |
|------|---------------|----------------------|----------------------|
| M3 | 外部身份与认证安全仓库实现完成 | M8 workflow 保留 M3；当前 Run 34281512196 远端 8/8 | 持久 Gate A 已应用；仍保持 password 模式 |
| M4 | 钱包/支付/退款代码完成 | Wallet `9 passed`、三域联合 `30 passed`；当前 M8 workflow 远端 success | 持久 Gate A 已应用，两个 backfill/reconcile 已零差异 |
| M5 | Reservation N1 完成 | 历史/当前 MySQL workflow 均通过 | 持久 Gate A 已应用；已有预约/单日店休继续作为 M8 不漂移基线 |
| M6 | 221 色目录、商品颜色库存和兼容 PNG 完成 | M6 snapshot/锁等待及 M8 迁移重放通过 | 持久 Gate A 已发布 221 色/PNG 与三启用色；M8 不得改这些事实 |
| M7 | 固定店休完成 | 单例/约束/并发及 M6→M7→M8 远端步骤通过 | 当前持久成功点；作为当前 M9 候选唯一允许规划的 source 起点 |
| M8 | HEX/API/小程序直绘/gzip 仓库实现完成；显式 M7→M8、21 表内容保护与 Online exact no-op 已实现 | 基线 0→8/Run 34242753255、加固 Run 34281512196，以及 head `62b1b15...` / Run 34288613644 的 GitHub-hosted 完整 updater 14/14 均 PASS；后者含双 Backup/Restore、221 HEX/gzip/PNG 和零残留 | NOT RUN；持久 Gate A 仍须当次只读预检、新 Backup/Restore、精确目标/窗口/写授权与数据后恢复 |
| M9 | 二维码开台、订单绑定、支付后分组计时、15 分钟支付超时、10 分钟缓冲、30 桌管理与清扫均已完成仓库实现；受控升级器扩展到 M9 | 本地 SQLite 定向/完整门槛及一次性 MySQL 0→9、M9 迁移/并发/领域门槛 PASS；当前 SHA 远端证据待生成 | NOT RUN；只允许从精确 M7 经当次 Backup/Restore 与显式授权执行 M8→M9，并在启动前重放 plan |

当前 M9 仓库候选的本地验证口径为后端等价完整 `2858 passed, 39 skipped`（沙箱
`2854 passed`，四项 loopback bind 在允许环境另为 `4 passed`）与 Release 等价完整
`736 passed`（沙箱 `734 passed`，其中两项 loopback bind 在允许环境另为 `2 passed`）。这些
结果不代替当前 SHA 的远端 required Jobs，也不表示持久 Gate A 已从 M7 升级。

任何“一次性 MySQL PASS”只关闭候选迁移实现风险，不等于已应用 Gate A。任何本地
SQLite 数据也只属于开发环境，不是 Gate A 的数据或图片发布证据。

## 4. 执行顺序

### 4.0 本仓库自动化入口

当前 CI 另有 `scripts/ci/gatea_m7_m8_drill.py`（为兼容既有 workflow/branch protection
保留文件名和 Job ID `gatea-m7-m8-updater`），用于在 GitHub 托管的一次性 Ubuntu
Runner 上自动复现完整 M7→M8→M9 updater。它与下方历史 Phase 9.3 工具分离：source 为冻结
M7 Runtime，target 为本次 checkout，顺序包含 source 数据/221 PNG、Backup/独立
Restore、M9 plan/apply/停服 replay、target app-up、221 HEX/gzip/PNG、30 桌与 table
session Runtime，以及 M9 数据后 Backup/Restore。`run` 内部和 workflow `always()` cleanup 均会精确回收固定
Compose/restore 资源与两张任务镜像；Artifact 只接收脱敏白名单，并且只有 cleanup 后
重新签发的最终安全扫描 marker 存在时才上传。

Workflow 总闸为 60 分钟；主体由 40 分钟进程组 watchdog 约束，独立 cleanup 最多 8
分钟。不得删掉内层 watchdog 或让它等于总闸，否则 Docker/Restore 卡死时可能没有补偿
清理和安全证据时间。

该入口必须拒绝本机、self-hosted、共享 Docker 或已经存在 Gate A 固定卷/网络/容器的
环境；不得为了复用它而放宽 guard。它通过后只关闭 disposable Linux 的 updater 复现
缺口，仍不授权持久迁移、Runtime 切换、真实 Origin/TLS、微信上传或真机操作。

历史 M8 执行记录：head `62b1b15...` / merge-ref `a9ff3d2...` 的
[Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) 已完成
14/14 阶段，source Backup/Restore ID 为 `20260908t230214z`，target Backup/Restore ID
为 `20260908t230329z`；221 HEX、63,445→10,948 bytes gzip、PNG 回退、20 文件
artifact 白名单/Secret 扫描和零残留均通过。这是一次性入口的已执行
证据，不是当前 M9 候选或持久 Gate A 记录。

9.3.3–9.3.4 已把本 Runbook 固化为以下入口。`<run-id>` 必须使用 `YYYYMMDDtHHMMSS`；准备命令会先要求工作树 clean、记录 HEAD/Compose digest、确认四个回环端口空闲且同名 project 不存在，未通过时不会创建 Secret、证书或 Docker 资源。以下命令不包含 Secret 值，所有原始证据只写入 `/tmp/pinkdoohub-phase93/<run-id>/evidence`：

```bash
python -m scripts.release.phase93_rehearsal prepare --run-id <run-id>

python -m scripts.release.phase93_operations pull-images --run-id <run-id>
python -m scripts.release.phase93_operations build-app --run-id <run-id>
python -m scripts.release.phase93_operations start-data --run-id <run-id>

python -m scripts.release.phase93_operations migrate --run-id <run-id>
python -m scripts.release.phase93_operations verify-current --run-id <run-id>
python -m scripts.release.phase93_operations legacy-m0 --run-id <run-id>
python -m scripts.release.phase93_operations legacy-m1 --run-id <run-id>

python -m scripts.release.phase93_operations bootstrap --run-id <run-id>
python -m scripts.release.phase93_operations bootstrap-replay --run-id <run-id>
python -m scripts.release.phase93_operations verify-bootstrap --run-id <run-id>
python -m scripts.release.phase93_operations runtime-seed --run-id <run-id>
python -m scripts.release.phase93_operations start-app --run-id <run-id>
python -m scripts.release.phase93_operations live-smoke --run-id <run-id>

python -m scripts.release.phase93_operations backup-db --run-id <run-id>
python -m scripts.release.phase93_operations backup-images --run-id <run-id>
```

以下步骤会执行恢复、依赖停止、受控失败或资源删除，必须在执行时把 `<project>` 替换为 manifest 中的精确 project，并取得当次授权：

```bash
python -m scripts.release.phase93_operations restore-db \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_restore
python -m scripts.release.phase93_operations restore-images \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations verify-restore \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_restore
python -m scripts.release.phase93_operations dependency-drill \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations restart-app \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations failure-drill \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_failure

python -m scripts.release.phase93_report --run-id <run-id>
python -m scripts.release.phase93_operations stop \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations cleanup \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-workspace /tmp/pinkdoohub-phase93/<run-id>
```

`phase93_report` 只有在 DR-01～DR-07 与 DR-09 服务端必需报告全部 `passed=true` 时才生成仓库外脱敏摘要；DR-08 明确写为 9.4 deferred。清理前先保存该摘要，清理后再把端口释放、project label 归零和临时目录删除结果人工回写最终报告。工具不会自动 commit、push、连接微信后台或执行任何持久/生产资源操作。

#### 4.0.1 当前工具适用边界与停止条件

历史演练不能直接承担当前 M7→M8→M9；仓库候选已新增精确入口，但仍不是持久执行授权：

- `scripts.release.phase93_operations` 的迁移版本、Schema 断言和 legacy 场景硬编码为
  M0–M2，只能复核历史 9.3 报告；在更新并重新测试前不得称为“0→当前”。
- `scripts.release.gatea_operations initial-migrate` 仍只接受 0 张表的首次数据库，不得
  对非空 Gate A 使用；`app-up` 现同时接受精确匹配的 initial migration Record 或
  `gatea_upgrade` 成功生成的 existing-database upgrade Record。
- `scripts.release.gatea_operations database-status` 已可对健康 MySQL 只读输出精确
  Aerich 链、Schema 数量/指纹和关键业务聚合，但不会迁移或批准未知起点。
- `scripts/local/import_mard_bead_colors.py` 仍只操作项目内 SQLite；Gate A 的
  `app.tasks.gatea_mard_publish` 只供受控编排，不能把本地开发图片
  复制为持久发布证据。

`scripts.release.gatea_upgrade` 已实现并在本地单测、一次性 MySQL 8.0.46 与历史 Gate A
执行中验证 M2 起点的通用保护能力；当前仓库候选又新增显式 `--source-version 7`，旧调用
仍默认 M2，从而让遗漏 M7 选择的调用在读取 Backup、停写或写入前 fail closed：

1. 先用 `database-status` 保存不含 Secret/PII 的只读起点证据；非空库升级入口再验证
   Root/Secret/镜像、停写状态、新 Backup/Restore Record、候选 SHA/Image ID 和该份
   Aerich/Schema 证据；受支持起点清单必须单独 Review，不能由
   一次性 MySQL 的 M0–M6 矩阵自动推导；
2. M7/M8/M9 Backup 必须带 `m7-preserved-business-v1`：20 个非 `bead_colors` 表的稳定顺序
   data dump 加该表 M7 字段投影，共覆盖 21 个业务表；独立 Restore、停写源和最终态都
   重算精确 SHA-256。精确 M9 Backup 还必须带 `m9-table-business-v1`，以稳定主键
   顺序覆盖 `store_tables`、`table_sessions`、`table_session_timers` 和
   `table_occupancies`，并在独立 Restore 重算相同摘要。Record 只保存版本化
   profile 和 digest，不保存原始桌台 Token/行内容。Aerich 链与完整图片 manifest
   另行比较，旧聚合仅作诊断；
3. 停写源与 Backup 对齐后、M8 原语前，raw preflight 要求 `swatch_hex` 列为 0，221 条
   M7 slot/code/name/URL/sort/active 逐槽等于冻结 manifest，221 张预期 PNG 为普通非软
   链接文件、checksum 精确且权限 `0644`；
4. 入口按真实 Aerich 版本逐步升级到 M9，保存每步 Schema/数据摘要，失败时保留现场，并在
   全部核验通过后生成新的 candidate upgrade Record；
5. Gate A 221 色发布原语接入受控流程：M2 路径可按 preview、显式 checksum apply、
   MySQL 事务、持久图片原子发布/补偿、幂等重放和 HTTPS URL 核验留证；M7 路径则要求
   preview/apply/replay 全部为精确 221 项 no-op；
6. M9 成功迁移后只由编排运行 30 桌 bootstrap/replay，要求 T01–T30 唯一、display name
   精确、Token 格式和唯一性正确；随后执行 table reconcile/sweep 并核验四表约束与索引；
7. 失败保留脱敏 evidence 和停止状态，成功 Record 可重放；输出不含 Secret、PII 或
   幂等键。成功后继续停写，并在 `app-up` 前紧邻重放同一 upgrade plan；重放会验证
   evidence 哈希、live DB、图片 manifest、21 表内容摘要和只读 MARD preview，并排他生成
   `<target-sha>.upgrade-plan-replay.json`。`app-up` 必须消费该 sidecar，重读 live M9
   Aerich/静态 Schema 摘要、运行 table reconcile 并在启动前复验 Image ID；它不重算图片
   manifest、M7 内容摘要或 MARD preview，所以不能省略紧邻 replay。

默认 plan 只读；apply 必须同时确认 source SHA、target SHA、Backup ID 与 MARD manifest
SHA-256。M7 起点必须显式选择，且 Record 同时绑定 `source_version=7`、精确 M0–M7 source
链和 M0–M9 target 链；当前入口只接受既有历史组合以及当前 M7→M9 组合，不能把 M8
历史 Record 冒充 M9 Record。新增
实现已由 head `fa6fce05...` / Run 34281512196 完成干净远端 8/8，后续当时仍以 M8 为
目标的 head `62b1b15...` / Run 34288613644 又在专用一次性 Linux/MySQL 中完整运行。
这只关闭了当时 M8 的 disposable updater 门槛，不构成当前 M9 的 9/9，也不构成持久
Gate A 的目标冻结、当次只读预检、
新 Backup/Restore 或写授权。持久执行仍不得使用临时 SQL、删除旧 Record、
伪造 Record 或绕过保护逻辑。

候选镜像已提供 `app.tasks.gatea_migrate_step` 与 `app.tasks.gatea_wallet_prepare` 两个
内部执行原语：前者将 Aerich 限制为 M3–M9 单步前进，后者完成 M4 后双 preview、冻结
上界 apply、重放与 reconcile。它们不拥有主机/备份/停写/Record 验证，只能由
经批准的升级编排调用，不得直接用于持久 Gate A。M7→M8 不重复执行 Wallet backfill；
升级器也不在内部重复运行 `wallet_reconcile`。它改用写前 Backup/Restore、停写源和写后
目标之间完全相同的 `m7-preserved-business-v1` 内容摘要，证明既有 Wallet 及其他 21 表
内容没有漂移；语义级 `wallet_reconcile` 仍在 `app-up` 后作为独立只读验收执行并单独留证，
不写入 upgrade Record。

M6 色卡原语 `app.tasks.gatea_mard_publish` 也已完成：它固定 production MySQL、
`/data/images`、HTTPS URL、manifest SHA-256 和 `0644` 图片，事务失败补偿本轮文件，
精确重放零写入。它同样不拥有停写/Backup/Restore 授权，必须由升级编排调用。当前候选
允许已有 Online 自选色商品和启用色仅在目录与 221 图片完全匹配时通过：apply 仍进入
事务，锁定并重读完整 BeadColor，重新检查图片和 Online 引用，最终必须为
`database_changes=0`、`images_to_create=0`、`images_reused=221`、`created_images=0`；
任何漂移都会在写入前拒绝。不得为通过它临时下架商品或修改启用态，也不得脱离 M7→M8
编排单独运行；新增安全分支的远端 CI 已通过，但仍须取得完整 updater 隔离 MySQL 证据。

#### 4.0.2 持久候选生命周期与全局互斥

所有持久、可变或依赖稳定现场的 Gate A 入口共用
`/run/lock/pinkdoohub-gatea-operation.lock`。它必须是 `root:root 0600` 普通文件、禁止软链接，
并以非阻塞方式独占；另一个操作在运行或锁元数据异常时立即停止。生产 CLI 不允许指定
另一锁路径。锁在任何 TTY 凭据读取、HTTP 请求、pending journal、数据库/图片/配置/容器
状态读取之前取得，并持续到补偿清理、登出和 success/failure journal 落盘之后；不能用两
个 shell 并跑候选、升级、备份、Restore verify、acceptance 或 resilience。纯只读
`preflight`、`database-status`、`status` 不持锁，其旧输出不是写入授权。`preflight` 的
端口空闲断言只用于尚无 Runtime 的首次部署；已有健康 M7 source 的升级使用 `status`、
`database-status` 与唯一现有 loopback publisher 核验，不得为了运行 `preflight` 而停止
source 或换端口，后续 Backup/activation/upgrade 仍在操作锁内重新校验同一现场。

当前 M7→M9 的持久成功路径必须严格按以下顺序执行，完整参数形状见
[`deploy/gatea/README.md`](../../deploy/gatea/README.md)：

以下从已安装 target Release 执行的宿主 `scripts.release.gatea_*` CLI 必须使用
`python3 -B -m`，避免在已冻结的 Release 树写入 `__pycache__`/`.pyc` 并改变 source
manifest。唯一例外是从同一 source archive 提取并校验的 `stage` launcher；它直接以
`python3 -B <launcher>` 运行。容器内 `python -m app.tasks.*` 和历史一次性 Phase 9.3
工具不属于这项宿主 Release 约束。

1. 先取得同一个 target checkout 的 source archive、当前 Run/attempt 的
   `gatea-m7-m9-updater-<target-sha>-<run-id>-<attempt>` artifact、两者 SHA-256 和 9/9
   required Jobs 证据；以 archive 中已单独校验的 launcher 执行 candidate `stage`。
   `stage` 只安装版本化 Release/目标镜像和不可覆盖证据，不改 config、Runtime、DB 或
   `current`。
2. 用 `status`、`database-status` 和唯一现有 loopback publisher 只读核验健康 source M7；
   不运行只适用于空端口首次部署的 `preflight`，也不停止 source 来迎合该检查。随后创建
   新的 source Backup 并完成同 ID 独立 Restore。Backup/Restore 任何失败、pending 或摘要
   不匹配都停止；不得先把 config 指向 target 再补 source 备份。
3. 从 `/srv/pinkdoohub/gatea/releases/<target-sha>` 运行 candidate `activate-config`：先不带
   `--apply` 取得 M7→M9 plan，再用相同 source/target SHA、Backup ID 和 manifest SHA-256
   明确确认 apply。它只原子修改 `GATEA_APP_IMAGE` 和
   `TABLE_SESSION_CLAIMS_ENABLED=true`，保存 `0600` 回退副本；此时 `current` 仍为 source，
   DB/Runtime 尚未切换。
4. 若在任何 target upgrade Record/evidence/replay 出现前终止，且 live DB 仍精确 M7、旧
   四服务健康、sweeper 未运行、`current` 未变，只能以 activation Record 的 SHA-256 调用
   `rollback-config --apply`。该命令只恢复 config；升级一旦开始便永久拒绝，不得把它当作
   DB downgrade。回退成功的 candidate 也不得 finalize。
5. 成功路径继续执行 `gatea_upgrade --source-version 7 --apply`；全部 M8/M9/30 桌/内容
   核验成功并保持三项业务服务停止后，以完全相同 source SHA/Backup ID 再运行一次不带
   `--apply` 的 plan-replay。它必须返回 `already_current=true` 并排他发布绑定 upgrade
   Record/evidence SHA-256 的 replay sidecar。
6. 紧邻执行 `gatea_operations app-up`。它必须消费 replay sidecar，重读 live M9 静态
   Schema、运行 table reconcile、复验目标 Image ID，并只启动精确五服务与 loopback
   publisher；图片 manifest/M7 内容/MARD 仍由刚完成的 replay 证明，期间禁止旁路写入。
7. 先运行 `gatea_m9_acceptance` 默认只读 plan，再运行一次
   `--apply-admin-assisted`；成功后把该 acceptance Record 的精确路径与 SHA-256 显式传给
   同 target 的 `gatea_resilience`（同时使用 `--runtime-acceptance-record`、
   `--confirm-runtime-acceptance-record-sha256` 与 `--apply`）。两项都必须绑定同一旧 M7
   代表数据证据，任一
   不能按严格状态机恢复的 pending、acceptance direct binding、清理不完整或脱敏失败都
   停止。
8. 在 acceptance 与 resilience 都完成后创建新的 M9 数据后 Backup，再完成同 ID 独立
   Restore；该 ID 不得复用 source Backup。最后把 acceptance/resilience Record 路径及
   SHA-256、各自 guarded record directory 和数据后 Backup ID 逐项传给 candidate
   `finalize --apply`。Record 父目录必须分别与 guarded 目录精确相同；只有它复验所有绑定、
   时序、live M9、五服务与 Restore digest 后才原子切换 `current` 到 target。

`stage`、activation、rollback、plan-replay、acceptance、Backup 和 finalization 的同名
Record/pending/Release/image 都采取 no-overwrite。`.pending` 是状态机 journal，不是通用重跑
许可：同一命令只有在其中的 source/target、Run/attempt、Record digest 和全部显式确认值
严格一致，且 checkpoint 明确允许恢复时，才可继续自己的 pending；更早阶段、另一动作或
内容冲突的 pending 一律阻断。不能满足这一恢复契约，或某一步 digest 与下一步不一致时，
必须保持 No-Go、保全证据并由授权人选择精确前滚或从已验证备份恢复，禁止删除、覆盖或
换路径绕过。

每次进入可变流程还必须做跨命令、跨候选 inventory：Release Record 目录直接子项中，
任何以 `.candidate-stage.pending.json`、`.config-activation.pending.json`、
`.config-rollback.pending.json` 或 `.current-finalization.pending.json` 结尾的路径都会阻断，
包括畸形候选名以及 symlink、目录、FIFO 等异常项。M9 acceptance 目录中的任意候选
`.json.pending`/`.json.complete` sidecar 也同样阻断；目录首次不存在可视为空，已存在则
必须是 `root:root 0755` 真实目录。candidate/acceptance 原命令只可对严格匹配当前
candidate、动作、路径与安全元数据的 own journal/sidecar 获得一次结构化恢复 allowance，
目录里出现第二个 blocker 就失败；allowance 之后仍须验证全部内容和 live 状态。

这两类 inventory 已接到 candidate 四动作、Backup/Restore、upgrade plan/apply、Bootstrap、
基础与 M7 代表数据、`initial-migrate`、普通 `app-up`、acceptance 和 resilience 的早期边界，
会在数据库快照、TTY、业务 API 或资源启停前阻断；只读配置/Secret 元数据校验不能越过
inventory 进入现场动作。不得以换候选 SHA、换命令或换路径绕开。Backup pending 不采用
“所有 ID 全局互斥”：只要选定 ID 的 pending 未收口，消费该 ID 的 Restore/Upgrade 必须
拒绝；其他 ID 仍按自己的 no-clobber 契约独立判断。
`infra-up`/`safe-stop` 保持为取得同一锁的故障处置原语，可以把依赖拉起或把现场停到安全
状态，但不会消费、删除或宣称解决 inventory；pending/sidecar 未收口时，所有后续发布
阶段仍必须拒绝。

不可变证据与 artifact 的发布也必须抗崩溃：先向同目录随机临时文件完整写入并 file
`fsync`，再以 hard-link no-clobber 发布、同步父目录，最后才清理临时文件并再次同步；状态
journal 的原子替换同样同步父目录。candidate 四动作分别从各自 checkpoint 恢复，不跨阶段
猜测。Upgrade 只在 canonical success 与 `succeeded/completed` evidence 路径/digest 一致时
提交；如果 success 已经可见，随后的临时清理/第二次目录同步失败不能把已提交 evidence
改写成 failed，重跑应先严格验证已有提交并执行只读 replay。

`finalize` 的 `current` 原子切换是 finalization commit point。若中断后 `current` 已精确
指向 target，只有 own pending 已到 `live-rechecked`、`current-switched` 或后续
`runtime-restored`，且全部身份、确认值与不可变证据仍严格匹配时，原命令才可复验
`current`/配置/目标 Image/live M9 结构与 Runtime invariant、恢复五服务并补齐 final Record。
Runtime 恢复后可能已有合法业务写入；此路径不得再拿切换前的旧 Backup 业务内容摘要（包括
pre-upgrade source 与 finalize 直接绑定的 post-acceptance Backup）和在线数据重比。
checkpoint 更早或任何证据冲突均 fail closed，并非看到 target symlink 就算完成。
普通 `app-up` 默认拒绝这个 finalization pending；只有已严格校验 own journal 的 candidate
内部恢复调用可显式跳过这一项检查，且 stage/activation/rollback 等其他 pending 仍会阻断。
正常 cutover、pending+target 续跑和已有 final 的 Runtime 修复都必须先恢复并核验五服务，
然后才能传播 HUP/TERM、SIGINT 或 `SystemExit`；若恢复失败，以恢复失败作为阻断结果并保留
原异常为 cause。

`finalize` 的 `--acceptance-record-dir` 与 `--resilience-record-dir` 默认分别为
`/srv/pinkdoohub/gatea/records/m9-acceptance` 和
`/srv/pinkdoohub/gatea/records/resilience`；两个传入 Record 的 lexical 父目录必须分别与
对应 guarded 目录完全相同，非默认路径必须把 Record 与目录参数一起显式传入。入口会在
读取 Release/live 证据前先扫描全候选 acceptance sidecar。它不替 resilience 清理发布残留：
待消费 resilience final 必须是稳定的 `root:root 0644` 普通文件、`nlink=1`，对应目录中没有
该 final 的 `.tmp-*` 或其他 publication alias/sidecar；否则先停止并由 resilience 自身的
精确恢复入口收口。

所有持久变更入口共用同一操作锁，并在 CLI work 前为 SIGHUP/SIGTERM/SIGINT 安装终止信号
guard；SIGINT 对外保持 Python `KeyboardInterrupt`。Backup、Restore、candidate
finalization 与 resilience 还在首次停服前安装 work→recovery 状态控制；工作阶段首个信号
先切换恢复相位再抛出，恢复阶段的后续信号只延期记账，必须完成精确恢复、清理与健康核验
后才传播。mandatory recovery/cleanup 子命令使用新 session/独立进程组，避免终端
`Ctrl-C` 同时直接终止父状态机和补偿子进程。服务 stop 必须用 Compose `ps` 复核目标进入
允许的停止状态；Restore project 最多执行两轮 `down --volumes --remove-orphans`→inventory，
并确认该 project 的容器、两个临时 named volumes 与 internal network 全部消失；candidate
临时镜像也最多执行两轮删除→精确 reference inventory。命令返回码不能替代这些状态盘点。
异常传播优先级固定为 recovery/cleanup failure > original work/control error > deferred
signal；延期信号不得掩盖补偿失败或原始根因。SIGKILL/断电不可捕获，有 durable
pending 的流程后续必须先按 journal 状态机处理，不能满足严格恢复契约即 fail closed；resilience 没有 durable
pending，因此 M9 演练若在成功 final 尚未可见时遭此中断，必须人工核验 MySQL、Redis、
App、Nginx、`table-sweeper` 五项服务和现场状态后才能决定下一步。final 已经可见时，相同
参数重跑只接受 `root:root 0644` 普通文件，并严格复验 schema v1/v2、全部绑定/时序、日志，
以及前后两次当前 Runtime、数据库和图片一致性，不重新制造 MySQL/Redis outage 或执行 App
restart。若只残留 writer 产生的最多一个临时别名，还须证明它与 final 同 inode/内容/冻结
身份，先同步 final 目录项、精确删除别名并再次同步；孤儿/多个/不一致 temp、同候选另一
sidecar 或任何漂移仍 fail closed。

### 4.1 预检（只读）

1. 两名人员核对目标主机、端口、数据库名、环境标识和资源所有者。
2. 确认目标不是生产、共享 `3306`、开发 SQLite 或其他任务资源。
3. 记录 MySQL/Redis/Python/Node/Taro 版本、Git SHA、artifact checksum 和当前 Runtime
   image；对持久 Gate A 通过受控只读查询同时记录精确 Aerich 版本链、表/列/约束/索引
   摘要和关键领域行数。若与 2026-09-08 的 M7 成功 Record/Backup 不一致，停止并调查。
4. 确认应用写入尚未开启；已有数据场景进入明确停写窗口。
5. 检查磁盘/配额、备份目标、证书有效期、HTTPS Origin 和微信后台合法域名。
6. 检查 Secret 仅由受控环境注入，命令行历史、日志和 artifact 中无 Secret。
7. 确认当前版本已经通过 9.2 所有 CI 门槛；任何必需 Job 缺失即停止。
8. 验证 4.0.1 所述非空升级和颜色发布入口已经实现并通过当前 SHA 的自动化；缺失即停止。

### 4.2 备份与恢复预验证

1. 对有数据场景创建一致性备份或快照，使用全新的 UTC ID，并在停服前确认同 ID 的
   MySQL/image artifact、最终 Record 与 `.<backup-id>.pending.json` 均不存在。备份器先
   排他创建 `0600` pending，再停写、复验迁移链并读取摘要/图片 manifest，然后才以排他
   方式向同目录随机 `0600` 临时文件流式导出，完整写入与 file `fsync` 后再以 hard-link
   no-clobber 发布两个正式 artifact 并同步目录；只在服务恢复及最终 Backup Record 也全部
   完成后删除 pending。
2. Backup 导出、服务恢复、Record 发布或中断任一失败，都保留 pending 并尽力删除本轮
   不完整 artifact；同一 ID 不可复用。不得删除 pending 或覆盖 Record 来重跑，必须保全
   现场并确认 live 服务/数据状态后再决定新 ID 或经授权恢复。只要同 ID 的 unresolved
   pending 仍存在，即使最终 Record 或 artifact 看似齐全，Restore 与 Upgrade 也绝不消费
   该备份；不得通过补文件、删 pending 或原命令重试复用这个 ID。
3. 在新的隔离实例恢复该备份。Restore success Record 不可覆盖；清理使用独立进程组，最多
   执行两轮有界的 `down --volumes --remove-orphans`→inventory，并逐项确认该 project 的
   全部容器、两个临时 named volumes 和 internal network 都不存在。只有内容核验与该精确
   盘点都通过后才发布 Record，不能以 `down` 返回码替代；Record 必须记录并绑定 Backup
   Record、MySQL artifact、image artifact 的三个 SHA-256。后续 upgrade/finalize 必须重新
   计算并匹配这些 digest，不能只看 `passed=true`。
4. 对精确 M7/M8/M9 链，Backup Record 必须包含 `m7-preserved-business-v1`：20 个非
   `bead_colors` 业务表的确定性 data dump 与该表 M7 投影，共 21 表；Restore Record
   必须重算同一摘要并记录 `m7_content_matches=true`。缺少此字段的旧 M7 Backup 不得
   用于当前升级。精确 M9 链还必须包含覆盖四张桌台业务表的
   `m9-table-business-v1`，Restore Record 必须记录 `m9_table_content_matches=true`
   且摘要完全相同；M8 及更早链出现该 M9 证据也应 fail closed。
5. 比较 Schema/诊断摘要、完整图片 manifest 和预先冻结的业务抽样；启动只读应用 Smoke。
   聚合行数不能替代版本化内容摘要。
6. 记录恢复耗时和恢复点。恢复验证失败时不得继续迁移。
7. 备份器必须按精确 Aerich 链恢复常驻服务：M7/M8 不启动尚无桌台表的
   `table-sweeper`；M9 必须先证明 sweeper 健康，并把它与 App/Nginx 一起纳入停写和
   恢复健康检查。未知链或进入停写窗口期间版本变化必须拒绝，不得通过放宽健康检查绕过。
8. 当且仅当备份器在停写前读到精确 M0–M7 链时，它的内部 App 恢复分支才允许
   2026-09-08 旧 M7 镜像的冻结命令形状缺少 `--no-access-log`。停写后的链必须与运行中
   快照相同，恢复 `app-up` 还必须第二次读到精确 M0–M7，并且该分支不得启动
   `table-sweeper`。普通 `app-up`、M8/M9 Backup 和任何其他命令变体仍必须严格要求
   `--no-access-log`；这不是可供人工传入的通用兼容开关。
9. M9 数据后异机加密副本在 export 前与解密 verify 时都必须重新校验精确
   Aerich 链、M7/M9 内容摘要、Restore match 布尔值和摘要一致性。只校验
   AES-GCM/Bundle 或两个来源 Artifact checksum 会将语义不合格的 Restore Record
   原样固化，不是可接受的灾备证据。

版本化摘要的 20 表 dump 与 `bead_colors` 投影是两次顺序读取，MySQL 内容与图片归档也
不在同一个跨系统事务中。其一致性依赖所有写入方停止：M7/M8 为 App/Nginx，M9 还包括
`table-sweeper`；同时不得存在直接 SQL、其他迁移进程或宿主图片旁路写入。不能满足时
保持 No-Go。

### 4.3 数据库迁移

以下是 M7→M8→M9 已由仓库候选固化的验收顺序，不是可以人工拆跑的现场命令。该
`--source-version 7` 路径已修复独立只读代码审查发现的 replay 停服复验缺口，修复后
复核无未解决 P0–P3；结论已绑定 head `fa6fce05...` / Run 34281512196 的干净远端 8/8。
历史 M8 SHA 的完整 updater 一次性 MySQL 已通过；当前 M9 SHA 必须重新通过完整 updater，
并且 Gate A 的只读状态、新 Backup/Restore、目标 Image 与当次持久写入授权全部绑定后，
才可执行。截至本文更新，这些外部门槛尚未关闭，本节仍为 **BLOCKED / NOT AUTHORIZED**。

1. 再次核对连接身份、目标 Schema、当前版本和备份 ID。
2. 停止 App/Nginx 的业务写入，并要求 `table-sweeper` 不在运行（M7 未创建容器可接受）；
   证明无活跃写请求，MySQL/Redis 保持受控可用。
3. 当前真实 Aerich 必须精确为 M0–M7；确认 Schema、21 表
   `m7-preserved-business-v1`、当次完整图片 manifest 必须与 Backup/Restore 一致；不得把
   历史环境的图片总数写死为当前基线。
   接着在仍停写状态执行 raw M7 source preflight：`swatch_hex` 列必须为 0；221 条
   slot/code/name/URL/sort/active 必须逐槽等于冻结 manifest；221 张预期兼容 PNG 必须
   为普通非软链接文件、SHA-256 精确且权限 `0644`。额外 Product 图片可以保留，但已经
   由完整 manifest 绑定。未知、缺口、重复、部分 M8 或不一致时在 M8 任务前停止；不得
   退回 M2 路径。
4. 只通过受保护编排调用 M8、M9 单步原语，记录开始/结束、退出码、前后 Aerich/Schema 摘要
   和候选身份。不得 `--fake`、直接改 Aerich 表、手工补列或把 downgrade 当回滚。
5. M8 DDL 可能出现物理 `swatch_hex` 已提交而 Aerich 仍为 M7 的部分状态。发生任何失败
   立即保持 App/Nginx 停止并保存 evidence；由授权人选择经 Review 的精确前滚修复或从
   当次已验证 Backup 恢复，禁止盲目重跑。
6. 核验最终 Aerich 精确为 M0–M9；`swatch_hex` 为 nullable `VARCHAR(7)`，221 个槽按
   `slot_no` 与冻结 manifest 逐项相等且值唯一。code/name/active/URL/sort、商品颜色启用/
   库存、Order/Inventory/Wallet/Reservation/Audit 等 21 表内容和既有时间戳边界不得
   出现未批准漂移；重新计算的 `m7-preserved-business-v1` 必须与停写源完全相同。升级器
   到此只证明内容零漂移，不把独立语义对账伪装成内部步骤。
7. 由受控编排调用 publisher 的精确 no-op 分支，确认 221 张兼容 PNG 内容、权限、路径
   与 M7 基线逐项相同且无需创建；不得脱离编排单独运行 publisher，不改变商品状态，
   不转换或删除 PNG。
8. 执行 30 桌 bootstrap 并立即 replay；核验仅有 T01–T30、display name 精确为
   `T01号桌` 至 `T30号桌`、每桌一个不可预测且唯一的 32 位字母数字 Token。立即运行
   只读 table reconcile，其 `open_sessions`、`occupancies`、三类异常、`scanned` 和
   `violations` 计数必须全部是精确整数零；保存 sweep 前 SQL 空表 invariant，再运行
   table sweep 并要求结果精确为 `{"status":"ok","closed":0}`，最后重算 sweep 后的同一组
   SQL invariant。不得把 Token 写入日志、URL 访问日志、CI artifact 或交付报告。
9. 只在全部检查通过后写入绑定 source/target SHA、Image ID、M7→M8→M9、Backup ID、HEX/
   图片 manifest、21 表内容摘要、30 桌摘要、reconcile/sweep 精确结果和复核时间的新
   upgrade Record；evidence 同时保存两个任务的 result 与前后 SQL 摘要，Record 以 SHA-256 绑定
   evidence。该 Record 不包含 `wallet_reconcile` 结果。保持 App/Nginx/`table-sweeper`
   停止，以与成功 apply 完全相同的 source version/SHA/Backup ID 立即重放 upgrade plan；
   它必须验证 evidence 路径/哈希、当前最终 DB、图片 manifest、M7 内容摘要、Record/evidence
   内已绑定的 reconcile/sweep，以及 live SQL 空表 invariant；再次运行只读 MARD preview 和
   table reconcile，两者都必须为精确 no-op/零差异。plan replay 不重跑可能关闭会话并写库的
   table sweep。只有返回 `already_current=true` 并生成不可覆盖 replay sidecar 才可紧邻执行
   `app-up`；`app-up` 会验证 sidecar 对 upgrade/evidence 的 digest 绑定、重读 live M9
   Aerich/静态 Schema 摘要并再次运行 table reconcile，但仍不重算图片 manifest、M7 内容
   摘要或 MARD preview。
   启动后必须先完成本节的 M9 admin-assisted acceptance 与 target resilience，再创建新的
   M9 数据后 Backup/Restore。当前 M7 的 `20260908t021224z` 不得冒充 M9 数据后证据。

迁移失败后立即停止应用写入和后续步骤。先记录真实 Schema/Aerich 状态，再由授权人选择前滚修复或从已验证备份恢复；不得盲目重跑、fake 版本或直接 downgrade。

### 4.4 应用部署与运行时验证

1. 注入已冻结的非 Secret 配置和受控 Secret；验证 `APP_ENV=production` 语义、`APP_DEBUG=false`、MySQL、Redis 和图片持久化。
2. 启动后端，先验证 liveness，再验证包含 MySQL/Redis 的 readiness。
3. 验证启动失败不会泄漏连接串或凭据；Redis 不可用时实例不接收业务流量。
4. 执行管理员幂等 bootstrap，保存审计证据并按流程处置初始凭据。
5. 执行 API Smoke、图片上传/读取、日志检索和优雅停止/再次启动。

#### 4.4.2 已执行的 M7 综合代表性测试数据（历史检查点）

本节保留 2026-09-08 建立当前 M7 综合数据时使用的受控流程，结果已由 M7 报告关闭。
M8 不新增代表性业务数据，不得为 M7→M8 重跑本节或重新开启密码注册；当前合成数据只
作为迁移前后不漂移和 HEX/API 验收样本。

M2 历史代表数据只证明 User/Product/Order/Inventory 的旧链路；M7 持久升级通过后，
仍需为 Wallet/Payment/Refund、自选颜色 Kit 和 Reservation 建立可供 Gate A 人工验收的
合成数据。先保持微信 Provider 与充值开关关闭；仅在 M4 backfill、legacy settlement
backfill、`wallet_reconcile`、扩展 MySQL 门槛和当前候选升级 Record 全部通过后，显式
开启以下内部 Gate A 能力并重建 App：

```dotenv
WALLET_ADMIN_WRITE_ENABLED=true
WALLET_ORDER_PAYMENT_ENABLED=true
WALLET_REFUND_ENABLED=true
WALLET_TOPUP_ENABLED=false
PAYMENT_PROVIDER=disabled
PASSWORD_REGISTRATION_ENABLED=true
```

开关切换必须先备份 `config.env`，重建后复核 production Settings、四项 Healthy、唯一
`127.0.0.1` publisher、liveness/readiness、六个开关的 PID 1 实际值，以及微信充值/支付
仍为 503。`PASSWORD_REGISTRATION_ENABLED` 只为创建合成账号临时开启；成功保存随机凭据
并确认所有合成会话撤销后必须恢复为 `false`、重建 App 并再次核验注册被拒绝，其他三个
内部钱包开关按 Gate A 人工验收计划保留。随后对当前 M7 候选创建新的 Backup 并完成独立
无端口 Restore；不得复用升级前 M2 Backup。把已经通过当前远端 CI 的 Operations commit
安装为单独版本化 Release 并保留 `.source-sha` 与 `.ci-run-id` sidecar，再从该目录执行：

```bash
sudo python3 -B -m scripts.release.gatea_m7_representative_data \
  --super-admin-username '<current-super-admin>' \
  --confirm-super-admin-username '<current-super-admin>' \
  --backup-id '<current-m7-backup-id>' \
  --confirm-backup-id '<current-m7-backup-id>' \
  --apply
```

当前 SUPER_ADMIN 密码只经 TTY 隐藏双输入，不放入参数、环境、文件或 Record。工具会创建
三个合成账号和覆盖 M3–M7 的聚合场景；其随机密码只保存在
`/srv/pinkdoohub/gatea/records/representative-data/gatea-m7-synthetic-credentials.json`
（`root:root 0600`）。成功后必须再次执行 `wallet_reconcile`、新 Backup/独立 Restore、
数据库/图片摘要和日志 Secret 扫描。工具由多次正式 API 请求组成，不是跨请求单事务：
任何中断或失败都保留 `.pending` 凭据与现场，立即停止后续写入并从该次已验证 Backup
恢复；禁止删除失败现场、手工补行或直接重跑。

历史 M2 环境已验证 dependency-free liveness、DB/Redis dependency-aware readiness、
故障摘流量/恢复、Bootstrap 和凭据处置；M7 镜像随后已在升级后的持久环境重新验证。
这些结果不能直接关闭 M9 候选项目。

#### 4.4.3 M8 HEX/gzip、M9 桌台计时与数据后恢复验收

只有 §4.3 的 M7→M8→M9 成功 Record 已生成、独立复核，并在同一无旁路写入的停写窗口完成
紧邻 `plan-replay`（`already_current=true` 和不可覆盖 sidecar）后，才允许启动目标
Runtime。单有 Record 不够：`app-up` 会重读 live M9 静态 Schema、运行 table reconcile
并复验 Image ID，但图片 manifest、M7 内容摘要和 MARD preview 仍只由紧邻 replay 重新
证明。验收必须至少包含：

1. MySQL、Redis、App、`table-sweeper`、Nginx 五项服务 Healthy，liveness/readiness 为 200，
   唯一 publisher 仍是批准的 loopback
   边界；运行镜像 revision、配置和 upgrade Record 精确绑定目标 SHA/Image。
2. 管理目录和公开 Online 自选色 Kit 均按冻结 manifest 返回规范大写 HEX；公开 221 色
   无 null/非法/重复值，code/name/URL 与 M7 基线不变。小程序开发者工具可以验证
   `backgroundColor` 与零数字色块 PNG 请求，但不能替代 iOS/Android 真机。
3. 对大于等于 1 KiB 的 JSON 分别以有/无 `Accept-Encoding: gzip` 请求：压缩响应只出现
   一次 `Content-Encoding: gzip`、可解码、正文语义一致，并包含缓存所需的 `Vary`；小于
   阈值的文本保持未压缩。通过 Nginx 时还要证明上游已编码响应没有被二次压缩。
4. 请求一张现有 PNG、一张 Product JPEG/WebP（若样本存在），确认图片 MIME 不被 gzip；
   221 张兼容 PNG 的数量、权限和 checksum 与 M7 Backup 一致。Brotli 不属于本候选。
5. 先执行 `gatea_m9_acceptance` 默认只读 plan；它必须在读取 TTY 或业务写入前绑定精确
   M7→M9 upgrade/replay、同 SHA/CI Run 的 Operations、旧 M7 代表数据/合成凭据、五服务、
   feature flags、30 桌且无 Session/Timer/Occupancy 历史的单次基线，并运行零差异
   wallet/table reconcile。plan ready 后才执行一次 `--apply-admin-assisted`；SUPER_ADMIN
   username/password 只能从 `/dev/tty` 隐藏双输入，禁止参数、环境和 stdin。
   v3 apply 必须在首次登录、因而也在首个 RefreshSession 可能产生之前，先持久写入
   `authentication_started` checkpoint。只有本次刚创建 journal、尚无已知会话或业务副作用，
   且首次管理员登录精确返回 HTTP 400/业务码 `1003` 时，才可删除这个无副作用 journal 后
   重新输入密码；连接/响应不确定、角色或响应异常、旧 v2 journal、任一会话 cleanup/revocation
   证明不完整均保留 pending 并 fail closed。同一 v3 命令也只有严格身份/确认值一致且
   checkpoint 允许时才可恢复自己的 pending。
6. admin-assisted 闭环只经正式 loopback API 建立 60/60/120 分钟三个 Option、小额 Kit 和
   `quantity=2/1/1` 的 Experience+Kit 混合订单，验证匿名桌码解析、Claim/payment/release
   幂等、15 分钟 deadline、两个时长 Timer 各加 10 分钟、同长合并、异长分开、quantity
   不乘时长、Kit 排除、管理员可见、sweep/table+wallet reconcile；随后必须通过管理 API
   下架 Experience/Kit 并二次读回为 offline，再完成日志脱敏和双会话注销。
   当前持久脚本只使用 wallet 支付；manual、等待 15 分钟自然超时以及取消/完成/退款释放
   不写入该 success Record，继续由当前 SHA 的 CI/MySQL 自动化证据覆盖。若决策人要求这些
   行为也作为 live Gate A 证据，应另立经 Review 的人机步骤，不得手工把布尔值补成 PASS；
   真实微信支付仍是独立项目。
7. acceptance 成功后以两项 acceptance 绑定参数运行 M9 `gatea_resilience` 的 `--apply`，重跑
   数据库/图片/日志验证及 MySQL/Redis 依赖恢复和 App 重启。它必须先从精确 Aerich 链
   选择服务集：M2/M7/M8
   恢复并验证 MySQL/Redis/App/Nginx 四项，M9 额外包含 `table-sweeper` 共五项，未批准链
   直接拒绝。对 M7→M9 upgrade Record，默认自动选择并校验与 source SHA/Image 绑定的
   `gatea-m7-representative-data-<source-sha>.json`；不得用目标 SHA 伪造新代表数据。演练
   前后必须比较完整数据库摘要、图片 manifest 和版本化内容摘要：M7/M8 使用
   `m7-preserved-business-v1`，M9 同时使用它与 `m9-table-business-v1`。Record 只保存
   profile/digest，任何未解释漂移都阻断。M9 调用还必须显式传入 acceptance Record 与
   人工确认 SHA-256；工具在演练前和 success 发布前冻结并重验文件身份、sidecar 为空、
   candidate/Image、Operations/CI Run、upgrade/replay、代表数据/凭据、五服务、attempt
   digest 和完成时间，且 resilience 开始时间不能早于 acceptance 完成时间。M9 成功
   Record 使用 schema v2 并直接保存 acceptance Record digest、attempt digest 与完成时间；
   M2/M7/M8 legacy 四服务 Record 继续使用严格 schema v1，二者不能互换。CLI 默认 guarded
   acceptance 目录为 `/srv/pinkdoohub/gatea/records/m9-acceptance`，Record 必须位于该目录；
   若使用另一受控目录，必须显式提供 `--acceptance-record-dir`，且两者规范路径必须精确相同，
   禁止扫描一个目录却消费另一个目录的 Record。resilience success 本身也经随机临时文件、
   file `fsync`、hard-link no-clobber 和目录 `fsync` 发布；final 已可见后的合法收口只做两次
   live 一致性复验，并至多清理一个严格同 inode/内容/身份的 writer temp，不重跑故障演练。
8. 在成功运行状态先证明 `table-sweeper` 健康，再把它与 App/Nginx 一起停止并创建新的
   M9 MySQL/图片 Backup；成功后必须恢复三者健康，并完成独立无端口 Restore、空 Redis、
   Restore App readiness、包含 acceptance fixture 的完整图片 manifest、30 桌聚合和
   `m9-table-business-v1` 四表内容摘要核验；Restore Record 还必须绑定 Backup Record、
   MySQL artifact、image artifact 三个 digest。acceptance 后的图片
   数量应精确等于验收前完整 manifest 数量加 5；resilience 自身必须证明演练前后 manifest
   未变，`finalize` 还会要求其 `image_file_count` 等于这份数据后 Backup 的完整
   `image_manifest` 长度，且 M7/M9 内容摘要相等。随后以 acceptance、
   resilience 和这组数据后 Backup/Restore 的路径/哈希调用 candidate `finalize`，最后再按
   既有 AES-256-GCM/RSA-OAEP-SHA256 流程生成并立即解密复核异机副本。M9 检查点只能引用
   这组新 Record。`finalize` 还必须显式或按 canonical 默认绑定 acceptance/resilience 两个
   guarded 目录，并只接受父目录相等、`nlink=1` 且无 publication temp/alias/sidecar 的已
   收口 resilience final；candidate 不替上游删除这些残留。

```bash
# 两条命令都从已安装 target Release 目录执行；第一条零业务写入。
sudo python3 -B -m scripts.release.gatea_m9_acceptance
sudo python3 -B -m scripts.release.gatea_m9_acceptance --apply-admin-assisted

acceptance_record=/srv/pinkdoohub/gatea/records/m9-acceptance/gatea-m9-runtime-acceptance-<target-sha>.json

sudo python3 -B -m scripts.release.gatea_resilience \
  --runtime-acceptance-record "$acceptance_record" \
  --confirm-runtime-acceptance-record-sha256 <acceptance-record-sha256> \
  --apply
```

Success Record 固定为
`records/m9-acceptance/gatea-m9-runtime-acceptance-<target-sha>.json` 且不可覆盖；它只保存
schema v1（与 schema v3 pending 独立），并保存绑定 digest、脱敏内部 ID/Session 哈希、
聚合断言和清理布尔值；Payment ID、Payment No SHA-256 与 `succeeded_at` 必须和 pending
payment evidence 精确相等，不保存原始 Payment No。成功路径先将完整 JSON 写入
同目录随机 `0600` 临时文件并执行 file `fsync`，再以 hard-link no-clobber 发布 `.complete`
和同步目录；随后把 `.json.pending` 持久提交为 `verified/failure=false`，再以 hard-link
no-clobber 发布最终 Record。只有最终 Record 已同步后才删除 pending 与 `.complete`。合法
崩溃续跑会先精确清理安全的 writer temp，再严格匹配三者及全部业务绑定，且只完成发布
收口，不得重复调用业务 API。失败
路径会尽力取消未支付订单或 release 已开 Session、将已创建 Product 收口为不可售并注销
会话；它不会删除已提交付款/fixture、不会恢复 source 卷。成功路径保留 paid Order、closed
Session、五张新图片及库存/钱包变化用于数据后证据，但 fixture Product 必须为 offline；
不满足上述 v3 严格恢复契约的 pending、清理不完整或非空旧基线都必须人工审计并保持
No-Go，禁止删 Record 后重跑。

上述服务端 PASS 仍不关闭真实 HTTPS Origin、微信合法域名、release-eligible RC 或真机
矩阵，也不授予体验版上传、分发、提审或公开发布权限。

#### 4.4.1 SUPER_ADMIN Bootstrap 安全执行

人工执行时优先使用 TTY 隐藏双输入，命令行不出现密码：

```bash
python -m app.tasks.super_admin_bootstrap \
  --username <synthetic-username> \
  --nickname <synthetic-nickname> \
  --phone <synthetic-phone> \
  --apply
```

非交互部署只允许 Secret 系统短期注入 `PINKDOOHUB_BOOTSTRAP_PASSWORD`；不得在 shell 命令、`.env`、日志、截图、报告或 CI artifact 中填写真实值。命令必须在已迁移数据库上运行，不会自动建表。演练依次验证：首次结果 `created=true`；数据库只有一个正常 SUPER_ADMIN 和一条自指向 `BOOTSTRAP_SUPER_ADMIN` Audit；相同四项身份/密码重放为 `created=false/replay=true` 且 `updated_at`、密码哈希和 Audit 数量不变；不同输入、普通用户占用、禁用状态和审计矛盾均拒绝。最后完成真实登录、初始凭据轮换/撤销记录，再移除命令进程 Secret。

### 4.5 微信体验版与真机验证

1. 仅取同一 CI run、同一 Git SHA 的 `weapp` artifact；不得在开发者电脑二次修改。
2. 核对 API Origin、AppID、主包/分包大小、source map 策略和产物 Secret 扫描。
3. 取得外部上传授权后才上传体验版，并记录微信版本号、备注、上传人和时间。
4. 在 iOS/Android 真机验证 request/upload/download、登录、图片、弱网、断网和 unknown 结果。
5. 按验收矩阵执行最小纵向链路，记录设备、基础库、网络、环境和结果。

## 5. Smoke 最小集合

- Guest：冷启动、Product 列表/详情、登录入口；
- 普通用户：登录、Cart、创建 Experience/fixed/color/mixed Order、订单详情、Pending
  取消、会员余额/流水、合成余额支付、预约创建/列表/详情/取消；
- ADMIN：订单 Paid/Completed、Product/221 色/图片、fixed/颜色 Inventory、Wallet 客户
  查询/调账/多颜色代客订单/退款、预约确认/拒绝、单日与固定店休、Audit、用户列表；
- SUPER_ADMIN：初始化后登录、角色边界、用户禁用；
- 安全边界：普通用户调用管理 API 为 403，被禁用用户旧 Token 失效；
- 运行边界：Token 刷新、弱网、断网、请求结果未知、重复点击、图片上传中断；
- 数据断言：订单金额/颜色/重量快照，fixed/颜色库存扣减/取消/PAID 退款恢复，钱包
  余额链与 Payment/Settlement/Refund，预约状态/店休历史，幂等重放和审计顺序一致；
- 诚实能力边界：真实微信充值/支付/退款仍返回 503 零写入，Reservation N1 不显示
  主动通知或自动容量已实现；
- 视觉回归：会员缺省头像小屏/大字体居中，代客多颜色手机六列/宽屏十列可操作。

完整场景及证据等级以 [wechat_acceptance_matrix.md](wechat_acceptance_matrix.md) 为准。

## 6. 前滚、恢复与停止条件

优先停止并进入 No-Go 的条件包括：

- 目标身份不清、疑似连接共享/生产资源或备份未验证；
- 迁移、Schema、库存、订单或审计发生无法解释的漂移；
- readiness、Redis、图片持久化或管理员初始化失败；
- 越权、凭据泄漏、数据破坏、重复订单/扣库存或无法恢复；
- artifact 与已测试 SHA 不一致；
- 全局 operation lock 缺失安全元数据、被另一未知操作占用，或全候选 inventory 中任一
  candidate pending / acceptance pending/complete（含畸形或非普通项）不能由原命令按
  严格身份、确认值和 checkpoint 契约恢复；
- 当前远端 CI 未达现行 required Jobs，或 MySQL snapshot 未精确覆盖 M0–M9；历史 head
  `62b1b15...` / Run 34288613644 只满足 M8，当前 M9 业务 SHA 必须重验；
- M7→M8→M9 候选没有与当前身份绑定的 disposable 完整 updater 证据，持久候选
  upgrade Record 缺失，或试图对当前 M7 Gate A
  使用空库 `initial-migrate`、省略显式 source 选择、退回默认 M2 路径或直接运行内部原语；
- 新 M7 Backup/Restore 缺少或不匹配 `m7-preserved-business-v1`，raw source preflight
  发现部分 M8、色卡/PNG 漂移，或成功 Record 后未在 `app-up` 前完成紧邻 live replay；
- Backup/Restore Record 被覆盖、Restore 未绑定当前 Backup Record/MySQL/image 三个 digest，
  或 M9 数据后 Backup 早于 acceptance/resilience；
- 停写窗口内存在或无法排除直接 SQL、其他迁移进程、容器外脚本或宿主图片旁路写入；
- wallet reconcile 非零差异，HEX/图片 manifest 不一致，或试图对已有 Online 自选色
  商品独立运行 publisher、临时改商品状态、转换/删除兼容 PNG；
- gzip 无法解码、重复编码、缺少正确 `Vary`，或图片被错误压缩；
- 30 桌编号/display name/Token、M9 四表约束、15 分钟支付边界、分组计时加 10 分钟、
  table sweep/reconcile 或敏感 Token 脱敏任一不匹配；
- M9 admin-assisted acceptance 不是一次性空 Session 基线、无法安全读取 TTY、清理/登出
  不完整、resilience 没有显式绑定其路径与 digest，或 `finalize` 初次执行/commit point 前
  发现 `current` 不再指向 source；commit
  point 后又没有严格匹配且至少处于 `live-rechecked` 的 own pending，或任一证据哈希/时序
  不匹配；
- 微信真机无法通过 HTTPS 或合法域名访问。

Inventory downgrade 会删除流水结构并可能丢失新版本运行后的历史，不是常规无损回滚。一旦新版本开始写数据，首选停写、保全证据和前滚修复；从备份恢复只由授权人决定，并明确恢复点之后数据的处置。

## 7. 演练记录模板

```text
演练 ID：
日期/窗口：
Git SHA / artifact checksum：
环境与资源所有者：
执行人 / 复核人 / 决策人：Yijie Shen（实际执行时分别确认时间）
场景：DR-01 ... DR-14
迁移前/后 Aerich 版本：
备份/快照 ID 与恢复验证：
步骤、开始/结束、退出码、证据链接：
Smoke 结果：
发现的问题与风险 ID：
决策：Go / No-Go / 前滚修复 / 批准恢复
清理与复核：
```

证据只引用受控日志、报告、截图、checksum 和 CI run，不粘贴 Secret 或个人信息。

## 8. 资源回收清单

无论成功、失败、取消或超时，执行人都必须：

- 优雅停止本次启动的 Uvicorn、测试进程、代理、隧道和 watcher，并按 PID/进程树复核；
- 停止本次专用容器/数据库/Redis，检查端口已释放；
- 删除仅属于本次演练且已批准删除的临时目录、合成数据和短期 artifact；
- 保留受控证据和已批准快照，不删除共享缓存、用户文件或来源不明资源；
- 对故意保留的环境记录资源 ID、用途、所有者、到期时间和停止方法；
- 把不能安全清理的残留、原因、风险和精确处置方式写入演练报告。
