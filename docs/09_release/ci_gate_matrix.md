# Phase 9.2 CI Gate Matrix

> **Status:** Phase 9.2 historical baseline complete；current Operations candidate remote gate passed (8/8)
> **Last Updated:** 2026-09-08
> **Current Provider:** GitHub Actions（[Draft PR #2](https://github.com/EVEBios/pinkdooHub/pull/2) / [latest recorded successful Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663)）

本文件是 9.2 的实施契约。可以使用 GitHub Actions 或未来批准的等价 CI，但 Job 语义、隔离边界和阻断规则不能因供应商变化而弱化。

9.2.1–9.2.6 的历史基线已完成：当时 `.github/workflows/ci.yml` 的 `backend-sqlite`、
`backend-mysql-release`、`frontend-quality`、`openapi-contract`、`weapp-build`、
`repository-hygiene`、`python-dependency-audit` 和 `npm-dependency-audit` 已在真实
Pull Request 的干净 checkout 全部通过。当前 workflow 仍保留八类 Job；加入 Wallet、
Reservation、颜色 Kit 与 M7 后，head `4d6430c...` 的 Run 34129910349 已重新取得
8/8；包含后续 Gate A Operations 和 loopback 端口快速复用修复的当前 head
`353455bb...` 又由 Run 34178908663 完成 8/8。历史结论只关闭当时 Phase 9.2 的 CI 与
可重复构建范围，不替代 9.3 的生产相似演练、9.4 的微信真机 RC 或后续模块的重新留证。

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

### 0.2 M7 与当前前端候选（2026-09-07）

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
- 当前 PR head `4d6430c1bf9532d644bd7039ed7603fe9ee2c2bf` 已推送；PR merge-ref
  `ccbbe9dcb675a99369867814386051befc5922f2` 的
  [Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 为
  8/8 success。远端 SQLite 为 `2000 passed, 2 skipped`，MySQL 为 `21 passed`，7 组
  artifact 均绑定 merge-ref/Run ID 并有 GitHub digest。详见
  [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)。

### 0.3 Gate A Operations 当前候选（2026-09-08）

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

| Job | 服务 | 关键命令/动作 | 阻断规则 | Artifact/证据 | 负责人 |
|-----|------|---------------|----------|---------------|--------|
| `backend-sqlite` | 隔离 Redis 或 fakeredis | 安装 Python；`pytest tests/ -q` | 任一失败；除已批准 MySQL-only 外出现未知 skip | pytest 日志/JUnit | Yijie Shen |
| `backend-mysql-release` | 专用 MySQL 8+，非 3306，专用 Schema | Aerich 0→7；M5 fixed→M6→M7 历史重放；M7 settings snapshot；联合运行 `tests/inventory/mysql tests/reservation/mysql tests/wallet/mysql` | 迁移、版本、历史兼容、221 槽、M7 单例/默认值、FK/约束/索引、库存/预约/资金并发、1205/1213、跨域锁序、HTTP、店休一致性、EXPLAIN 任一失败 | MySQL 版本、Aerich/M6/M7 快照、pytest/JUnit、cleanup | Yijie Shen |
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

当前本地普通基线为 `2000 passed, 30 skipped in 113.05s`；30 项均为需要显式 MySQL
环境的门槛，并已由一次性 MySQL 联合 `30 passed` 覆盖。旧远端 Job 显式忽略两个
MySQL 目录后为 `2000 passed, 2 skipped in 736.46s` 并保存 JUnit；新的候选改为显式
忽略三个 MySQL 目录，尚待远端复现。历史 16 项 Inventory + Reservation MySQL-only
只绑定 M5 Schema；旧远端 M7 联合 MySQL 结果为 `21 passed`。回环端口发布探测已在本地
完整主套件中直接通过，Linux CI 也应直接执行。测试数量变化不是失败本身，但必须解释
增删原因；不能把真实失败改成 skip 来维持数字。

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

全部 npm 例外由 Yijie Shen 分别以安全负责人和项目负责人记录，2026-11-30 自动到期。检查器要求精确 10 包、5 公告和 4 moderate/1 high/5 critical；新增、消失、版本/严重性/路径变化、registry 错误或例外到期均失败。

Python 选用 Apache-2.0 的 `pip-audit==2.10.1`，仅安装在隔离 CI venv。首次扫描的 4 包/9 条报告中，asyncmy、cryptography、python-jose 均存在可用安全版本，已分别升级到 0.2.14、50.0.1、3.5.0；复扫只剩 `ecdsa==0.19.2` 的 `GHSA-wj6h-64fc-37mp`。上游无 patched release，且项目 production 固定 HS256，不生成 ECDSA 私钥或执行 ECDSA/ECDH，因此在 `python-policy.json` 记录到 2026-11-30 的不可达例外。任何 JWT 算法、依赖、公告或到期变化都会使 Job 失败。

Python 漏洞扫描已选用并固定 `pip-audit==2.10.1`；扫描器只安装在隔离 CI venv，
不进入生产运行环境。未来更换工具时仍须检查维护状态、许可证、锁定方式和 CI 可复现性。

## 5. 触发与权限

| 事件 | 必须 Job | Secret 权限 | 外部动作 |
|------|----------|-------------|----------|
| 普通 PR | 全部非发布 Job；MySQL Job | 无生产 Secret | 无 |
| Fork PR | 同上；使用无 Secret 的隔离服务 | 无 | 无 |
| 集成分支 | 全部 Job | 仅测试环境 Secret | 生成 artifact，不上传微信 |
| Gate A RC | 全部 Job重跑 | 受保护测试环境 Secret | 经批准后可人工上传体验版 |
| Gate B RC | 全部 Job + Gate B 专项 | 受保护生产候选 Secret | 经双人/明确审批后提审 |
| 定时 | 依赖审计、可选工具链兼容检查 | 最小读取权限 | 无发布 |

## 6. 历史 9.2 完成定义与当前候选重开项

以下 `[x]` 仅表示 Phase 9.2 的 M0–M2 历史基线完成；不表示当前 M7 候选已经通过：

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

当前 M7 候选重新关闭结果：

- [x] 修复后的同一干净 PR checkout 完成八类 Job 8/8，保存 Run 34129910349 与 7 组 artifact；
- [x] MySQL Job 在远端精确覆盖 M0–M7、M5→M6→M7 历史重放、M7 snapshot、联合
  `21 passed` JUnit 和成功 cleanup 步骤；
- [x] Wallet 扩展 MySQL 门槛已独立完成本地候选验证：Wallet `9 passed`、三域联合 `30 passed`；
- [x] Wallet-expanded workflow 已由 head `62f807a...` 的 Run 34134341829 在干净 Runner
  复现，JUnit/cleanup artifact 上传步骤均 success；
- [ ] 其后新增的 Gate A 运维与 MARD 入口尚待后续干净 SHA 的远端 Runner 复现；
- [x] 当前前端/OpenAPI/微信 production artifact、依赖审计与仓库卫生都绑定上述 Run；
- [ ] Gate A 持久升级、真实 RC、微信后台和真机继续由后续 Gate 单独授权，CI 不自动执行。
