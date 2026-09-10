# Gate A 持久部署

> **Status:** 持久 Gate A 当前为 M7；M7→M8→M9 updater 已完成仓库候选，须在 CI 通过后才能持久执行；DNS/HTTPS 和真机待完成
> **Scope:** 微信小程序受邀内部测试环境；不是 Gate B 正式生产

本目录把 Phase 9.3 已验证的一次性演练拓扑收敛为单服务器长期 Gate A
环境。数据库、Redis、应用和图片只在 internal Docker network 中通信；仅
Nginx 可以加入 edge network。任何命令都不得把 3306、6379 或 8000 发布到
宿主公网。

2026-09-08 的持久成功点是 M7 Runtime `73dca350...` 和数据后 Backup
`20260908t021224z`；M8/M9 尚未应用 Gate A。历史 M7→M8 updater 已由 head
`62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、Run 34288613644 验证；当前候选把同一
保护链扩展到 M9、30 桌 bootstrap/replay、桌台一致性核验和常驻 sweeper。当前候选必须
先取得自身干净 SHA 的 CI 全绿证据，再允许执行已明确授权的持久 M7→M8→M9 流程。

## 文件

| 文件 | 用途 |
|------|------|
| `compose.yml` | MySQL、Redis、App、Nginx、显式迁移和三个固定数据卷 |
| `compose.loopback.yml` | 备案等待期只绑定 `127.0.0.1:18080` |
| `compose.tls.yml` | ICP/DNS/证书完成后才允许发布 80/443 |
| `compose.bootstrap.yml` | 一次性 SUPER_ADMIN Bootstrap；不属于常驻服务 |
| `compose.restore.yml` | 独立 MySQL/空 Redis/图片卷/Restore App；无宿主端口，验证后删卷 |
| `nginx/loopback.conf` | SSH 隧道/宿主环回 Smoke，不构成微信 RC 证据 |
| `nginx/tls.conf.template` | 真实 Gate A HTTPS、ACME、图片和反向代理 |
| `config.env.example` | 非 Secret 配置模板；真实文件位于 `/etc` |
| `target.env.example` | 非 Secret 连接目标；固定 Gate A SSH 为 `ubuntu@118.195.195.59`，微信内部验收为 `develop` |

Gate A 当前唯一获授权的 SSH 目标是 `ubuntu@118.195.195.59`。该值是非 Secret
连接标识，固化于 `target.env.example`；私钥路径、密码、Token 和其他凭据
仍只能保留在仓库外。现场命令必须核对完整 `user@host`，不得用别名、
空变量或其他主机替代。

仓库因兼容既有 workflow/branch protection 保留文件名
`scripts/ci/gatea_m7_m8_drill.py` 和 CI Job ID `gatea-m7-m8-updater`；当前语义是独立
M7→M8→M9 CI 编排器，不是持久部署入口。它只在
GitHub-hosted disposable Linux Runner、root、显式 sentinel、本地 Docker daemon 且
固定 Gate A 资源全部不存在时运行。CI 会用一次性随机 Secret 建立 source M7，真实完成
Backup/独立 Restore、M9 plan/apply/停服 replay、target `app-up`、HEX/gzip/PNG、30 桌、
table reconcile/sweep 验收和 M9 数据后 Backup/Restore，并在成功/失败的内部 `finally`
与 workflow `always()` 补偿步骤
精确回收资源。上传 artifact 同时受脱敏白名单和最终安全扫描 marker 约束；dump、图片
tar、配置、Secret、密码和 Token 不上传，扫描失败时先清空候选上传目录再重建最小安全
失败证据。

Run 34288613644 的历史 `gatea-m7-m8-updater` Job 已在 GitHub-hosted disposable Ubuntu/Linux
root、本地 Unix Docker daemon 上走通 14/14 阶段：source SHA
`73dca350505d43775fb1ff1158ccf6aabc221998`，M7 source Backup/同 ID Restore
`20260908t230214z`、M8 target Backup/同 ID Restore `20260908t230329z` 均通过；Runtime
核验 221 个 HEX、gzip `63445→10948` bytes（减少 `52497`）和 PNG 回退。上传 artifact
只有 20 个白名单文件并通过 Secret 扫描；首次 `compose-down` 瞬态失败后第二次清理成功，
最终零残留。Run 首 attempt 的 OpenAPI Job 只在安装阶段遇到 pip truststore 瞬态异常，
相同提交重跑通过，不是 OpenAPI Schema 漂移。该演练只能证明当时的 M8 候选在一次性
MySQL 8.0.46/Linux 上走通过完整 updater；它不
复用或授权 `/etc/pinkdoohub/gatea`、`/srv/pinkdoohub/gatea`、真实 Gate A 卷、DNS、TLS
或微信环境，也不能替代当次持久 Backup/Restore、目标 Image ID、RC 与真机验收。

App 对客户端声明支持 gzip 且不小于 1 KiB 的文本响应执行 level 6 压缩；两份 Gate A
Nginx 配置也以相同阈值/级别压缩 JSON、JavaScript、XML、SVG、CSS 和纯文本，并通过
`Vary: Accept-Encoding` 保持缓存正确。上游已经设置 `Content-Encoding` 时 Nginx 不会
二次压缩，PNG/JPEG/WebP 等图片 MIME 不在压缩列表中。当前固定的标准 Nginx 镜像没有
Brotli 模块，本次不为此更换镜像或引入第三方动态模块。

Gate A Runtime 关闭 Uvicorn 自带 access log，由 Nginx 统一记录访问；Nginx 会把
`/api/v1/table-codes/<token>` 固定投影为 `/api/v1/table-codes/<redacted>`。应用异常日志
使用相同脱敏规则，避免公开桌台定位符进入持久日志。不得为调试临时重新打开未经脱敏的
Uvicorn access log。

共享应用镜像由 `deploy/runtime/Dockerfile` 构建，Phase 9.3 演练与 Gate A
使用同一非 root Runtime，避免两套入口脚本漂移。

## 不可跨越的边界

- Compose 必须使用完整 Git SHA 镜像标签，禁止 `latest`。
- App 启动不自动执行 Aerich；迁移是独立 `operations` profile。
- 常驻 Secret 只通过 `/run/secrets` 文件注入；非 Secret `config.env` 中禁止
  `DB_PASSWORD`、`REDIS_URL`、`JWT_SECRET_KEY` 和 Root 密码。
- App 不获得 MySQL Root 密码；Nginx 不获得任何应用 Secret。
- Bootstrap 临时密码文件只在明确操作时挂载，完成首次/重放/登录/轮换后删除。
- `docker compose down --volumes`、`docker volume prune` 和
  `docker system prune --volumes` 禁止进入普通部署流程。
- Loopback 模式和 TLS 模式不能同时合并使用。
- TLS override 只有在备案、DNS、证书、腾讯云防火墙和微信合法域名步骤分别
  取得授权后才可启用。

## 服务器路径与权限

```text
/etc/pinkdoohub/gatea/config.env                         root:root 0640
/etc/pinkdoohub/gatea/secrets/                           root:root 0700
/etc/pinkdoohub/gatea/secrets/mysql_app_password         root:10001 0440
/etc/pinkdoohub/gatea/secrets/mysql_root_password        root:root 0400
/etc/pinkdoohub/gatea/secrets/redis_password             root:10001 0440
/etc/pinkdoohub/gatea/secrets/jwt_secret                 root:10001 0440
/run/pinkdoohub-gatea/bootstrap_password.pending        root:10001 0440（仅临时）

/srv/pinkdoohub/gatea/releases/<git-sha>/
/srv/pinkdoohub/gatea/current -> releases/<git-sha>
/srv/pinkdoohub/gatea/backups/mysql/
/srv/pinkdoohub/gatea/backups/images/
/srv/pinkdoohub/gatea/records/{releases,backups,restores,bootstrap}/
/srv/pinkdoohub/gatea/staging/
```

真实 Secret 值不得写入本文、仓库、命令行参数、聊天、日志或 Release Record。
Secret 目录本身保持 `root:root 0700`，因此宿主普通用户无法遍历。三个 App Runtime
Secret 使用未分配给宿主账号的数值 GID 10001 和 `0440`，使 Compose bind mount
保留宿主权限时，容器内 UID/GID 10001 仍能只读；MySQL Root Secret 继续保持
`root:root 0400`，App 不挂载它。临时 Bootstrap Secret 使用同一 Runtime
GID/mode，但只写入 `/run` tmpfs，并在完成登录与轮换后删除。

## 受控生命周期命令

Root 创建真实配置后，先执行只读预检。预检只检查非 Secret 配置语义、Secret
文件元数据/非空大小、环回端口和 Compose 渲染，不输出 Secret 值，也不创建
Docker 资源：

```bash
sudo python -m scripts.release.gatea_operations \
  preflight \
  --mode loopback
```

TLS 模式必须在真实证书和 ACME 目录准备完毕后才能预检：

`GATEA_LETSENCRYPT_DIR` 必须指向完整的 Let’s Encrypt 根目录（通常为
`/etc/letsencrypt`），不能只指向 `live/<域名>`；完整挂载才能保留证书指向
`archive/` 的软链接。

```bash
sudo python -m scripts.release.gatea_operations \
  preflight \
  --mode tls
```

生命周期脚本支持空库首次部署，以及经批准的既有 M2/M7→M9 升级。仓库候选提供
显式 `gatea_upgrade --source-version 7` 的 M7→M8→M9 入口；只有当前候选自身完成全部
required Job，且真实 Gate A 当次只读状态、Backup/Restore、目标 SHA/Image 和授权均匹配，
才允许在持久环境执行。所有已有写操作都会再次验证
Root 配置/Secret、完整 SHA 镜像、镜像 revision、UID/GID、Entrypoint 和 CMD；TLS
写操作仍被拒绝。既有库 upgrade apply 还会在停止 App/Nginx 前，以镜像默认 Entrypoint
挂载并加载 Runtime Secret，执行一次不连接数据库的 production Settings 预检。迁移、
Wallet 和 MARD 一次性任务同样保留该 Entrypoint，禁止用 `--entrypoint python` 绕过
Secret 注入。

```bash
# 只读输出精确 Aerich 链、Schema 数量/指纹和关键业务聚合。
sudo python -m scripts.release.gatea_operations \
  database-status \
  --mode loopback

# 只启动 MySQL/Redis；失败时停止服务但保留命名卷。
sudo python -m scripts.release.gatea_operations \
  infra-up \
  --mode loopback

# 只允许空 application schema；迁移成功后原子记录 SHA 与 Image ID。
sudo python -m scripts.release.gatea_operations \
  initial-migrate \
  --mode loopback

# 必须存在与候选 SHA/Image ID 匹配的首次迁移或既有库升级 Record；复核唯一发布端口。
# 对 M7→M9，调用本命令前还必须按下文重放同一 gatea_upgrade plan 并取得
# already_current=true；app-up 本身不会重读 live DB、图片卷或运行 MARD preview。
sudo python -m scripts.release.gatea_operations \
  app-up \
  --mode loopback

# 只输出 service/state/health、候选 SHA 和迁移记录布尔状态。
sudo python -m scripts.release.gatea_operations \
  status \
  --mode loopback

# 停止服务但不删除容器、命名卷、Secret 或迁移记录。
sudo python -m scripts.release.gatea_operations \
  safe-stop \
  --mode loopback
```

`initial-migrate` 在运行 Aerich 前通过 MySQL 容器内 Root Secret 查询
`information_schema`，只有目标 application schema 为 0 张表才继续。候选已有匹配
迁移记录时严格重放为 no-op；记录缺失但数据库非空时 fail closed，不会猜测状态或
使用 `--fake`。`app-up` 完成后要求 App/Nginx 均为 healthy，且只有 Nginx 发布
`127.0.0.1:${GATEA_LOOPBACK_PORT}:8080`。M9 后 `app`、`table-sweeper`、`mysql`、
`redis`、`nginx` 五项常驻服务都必须为 healthy。

`database-status` 只接受已有健康 MySQL，输出当前候选、应用版本、精确 Aerich 链、
Schema 的列/索引/约束数量与确定性 SHA-256，以及 M2 已存在关键表的行数和金额/库存
聚合。它不启动、停止或迁移服务，也不输出配置值、Secret、PII 或业务明细；执行人应
将完整 JSON 作为升级前证据保存到仓库外受控位置。该命令只解决只读起点确认，仍不
构成非空库升级授权。

`gatea_backup.py backup` 会从只读数据库摘要精确区分 M7/M8 与 M9：M7/M8 写前备份只
要求并恢复 App/Nginx，不启动尚无对应表的 `table-sweeper`；M9 备份则先要求 sweeper
健康，把它与 Nginx/App 一起停止后再读取停写摘要和导出资产，成功后必须与 App/Nginx
一起恢复健康。精确 M9 链同时生成 `m9-table-business-v1`，对四张桌台业务表
进行稳定主键顺序内容摘要；独立 Restore 必须重算一致。原始 Token 和行内容只能
存在于权限 `0600` 且由 trap 删除的容器临时文件，Record/CI artifact 只保存
profile、schema version 和 SHA-256。普通 `gatea_operations app-up` 仍默认严格要求 M9 sweeper；旧版本分支
只存在于备份器对批准 Aerich 链的内部调用，未知或中途变化的迁移链一律 fail closed。

候选镜像内另有三个只供受控非空升级编排调用的执行原语：

- `python -m app.tasks.gatea_migrate_step --target-version <3..9>` 在容器 `/tmp`
  生成只含目标及更早迁移的短期目录，通过 Aerich 公开接口一次只应用一条迁移；当前
  链必须精确等于目标前一版本或目标版本，未知起点和跳级均拒绝。
- `python -m app.tasks.gatea_wallet_prepare` 只允许 production MySQL；先执行 Wallet 与
  legacy settlement 双 preview，存在 blocker 时保持零写入，再冻结 ID 上界 apply、
  二次 preview 并执行全量 reconcile。输出仅含聚合计数。
- `python -m app.tasks.gatea_mard_publish` 默认 preview；M8 后以精确 manifest SHA-256
  确认 apply，将 221 槽事务更新并把 221 张 `0644` PNG 原子写入持久图片卷，失败只
  补偿本轮新文件。已有 Online 引用时仅允许目录/图片严格一致的 no-op，apply 仍在
  事务内锁定、重读和复验，零数据库/图片写入。

这些模块不自行验证目标主机、停写、Backup/Restore Record 或候选镜像身份，因此
不得脱离经批准的宿主编排单独在持久环境运行。尤其不能用内部 M8/M9 单步原语绕过
`gatea_upgrade --source-version 7` 的完整保护。

宿主机上的 `scripts.release.gatea_*` 编排入口只能依赖 Python 标准库和 Docker CLI；
不得在模块导入阶段加载 Aerich、Tortoise 或其他应用 Runtime 依赖。迁移、Wallet 与
MARD 任务只允许通过目标 App 镜像内的 `app.tasks.*` 执行。

### M2/M7→M9 非空升级候选（仅按当次授权与证据执行）

`gatea_upgrade.py` 是既有库升级的受保护入口。旧调用为兼容历史流程默认只接受精确
M0–M2 Aerich 链；当前 M7 必须显式提供 `--source-version 7`，否则在读取 Backup、停止
业务入口或产生写入前 fail closed。它不把一次性 MySQL 的其他历史起点自动批准为
持久起点。执行前必须先在 source 配置下生成 24 小时内的新 Backup，并完成相同 Backup
ID 的无端口独立 Restore；随后把受保护配置切换为已经构建和检查的目标 SHA 镜像。

下面展示当前 M7 路径的参数形状。plan 默认只读；apply 只接受与当次成功 CI、
Backup/Restore、目标 SHA/Image 及明确写授权完全一致的身份：

```bash
sudo python -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 7 \
  --source-candidate-sha <source-40位-sha> \
  --backup-id <YYYYMMDDtHHMMSSz>
```

真正写入必须把 plan 输出的四个身份逐项原样确认：

```bash
sudo python -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 7 \
  --source-candidate-sha <source-40位-sha> \
  --backup-id <YYYYMMDDtHHMMSSz> \
  --apply \
  --confirm-source-sha <source-40位-sha> \
  --confirm-target-sha <target-40位-sha> \
  --confirm-backup-id <YYYYMMDDtHHMMSSz> \
  --confirm-manifest-sha256 <plan-manifest-sha256>
```

入口在任何数据库写入前校验 Root/Secret/目标 Image ID、新鲜 Backup 与 Restore PASS
Record、健康的四项服务和显式起点；随后停止 Nginx/App，并要求停写后的数据库和图片
与备份完全一致。M7/M8 Backup 还必须带版本化 `m7-preserved-business-v1` 内容摘要：它对
20 个非 `bead_colors` 业务表做稳定主键顺序的数据 dump，再追加 `bead_colors` 的 M7
字段投影（含 ID/时间戳、slot/code/name/URL/sort/active，不含 M8 `swatch_hex`），共覆盖
21 个业务表；Aerich 精确链和完整图片 manifest 仍分别绑定。Restore 必须重算并精确匹配
同一摘要，旧的 M7 Backup 若没有该字段会被拒绝。

停写源与 Backup 匹配后、运行 M8 原语前，M7 路径还执行 raw source preflight：
`information_schema` 必须证明 `swatch_hex` 列为 0；只读取 M7 已有字段的 raw SQL 必须按
slot 逐项精确匹配冻结 manifest 的 221 条 code/name/URL/sort/active；221 张预期兼容 PNG
必须是普通文件而非软链接，内容 SHA-256 精确匹配且权限为 `0644`。额外 Product 图片可
存在，但完整图片 manifest 已先与 Backup 精确比较。任一检查失败都发生在 M8 迁移任务
之前。M7 路径随后执行 M8 → MARD preview/apply/replay → M9 → 30 桌
bootstrap/replay，不重复 M3–M7、Wallet backfill 或代表数据；三次 MARD 结果都必须为 `already_current=true`、`database_changes=0`、
`images_to_create=0`、`images_reused=221`、`created_images=0`。迁移结束后再次计算同一
21 表 M7 保留内容摘要，并要求与停写源完全一致；随后核验 M9 四表结构、30 桌定义、
零初始 Session/Occupancy、`table_reconcile` 和 `table_sweep`。历史 M2 路径仍按
M3 → M4 → Wallet → M5 → M6 → M7 → M8 → MARD → M9 → Table Bootstrap 执行。

只有全部通过才生成 `<target-sha>.existing-database-upgrade.json`；Record 必须绑定合法的
M2→M7、M2→M8、M2→M9 或 M7→M9 组合，M7→M9 还必须明确 `source_version=7`。成功后 App/Nginx
继续保持停止。执行人复核 Record 后，必须在无旁路写入的同一停写窗口立即以完全相同的
`--source-version 7`、source SHA 和 Backup ID 重跑上方 plan 命令；已有成功 Record 的
重放会校验证据路径/哈希、当前最终数据库摘要、完整图片 manifest、21 表 M7 保留内容
摘要，并再次运行只读 MARD preview，只有返回 `already_current=true` 才能继续：

```bash
# 使用与成功 apply 完全相同的 source SHA、Backup ID 和目标 config；不得增加 --apply。
sudo python -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 7 \
  --source-candidate-sha <source-40位-sha> \
  --backup-id <YYYYMMDDtHHMMSSz>

# 上一命令必须成功且输出 already_current=true、mode=plan-replay 后才能执行。
sudo python -m scripts.release.gatea_operations \
  app-up \
  --mode loopback
```

`app-up` 同时接受该 Record 与空库 `initial-migration` Record，但它只验证 Record 与当前
target SHA/Image ID/合法迁移组合并启动服务；它**不会**重读 live DB、图片卷、M7 内容
摘要、MARD 或桌台状态。因此 M7→M9 的上述紧邻 replay verification 是强制前置条件，不能用
“Record 已存在”代替。replay 与 `app-up` 之间也必须维持 App/Nginx 停止且不存在直接
SQL、迁移原语或宿主图片写入。失败不自动恢复服务、不 downgrade、不 fake；失败或中断
的 evidence 会阻断盲目重跑，必须先人工确认实际 Schema/Aerich 并另行批准处置。

当前 Gate A 有 Online 自选色 Kit 与启用色。publisher 候选只有在迁移后 221 个 HEX 与
manifest 逐项相等、既有 221 张兼容 PNG 内容/权限不变且无需创建时才允许 no-op；任何
变化仍拒绝。不能为了通过 preview 临时下架商品或修改启用态，也不能脱离升级编排直接
调用。纯数字色块不转 WebP、不删除这批回退文件。该 M7 路径及 publisher 安全分支已
通过本轮本地 `tests/release` `229 passed`，完整后端为
`2317 passed, 33 skipped in 125.31s`。独立只读代码审查发现成功重放没有重新证明
App/Nginx 仍停服；修复并补齐服务状态 fail-closed 矩阵后复核无未解决 P0–P3。上述
实现与复核的历史加固点绑定 head `fa6fce05...`、merge-ref `b2f02ebc...` 和
Run 34281512196 的远端 8/8；当前完整 updater 证据进一步绑定 head `62b1b15...`、
merge-ref `a9ff3d2...` 和 Run 34288613644 的 9/9。持久执行和现场验收仍未完成。

上述一致性依赖受控维护窗口：App/Nginx 停止后，不得有直接 SQL、另一个迁移进程、容器
外脚本或宿主机图片写入。数据库内容摘要、MySQL 事务锁与图片 manifest/原子文件替换是
相互补强的边界，但不构成跨数据库与文件系统的绝对原子事务；发现旁路写入可能性时必须
保持 No-Go，不能把本流程描述为可抵御任意外部写入。

## 受控 SUPER_ADMIN Bootstrap

`gatea_bootstrap.py` 是持久 Gate A 唯一批准的 Bootstrap 编排入口。它要求 Root、
完整 Runtime image/首次迁移 Record、MySQL/Redis/App/Nginx 四项健康、唯一 loopback
publisher，以及精确重复的用户名确认。命令不接受任何密码参数或密码环境变量；
初始密码和最终密码都通过 TTY 各隐藏输入两次，且最终密码必须不同。

执行前由 Root 创建脱敏 Record 目录：

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/bootstrap

sudo python -m scripts.release.gatea_bootstrap \
  --username <approved-username> \
  --nickname <approved-nickname> \
  --phone <approved-phone> \
  --confirm-username <approved-username> \
  --apply
```

初始密码只短暂写入 tmpfs 上的
`/run/pinkdoohub-gatea/bootstrap_password.pending`，权限为 `root:10001 0440`；
首次创建后使用同一 Secret 严格重放，要求 SUPER_ADMIN/Audit 各唯一且用户时间戳
不变。随后脚本只经 `127.0.0.1` Nginx 执行初始登录、密码轮换、旧密码拒绝、
新密码登录、两次 Refresh 会话注销与撤销验证。成功或失败都会删除临时 Secret 和
一次性容器；成功 Record 固定为
`records/bootstrap/super-admin-bootstrap.json`，只记录用户 ID、计数、候选、布尔
证据和 UTC 时间，不记录 username、nickname、phone、密码、Token 或密码 hash。

已有成功 Record 时命令 fail closed；不得删除 Record 后尝试创建第二个
SUPER_ADMIN。若操作返回失败，先保留数据库与日志现场并确认临时 Secret 已删除，
再按同一批准身份和已知初始密码决定是否恢复执行，不能改用不同身份绕过严格重放。

## 受控代表性备份数据

`gatea_representative_data.py` 只允许在 Bootstrap 已通过、业务表仍为空且图片卷无文件
时执行一次。工具先绑定 Runtime image、迁移/Bootstrap Record、四项服务健康和唯一
loopback publisher，再要求执行人通过 TTY 隐藏输入并确认当前 SUPER_ADMIN 密码；
密码不接受参数或环境变量，不写文件、日志或 Record。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/representative-data

sudo python -m scripts.release.gatea_representative_data \
  --super-admin-username <approved-username> \
  --confirm-super-admin-username <approved-username> \
  --apply
```

写入全部经过当前 `127.0.0.1` Nginx 和正式 API：一个随机临时密码的合成 USER、一个
Online Experience/Option、一个 Online Kit、三张真实 PNG、库存调整/订单扣减/取消
恢复，以及 Cancelled 混合订单和 Completed 体验订单。流程结束前注销并验证撤销
合成用户会话、禁用合成用户、拒绝其再次登录，并注销/撤销本次 SUPER_ADMIN 会话。
随机合成密码只存在于进程内存，不返回给调用者。

成功 Record 只保存前后计数、内部 ID、业务断言和清理布尔值，不保存真实管理员
身份、合成身份、密码、Token、手机号或 hash。任何部分失败都不写成功 Record，并
尽力注销两个会话、禁用已经创建的合成用户；此时必须保留现场人工审计，不能删除
订单或绕过空基线重跑。

## 受控备份与隔离恢复

`gatea_backup.py` 只备份权威 MySQL 与商品图片。Redis 当前只保存 refresh-token
会话，恢复旧快照可能重新激活应失效的会话，因此恢复环境固定启动空 Redis，使
全部旧 refresh 会话失效。备份 ID 必须使用 UTC `YYYYMMDDtHHMMSSz`；备份短暂
停止 Nginx/App 形成停写窗口，MySQL/Redis 保持运行，完成后自动恢复 App/Nginx
并再次验证 health。SQL/Tar 为 `root:root 0600`，Record 只保存摘要、计数、路径、
checksum 和 Redis 策略，不保存 Secret 值。

M7/M8 的 `m7-preserved-business-v1` 由一次 20 表 `mysqldump --single-transaction` 与随后
一次 `bead_colors` M7 投影查询组成，临时内容文件为 `0600` 并在正常/错误/信号退出时
清理，Record 只保存版本、profile 和 SHA-256，不保存业务行或 PII。两次读取并不是同一个
数据库事务；其一致性前提是 App/Nginx 已停止且没有任何直接数据库写入。若无法排除旁路
写入，Backup 不得作为升级依据。

```bash
backup_id=20260902t120000z

sudo python -m scripts.release.gatea_backup \
  backup \
  --backup-id "$backup_id" \
  --mode loopback

sudo python -m scripts.release.gatea_backup \
  restore-verify \
  --backup-id "$backup_id" \
  --confirm-project "pinkdoohub-gatea-restore-$backup_id" \
  --mode loopback
```

恢复只写入精确确认的独立 project、internal network 和两个临时 named volumes；
不加入来源 project、不挂载来源卷、不发布宿主端口。工具比较数据库 Schema/诊断摘要、
图片内容 manifest；对精确 M7/M8 链还重算并比较 `m7-preserved-business-v1` 内容摘要，
覆盖 20 个非 `bead_colors` 表与 `bead_colors` M7 投影；M9 链在此基础上额外重算
`m9-table-business-v1`，覆盖桌台、Session、Timer 和 Occupancy 四表。随后启动 Restore App 验证
readiness，并在成功、失败和中断路径执行精确 `down --volumes` 后复核恢复容器/卷消失。
来源 Gate A 服务和三个持久卷不属于清理目标。

同机备份只能证明流程和恢复能力，不能覆盖服务器或系统盘故障。Gate A Go 前仍需
定义保留期，并把批准备份加密复制到独立故障域；工具不自动上传或删除备份。

### 客户端加密异机副本

`gatea_offsite_backup.py` 在受控管理电脑执行，不把解密私钥发送到服务器。它通过
现有只读 SSH 身份下载精确 Backup/Restore Record 与两个 Artifact，在权限为 `0700`
的本机临时目录重算来源 checksum；随后使用随机 AES-256-GCM 数据密钥加密、用独立
RSA-3072 OAEP-SHA256 公钥封装数据密钥。成功后必须用私钥完成 AEAD 解密、Bundle
成员白名单、数据库/图片 SHA-256 和 Restore PASS Record 的再次验证。export 前与解密
verify 都会按精确 Aerich 链重新执行内容证据契约：M7/M8/M9 必须有完全相同的
`m7-preserved-business-v1` 和 `m7_content_matches=true`；M9 还必须有完全相同的
`m9-table-business-v1` 和 `m9_table_content_matches=true`。缺失、结构无效、摘要不等、
match 为 false、未知迁移链或版本证据混装均 fail closed；加密/文件哈希本身不代替这项语义校验。

```bash
python -m scripts.release.gatea_offsite_backup keygen \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem" \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem"

python -m scripts.release.gatea_offsite_backup export \
  --backup-id <YYYYMMDDtHHMMSSz> \
  --host <gate-a-host> \
  --user <ssh-user> \
  --identity-file <ssh-private-key> \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem" \
  --destination-dir "$HOME/Backups/pinkdoohub/gatea"

python -m scripts.release.gatea_offsite_backup verify \
  --copy "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb" \
  --record "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb.json" \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem"
```

私钥目录固定 `0700`、私钥 `0600`、公钥 `0644`；加密副本 `0400`，脱敏客户端
Record `0600`。密钥与副本必须位于仓库外且相互分离；脚本拒绝覆盖已有 key/copy，
不提供自动删除。私钥丢失会使副本不可恢复，因此其离线恢复保管仍由项目负责人负责。

## 依赖故障、应用重启与日志观察

`gatea_resilience.py` 只在代表性数据成功 Record、Runtime/迁移绑定、四项 Healthy 和
唯一 loopback publisher 全部匹配时对当前 candidate SHA 执行一次。成功 Record 固定为
`gatea-resilience-<40位SHA>.json` 且不覆盖；历史候选记录保留，但不阻断新候选重新演练。
首次迁移要求代表性数据 Record 精确匹配当前 SHA/Image；既有库升级则只接受升级
Record 冻结的 source SHA/source image 对应历史 Record，由升级过程的数据不漂移证据
建立链路，不删除或伪造为新候选。它依次停止 MySQL、Redis，要求依赖
故障时 readiness 为 503 而 liveness 保持 200；恢复各依赖并等待 readiness 200 后，
再重启 App。最终比较完整数据库摘要与图片 manifest，验证四项服务、端口、Docker
日志轮转、24 小时 Nginx 请求数量/4xx/5xx/时延，并以内存中的四项真实 Secret 扫描
日志但不记录日志正文或 Secret 值。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/resilience

sudo python -m scripts.release.gatea_resilience --apply
```

任何阶段失败都先尝试恢复 MySQL、Redis、App 和 Nginx，再返回失败且不写成功 Record；
不得为了得到 PASS 删除代表性数据、当前候选 Record 或绕过日志匹配。

运维工具仍故意不提供备份删除、来源卷恢复、TLS 切换或公开发布命令；这些步骤
必须分别实现、测试和 Review，不能用未经审查的现场 Shell 绕过。

## 后续执行顺序

1. 从干净 Git SHA 构建 `pinkdoohub-gatea:<40位SHA>` 并记录 image ID。
2. Root 创建配置/Secret/持久运维目录；运行 loopback preflight。
3. 只读重新确认当前 Gate A 为精确 M7，并与 M7 upgrade/Backup/图片 Record 比较；任何
   不一致先停止。空库才可使用 `initial-migrate`，两条路径不得混用。
4. 当前 M7→M8→M9 候选必须先完成干净远端 required Jobs；通过后对持久目标重新只读
   盘点，再创建新的 MySQL/图片 Backup 并完成同 ID 独立 Restore。
5. 取得明确写授权后，只通过该编排应用 M8/M9 并核验 Aerich M0–M9、221 个精确 HEX、
   MARD/PNG 与 `m7-preserved-business-v1` 零漂移；成功后保持停写，以相同参数重放
   `gatea_upgrade` plan，确认 live DB、图片、M7 内容摘要、MARD preview、30 桌及一致性
   全部匹配，再紧邻使用 `app-up`。仅复核 upgrade Record 不足以启动。
6. 验证 liveness/readiness、`table-sweeper`、唯一 loopback publisher、HEX API/小程序直绘，
   以及 gzip 只压文本且不重复编码；再创建 M9 数据后 Backup/Restore 和加密异机副本。
7. 既有 Bootstrap 与 M7 综合数据不重复创建；只执行必要的登录/只读 reconcile/Smoke。
8. ICP 通过后再配置 DNS、证书、80/443 和 TLS override。
9. 将同一 SHA 绑定后端、OpenAPI 和微信 RC，配置合法域名并执行真机矩阵。

任一步失败都保持 Gate A `No-Go`。本目录不授权体验版上传、分发、提审或公开
发布。
