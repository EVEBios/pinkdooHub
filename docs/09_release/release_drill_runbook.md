# 微信 Gate A 隔离发布演练 Runbook

> **Status:** M2→M7 persistent/server drill passed；M7→M8 complete updater passed on GitHub-hosted disposable Linux；persistent M8 execution remains blocked
> **Last Updated:** 2026-09-09
> **Scope:** 微信小程序内部测试版（Gate A）

本文定义 Phase 9.3 的安全执行顺序、证据和失败处置。它不是生产操作授权，也不包含任何真实连接信息。首次实际演练必须在专用、可销毁、与共享环境隔离的 MySQL 8+、Redis 和图片存储中执行。

2026-08-31 的已执行报告只证明当时 M0–M2 候选。当前迁移链已经扩展到 M8，功能面
增加 M4 Wallet/Payment/Refund、M5 Reservation N1、M6 自选颜色 Kit 和 M7 可配置
固定店休；M8 又增加正式 HEX 与文本压缩。旧报告、旧工具输出和旧候选迁移 Record
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
一次性 updater 缺口已关闭，持久 Gate A M8 仍未执行。

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
| DR-01 | 全新空库 0→当前 | 当前要求为精确 0→8，并核验 M3–M8 表/约束/索引/默认数据/HEX | 一次性 MySQL Job 与 Run 34288613644 完整 updater PASS；持久 Gate A 仍为 M7 |
| DR-02 | 迁移 0 代表性数据升级 | 用户、Product、Audit 等数据保持；当前候选必须继续到 M8 | 一次性 0→8 和完整 M7→M8 代表数据演练 PASS；持久 Gate A 的 M2→M7 历史 PASS，M7→M8 NOT RUN |
| DR-03 | 历史版本代表性数据升级 | M5 fixed/Reservation 样本经 M6→M7→M8，已有数据不漂移 | M6→M7→M8 迁移步骤与 GitHub-hosted M7→M8 21 表内容保护 PASS；持久 M7→M8 NOT RUN |
| DR-04 | 备份并恢复到新实例 | Schema、关键行数、抽样聚合、登录和启动均通过 | 持久 M7 Backup `20260908t021224z`/独立 Restore/加密异机副本 PASS；一次性 M7 `20260908t230214z` 和 M8 `20260908t230329z` 同 ID Restore PASS |
| DR-05 | 可控迁移失败 | 识别实际部分提交状态；按批准方案前滚或从已验证备份恢复 | 历史 M2 PASS；M8 的“列已提交/Aerich 仍 M7”处置待 M7→M8 入口验证 |
| DR-06 | 应用与依赖 | FastAPI/Uvicorn、MySQL、Redis、图片、liveness/readiness、优雅重启通过 | 当前 M7 Runtime 候选级韧性 PASS |
| DR-07 | 管理员初始化 | 一次性、幂等、可审计地建立首个 SUPER_ADMIN；重复执行无第二账号 | 历史 Bootstrap PASS；当前账号登录、轮换密码和会话撤销在 M7 Seed 重验 PASS |
| DR-08 | 微信真机网络 | request/upload/download、证书、Token、图片和错误信封通过 | BLOCKED：备案/Origin/RC |
| DR-09 | Gate A 纵向 Smoke | 旧最小链路加 Wallet、颜色 Kit、Reservation、M7 和最新界面 | 当前服务端 82 请求及数据聚合 PASS；真机界面继续属于 DR-08 |
| DR-10 | M4 钱包补齐与对账 | wallet/legacy preview 与冻结上界 apply、二次 preview、只读 reconcile 全零差异 | 持久 Gate A PASS；综合数据后复核 `4/0/0` |
| DR-11 | M5 Reservation | 预约四状态、单日店休、隐私、并发/1205/1213/索引与历史数据 | MySQL 门槛与 Gate A 六预约聚合 PASS；真机待 DR-08 |
| DR-12 | M6 颜色目录与库存 | M5 fixed 重放到 M6/M7；221 槽/列/FK/索引；持久图、商品启用色/库存与 HTTPS | MySQL/持久图/三启用色/库存/Backup 已 PASS；HTTPS 真机待 DR-08 |
| DR-13 | M7 固定店休 | 单例/默认周一/唯一约束，历史预约/单日店休不漂移，更换的事务/锁序/批量取消 | 一次性/远端 MySQL 与持久 Gate A 结构/聚合 PASS；真机待 DR-08 |
| DR-14 | M8 HEX 与 gzip | `swatch_hex` 221 项精确/唯一，目录与图片零漂移；API/小程序直绘；文本只压缩一次、图片不压缩 | 一次性 updater Runtime 221 HEX、63,445→10,948 bytes gzip、PNG 不压缩 PASS；持久 M7→M8、Gate A HTTPS Runtime 与真机 NOT RUN |

对当前最后留证为非空 M7 的 Gate A，以及未来任何需要接管的既有数据库，都必须先执行
只读审计，确认 Schema、Aerich 版本、数据质量、图片 manifest 和备份；未审计的库不
自动成为“受支持升级起点”。

历史 M2 执行的 SHA、CI、结果、耗时、修复项和资源清理记录见
[Phase 9.3 隔离发布演练报告](reports/phase93_rehearsal_2026-08-31.md)。该报告不修改，
当前候选的每次新执行必须另建独立报告并列出 DR-01～DR-14 的适用/不适用项。

M7 的本地可销毁迁移与联合门槛见
[M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)。该报告运行于提交前
dirty 工作树；同内容随后成为提交 `58d8435...`，并随 head `4d6430c...` 在
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 取得远端
8/8。远端证据见 [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)，但仍不包含
持久部署、备份恢复、应用/图片/Redis Smoke 或微信真机，因此不能把 DR-01～DR-14
整体标成 M8 候选 PASS。M8 的远端身份、首轮失败与修复、8 Job/artifact 见
[M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。

### 3.1 当前 M4–M8 证据分层

| 版本 | 仓库/历史事实 | 当前候选一次性 MySQL | 持久 Gate A 必需动作 |
|------|---------------|----------------------|----------------------|
| M3 | 外部身份与认证安全仓库实现完成 | M8 workflow 保留 M3；当前 Run 34281512196 远端 8/8 | 持久 Gate A 已应用；仍保持 password 模式 |
| M4 | 钱包/支付/退款代码完成 | Wallet `9 passed`、三域联合 `30 passed`；当前 M8 workflow 远端 success | 持久 Gate A 已应用，两个 backfill/reconcile 已零差异 |
| M5 | Reservation N1 完成 | 历史/当前 MySQL workflow 均通过 | 持久 Gate A 已应用；已有预约/单日店休继续作为 M8 不漂移基线 |
| M6 | 221 色目录、商品颜色库存和兼容 PNG 完成 | M6 snapshot/锁等待及 M8 迁移重放通过 | 持久 Gate A 已发布 221 色/PNG 与三启用色；M8 不得改这些事实 |
| M7 | 固定店休完成 | 单例/约束/并发及 M6→M7→M8 远端步骤通过 | 当前持久成功点；作为 M8 唯一允许规划的 source 起点 |
| M8 | HEX/API/小程序直绘/gzip 仓库实现完成；显式 M7→M8、21 表内容保护与 Online exact no-op 已实现 | 基线 0→8/Run 34242753255、加固 Run 34281512196，以及 head `62b1b15...` / Run 34288613644 的 GitHub-hosted 完整 updater 14/14 均 PASS；后者含双 Backup/Restore、221 HEX/gzip/PNG 和零残留 | NOT RUN；持久 Gate A 仍须当次只读预检、新 Backup/Restore、精确目标/窗口/写授权与数据后恢复 |

任何“一次性 MySQL PASS”只关闭候选迁移实现风险，不等于已应用 Gate A。任何本地
SQLite 数据也只属于开发环境，不是 Gate A 的数据或图片发布证据。

## 4. 执行顺序

### 4.0 本仓库自动化入口

当前 CI 另有 `scripts/ci/gatea_m7_m8_drill.py`，用于在 GitHub 托管的一次性 Ubuntu
Runner 上自动复现完整 M7→M8 updater。它与下方历史 Phase 9.3 工具分离：source 为冻结
M7 Runtime，target 为本次 checkout，顺序包含 source 数据/221 PNG、Backup/独立
Restore、M8 plan/apply/停服 replay、target app-up、221 HEX/gzip/PNG Runtime，以及
M8 数据后 Backup/Restore。`run` 内部和 workflow `always()` cleanup 均会精确回收固定
Compose/restore 资源与两张任务镜像；Artifact 只接收脱敏白名单，并且只有 cleanup 后
重新签发的最终安全扫描 marker 存在时才上传。

Workflow 总闸为 60 分钟；主体由 40 分钟进程组 watchdog 约束，独立 cleanup 最多 8
分钟。不得删掉内层 watchdog 或让它等于总闸，否则 Docker/Restore 卡死时可能没有补偿
清理和安全证据时间。

该入口必须拒绝本机、self-hosted、共享 Docker 或已经存在 Gate A 固定卷/网络/容器的
环境；不得为了复用它而放宽 guard。它通过后只关闭 disposable Linux 的 updater 复现
缺口，仍不授权持久迁移、Runtime 切换、真实 Origin/TLS、微信上传或真机操作。

实际执行记录：head `62b1b15...` / merge-ref `a9ff3d2...` 的
[Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) 已完成
14/14 阶段，source Backup/Restore ID 为 `20260908t230214z`，target Backup/Restore ID
为 `20260908t230329z`；221 HEX、63,445→10,948 bytes gzip、PNG 回退、20 文件
artifact 白名单/Secret 扫描和零残留均通过。这是一次性入口的已执行
证据，不是持久 Gate A 记录。

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

历史演练不能直接承担当前 M7→M8；仓库候选已新增精确入口，但仍不是持久执行授权：

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
2. M7/M8 Backup 必须带 `m7-preserved-business-v1`：20 个非 `bead_colors` 表的稳定顺序
   data dump 加该表 M7 字段投影，共覆盖 21 个业务表；独立 Restore、停写源和最终态都
   重算精确 SHA-256。Aerich 链与完整图片 manifest 另行比较，旧聚合仅作诊断；
3. 停写源与 Backup 对齐后、M8 原语前，raw preflight 要求 `swatch_hex` 列为 0，221 条
   M7 slot/code/name/URL/sort/active 逐槽等于冻结 manifest，221 张预期 PNG 为普通非软
   链接文件、checksum 精确且权限 `0644`；
4. 入口按真实 Aerich 版本逐步升级，保存每步 Schema/数据摘要，失败时保留现场，并在
   全部核验通过后生成新的 candidate upgrade Record；
5. Gate A 221 色发布原语接入受控流程：M2 路径可按 preview、显式 checksum apply、
   MySQL 事务、持久图片原子发布/补偿、幂等重放和 HTTPS URL 核验留证；M7 路径则要求
   preview/apply/replay 全部为精确 221 项 no-op；
6. 失败保留脱敏 evidence 和停止状态，成功 Record 可重放；输出不含 Secret、PII 或
   幂等键。成功后继续停写，并在 `app-up` 前紧邻重放同一 upgrade plan；重放会验证
   evidence 哈希、live DB、图片 manifest、21 表内容摘要和只读 MARD preview。`app-up`
   只校验 Record 与 target SHA/Image ID/迁移组合，本身不执行这些 live 检查。

默认 plan 只读；apply 必须同时确认 source SHA、target SHA、Backup ID 与 MARD manifest
SHA-256。M7 起点必须显式选择，且 Record 同时绑定 `source_version=7`、精确 M0–M7 source
链和 M0–M8 target 链；只有 M2→M7、M2→M8、M7→M8 三种组合可被部署入口接受。新增
实现已由 head `fa6fce05...` / Run 34281512196 完成干净远端 8/8，后续又由
head `62b1b15...` / Run 34288613644 在专用一次性 Linux/MySQL 中完整运行。
这关闭了 disposable updater 门槛，不构成持久 Gate A 的目标冻结、当次只读预检、
新 Backup/Restore 或写授权。持久执行仍不得使用临时 SQL、删除旧 Record、
伪造 Record 或绕过保护逻辑。

候选镜像已提供 `app.tasks.gatea_migrate_step` 与 `app.tasks.gatea_wallet_prepare` 两个
内部执行原语：前者将 Aerich 限制为 M3–M8 单步前进，后者完成 M4 后双 preview、冻结
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

1. 对有数据场景创建一致性备份或快照，记录不可变 ID、开始/结束时间、工具版本和校验和。
2. 在新的隔离实例恢复该备份。
3. 对精确 M7/M8 链，Backup Record 必须包含 `m7-preserved-business-v1`：20 个非
   `bead_colors` 业务表的确定性 data dump 与该表 M7 投影，共 21 表；Restore Record
   必须重算同一摘要并记录 `m7_content_matches=true`。缺少此字段的旧 M7 Backup 不得
   用于当前升级。
4. 比较 Schema/诊断摘要、完整图片 manifest 和预先冻结的业务抽样；启动只读应用 Smoke。
   聚合行数不能替代版本化内容摘要。
5. 记录恢复耗时和恢复点。恢复验证失败时不得继续迁移。

版本化摘要的 20 表 dump 与 `bead_colors` 投影是两次顺序读取，MySQL 内容与图片归档也
不在同一个跨系统事务中。其一致性依赖 App/Nginx 已停止且没有直接 SQL、其他迁移进程
或宿主图片旁路写入；不能满足时保持 No-Go。

### 4.3 数据库迁移

以下是 M7→M8 已由仓库候选固化的验收顺序，不是可以人工拆跑的现场命令。该
`--source-version 7` 路径已修复独立只读代码审查发现的 replay 停服复验缺口，修复后
复核无未解决 P0–P3；结论已绑定 head `fa6fce05...` / Run 34281512196 的干净远端 8/8。
只有该 SHA 的完整 updater 一次性 MySQL 也通过，
并且 Gate A 的只读状态、新 Backup/Restore、目标 Image 与当次持久写入授权全部绑定后，
才可执行。截至本文更新，这些外部门槛尚未关闭，本节仍为 **BLOCKED / NOT AUTHORIZED**。

1. 再次核对连接身份、目标 Schema、当前版本和备份 ID。
2. 停止 App/Nginx 的业务写入并证明无活跃写请求；MySQL/Redis 保持受控可用。
3. 当前真实 Aerich 必须精确为 M0–M7；确认 Schema、21 表
   `m7-preserved-business-v1`、完整 225 图片 manifest 必须与当次 Backup/Restore 一致。
   接着在仍停写状态执行 raw M7 source preflight：`swatch_hex` 列必须为 0；221 条
   slot/code/name/URL/sort/active 必须逐槽等于冻结 manifest；221 张预期兼容 PNG 必须
   为普通非软链接文件、SHA-256 精确且权限 `0644`。额外 Product 图片可以保留，但已经
   由完整 manifest 绑定。未知、缺口、重复、部分 M8 或不一致时在 M8 任务前停止；不得
   退回 M2 路径。
4. 只通过受保护编排调用 M8 单步原语，记录开始/结束、退出码、前后 Aerich/Schema 摘要
   和候选身份。不得 `--fake`、直接改 Aerich 表、手工补列或把 downgrade 当回滚。
5. M8 DDL 可能出现物理 `swatch_hex` 已提交而 Aerich 仍为 M7 的部分状态。发生任何失败
   立即保持 App/Nginx 停止并保存 evidence；由授权人选择经 Review 的精确前滚修复或从
   当次已验证 Backup 恢复，禁止盲目重跑。
6. 核验最终 Aerich 精确为 M0–M8；`swatch_hex` 为 nullable `VARCHAR(7)`，221 个槽按
   `slot_no` 与冻结 manifest 逐项相等且值唯一。code/name/active/URL/sort、商品颜色启用/
   库存、Order/Inventory/Wallet/Reservation/Audit 等 21 表内容和既有时间戳边界不得
   出现未批准漂移；重新计算的 `m7-preserved-business-v1` 必须与停写源完全相同。升级器
   到此只证明内容零漂移，不把独立语义对账伪装成内部步骤。
7. 由受控编排调用 publisher 的精确 no-op 分支，确认 221 张兼容 PNG 内容、权限、路径
   与 M7 基线逐项相同且无需创建；不得脱离编排单独运行 publisher，不改变商品状态，
   不转换或删除 PNG。
8. 只在全部检查通过后写入绑定 source/target SHA、Image ID、M7→M8、Backup ID、HEX/
   图片 manifest、21 表内容摘要和复核时间的新 upgrade Record。该 Record 不包含
   `wallet_reconcile` 结果。保持
   App/Nginx 停止，以与成功 apply 完全相同的 source version/SHA/Backup ID 立即重放
   upgrade plan；它必须验证 evidence 路径/哈希、当前最终 DB、图片 manifest、M7 内容
   摘要，并再次得到只读 MARD preview 精确 no-op，输出 `already_current=true`。只有这次
   replay 成功后才可紧邻执行 `app-up`；`app-up` 自身不会重读 live DB、图片或 MARD。
   启动后再创建新 Backup/Restore。当前 M7 的 `20260908t021224z` 不得冒充 M8 数据后证据。

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
sudo python3 -m scripts.release.gatea_m7_representative_data \
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
这些结果不能直接关闭 M8 候选项目。

#### 4.4.3 M8 HEX、gzip 与数据后恢复验收

只有 §4.3 的 M7→M8 成功 Record 已生成、独立复核，并在同一无旁路写入的停写窗口完成
紧邻 `plan-replay`（`already_current=true`）后，才允许启动目标 Runtime。单有 Record
不够，因为 `app-up` 不会重读 live DB、图片或 MARD。验收必须至少包含：

1. 四项服务 Healthy，liveness/readiness 为 200，唯一 publisher 仍是批准的 loopback
   边界；运行镜像 revision、配置和 upgrade Record 精确绑定目标 SHA/Image。
2. 管理目录和公开 Online 自选色 Kit 均按冻结 manifest 返回规范大写 HEX；公开 221 色
   无 null/非法/重复值，code/name/URL 与 M7 基线不变。小程序开发者工具可以验证
   `backgroundColor` 与零数字色块 PNG 请求，但不能替代 iOS/Android 真机。
3. 对大于等于 1 KiB 的 JSON 分别以有/无 `Accept-Encoding: gzip` 请求：压缩响应只出现
   一次 `Content-Encoding: gzip`、可解码、正文语义一致，并包含缓存所需的 `Vary`；小于
   阈值的文本保持未压缩。通过 Nginx 时还要证明上游已编码响应没有被二次压缩。
4. 请求一张现有 PNG、一张 Product JPEG/WebP（若样本存在），确认图片 MIME 不被 gzip；
   221 张兼容 PNG 的数量、权限和 checksum 与 M7 Backup 一致。Brotli 不属于本候选。
5. 重跑只读 Wallet reconcile、数据库领域摘要、图片 manifest、日志 Secret/高置信敏感
   模式扫描，以及 MySQL/Redis 依赖恢复和 App 重启；任何未解释漂移都阻断。
6. 在成功运行状态创建新的 M8 MySQL/图片 Backup，完成独立无端口 Restore、空 Redis、
   Restore App readiness 和 225 图片核验，再按既有 AES-256-GCM/RSA-OAEP-SHA256 流程
   生成并立即解密复核异机副本。M8 检查点只能引用这组新 Record。

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
- 当前远端 CI 未达现行 9/9，或 MySQL snapshot 未精确覆盖 M0–M8（当前 head
  `62b1b15...` / Run 34288613644 已满足；任何后续业务 SHA 必须重验）；
- M7→M8 候选没有与当前身份绑定的 14/14 disposable 完整 updater 证据（当前
  Run 34288613644 已满足），持久候选 upgrade Record 缺失，或试图对当前 M7 Gate A
  使用空库 `initial-migrate`、省略显式 source 选择、退回默认 M2 路径或直接运行内部原语；
- 新 M7 Backup/Restore 缺少或不匹配 `m7-preserved-business-v1`，raw source preflight
  发现部分 M8、色卡/PNG 漂移，或成功 Record 后未在 `app-up` 前完成紧邻 live replay；
- 停写窗口内存在或无法排除直接 SQL、其他迁移进程、容器外脚本或宿主图片旁路写入；
- wallet reconcile 非零差异，HEX/图片 manifest 不一致，或试图对已有 Online 自选色
  商品独立运行 publisher、临时改商品状态、转换/删除兼容 PNG；
- gzip 无法解码、重复编码、缺少正确 `Vary`，或图片被错误压缩；
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
