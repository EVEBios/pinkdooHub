# Phase 9.2 CI Gate Matrix

> **Status:** Phase 9.2 historical baseline complete；live Gate A is predecessor A/M9 while `current` remains finalized lineage S/M7；A acceptance failed after order creation and the recovery candidate B still awaits its own fresh complete 9/9 required-Job run
> **Last Updated:** 2026-09-11
> **Current Provider:** GitHub Actions（[Draft PR #2](https://github.com/EVEBios/pinkdooHub/pull/2) / historical M8 success [Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644), attempt 2 / latest persistent M9 diagnostic [Run 34523689519](https://github.com/EVEBios/pinkdooHub/actions/runs/34523689519)）

本文件是 9.2 的实施契约。可以使用 GitHub Actions 或未来批准的等价 CI，但 Job 语义、隔离边界和阻断规则不能因供应商变化而弱化。

9.2.1–9.2.6 的历史基线已完成：当时 `.github/workflows/ci.yml` 的 `backend-sqlite`、
`backend-mysql-release`、`frontend-quality`、`openapi-contract`、`weapp-build`、
`repository-hygiene`、`python-dependency-audit` 和 `npm-dependency-audit` 已在真实
Pull Request 的干净 checkout 全部通过。当前候选在这八类 Job 之外新增
`gatea-m7-m8-updater`；它只允许在 GitHub 托管的一次性 Linux Runner 运行，不读取生产
Secret，也不触碰持久 Gate A。加入 Wallet、
Reservation、颜色 Kit 与 M7 后，head `4d6430c...` 的 Run 34129910349 已重新取得
8/8；包含后续 Gate A Operations 和 loopback 端口快速复用修复的 M7 持久检查点 head
`353455bb...` 又由 Run 34178908663 完成 8/8。M8 基线 head `4e745848...` 由
Run 34242753255 完成 8/8；其后新增的显式 M7→M8/Online no-op 发布保护已由 head
`fa6fce05...` 的 Run 34281512196 完成 8/8。这些历史 8/8 证据继续保留；当前 head
`62b1b15f...` / checkout `a9ff3d24...` 的 Run 34288613644 attempt 2 又把新增完整
updater 在内的 9 个 required Jobs 全部关闭。该 Job 名为兼容历史 required-check
设置继续保留 `gatea-m7-m8-updater`，当前实际候选流程已经扩展为 M7→M8→M9。
历史结论只关闭当时 Phase 9.2/M8 的 CI 与
可重复构建范围，不替代 9.3 的生产相似演练、9.4 的微信真机 RC 或后续模块的重新留证。
当前 M9 head 尚未取得完整 9/9，新修复候选不得复用 Run 34288613644 的 M8 PASS。

## 0. Phase 9.2.6 远端证据

- Draft PR：[#2 `feature/phase9-ci` → `develop`](https://github.com/EVEBios/pinkdooHub/pull/2)，保持 Draft/Open，未合并；实现证据 head SHA 为 `23a0f0898d1b4e2b49e16035bb1e382939865dd6`。
- 成功 Run：[33355935212](https://github.com/EVEBios/pinkdooHub/actions/runs/33355935212)，事件为 `pull_request`，2026-08-31 04:06:12Z 启动，04:08:21Z 完成，8 个 Job 全部 `success`。
- PR Run 的 `github.sha` 是 GitHub 生成的 merge-ref `eac0d5e85585520d3e41828ec7ede61106c7384e`；JUnit、MySQL、双依赖审计、repository hygiene 和微信 artifact 名称均绑定该 merge-ref 与 Run ID。PR head SHA 由 Run 元数据单独绑定，二者不得混写。
- 微信 Job 远端证据为 97 文件，主包 425,527 bytes、`admin` 分包 178,092 bytes、总计 603,619 bytes，`release_eligible=false`；manifest SHA-256 为 `d915912d711cf6f6408a833c084e27fd399b2c46fd3a4a0c8b5f7eb8ac8ece92`，权威 `project.config.json` SHA-256 为 `0c9d34336b46bbdb82b511838bced106454e9028a61a312ea6e33d6beecb47db`。
- Run 保存 7 组未过期证据 artifact：SQLite JUnit、MySQL 迁移/JUnit/cleanup、前端 Jest、微信产物/manifest/checksum/根配置、Python/npm 原始审计与策略结果，以及 repository hygiene 报告。

真实 Runner 的两轮失败被保留为回归依据，而不是删除或重跑掩盖：

1. Run `33354728020` 暴露 Python 策略测试硬编码 `.venv/bin/python`，以及微信检查器错误假设 `project.config.json` 一定存在于 `dist/weapp`；改为 `sys.executable`，并分别校验编译目录与项目根配置。Taro 若生成规范化副本，只允许 `miniprogramRoot` 从 `dist/weapp/` 变为 `./`，其他字段必须一致。
2. Run `33355556336` 进一步暴露 `NODE_ENV=production` 使 `npm ci` 省略 Taro 构建期 devDependencies，且 `tee` 掩盖 `taro: not found`；微信 Job 现显式 `--include=dev` 并启用 `pipefail`。构建期依赖不会因此进入微信运行产物。

### 0.1 Reservation N1 / M6 本地候选历史增量（2026-09-06）

- M6 接入前最近一次已实测的 workflow 已把迁移链升级为 Aerich 0→5，`backend-mysql-release` 联合运行 `tests/inventory/mysql` 与 `tests/reservation/mysql`。一次性 MySQL 8.0.46 本地验证结果为 `16 passed`，其中 Reservation 专项为 `7 passed`；覆盖 M5、店休并发/回滚、1205/1213 与六个索引计划。
- M6 接入后，workflow 候选会先真实执行空库 0→6，再以 `downgrade -v 6` 只回退 M6、写入一条 M5 非零库存 fixed Kit、重新升级 M6。最终 snapshot 必须同时核验七条 Aerich 版本、221 个未配置占位槽、历史 fixed 库存/类型兼容、19 个关键列、4 个命名 `RESTRICT` 外键和 7 个命名索引（其中 3 个 `NON_UNIQUE=0`）；Inventory MySQL 目录另增加 2 项结构/EXPLAIN 与反向颜色行锁等待门槛。截至该日期，这套 M6 workflow 与测试尚未在远端真实 MySQL Runner 执行，不能把 M5 的 `16 passed` 历史结果改称 M6 已通过；后续本地 M7 一次性 MySQL 结果单独记录在 0.2。
- 当时的本地后端计数只属于 2026-09-06 候选，不继续充当当前基线；当前候选必须在
  本轮改动全部收口后重新完整执行并记录实际 pass/skip。回环端口发布探测仍应在
  Linux CI 直接执行。
- 截至 2026-09-06，该 M6 候选的前端结果为 `81 suites / 556 tests`；TypeScript、ESLint、Stylelint、OpenAPI 类型漂移和 17 项 CI policy 通过。微信 production build 成功；固定 CI HTTPS Origin 产物通过扫描（141 个文件、主包 645,547 bytes、分包 390,570 bytes、总计 1,036,117 bytes，manifest SHA-256 `260e2f3e129ce75e418a1e487886a27e26684000111be5bd8c19161bc1570f8a`，`release_eligible=false`）。
- 上述均是本地候选证据，尚无绑定当前候选 SHA 的 PR/远端 Run，也不是可发布微信 RC；历史 PR #2 / Run 33355935212 的数值继续按原样保留，不能冒充 N1 证据。

### 0.2 M7 与当时前端候选（2026-09-07）

- 审计起点 HEAD 为 `c6778e79cccd7940928431ab17b958ea19993915`。其远端
  Run 34104680282 为 7/8；`backend-mysql-release` 在“M5 历史数据演练 M6”阶段失败，
  因为迁移链已新增 `7_20260907190000_add_reservation_settings.py`，而 workflow 的
  downgrade/重放顺序及 `check_mysql_gate.py::EXPECTED_MIGRATIONS` 仍只到 M6。
- 当前修复必须保留 M5 非零库存 fixed Kit→M6 兼容演练，并继续升级到 M7；最终
  snapshot 精确接受 M0–M7，核验 `reservation_settings` 默认周一、单例 CHECK/UNIQUE、
  已有 Reservation/StoreBusinessDay/M5 历史数据不漂移。M7 固定店休更换的事务、
  稳定锁序、批量取消、1205/1213 与索引也必须在一次性 MySQL 8.0.46 留证。
- 当前后端完整本地基线为 `2000 passed, 30 skipped in 113.05s`；30 项为三类需要显式
  MySQL 环境的门槛，已由一次性 MySQL 联合 `30 passed` 覆盖。该结果是本地候选证据，
  不是远端 `backend-sqlite` JUnit。
- 当前前端为 `83 suites / 562 tests`，已包含 M7 固定店休、代客钱包订单多颜色请求/
  布局和会员缺省头像居中回归；TypeScript、ESLint、Stylelint 及 17 项 CI policy
  本轮本地通过。当前 OpenAPI 仍须由新的远端 `openapi-contract` Job 绑定候选 SHA。
- 当前微信 production-mode 代码检查产物为 141 个文件、主包 649,739 bytes、分包
  407,624 bytes、总计 1,057,363 bytes，manifest SHA-256 为
  `693fb673df044e03c2865af2827e39ac7a5d6de86dbb1b3214f0b4237eeb69b4`，并明确
  `release_eligible=false`。修复后的新 SHA 必须完整重跑八类 Job，不能只重跑失败 Job
  后与 `c6778e7...` 的七个成功结果拼接。
- 本地提交 `58d8435d76022db41e625e3cdb7704a37943c94d` 已实现 M7 gate 修复；提交前
  的同内容 dirty 工作树在一次性 MySQL 8.0.46 完成 0→7、M0–M6 七个历史起点→M7、
  M6/M7 snapshot 与联合 MySQL `21 passed`。运行时不是干净 SHA，且远端尚未重跑；
  精确结果、第一次测试污染和 cleanup checker 的 `--rm` inspect 假失败见
  [M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)。
- 当时的 M7 PR head `4d6430c1bf9532d644bd7039ed7603fe9ee2c2bf` 已推送；PR merge-ref
  `ccbbe9dcb675a99369867814386051befc5922f2` 的
  [Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 为
  8/8 success。远端 SQLite 为 `2000 passed, 2 skipped`，MySQL 为 `21 passed`，7 组
  artifact 均绑定 merge-ref/Run ID 并有 GitHub digest。详见
  [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

### 0.3 Gate A Operations M7 持久检查点（2026-09-08）

- PR head `353455bbd05d658bc7b99753d790149d3ce48041`、merge-ref
  `92649bac7dc90aa3098c57d55aba05782e194e96` 的
  [Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663)
  于 `02:06:28Z`–`02:10:50Z` 完成 8/8；所有 Job 均为 `success`。
- 该 head 包含 M2→M7、Wallet/MARD、韧性、M7 综合数据与 loopback 快速端口
  复用工具。本地发布套件为 `169 passed`，完整后端为
  `2039 passed, 31 skipped`；远端 `backend-mysql-release` 继续完成 MySQL 8.0.46
  的 M0–M7、三域联合门槛和 cleanup。
- Run 保留 7 组绑定 merge-ref/Run ID 且带 GitHub digest 的 artifact；
  `openapi-contract` 按 workflow 只做阻断检查，因此没有第八组 artifact。
- 该 Run 通过后，`353455bb...` 作为不切换 Runtime 的版本化 Operations Release
  投放，并成功生成数据后 Backup/Restore 证据。完整 Job/artifact 清单与服务器
  证据边界见
  [Gate A M2→M7 升级与综合数据报告](reports/gatea_m7_upgrade_and_data_2026-09-08.md)。

### 0.4 M8 HEX/gzip 基线（2026-09-08）

- 首轮 head `06b5502...` / merge-ref `9437ee5...` 的 Run 34242022911 为 7/8；
  `backend-mysql-release` 的迁移演练、cleanup 和 evidence 成功，但 Reservation MySQL
  测试的迁移清单漏列已经应用的 M8，在联合 gate 中失败。
- 提交 `4e745848315aab56805a872ecf5b9f5e3c10135b` 只把
  `8_*_add_bead_color_swatch_hex.py` 纳入该测试的存在性/顺序断言。新的 merge-ref
  `3ddda81bc15986f0531c4887311611b7473d0d4b` 由
  [Run 34242753255](https://github.com/EVEBios/pinkdooHub/actions/runs/34242753255)
  完整执行八类 Job并取得 8/8，保留 7 组带 digest 的 artifact。
- `backend-mysql-release` 的受控 M6→M7→M8 legacy migration、真实 MySQL release
  gates、专用 Schema/service cleanup 和 evidence 步骤均 success；其他七个 Job 也均
  success。完整身份、时间与 artifact 见
  [M8 远端 CI 报告](reports/m8_remote_ci_2026-09-08.md)。
- 该结果不执行 Gate A M7→M8、不部署 gzip Runtime，也不授权任何持久数据库、DNS、
  微信上传、分发、提审或公开发布操作。
- 报告形成后，仓库候选新增显式 `--source-version 7`、版本化
  `m7-preserved-business-v1` 21 表内容摘要、停写后的 raw M7 schema/221 色/221 PNG
  精确预检、成功 Record 的 live replay verification，以及已有 Online 引用下 publisher
  的事务内 exact no-op；本轮完整 `tests/release` 为 `229 passed`，MARD 一次性 MySQL
  并发/锁序为 `3 passed`。这些变更晚于 `4e745848...`，不能复用本节 PASS；其干净
  SHA/远端重跑结果见 §0.5；当时仍独立的一次性完整 M7→M8 updater 门槛
  已由后续 §0.6 关闭。

### 0.5 M8 发布加固候选（2026-09-09）

- head `fa6fce05a153321d5c4079cb50f123c7996695f2`、merge-ref
  `b2f02ebc65bedf736197d54ed65228320d9962a4` 已由
  [Run 34281512196](https://github.com/EVEBios/pinkdooHub/actions/runs/34281512196)
  在 `2026-09-08T21:36:11Z`–`21:41:27Z` 从头执行八类 Job并取得 8/8。
- Run 保留 7 组未过期且带 GitHub digest 的 artifact；`openapi-contract` 按 workflow
  只做阻断检查、不上传 artifact，因此 7 组符合设计。
- 该候选包含显式 M7→M8、21 表内容保护、Online exact no-op、成功后停服 live replay
  及 fail-closed 容量工具，关闭了最终干净 SHA/新远端 CI 缺口。完整身份、Job 时长和
  artifact 清单见
  [M8 发布加固远端 CI 报告](reports/m8_hardening_remote_ci_2026-09-09.md)。
- 在该 8/8 检查点，workflow 的 `backend-mysql-release` 不执行 `deploy/gatea`
  完整生命周期，因此当时的一次性完整 updater 仍为独立阻断项；该项已由
  下方 §0.6 的新 Job 关闭。Gate A 持久 M8、candidate-pre 三轮、
  `release_eligible=true` RC 与真机仍为独立阻断项，CI 不授予任何写入或发布权限。

### 0.6 M8 完整 updater 隔离 CI（2026-09-09）

- PR head `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、真实 GitHub Actions
  checkout/merge-ref `a9ff3d246c61a4aeede062596c32817a69834d7a` 由
  [Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) 验证。
  最终 attempt 2 为 9/9 Success，所有当前 required Jobs 都是阻断项。
- attempt 1 的唯一失败是 `openapi-contract` 在依赖安装阶段遇到 pip
  truststore TLS 瞬态错误；OpenAPI 契约命令尚未运行，因此不记为契约失败。对该
  failed Job 的 rerun 用时 51 秒并通过，形成最终 attempt 2。
- `gatea-m7-m8-updater` 在 GitHub-hosted disposable Linux 上完成 14/14 stages，
  未获取生产 Secret，也没有持久环境读写授权。source M7 Backup 与同 ID
  独立 Restore 为 `20260908t230214z`；target M8 数据后 Backup 与同 ID 独立
  Restore 为 `20260908t230329z`。
- Runtime 精确验证 221 个规范 HEX，同一 221 色响应的 identity/gzip 大小为
  `63445 → 10948` bytes，同时验证 PNG 兼容回退。最终上传边界为 20 文件
  allowlist/Secret scan；`run` 清理后，workflow 第二次幂等 cleanup 再次通过并确认
  container/volume/network/image/port/workspace 零残留。
- 这个 PASS 关闭的是当时仓库候选的完整 updater 可执行性和隔离恢复证据；在该
  2026-09-09 历史检查点，持久 Gate A 权威状态仍为 M7，M8 尚未应用。后续 live
  A/M9 失败检查点见 §0.7。真实 Origin/TLS/RC、iOS/Android
  真机、微信上传、灰度和发布授权仍是独立阻断项。

完整身份、Job、阶段、Backup/Restore、artifact 和 cleanup 数值见
[Gate A M7→M8 完整更新器远端 CI 演练报告](reports/gatea_m7_m8_updater_remote_ci_2026-09-09.md)。

### 0.7 M9 现场失败检查点与前滚候选（2026-09-11）

required-check 的兼容名称仍为 `gatea-m7-m8-updater`，避免改变分支保护配置；从 M9
候选开始，它执行的实际链路是 M7→M8→M9：先恢复受控 M7 source，连续应用 M8/M9，
bootstrap 精确 30 张桌台，启动 App/Nginx/常驻 table sweeper，完成 M9 Runtime API
核验，再执行 M9 数据后 Backup/独立 Restore。名称兼容不代表流程仍停留在 M8。

当前失败 Run 全部保留为诊断与回归依据，不得拼接为 PASS：

1. [Run 34455514865](https://github.com/EVEBios/pinkdooHub/actions/runs/34455514865)
   暴露 M7 source Backup/Restore 按 M9 Runtime 默认值误启动 table sweeper；M7 尚无桌台
   表，恢复流程必须按精确 Aerich 版本只恢复该版本应存在的常驻服务。
2. [Run 34466953348](https://github.com/EVEBios/pinkdooHub/actions/runs/34466953348)
   暴露官方 MySQL CLI 默认 `latin1` 会把合法 UTF-8 桌台显示名误判为非法；数据库
   invariant 的 CLI 连接必须显式使用 `utf8mb4`，显示名后缀也必须由 UTF-8 字节构造。
3. [Run 34477579769](https://github.com/EVEBios/pinkdooHub/actions/runs/34477579769)
   已越过 M9 最终数据库 invariant 和 `app-up`，随后 Runtime verifier 错把只覆盖
   M0–M7 核心表的通用 snapshot 当成 M9 full snapshot，因缺少桌台键而失败。该结果只
   证明失败点之前的阶段在该 Run 到达成功状态，不构成完整 updater 或 9/9 PASS。
4. [Run 34520442209](https://github.com/EVEBios/pinkdooHub/actions/runs/34520442209)
   的其他 8 个 required Job 均通过；updater 在 source Backup 完成后因新增必填
   `release_record_dir` 未从 disposable 编排器透传给 Restore 而失败。当前实现已复用
   同一受保护 Release Record 目录并新增接线回归，但该失败 Run 仍不构成 updater PASS。
5. [Run 34523689519](https://github.com/EVEBios/pinkdooHub/actions/runs/34523689519)
   已为 head `41ad3cd...` / merge target `ceb664e...` 完成 9/9；持久 Gate A 的 candidate
   stage 与新 M7 Backup/Restore `20260911t013550z` 也通过，但旧 Runbook 从已安装 Release
   执行宿主 `python3 -m scripts.release.gatea_*` 时生成三个 `__pycache__/*.pyc`，使 stage
   冻结的 968 文件 manifest 变成 971 文件，故 `activate-config` 在零写入 plan 阶段正确
   阻断。该 target 只保留为诊断证据，不能手工删除 cache 后续跑；当前修复统一显式
   `python3 -B` 并加入真实 staged release + fresh subprocess 回归，仍须新 SHA 的 9/9。

当前仓库修复候选把 M9 最终 full snapshot 与 Runtime verifier 统一到同一组 11 项
count-only invariant；artifact 扫描显式拒绝 `qr_token`、未脱敏桌台码 payload/URL；
M9 Backup/Restore 新增精确、只输出摘要的 `m9-table-business-v1` 内容指纹，覆盖
`store_tables`、`table_sessions`、`table_session_timers` 与 `table_occupancies`，避免
只比较旧核心 snapshot 时对桌台内容丢失产生假阳性。upgrade apply 还把精确零值
`table_reconcile`、`{"status":"ok","closed":0}` sweep 与 sweep 前后 SQL 空表 invariant 写入
evidence 并由成功 Record 绑定；停写 plan replay 只重跑只读 reconcile 与 SQL invariant，
不重跑可能写库的 sweep。旧 M7 镜像缺少 `--no-access-log` 的兼容只能由精确 M7
Backup 内部恢复分支在停写前/恢复时双重验链后启用；默认、M8 和 M9 仍严格。本地
验证口径为后端完整 `3067 passed, 39 skipped` 与 Release 完整 `945 passed`；其中新增覆盖
A→B 失败验收退休、M9→M9 零迁移接管、M8 色块内容摘要、跨候选恢复 allowance、订单钱包
流水/完整库存审计链与恢复错误优先级；隔离 MySQL 探针也已覆盖前序 M9 迁移与运行时门槛。
这些都不是 B 的远端 required Job 证据。旧候选 A
`d6c09482ee0f5583d79bd847e995746c9c6ee1a3` 已把 live 配置、数据库和五项常驻服务带到
M9，但 acceptance 在 `order_created` 后因桌台身份读取绕过 Entrypoint Secret 加载而安全
失败；补偿已取消订单、恢复库存、下线 fixture、撤销会话，且未产生资金或桌台会话数据。
`current` 仍指向 finalized lineage S `73dca350505d43775fb1ff1158ccf6aabc221998`，canonical
schema v3 failure pending 必须保留到 B 的受控退休动作。只有同一 B SHA 从干净 checkout
完成全新 9/9，才允许依次执行 stage、失败验收退休、新 A/M9 Backup/Restore、M9→M9
零迁移 adoption/replay、B acceptance/resilience、数据后 Backup/Restore 与 finalize；禁止
手工删除 pending、临时注入 Secret、数据库降级或重跑 M7→M9。

## 1. 全局规则

- PR、集成分支和 RC 初期全部运行完整门槛，不做路径跳过；
- CI 使用干净 checkout，不复用开发者机器的 `.venv`、`node_modules`、SQLite、Redis 或构建目录；
- Python 固定 3.10.9；Node/npm 固定 24.13.0/11.6.2，并写入仓库版本文件、`engines`、`packageManager` 和 CI；
- Python 使用 `requirements.txt`，Node 使用 `npm ci --legacy-peer-deps` 和 `package-lock.json`；
- 每个 Job 有超时、取消和日志保留策略；
- Secret 只通过受保护环境注入，Fork PR 不获得发布 Secret；
- RC artifact 必须绑定 Git SHA、workflow run 和 checksum；
- CI 成功不自动上传微信、提审、发布或迁移持久数据库。

## 2. Job 矩阵

当前 workflow 共有 9 个 required Jobs；历史报告中的 8/8 是当时尚未加入
`gatea-m7-m8-updater` 时的完整集合，应保留其原有证据边界。该名称为分支保护兼容名；
当前 Job 在一次性环境中的实际候选语义仍为 M7→M8→M9，用于验证完整新装/升级路径；
B 现场接管则是独立的 M9→M9 零迁移路径。两者都必须由同一 B SHA 的全新 9/9 绑定。

| Job | 服务 | 关键命令/动作 | 阻断规则 | Artifact/证据 | 负责人 |
|-----|------|---------------|----------|---------------|--------|
| `backend-sqlite` | 隔离 Redis 或 fakeredis | 安装 Python；`pytest tests/ -q` | 任一失败；除已批准 MySQL-only 外出现未知 skip | pytest 日志/JUnit | Yijie Shen |
| `backend-mysql-release` | 专用 MySQL 8+，非 3306，专用 Schema | Aerich 0→9；M5 fixed→M6→M7→M8→M9 历史重放；M6/M7/M8/M9 snapshot；联合运行 `tests/inventory/mysql tests/reservation/mysql tests/wallet/mysql tests/table_sessions/mysql` | 迁移、版本、历史兼容、221 槽/HEX、M7 单例/默认值、M9 四表/约束/索引、库存/预约/资金/桌台并发、1205/1213、跨域锁序、HTTP、店休一致性、EXPLAIN 任一失败 | MySQL 版本、Aerich/M6/M7/M8/M9 快照、pytest/JUnit、cleanup | Yijie Shen |
| `gatea-m7-m8-updater`（兼容名） | GitHub-hosted disposable Ubuntu；真实 Gate A Compose/MySQL 8.0.46/Redis/Nginx/图片卷 | 冻结 M7 Runtime 建库与 221 PNG；source Backup/独立 Restore；当前 checkout 连续执行 M8/M9 plan/apply/停服 replay；30 桌 bootstrap；App/Nginx/table sweeper app-up；M9 DB/Runtime/reconcile；M9 Backup/Restore | Runner/资源身份、版本化服务恢复、备份恢复、升级、11 项桌台 invariant、Runtime API、桌台内容摘要、桌台码 Secret 扫描或精确清理任一失败 | 白名单 summary、两组 Backup/Restore Record、upgrade plan/apply/replay/Record/evidence、M9 runtime、cleanup | Yijie Shen |
| `frontend-quality` | 无 | `npm ci --legacy-peer-deps`；typecheck；ESLint；Stylelint；Jest；CI policy tests | 安装/检查/测试任一失败；新增未批准 warning | Jest JSON/log、版本清单 | Yijie Shen |
| `openapi-contract` | 无外部 DB/Redis | 设置 UTF-8；真实导出到临时文件；比较固定 JSON；生成类型 `--check` | JSON/类型漂移、临时文件残留、CLI smoke 失败 | diff、paths/schemas 摘要 | Yijie Shen |
| `weapp-build` | 无 | 注入受控 HTTPS Origin；`npm run build:weapp`；配置/包体/Secret 扫描 | 构建失败、非预期/占位/本机 Origin、Secret、微信包体越界、未批准 warning；保留 `.test` Origin 若被标成可发布也必须失败 | `dist/weapp`、manifest、checksum、构建日志 | Yijie Shen |
| `repository-hygiene` | 无 | 生成后 `git diff --exit-code`；敏感值、数据库、上传、缓存和调试输出检查 | 工作树漂移或意外文件/Secret | diff 与扫描报告 | Yijie Shen |
| `python-dependency-audit` | 网络 | `pip check`；使用批准的漏洞/许可证扫描器 | 依赖损坏；未处置的运行时 high/critical | 原始报告、例外记录 | Yijie Shen |
| `npm-dependency-audit` | 网络 | 显式官方/支持 audit 的 registry；`npm audit --omit=dev --json`；reachability 分类 | 微信 runtime 可达且未处置 high/critical；审计端点失败未被报告 | 原始 JSON、分类和例外 | Yijie Shen |

## 3. 当前命令基线

### 3.1 Backend SQLite

```powershell
python -m pip install -r requirements.txt
python -m pip check
python -m pytest tests/ -q --ignore=tests/inventory/mysql --ignore=tests/reservation/mysql --ignore=tests/wallet/mysql
```

M8 基线的本地完整结果为 `2069 passed, 31 skipped`；31 项均为需要显式 MySQL 环境的门槛，
对应集合已在一次性 MySQL 中执行。Run 34242753255 的 `backend-sqlite` Job 与 JUnit
保存步骤均 success；公共 Job API 不暴露未认证原始日志，因此不把本地计数冒充远端
计数。远端 MySQL Job 已明确完成 M6→M7→M8、联合 gate 和 cleanup。测试数量变化不是
失败本身，但必须解释增删原因；不能把真实失败改成 skip 来维持数字。

### 3.2 Backend MySQL Release Gate

沿用 `tests/inventory/mysql/conftest.py` 的安全边界：

- 显式 `INVENTORY_MYSQL_TEST_ENABLED=1`；
- host 是 `127.0.0.1`；
- port 不是 3306；
- Schema 以 fixture 要求的专用前缀开头；
- Job 自己创建、迁移和销毁实例/Schema；
- 运行完成后复核进程、端口和临时数据目录。

CI 配置不得放宽 fixture 来连接共享 MySQL，也不得使用 `--fake` 或应用自动建表替代迁移。

历史 9.2.4 已实现以下边界（以下 M0–M2 数值只描述旧 Run）：

- service 固定 `mysql:8.0.46`，只映射宿主 `127.0.0.1:13306`，Schema 固定为 `pinkdoohub_inventory_4311_ci`；仓库中的密码只是一容器一生命周期的 disposable test credential，不是发布 Secret；
- `check_mysql_gate.py preflight` 要求 `APP_ENV=testing`，并强制 Aerich 使用的 `DB_*` 与 pytest 使用的 `INVENTORY_MYSQL_TEST_*` 在 host/port/Schema/user/password 上完全一致；
- `aerich --app models upgrade` 真实应用三条权威迁移，snapshot 校验 MySQL 8.0.46 与精确 0、1、2 版本链；没有 `--fake`、`init-db` 或 `generate_schemas()`；
- 9 项门槛保存 JUnit；`always()` cleanup 删除精确专用 Schema、停止 GitHub service container、确认容器不再运行和 13306 关闭，再上传 preflight、迁移日志、snapshot、JUnit 与 cleanup JSON；
- 2026-08-31 本地以同一镜像、端口和 Schema 真实执行：三条迁移及 9 项门槛全部通过，cleanup 四项均为 true，容器对象和临时证据目录随后删除；未连接 3306、持久或共享数据库。

M6 候选在上述安全边界上追加以下 fail-closed 门槛：

- `aerich --app models upgrade` 先从空库真实执行 0→6；随后仅以 `downgrade -v 6` 回退最后一条迁移，在 M5 表形状中写入一条非零库存 fixed Kit，再重新执行正常 `upgrade`，从而同时验证空库完整链和历史数据升级，而不是只检查 SQL 文本；
- snapshot 精确接受 M0–M6 七条版本，并核验 221 槽连续、唯一、初始未配置/未激活且 `sort=slot_no`，历史 Kit 仍为 `stock=7 / kit_kind=fixed / sale_unit_grams=NULL`，以及 M6 19 个关键列、4 个命名 `RESTRICT` 外键、7 个命名索引的列序和 `NON_UNIQUE`（3 个 UNIQUE 必须为 0，其余必须为 1）；
- `tests/inventory/mysql/test_color_selectable_mysql_gate.py` 复核最终 Schema、数据库 fixed 默认和颜色集合锁 `EXPLAIN`，并用正/反请求构造真实 `performance_schema.data_lock_waits`，确认等待释放后仍按 Product/BeadColor 稳定顺序取得锁；
- workflow 保存独立 `mysql-m6-legacy-seed.json`、迁移日志、最终 snapshot 和 18 项联合 JUnit，任一步失败均阻断；`always()` cleanup 语义保持不变。

当前 M7 候选还必须追加：

- `EXPECTED_MIGRATIONS` 精确包含 `7_20260907190000_add_reservation_settings.py`；
- 历史重放不能因 M7 插入而跳过 M5→M6：先恢复到正确的 M5 形状、写入 fixed 样本，
  再按官方迁移依次应用 M6 与 M7；禁止手改 Aerich 版本；
- snapshot 核验 `reservation_settings` 恰有一条 `singleton_key=1`、
  `weekly_closed_weekday=monday`，`ck_reservation_settings_singleton` CHECK 和
  `uidx_reservation_settings_singleton` UNIQUE 的列序/唯一性正确；重复检查或正常重放
  不创建第二条单例；
- M5 的 Reservation、StoreBusinessDay 与 legacy fixed 样本在 M7 后行数/关键字段不漂移；
- M7 固定店休更换至少覆盖 settings 行锁、Reservation ID 稳定锁序、未来 30 天
  pending/confirmed 批量取消、单日店休保持、事务回滚和 MySQL 1205/1213；
- `tests/inventory/mysql/test_gatea_mard_publish_mysql.py` 在同一真实 M7 Schema 中将
  221 占位槽事务更新为冻结目录，原子发布 221 张 `0644` PNG，并验证完整 no-op 重放；
  测试结束恢复 M6 占位槽，不污染后续迁移证据；
- workflow 保存可区分 M6 seed、M7 snapshot、联合 JUnit 与 cleanup 的 artifact。

审计起点 Run 34104680282 已真实暴露 M7 漂移并失败；随后本地 dirty-tree 一次性
MySQL 报告已通过上述迁移、snapshot、历史矩阵和 21 项联合门槛，只能作为实现证据。
正式远端记录仍须由 `58d8435...` 或后续同内容干净 SHA 的实际 Runner 完成并保存可复核
cleanup artifact；不能沿用 M5 的 `16 passed`、本地 SQLite、旧 8/8 或本地 checker
结果替代。

Wallet 的 MySQL v1 关键闭环原有单独一次性 `2 passed` 历史结果。2026-09-07 的本地
候选已将 `tests/wallet/mysql` 接入同一 Job，并在一次性 MySQL 8.0.46 完成 Wallet
`9 passed` 与 Inventory + Reservation + Wallet `30 passed`：覆盖并发调账/余额支付/
退款、真实 1205、首轮已写后的 1213 整事务回滚重试、可观测资金/库存锁等待和关键
`EXPLAIN`。精确本地证据见
[Wallet 扩展 MySQL 报告](reports/wallet_mysql_release_gate_2026-09-07.md)。受测 head
`62f807a...` 的 [Run 34134341829](https://github.com/EVEBios/pinkdooHub/actions/runs/34134341829)
随后取得 8/8，三域联合、cleanup 与 artifact 步骤均为 success；完整身份和 digest 见
[Wallet 远端 CI 报告](reports/wallet_remote_ci_2026-09-07.md)。其后新增的 Gate A 运维与
MARD 测试仍须由后续 SHA 重跑，不能沿用本 Run。

### 3.2.1 Gate A M7→M8→M9 Updater Rehearsal

`gatea-m7-m8-updater` 是对 3.2 的补充而不是替代。它要求完整 Git 历史，source 固定为
已留证的 M7 Runtime，target 绑定本次干净 checkout 的精确 `GITHUB_SHA`。Job 名称为
兼容既有 required-check 配置保留，当前实际链路是 M7→M8→M9。编排器只在
`RUNNER_ENVIRONMENT=github-hosted`、Linux、root、显式 sentinel 和本地 Docker daemon
同时成立时运行；固定 Gate A container、volume、network 或 loopback 端口若已存在，
必须在产生写入前拒绝。

Job 的总超时为 60 分钟，但完整 `run` 另受 40 分钟进程组 watchdog 约束；超时会终止
Python 及其 Docker 子进程，并为独立 `always()` cleanup 保留最多 8 分钟，避免卡死操作
耗尽总闸而跳过资源补偿与证据收口。

当前顺序固定为：M7 首次迁移/启动与代表数据 → source 221 色 PNG 发布 → source
Backup/独立 Restore → M8 plan/apply → M9 plan/apply、30 桌 bootstrap/replay、精确零值
reconcile/sweep 与前后 SQL invariant → App/Nginx/`table-sweeper` 保持停止的只读 plan
replay（重跑 reconcile，不重跑 sweep）→ target `app-up`（含 table sweeper）→
221 HEX/gzip/PNG 与 M9 Runtime 核验 → M9 数据后 Backup/独立 Restore。M7 source Backup
恢复旧镜像时，只有精确 M7 链在停写前后被重复证明，才允许仅缺 `--no-access-log`
的冻结命令；M8/M9 和普通 `app-up` 仍严格要求当前命令。M7/M8 source Restore 不得
启动尚无桌台表的 sweeper；M9 Restore 必须恢复并核验它。`run` 的
`finally` 与 workflow 的 `if: always()` cleanup 双重回收精确资源；上传同时要求脱敏白名单
和 cleanup 后重新签发的安全扫描 marker，MySQL dump、图片 tar、配置、Secret、合成密码
和 Token 均不得进入 artifact。扫描异常会先失效 marker 并清空候选上传内容，只重建安全
状态/清理/失败摘要后才允许上传。

清理 PASS 不能只看 Docker 子命令退出码：服务 stop 后必须用 Compose `ps` 复核目标状态；
Restore project 最多执行两轮 `down --volumes --remove-orphans`→inventory，并确认该 project
的全部容器、两个临时 named volumes 与 internal network 都消失；candidate 临时镜像也最多
执行两轮删除→精确 reference inventory，只有 reference 为空才算收口。mandatory
recovery/cleanup 子命令使用新 session/独立进程组，避免父状态机与补偿子进程被同一终端信号
同时终止。

Run 34288613644 attempt 2 已将这一顺序在精确 checkout
`a9ff3d246c61a4aeede062596c32817a69834d7a` 上真实执行并完成 14/14 stages；
两组 Backup/Restore ID、221 HEX、`63445 → 10948` bytes gzip、PNG 回退、20 文件
安全扫描和二次零残留 cleanup 见 §0.6。该 Job 的通过只关闭“仓库候选尚未走过完整
updater”的隔离环境缺口，不构成持久 Gate A 写入授权，也不替代真实候选
Image ID、当次持久 Backup/Restore、真实 Origin/TLS、`release_eligible=true` RC
或 iOS/Android 真机。

Run 34455514865、34466953348、34477579769 依次暴露版本化 sweeper 恢复、MySQL CLI
字符集和 M9 Runtime full-snapshot 读取缺陷，详见 §0.7。当前修复候选还加入共享 11 项
invariant、upgrade reconcile/sweep Record 闭环、桌台码 artifact 扫描、
`m9-table-business-v1` Backup/Restore 内容摘要，以及按精确链选择 4/5 项服务的
resilience 复验。M7→M9 resilience 会自动绑定 upgrade source SHA/Image 对应的旧 M7
代表数据 Record，并在演练前后比较 M7/M9 版本化内容摘要；这些
改动只有取得同一当前 SHA 的全新 9/9 后才能成为远端 PASS 证据。

### 3.2.2 持久 Gate A 对 CI 证据的消费边界

本节描述仓库中已经实现的持久候选保护契约，不新增第十个 required Job，也不表示当前
M9 候选已经通过 CI 或已应用 Gate A。持久工具只接受同一 target checkout 的 source
archive 与 `gatea-m7-m9-updater-<target-sha>-<run-id>-<attempt>` artifact；candidate
`stage` 会复验 artifact 内 target、reported PR head、Run/attempt、白名单、安全扫描和零
残留，再安装版本化 Release/目标镜像。它不改 config、Runtime、DB 或 `current`，因此仅有
stage Record 不能升级。

持久成功链固定为：`stage` → 新 source M7 Backup/同 ID Restore → candidate
`activate-config` plan/apply → `gatea_upgrade --source-version 7 --apply` → 不带 apply 的
plan-replay → `app-up` → M9 acceptance plan/`--apply-admin-assisted` → target resilience →
新 M9 Backup/同 ID Restore → candidate `finalize --apply`。配置激活只允许改目标 Image 与
`TABLE_SESSION_CLAIMS_ENABLED=true`，且 `current` 保持 source；`rollback-config` 只在 DB
仍为精确 M7、没有任何 target upgrade evidence 时恢复旧配置，升级开始后拒绝。`finalize`
直到全部现场证据通过才原子切换 `current`，不会把 CI artifact 自身当作现场 PASS。

上述持久入口共用 `/run/lock/pinkdoohub-gatea-operation.lock`（root-owned regular `0600`、
非阻塞、禁止 CLI 改路径），并从首次可变现场读取/TTY/HTTP/pending 前持有到补偿、登出和
journal 完成。candidate、upgrade、Backup/Restore、acceptance 或 resilience 的并发调用、
不安全锁文件、已有冲突 Record/pending 都 fail closed。`.pending` 只是一条 durable 状态机
journal：同一命令必须严格匹配其中的 source/target、Run/attempt、Record digest 和全部显式
确认值，且 checkpoint 明确允许恢复，才可继续自己的 pending；更早阶段、另一动作或内容
冲突的 pending 一律在读取可变现场前阻断。只读 `preflight`、
`database-status`、`status` 不持锁，其旧输出不能替代各写入口内部复验。

这里的“冲突 pending”是全局 inventory，不是只查当前 target SHA。Release Record 目录的
四种后缀——`candidate-stage`、`config-activation`、`config-rollback`、
`current-finalization` 的 `.pending.json`——会跨所有候选与动作扫描；畸形 SHA/名称及
symlink、目录、FIFO 等非普通项也阻断。candidate 原动作最多只恢复一个精确绑定
candidate/kind/path 的 own journal，finalization 内部 `app-up` 也只获得该精确结构化
allowance；任何第二个 blocker 仍失败。M9 acceptance 目录同样跨所有候选扫描
`gatea-m9-runtime-acceptance-*.json.pending/.json.complete`；目录尚不存在仅在首次验收前
视为空，已存在时必须是安全的 `root:root 0755` 真实目录。acceptance 原命令最多放行自己
的 `0600` pending 和 `0600/0644` complete，且仍需随后验证完整内容与 live 状态。

四个 candidate 动作、Backup/Restore、upgrade plan/apply、Bootstrap、基础/M7 代表数据、
`initial-migrate`、普通 `app-up`、acceptance 与 resilience 都在数据库快照、TTY、业务 API
或资源启停之前接入上述扫描；只读配置/Secret 元数据校验不能越过 inventory 进入现场动作。
不同 Backup ID 不因此互相阻断；只有消费某一精确 Backup ID 的 Restore 或 Upgrade 会拒绝
该 ID 自己未收口的 backup pending。
`infra-up`/`safe-stop` 仍是只负责取得锁并把现场拉到可诊断/安全状态的恢复原语；它们不消费
或清除 inventory，也不能让任何后续发布阶段绕过未收口状态。

所有持久变更入口共用同一操作锁，并在 CLI work 前为 SIGHUP/SIGTERM/SIGINT 安装终止信号
guard；SIGINT 对外保持 Python `KeyboardInterrupt`。Backup、Restore、candidate
finalization 与 resilience 还在首次停服前安装 work→recovery 状态控制；工作阶段首个信号
先切换恢复相位再抛出，恢复阶段的后续信号只延期记账，必须完成精确服务恢复、清理与健康
核验后才传播。mandatory recovery/cleanup 子命令均使用新 session/独立进程组；服务 stop
必须由 Compose `ps` 确认进入允许状态，Restore project 与 candidate 临时镜像分别由精确
资源 inventory/reference inventory 确认清除。异常优先级固定为 recovery/cleanup failure >
original work/control error > deferred signal，延期信号不得掩盖补偿失败或原始根因。
SIGKILL/断电不可捕获，有 durable
pending 的动作在后续入口必须先按 journal 状态机处理，不能满足严格恢复契约即 fail closed；resilience 不写
durable pending，因此 M9 演练若在此处遭遇 SIGKILL/断电，
必须人工核验 MySQL、Redis、App、Nginx、`table-sweeper` 五项服务与现场状态。

持久文件的提交点也独立于进程退出码：candidate/Backup/Restore/upgrade/acceptance/resilience 的
不可变 Record 或 artifact 先在同目录随机临时路径完整写入并执行 file `fsync`，再通过
hard-link no-clobber 发布并同步父目录；状态 journal 的原子替换也同步父目录。candidate
四阶段分别只恢复自己的持久 checkpoint，不能跨动作借用 pending。Upgrade success 只有在
canonical success bytes 与 `succeeded/completed` evidence 路径及 digest 一致时成立；一旦
该提交已经可见，随后的临时清理或第二次目录同步错误不得反向把 evidence 标成 failed，
而是由下一次只读 replay 重新验证并收口。

M9 plan-replay 会排他生成 `<target-sha>.upgrade-plan-replay.json`，绑定 upgrade
Record/evidence、最终数据库/图片摘要和零差异 table reconcile。`app-up` 现在必须消费该
sidecar，重读 live M0–M9/静态 Schema 摘要、运行 table reconcile 并在启动前复验 Image
ID；它仍不现场重算图片 manifest、M7 内容摘要或 MARD preview，所以紧邻 replay 与无旁路
写入窗口仍不可省略。

admin-assisted acceptance 仅从安全 `/dev/tty` 读取并双重确认 SUPER_ADMIN 身份，不接受
凭据参数、环境或 stdin；它把 target/CI/upgrade/replay、旧 M7 代表数据/合成凭据、五服务、
一次性空 Session 基线和正式 loopback API 行为绑定到不可覆盖的脱敏 Record。自动闭环使用
wallet，验证 15 分钟 deadline、60/120 分钟分组各加 10 分钟、同长合并、异长拆分、
quantity 不乘时长、Kit 排除、Claim/payment/release 幂等、对账、sweep、日志脱敏和登出；
完成业务断言后还必须通过管理 API 下架 Experience/Kit 并二次读回为 offline，失败清理也
尽力保证已创建 Product 不可售。success 保留 paid Order、closed Session、五张图片和
库存/钱包变化作为数据后证据；不把 manual、自然等待超时或取消/完成/退款 live 行为伪写
为 PASS。

acceptance 成功证据采用两阶段不可覆盖发布：先把完整 JSON 写入同目录随机 `0600` 临时文件
并完成 file `fsync`，再 hard-link 到 `.complete` 并同步目录；随后才把 own pending 持久提交为
`verified/failure=false`，再 hard-link 到最终 Record。最终 Record 完成目录同步后才删除
pending 与 `.complete`。合法崩溃恢复必须严格匹配 candidate/Run/attempt、全部前后对账、
Fixture/Order/Session/Payment/Timer 与 cleanup 绑定，先精确清理安全的 writer temp，且只收口
发布，不重新调用业务 API。pending 固定为 schema v3，最终 success 独立保持 schema v1；
success 中 Payment ID、Payment No SHA-256 与 `succeeded_at` 必须和 pending payment evidence
相等，不保存原始 Payment No。

M9 acceptance v3 在首次登录、因而也在首个 RefreshSession 可能产生之前先持久写入
`authentication_started` checkpoint。只有本次刚创建 journal、尚无已知会话或业务副作用，
且首次管理员登录精确返回 HTTP 400/业务码 `1003` 时，才可安全删除该 journal 以重新输入
密码；连接或响应不确定、角色/响应异常、旧 v2 journal、会话 cleanup/revocation 证明不完整
均保留 pending 并 fail closed。v3 own pending 仍须满足上面的严格身份、确认值和 checkpoint
恢复契约，不能作为换参数重跑的入口。

M9 resilience 必须显式接收这份 acceptance Record 路径和
`--confirm-runtime-acceptance-record-sha256`，不能靠目录发现或仅检查 `passed=true`。它在
演练前与 success 发布前验证文件/父目录元数据、sidecar 为空、文件身份与 digest 稳定，并
把 candidate/Image、Operations/CI Run、M7→M9 upgrade/replay、代表数据/凭据、五服务、
attempt digest 与 acceptance 完成时间直接绑定。M9 resilience 成功 Record 因此固定为
schema v2，新增 acceptance Record digest、attempt digest 与完成时间；M2/M7/M8 的四服务
legacy 演练继续使用严格 schema v1，不能把两种 Record 混用。`finalize` 会再次校验这条
direct binding。CLI 默认 guarded acceptance 目录为
`/srv/pinkdoohub/gatea/records/m9-acceptance`，Record 必须位于该目录；若使用另一受控目录，
必须显式传 `--acceptance-record-dir`，且两者必须按不跟随软链接的规范路径完全相同。
resilience final 一旦可见即是不可变提交；同参数重跑只接受 `root:root 0644` 普通 final，
严格复验 schema v1/v2、全部绑定/时序、日志，以及前后两次当前 Runtime、数据库和图片一致性，
不重新执行 MySQL/Redis outage 或 App restart。若只残留 writer 产生的最多一个临时别名，
还须证明它与 final 同 inode/内容/冻结身份，先同步 final 目录项、精确删除别名并再次同步。
孤儿/多个/不一致 temp、同候选另一 sidecar、任一现场或证据漂移均 fail closed。演练过程仍
没有 durable pending，所以 final 尚未可见时的 SIGKILL/断电必须人工核验五服务和现场，
不能猜测为 PASS。

每个 Backup ID 在停服前先排他创建 `0600` 的 `.<backup-id>.pending.json`；随后停写、复验
迁移链和摘要，再向同目录随机 `0600` 临时文件流式导出；完整写入与 file `fsync` 后才以
hard-link no-clobber 发布两个正式 artifact 并同步目录。只有服务恢复和最终
Record 发布后删除 pending，失败时保留 pending 且同 ID 不可复用。Restore
Record 只在隔离资源清理完成后排他发布，并绑定 Backup Record、MySQL artifact、image
artifact 三个 SHA-256。隔离清理最多执行两轮 `down --volumes --remove-orphans`→inventory，
且必须确认该 project 的容器、两个临时 named volumes 和 internal network 全部不存在；
`down` 返回成功本身不是清理证据。只要同 ID 的 unresolved backup pending 存在，Restore 与 Upgrade
就绝不消费该备份，即使最终 Record/artifact 看似齐全；不得补文件、删 pending 或重试来
复用该 ID。`finalize` 会重新计算这些 digest，并要求 acceptance/resilience
均早于新的 M9 Backup、Backup 早于 Restore；任一内容摘要、digest、时序、五服务、live M9
或 `current` source 身份不符都拒绝切换。数据后图片数必须为 acceptance 前完整 manifest
数量加 5，不写死历史 M7 基线；resilience 必须先证明演练前后 manifest 未变，随后
`finalize` 要求其 `image_file_count` 等于数据后 Backup 的完整 `image_manifest` 长度，
M7/M9 内容摘要也必须与该 Backup 精确相同。

首次 finalization 的最后一次 live recheck 之后，`current` 从 source 原子切到 target 是
commit point。若随后中断且 final Record 尚未发布，只有 own pending 已到
`live-rechecked`、`current-switched` 或后续 `runtime-restored`，且全部身份/确认值及不可变
证据仍严格匹配时，原命令才可恢复：复验 Record/artifact digest、`current`、配置、目标
Image 和 live M9 结构/Runtime invariant，恢复五服务并补齐 final Record。Runtime 重新开放
后可能已有合法业务写入，因此恢复路径不得再把切换前的旧 Backup 业务内容摘要（包括
pre-upgrade source 与 finalize 直接绑定的 post-acceptance Backup）和在线数据重比；更早
checkpoint、final/pending 冲突或任一不匹配都 fail closed，target symlink 本身不构成 PASS。
普通 `app-up` 默认拒绝这个 finalization pending；只有已严格校验 own journal 的 candidate
内部恢复调用可显式跳过这一项检查，且其他 candidate transition pending 仍会阻断。正常
cutover、pending+target 续跑和已有 final 的 Runtime 修复均须完成五服务恢复与健康核验后，
才传播原始或延期的 HUP/TERM、SIGINT、`SystemExit`；恢复失败优先作为阻断结果。

`finalize` 的 `--acceptance-record-dir` 与 `--resilience-record-dir` 默认分别指向
`/srv/pinkdoohub/gatea/records/m9-acceptance` 和
`/srv/pinkdoohub/gatea/records/resilience`；传入 Record 的 lexical 父目录必须分别与对应
guarded 目录完全相同，非默认路径必须同时显式传 Record 和目录。入口先扫描全候选
acceptance sidecar，再读取 Release/live 证据。candidate 只消费完全收口的 resilience final：
它必须是稳定 `root:root 0644` 普通文件、`nlink=1`，目录内不得存在该 final 的 `.tmp-*` 或
其他 publication alias/sidecar；`finalize` 不替 resilience 清理残留，未收口时继续 No-Go。

### 3.3 Frontend Quality

```powershell
npm ci --legacy-peer-deps
npm run typecheck
npm run lint
npm run lint:styles
npm test -- --runInBand
npm run api:types:check
```

React Test Utils 的 `act` 弃用告警暂时进入批准 warning 清单，只按精确来源匹配；出现新 warning 或数量/来源变化必须失败并 Review。

### 3.4 OpenAPI Contract

```text
FastAPI app.openapi()
  → UTF-8 临时 openapi.json
  → 与 miniapp/openapi/openapi.json 比较
  → openapi-typescript --check
  → git diff --exit-code
```

Windows 本地已发现非 UTF-8控制台下 `--help` 可能失败。CI 显式设置 UTF-8，并覆盖 `--help` 和真实导出；Linux 通过不能删除 Windows 开发说明。

### 3.5 WeChat Build

构建环境必须显式提供：

```text
NODE_ENV=production
TARO_ENV=weapp
TARO_APP_APP_ENV=production
TARO_APP_API_ORIGIN=https://<approved-test-or-production-origin>
```

检查：

- API Origin 与目标环境一致；
- 正式 artifact 无 `.example.invalid`、未批准测试 Origin 和实际 localhost Origin；
- 允许配置校验代码中出现 localhost 禁止列表，但扫描器必须证明实际注入 Origin；
- AppSecret/JWT/DB/Redis/支付/私钥标记为零；
- `app.json` 的主包/`admin` 分包符合预期；
- 使用微信当前规则/工具记录正式包体，不只使用文件系统 raw bytes；
- source map 策略与上传权限一致；
- artifact 命名包含 app version、Git short SHA 和 run ID。

## 4. 依赖审计处置

每项漏洞必须记录：

| 字段 | 说明 |
|------|------|
| Package/advisory | 包名和公告 ID |
| Dependency path | 从直接依赖到问题包的完整路径 |
| Reachability | build-time / H5-only / weapp-runtime / unknown |
| Actual usage | 项目是否调用受影响 API/代码路径 |
| Fix options | 安全升级、override、移除平台插件、等待上游 |
| Regression scope | 微信 Build、Jest、真机、包体和未来跨端影响 |
| Decision | fix / mitigate / time-boxed exception / block |
| Owner/expiry | 负责人和例外到期日 |

9.2.5 已把 npm 的 10 个受影响包解析为 5 个叶子公告，并在
`security/dependency_audit/npm-policy.json` 逐项固定版本、严重性、direct 标记、
affected range、完整依赖路径、actual usage、fix options、回归范围与 Gate A
reachability。结论不是整批 H5-only：

- `esbuild` 及 Taro helper/service/runner 聚合项属于 build-time，但公告只影响未启用的 development server；
- `lodash-es`、`taro-h5`、`components-react` 和 H5 插件链不进入固定 `TARO_ENV=weapp` 的 Gate A artifact；
- `@tarojs/components`/`swiper` 的 npm swiper 实现没有被业务源码使用，当前微信 artifact 使用原生 swiper 映射而非该 JS 运行库；新增 Swiper 使用会触发重新评估；
- Taro 4.2.1 仍是官方 registry 当前版本，npm 建议的“修复”是破坏性降级 Taro 3.x，因此未执行 `audit fix --force` 或未经上游验证的 override。

风险 `R-007` 的现状保持不变：全部 npm 例外由 Yijie Shen 分别以安全负责人和
项目负责人记录，精确覆盖既有 10 个受影响包/5 个叶子公告，并于 2026-11-30
自动到期。检查器要求精确 10 包、5 公告和 4 moderate/1 high/5 critical；新增、
消失、版本/严重性/路径变化、registry 错误或例外到期均失败。

2026-09-09 出现的 Joi Low 公告已通过在 `@tarojs/service@4.2.1` 允许范围内将
传递依赖升级到 `joi@17.13.7` 移除；Joi 不进入 `R-007` 例外，也不扩大上述
10 包/5 叶子公告的批准集合。

Python 选用 Apache-2.0 的 `pip-audit==2.10.1`，仅安装在隔离 CI venv。首次扫描的 4 包/9 条报告中，asyncmy、cryptography、python-jose 均存在可用安全版本，已分别升级到 0.2.14、50.0.1、3.5.0；复扫只剩 `ecdsa==0.19.2` 的 `GHSA-wj6h-64fc-37mp`。上游无 patched release，且项目 production 固定 HS256，不生成 ECDSA 私钥或执行 ECDSA/ECDH，因此在 `python-policy.json` 记录到 2026-11-30 的不可达例外。任何 JWT 算法、依赖、公告或到期变化都会使 Job 失败。

Python 漏洞扫描已选用并固定 `pip-audit==2.10.1`；扫描器只安装在隔离 CI venv，
不进入生产运行环境。未来更换工具时仍须检查维护状态、许可证、锁定方式和 CI 可复现性。

## 5. 触发与权限

| 事件 | 必须 Job | Secret 权限 | 外部动作 |
|------|----------|-------------|----------|
| 普通 PR | 全部 9 个 required Jobs | 无生产 Secret | 无 |
| Fork PR | 同上；使用无 Secret 的隔离服务 | 无 | 无 |
| 集成分支 | 全部 Job | 仅测试环境 Secret | 生成 artifact，不上传微信 |
| Gate A RC | 全部 Job重跑 | 受保护测试环境 Secret | 经批准后可人工上传体验版 |
| Gate B RC | 全部 Job + Gate B 专项 | 受保护生产候选 Secret | 经双人/明确审批后提审 |
| 定时 | 依赖审计、可选工具链兼容检查 | 最小读取权限 | 无发布 |

## 6. 历史 9.2 完成定义与当前 M9 候选重开项

以下第一组 `[x]` 仅表示 Phase 9.2 的 M0–M2 历史基线完成；§0.6 的 Run
34288613644 只支持当时 M8 候选的 9-Job 结论，不支持当前 M9 候选：

- [x] CI 配置已提交并经过至少一个 PR 真实运行；
- [x] 所有 Job 从干净 checkout 通过；
- [x] MySQL Job 创建、迁移、测试、关闭和清理均有证据；
- [x] 微信 artifact 绑定 SHA、checksum 和配置摘要；
- [x] OpenAPI 漂移在修改与未修改场景均被验证；
- [x] npm registry audit 失败会显式失败，不被吞掉；
- [x] 当前 10 项 npm 风险完成微信 reachability 分类并有 2026-11-30 到期策略；
- [x] Python 漏洞扫描已锁定，修复可升级项并只保留 1 条有期限不可达例外；
- [x] warning 策略为零项白名单，任何未批准 warning 都阻断；
- [x] 没有配置自动迁移持久数据库、自动提审或自动发布。

M8 基线与当时候选结果：

- [x] 修复后的同一干净 PR checkout 完成八类 Job 8/8，保存 Run 34129910349 与 7 组 artifact；
- [x] MySQL Job 在远端精确覆盖 M0–M7、M5→M6→M7 历史重放、M7 snapshot、联合
  `21 passed` JUnit 和成功 cleanup 步骤；
- [x] Wallet 扩展 MySQL 门槛已独立完成本地候选验证：Wallet `9 passed`、三域联合 `30 passed`；
- [x] Wallet-expanded workflow 已由 head `62f807a...` 的 Run 34134341829 在干净 Runner
  复现，JUnit/cleanup artifact 上传步骤均 success；
- [x] `4e745848...` 中的 Gate A 运维、MARD、M8 HEX/gzip 与迁移链基线已由
  Run 34242753255 在干净 Runner 复现，M8 Job/artifact 另有专门报告；
- [x] `4e745848...` 的前端/OpenAPI/微信 production artifact、依赖审计与仓库卫生都绑定 Run 34242753255；
- [x] 后续 M7→M8/21 表内容保护/Online exact no-op 候选在本地完成 `tests/release`
  `229 passed`，本轮完整后端为 `2317 passed, 33 skipped in 125.31s`；
- [x] 后续候选已绑定 head `fa6fce05...` / merge-ref `b2f02ebc...`，并由 Run 34281512196
  完整远端 8/8 与 7 组 artifact 复现；
- [x] 完整 updater 的受测实现 head `62b1b15f...` / checkout `a9ff3d24...` 已由 Run 34288613644 attempt 2
  完成当前 9/9 required Jobs；新增一次性 M7→M8 updater 为 14/14 stages，两组
  Backup/Restore、Runtime 和二次 cleanup 证据均完整；
- [x] attempt 1 的 `openapi-contract` 仅在安装依赖时遇到 pip truststore TLS 瞬态
  错误，contract 命令未运行；failed-job rerun 在 51 秒内通过并形成最终 attempt 2；
- [ ] 当前 M9 SHA 必须重新完成全部 9 个 required Jobs；兼容名
  `gatea-m7-m8-updater` 必须真实完成 M7→M8→M9、11 项桌台 invariant、M9 Runtime、
  `m9-table-business-v1` Backup/Restore、artifact 扫描和精确 cleanup；
- [ ] Run 34455514865、34466953348、34477579769 均为失败诊断证据，不得与其他 Run
  的成功 Job 拼接；当前修复只有在新的同 SHA 9/9 后才能记为 PASS；
- [ ] 持久 Gate A 仍需当次授权、新 Backup/独立 Restore、停写窗口、目标 Image、
  M7→M8→M9 迁移与 Runtime 验收后才能应用 M8/M9；
- [ ] 新 9/9 artifact 尚须由持久 candidate `stage` 绑定 source archive/Run/attempt，再按
  `activate-config` → upgrade/replay → `app-up` → admin-assisted acceptance → 显式绑定该
  acceptance Record/digest 的 resilience → M9 数据后 Backup/Restore → `finalize` 的顺序
  执行；任一全局 pending/sidecar、严格状态机恢复、no-overwrite、acceptance direct binding
  或 Restore digest 绑定失败都保持 No-Go，不能切换 `current`；
- [ ] Gate A M7→M8→M9、真实 Origin/TLS/RC、iOS/Android 真机、微信上传灰度发布继续由
  后续 Gate 单独授权，CI 不自动执行。
