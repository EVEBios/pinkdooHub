# Gate A 持久部署

> **Status:** live Gate A 是旧候选 A/M9，`current` 仍指向 M7 lineage S；候选 B 留下 `prepared` retirement pending，候选 C 的 pre-install isolated stage 在零现场写入前失败并已清理，当前只允许全新候选 D 在自身 9/9 后执行受控 A→B→D takeover 与 M9→M9 零迁移前滚，DNS/HTTPS 和真机仍待完成
> **Scope:** 微信小程序受邀内部测试环境；不是 Gate B 正式生产

本目录把 Phase 9.3 已验证的一次性演练拓扑收敛为单服务器长期 Gate A
环境。数据库、Redis、应用和图片只在 internal Docker network 中通信；仅
Nginx 可以加入 edge network。任何命令都不得把 3306、6379 或 8000 发布到
宿主公网。

2026-09-08 的最后 finalized lineage 是 M7 Runtime
`73dca350505d43775fb1ff1158ccf6aabc221998`；2026-09-11 的 live config、数据库和五服务
已经由旧候选 A `d6c09482ee0f5583d79bd847e995746c9c6ee1a3` 推进到 M9，但 A 的
admin-assisted acceptance 未通过，`current` 也尚未离开上述 M7 lineage。历史 M7→M8
updater 已由 head
`62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、Run 34288613644 验证；当前实现把同一
保护链扩展到 M9、30 桌 bootstrap/replay、桌台一致性核验和常驻 sweeper。旧恢复候选 B
`ad2ac8c1eb6633daebf3d66d9b3669e441c3c6dd` 只留下 `prepared` retirement pending。候选 C
head `e909c42cebaf59931536ddc2c82a43f19a29925c` / merge target
`c709d6252a07d65eb1457b23e7036ecb736f18b8` 已由 Run 34616037853 取得 9/9，但真实 stage
在任何 C pending/Image/Release 写入前因隔离 launcher 误调用已安装 Release 模块而安全失败，
清理后 A/B/S 与三份受保护 digest 均不变，C 无现场残留。全新候选 D 必须先取得自身干净
SHA 的 CI 9/9，才允许执行本文的 takeover retirement 与 M9→M9 adoption。不得把 live 数据库
当成 M7、重跑迁移、删除 pending，或用 A/B/C/旧 Run 的通过项拼接 D 的证据。

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
Uvicorn access log。当前仓库的默认镜像校验仍严格要求 `--no-access-log`；2026-09-08
已留证的旧 M7 镜像缺少该参数，兼容只能由 M7 Backup 的内部恢复路径启用，
不是 `gatea_operations app-up` 的 CLI 放宽开关。

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
/etc/pinkdoohub/gatea/config-history/                    root:root 0700
/etc/pinkdoohub/gatea/secrets/                           root:root 0700
/etc/pinkdoohub/gatea/secrets/mysql_app_password         root:10001 0440
/etc/pinkdoohub/gatea/secrets/mysql_root_password        root:root 0400
/etc/pinkdoohub/gatea/secrets/redis_password             root:10001 0440
/etc/pinkdoohub/gatea/secrets/jwt_secret                 root:10001 0440
/run/pinkdoohub-gatea/bootstrap_password.pending        root:10001 0440（仅临时）
/run/lock/pinkdoohub-gatea-operation.lock                root:root 0600

/srv/pinkdoohub/gatea/releases/<git-sha>/
/srv/pinkdoohub/gatea/current -> releases/<git-sha>
/srv/pinkdoohub/gatea/backups/mysql/
/srv/pinkdoohub/gatea/backups/images/
/srv/pinkdoohub/gatea/records/{releases,backups,restores,bootstrap,m9-acceptance,m9-acceptance-failures,m9-retirement-failures,resilience}/
/srv/pinkdoohub/gatea/staging/
```

真实 Secret 值不得写入本文、仓库、命令行参数、聊天、日志或 Release Record。
Secret 目录本身保持 `root:root 0700`，因此宿主普通用户无法遍历。三个 App Runtime
Secret 使用未分配给宿主账号的数值 GID 10001 和 `0440`，使 Compose bind mount
保留宿主权限时，容器内 UID/GID 10001 仍能只读；MySQL Root Secret 继续保持
`root:root 0400`，App 不挂载它。临时 Bootstrap Secret 使用同一 Runtime
GID/mode，但只写入 `/run` tmpfs，并在完成登录与轮换后删除。

## 受控生命周期命令

所有会改变 Gate A，或必须基于稳定现场得出结论的持久运维入口，共用唯一的非阻塞
操作锁 `/run/lock/pinkdoohub-gatea-operation.lock`。锁必须是 `root:root 0600` 的普通文件且
不得为软链接；已有操作持锁、路径元数据不安全或无法取得锁时立即 fail closed。候选
`stage`/`retire-failed-acceptance`/`activate-config`/`rollback-config`/`finalize`、升级、备份/恢复验证、M9
admin-assisted 验收、resilience，以及 `infra-up`/`initial-migrate`/`app-up`/`safe-stop`
都从首次现场读取前一直持锁到成功 Record 或失败 journal、业务补偿和登出完成。生产 CLI
不提供锁路径覆盖参数；只读 `preflight`、`database-status` 和 `status` 不持锁，因此它们的
输出只能作为当时快照，不能替代紧邻写操作自身的复验。

操作锁只解决“当前是否有人正在执行”，durable journal inventory 另行解决“此前是否有
未收口操作”。Release Record 目录的直接子项只要以以下任一后缀结尾，就会跨候选 SHA、
跨命令统一阻断后续变更：

- `.candidate-stage.pending.json`
- `.acceptance-retirement.pending.json`
- `.config-activation.pending.json`
- `.config-rollback.pending.json`
- `.current-finalization.pending.json`

扫描不只看当前 `GATEA_APP_IMAGE`：另一候选、非法/畸形 SHA 名称，以及软链接、目录、
FIFO 等非普通文件同样 fail closed。只有正在恢复的 candidate 原命令，或 finalization
内部恢复 Runtime 时调用的 `app-up`，才可传递结构化 allowance；allowance 必须精确绑定
当前候选、动作类型和唯一 pending 路径，目录里再多一个 blocker 仍会失败。

M9 acceptance 另有同样的全候选 sidecar inventory：
`gatea-m9-runtime-acceptance-<sha>.json.pending` 与 `.json.complete`。在首次验收前该目录
可以尚不存在；一旦存在，必须是 `root:root 0755` 的真实目录。除 acceptance 原命令按
严格状态机恢复自己的一个 `root:root 0600` pending，以及自己的一个
`root:root 0600/0644` complete 外，任一候选的 sidecar 都阻断。`backup`、
`restore-verify`、upgrade plan/apply、Bootstrap、两类代表数据入口、`initial-migrate`、
普通 `app-up`、acceptance、resilience 和四个 candidate 动作都在读取数据库快照、TTY、
调用业务 API 或启动/停止资源之前执行适用的全局扫描；部分入口会先完成只读的配置/Secret
元数据校验，但不能越过 inventory 进入现场动作。这不表示不同 Backup ID 之间相互阻断，
Backup pending 仍只由消费该精确 ID 的 Restore/Upgrade 拒绝。

`infra-up` 与 `safe-stop` 是故障处置原语：它们仍必须取得唯一操作锁，但不会消费、清除或
宣称解决任何 journal/sidecar，因此可用于把数据依赖拉起或把现场停到安全状态；只要
unresolved inventory 仍在，后续迁移、启动业务服务、验收、备份或候选切换依旧被阻断。

Root 创建真实配置且尚未启动任何 Gate A publisher 时，先执行首次部署只读预检。
预检只检查非 Secret 配置语义、Secret 文件元数据/非空大小、环回端口和 Compose
渲染，不输出 Secret 值，也不创建 Docker 资源。它故意要求环回端口尚未被占用，
因此不适用于已经由健康 source Nginx 发布同一端口的既有库升级；这类升级必须使用
下方的 `status` 与 `database-status` 核验 source，并由 Backup、candidate activation 和
upgrade 在操作锁内再次校验精确现有 publisher。不得为了让 `preflight` 通过而停止健康
source、改用临时端口或绕过受保护生命周期：

```bash
sudo python3 -B -m scripts.release.gatea_operations \
  preflight \
  --mode loopback
```

TLS 模式必须在真实证书和 ACME 目录准备完毕后才能预检：

`GATEA_LETSENCRYPT_DIR` 必须指向完整的 Let’s Encrypt 根目录（通常为
`/etc/letsencrypt`），不能只指向 `live/<域名>`；完整挂载才能保留证书指向
`archive/` 的软链接。

```bash
sudo python3 -B -m scripts.release.gatea_operations \
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
sudo python3 -B -m scripts.release.gatea_operations \
  database-status \
  --mode loopback

# 只启动 MySQL/Redis；失败时停止服务但保留命名卷。
sudo python3 -B -m scripts.release.gatea_operations \
  infra-up \
  --mode loopback

# 只允许空 application schema；迁移成功后原子记录 SHA 与 Image ID。
sudo python3 -B -m scripts.release.gatea_operations \
  initial-migrate \
  --mode loopback

# 必须存在与候选 SHA/Image ID 匹配的首次迁移或既有库升级 Record；复核唯一发布端口。
# 对 M7→M9，调用本命令前还必须按下文重放同一 gatea_upgrade plan 并取得
# already_current=true 及不可覆盖 sidecar；app-up 会重读 live M9 并运行 table reconcile，
# 但不会重算图片/M7 内容摘要或运行 MARD preview。
sudo python3 -B -m scripts.release.gatea_operations \
  app-up \
  --mode loopback

# 只输出 service/state/health、候选 SHA 和迁移记录布尔状态。
sudo python3 -B -m scripts.release.gatea_operations \
  status \
  --mode loopback

# 停止服务但不删除容器、命名卷、Secret 或迁移记录。
sudo python3 -B -m scripts.release.gatea_operations \
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
一起恢复健康。当前工具新建的精确 M8/M9 Backup 还必须生成
`m8-swatch-content-v1`，按 `bead_colors.id` 稳定排序并只投影 `id`、`slot_no`、
`swatch_hex`；M9 另生成 `m9-table-business-v1`，对四张桌台业务表进行稳定主键顺序
内容摘要。独立 Restore 必须逐项重算一致。原始 Token 和行内容只能存在于权限 `0600`
且由 trap 删除的容器临时文件，Record/CI artifact 只保存 profile、schema version 和
SHA-256。普通 `gatea_operations app-up` 仍默认严格要求 M9 sweeper；旧版本分支
只存在于备份器对批准 Aerich 链的内部调用。具体地，备份器先从运行中数据库确认
精确 M0–M7，停写后再要求迁移链未变；恢复 App 时 `app-up` 还会第二次读取并要求
精确 M0–M7，然后才允许旧 M7 镜像的唯一冻结命令形状（仅缺 `--no-access-log`）。默认
`app-up`、M8/M9 Backup、未知链、停写期间变链或其他命令变体仍一律 fail closed；该
兼容路径也绝不启动 `table-sweeper`。

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
从已安装 Release 执行时必须显式使用 `python3 -B -m`，禁止 Python 在不可变 Release
目录写入 `__pycache__`/`.pyc` 并改变后续 source manifest。`stage` 是唯一不能使用
`-m` 的例外，因为它必须直接执行从同一 source archive 提取并校验过的 launcher；该入口
仍必须使用 `python3 -B <launcher>`。容器内 `python -m app.tasks.*` 不适用这项宿主约束。
不得在模块导入阶段加载 Aerich、Tortoise 或其他应用 Runtime 依赖。迁移、Wallet 与
MARD 任务只允许通过目标 App 镜像内的 `app.tasks.*` 执行。

### M9 候选安装、配置激活与回退边界

持久 Gate A 不再从任意工作目录直接 build 并替换 `current`。`gatea_candidate.py` 把
候选生命周期包含 `stage`、`retire-failed-acceptance`、`activate-config`、
`rollback-config`、`finalize` 五个互不冒充的动作；retirement 只适用于本文冻结的
cleaned pre-claim M9 acceptance 失败前滚。每个动作都使用上文唯一操作锁，source archive 与
CI artifact 必须是 `root:root 0600` 普通文件，临时 launcher 必须是 `root:root 0700` 普通
文件，所有 Record 均 root-owned、不可覆盖：

1. `stage` 校验精确 source archive、其中的目标 Git 身份、当前 Run/attempt 的 updater
   artifact、artifact 白名单/Secret 扫描/零残留、九个 required Job 确认和临时 launcher
   哈希；随后安装 `/srv/pinkdoohub/gatea/releases/<target-sha>` 并构建
   `pinkdoohub-gatea:<target-sha>`。它不改 `config.env`、运行容器、数据库或 `current`；失败
   清理临时候选镜像时最多执行两轮 `image rm`→精确 reference inventory，只有该 reference
   为空才算完成，不能只看删除命令返回码。
2. 从已安装的目标 Release 运行 `activate-config`。第一次不带 `--apply`，只用临时派生
   配置执行 M7→M9 plan；第二次必须逐项确认 source/target SHA、Backup ID 和 plan 返回的
   manifest SHA-256，才会原子地只改 `GATEA_APP_IMAGE` 与
   `TABLE_SESSION_CLAIMS_ENABLED`，并保存 `0600` 回退副本。它不迁移数据库，也不切换
   `current`。
3. `rollback-config` 只是迁移前的配置回退：仅当 live DB 仍为精确 M7、旧四服务健康、
   sweeper 未运行、`current` 仍指向 source，且目标 upgrade Record/evidence/replay 均未
   出现时，才按 activation Record 哈希恢复旧配置。任何目标升级证据一旦出现，此命令
   永久拒绝；它不是 M9→M7 downgrade 或数据恢复命令。
4. `retire-failed-acceptance` 的普通路径只接受由 target stage 绑定的 A 失败 pending；当前
   A→B→D takeover 还必须由 D schema v3 stage 精确绑定 B stage Record 与 prepared pending。
   它先建立 planned downtime，停止 App/Nginx/`table-sweeper`，在 MySQL/Redis 健康且三个
   写入方持续停止的窗口中用目标镜像只读核验 A pending 冻结的业务身份与 live M9 清理结果；
   takeover 先归档 B journal、再归档 A pending，发布脱敏 retirement Record 后依次精确移除
   两个 canonical pending，最后无条件恢复并复验 A 的五服务。
   它不修改数据库、配置或 `current`，但会临时改变 Runtime 服务状态，不能按零停机命令执行。
5. `finalize` 只能在目标 Runtime/验收/resilience/数据后 Backup+Restore 全部完成后运行；
   它复验全部 Record 的 SHA-256、时间顺序、五服务、live M9、目标 Image ID 与当前
   配置，最后才原子切换 `current`。切换 `current` 不重启 Runtime，也不能替代前述验收。

`.pending` 是状态机 journal，不是通用重跑许可。同一命令只有在 pending 内的 source/target、
Run/attempt、Record digest 和全部显式确认值与本次调用严格一致，且记录的 checkpoint 明确
允许恢复时，才可恢复自己的 pending；更早阶段、另一动作或内容冲突的 pending 一律在读取
可变现场前阻断。不得删除、覆盖或换路径绕过这一约束。

五个动作各自只恢复自己已经持久提交的阶段：`stage` 从已完成 source/CI 校验且绑定临时
镜像的 journal 收口 Release、最终镜像和 Record；`activate-config` 只在逐项 apply 确认仍
一致时，按 source/target 配置摘要判断“尚未替换”或“已经替换”并补齐 Record；
`retire-failed-acceptance` 的 takeover 只按 `prepared` → `write-free-verified` →
`superseded-retirement-archived` → `acceptance-archived` → `record-published` →
`superseded-retirement-removed` → `canonical-removed` → `runtime-restored` 收口，并且只有 A 的五服务恢复
健康后才删除自己的 retirement pending；`rollback-config` 同理只允许目标配置或
已恢复的 source 配置两种精确状态；`finalize` 则按
`prepared` → `live-rechecked` → `current-switched` → `runtime-restored` 前进。所有不可变
Record 都先向同目录随机临时文件完整写入并 file `fsync`，再用 hard-link no-clobber 发布并
同步目录；配置、journal 与 `current` 的替换也在对应父目录同步。因而进程崩溃后要么仍可
辨认上一个 checkpoint，要么明确阻断，不会把截断 JSON、同名旧证据或仅有 target symlink
误判为完成。

`stage` 必须使用从同一 source archive 取出的、已单独校验 SHA-256 的 launcher，并用
`-I` 忽略 `PYTHON*` 环境配置并隔离现场模块搜索路径；下例中的
`<source-head-sha>` 是 artifact 报告的 PR head，`<target-sha>` 是 archive 与 CI 证明的精确
checkout，两者不得凭人工推断互换：

```bash
sudo python3 -I -B <checksum-confirmed-launcher>/gatea_candidate.py stage \
  --source-archive <root-owned-source-archive.tar> \
  --confirm-source-archive-sha256 <source-archive-sha256> \
  --ci-artifact <root-owned-updater-artifact.zip> \
  --confirm-ci-artifact-sha256 <updater-artifact-sha256> \
  --launcher <checksum-confirmed-launcher>/gatea_candidate.py \
  --confirm-launcher-sha256 <launcher-sha256> \
  --target-sha <target-sha> \
  --source-head-sha <source-head-sha> \
  --ci-run-id <run-id> \
  --ci-run-attempt <attempt> \
  --ci-artifact-name gatea-m7-m9-updater-<target-sha>-<run-id>-<attempt> \
  --confirm-required-jobs 9 \
  --confirm-target-sha <target-sha> \
  --apply
```

#### 当前 A/M9 acceptance 失败与 B/prepared 阻塞的受控 D 前滚

A acceptance 到达 `order_created` 后，在读取 T01 bootstrap identity 时失败。旧实现使用
`docker compose exec`，新进程没有经过 App Entrypoint 将文件型数据库 Secret 导出为运行
环境；工具因此返回不含 Secret 的通用错误并执行补偿。已知现场为：混合 Order 已取消、
Experience/Kit fixture 已下架、Kit 库存扣减已恢复、合成与管理员会话已撤销，没有
Payment/Settlement/Refund、TableSession、Timer 或 Occupancy。A 的 schema v3 失败 pending
保留在 canonical acceptance 目录。修复读取器改为
`docker compose run --rm --no-deps app ...`，保留默认 Entrypoint 且仍不输出 Token。

不得直接用修复后的读取器重跑 A，也不得手工删除 pending、临时向 `exec` 注入数据库
环境变量、恢复 M7 数据库或改 `current`。旧恢复候选 B
`ad2ac8c1eb6633daebf3d66d9b3669e441c3c6dd` 已完成 stage，但其 retirement journal 只到
`prepared`，`live_verification` 仍为 null；它没有停写、归档或删除 A 的证据，也不能继续
作为 target。B 的 stage Record SHA-256 是
`4746500031255a70b38f0b1619ff8a27b043051be7775c5c4f1b57cd64054eab`，prepared pending
SHA-256 是 `9ad2da46bedf3b1058552c7747ee2f22a90925310ade5efc0fd9129371e8b4d5`；A 的 canonical
failure pending SHA-256 是
`89fce946b872a425e43c6db128e7734f74196fddbbc1b061b7537384cdd147a2`。三份文件都必须从
受保护现场重新计算并人工复核，本文值不能替代当次读取。

候选 C 已以 head `e909c42cebaf59931536ddc2c82a43f19a29925c` / merge target
`c709d6252a07d65eb1457b23e7036ecb736f18b8` 在 Run 34616037853 完成 9/9，但其真实
schema v3 stage 在 pre-install takeover predecessor validation 中误调用 `_runtime_modules()`，
隔离 launcher 因此提示 `activation must run from an installed candidate release`。该失败发生在
任何 C pending、Image build 或 Release 安装之前；清理后 S/A/B 身份、三份受保护 digest
和五服务均不变，C 无现场残留且不得重用。

全新候选 D 必须先以自己的精确 SHA 完成全新远端 required Jobs 9/9；不得复用 C、B、A 或
任何旧 Run 的 CI。D stage 只在 source archive、launcher、CI artifact 和完整 GitHub
provenance 验证后先第二次扫描 blocker，再以 stable no-follow exact-bytes 加载归档内标准库
限定的 operations validator 并执行 predecessor validation；不允许 `PYTHONPATH`、
`current`、A/B Release 或现场工作树 fallback，验证未通过前不得写 pending 或 build Image。
随后使用下列 schema v3 stage 绑定安装，不要把未来 D SHA、Run ID 或 attempt 预填到文档：

```bash
sudo install -d -o root -g root -m 0700 \
  /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  /srv/pinkdoohub/gatea/records/m9-retirement-failures

sudo python3 -I -B <checksum-confirmed-launcher>/gatea_candidate.py stage \
  --source-archive <D-source-archive.tar> \
  --confirm-source-archive-sha256 <D-source-archive-sha256> \
  --ci-artifact <D-updater-artifact.zip> \
  --confirm-ci-artifact-sha256 <D-updater-artifact-sha256> \
  --launcher <checksum-confirmed-launcher>/gatea_candidate.py \
  --confirm-launcher-sha256 <launcher-sha256> \
  --target-sha <D> \
  --source-head-sha <D-source-head-sha> \
  --ci-run-id <D-run-id> \
  --ci-run-attempt <D-run-attempt> \
  --ci-artifact-name gatea-m7-m9-updater-<D>-<D-run-id>-<D-run-attempt> \
  --confirm-required-jobs 9 \
  --confirm-target-sha <D> \
  --superseded-candidate-sha <A> \
  --confirm-failed-acceptance-sha256 <A-failed-pending-sha256> \
  --superseded-retirement-candidate-sha <B> \
  --confirm-superseded-retirement-stage-record-sha256 \
    <B-stage-record-sha256> \
  --confirm-superseded-retirement-pending-sha256 <B-prepared-pending-sha256> \
  --acceptance-record-dir /srv/pinkdoohub/gatea/records/m9-acceptance \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures \
  --apply
```

Stage schema v3 必须同时记录 `transition_kind=m9-candidate-adoption`、A failure digest、B
candidate、B stage Record digest 与 B prepared pending digest；否则下一步拒绝。在 D
Release 中执行 takeover retirement：

```bash
cd /srv/pinkdoohub/gatea/releases/<D>

sudo python3 -B -m scripts.release.gatea_candidate retire-failed-acceptance \
  --source-candidate-sha <A> \
  --lineage-source-candidate-sha <S> \
  --target-sha <D> \
  --failed-acceptance-sha256 <A-failed-pending-sha256> \
  --confirm-source-sha <A> \
  --confirm-lineage-source-sha <S> \
  --confirm-target-sha <D> \
  --confirm-failed-acceptance-sha256 <A-failed-pending-sha256> \
  --superseded-retirement-candidate-sha <B> \
  --superseded-retirement-stage-record-sha256 <B-stage-record-sha256> \
  --superseded-retirement-pending-sha256 <B-prepared-pending-sha256> \
  --confirm-superseded-retirement-candidate-sha <B> \
  --confirm-superseded-retirement-stage-record-sha256 \
    <B-stage-record-sha256> \
  --confirm-superseded-retirement-pending-sha256 \
    <B-prepared-pending-sha256> \
  --acceptance-record-dir /srv/pinkdoohub/gatea/records/m9-acceptance \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures \
  --apply
```

Retirement 在任何业务读取、归档或删除前先创建 `prepared` journal，并计划停止
App/Nginx/`table-sweeper`。只有 MySQL/Redis 健康、三个写入方已停止且 A/S lineage、配置与
Image 均未变化，才进入 write-free 验证；数据库 snapshot、table reconcile、wallet reconcile
与 C 镜像只读 verifier 的每一步前后都会重复断言同一停写状态。verifier 按 pending 内精确
ID 检查 Order `CANCELLED`、总额 `5.00` 与固定 remark，两个 Product 的候选后缀名称/固定
description、精确五张图片绑定、三个 Experience item 与完整 Option/duration/participants/
day-type/price/quantity 快照、一个 Kit item，以及全部不可用颜色/销售单位快照均为 null；还要求
fixture 精确 `OFFLINE` 且 not-deleted、Kit stock 10、唯一 SUPER_ADMIN supply +10 与
deduction/restore -1/+1 流水构成 `0→10→9→10`、相同 Order 没有 Payment/Settlement/
Refund/WalletTransaction/TableSession，且全局没有打开
Session、Timer 或 Occupancy。原始数据库 ID 只通过宿主 root 进程创建的有界、拒绝重复字段的
stdin JSON 管道送入一次性 C verifier，不进入 Compose/容器 argv、环境、错误或 Record；输出
只含固定 count 与 evidence digest。通过后先把 B prepared journal no-clobber 归档到
`/srv/pinkdoohub/gatea/records/m9-retirement-failures`，再把 A 原始 pending no-clobber
归档到 `/srv/pinkdoohub/gatea/records/m9-acceptance-failures`；两个 archive directory 都
必须是 `root:root 0700`，归档文件必须是 `root:root 0600`、`nlink=1` 的稳定普通文件。C
retirement 按 `prepared` → `write-free-verified` → `superseded-retirement-archived` →
`acceptance-archived` → `record-published` → `superseded-retirement-removed` →
`canonical-removed` → `runtime-restored` 八阶段推进；只有已发布脱敏 Record 后，才依次用
稳定 inode 精确删除 B canonical retirement pending 与 A canonical acceptance pending。

一旦开始停写，无论归档流程成功、work error、SIGHUP/SIGTERM/SIGINT 或 Python control
error，命令都会进入独立进程组的屏蔽信号恢复，启动并复验精确 A/M9 五服务；恢复/清理失败
优先于原 work/control error，延迟信号只在恢复完成后传播。SIGKILL/断电后只能由同一命令按
八阶段 journal 恢复，不能猜测成功或手工删除 pending。任一阶段失败均保留可恢复 retirement
journal 和尚未安全处置的上游证据。

两份归档都不是 retirement 完成后可移动的历史附件。后续 `activate-config`、
`rollback-config`、M9→M9 adoption 与 `finalize` 都会从上述两个 guarded `0700` 目录重开
它们，要求精确 canonical archive 路径、`root:root 0600`、`nlink=1`、稳定内容与原 digest，
并重新绑定 B stage/prepared journal、A acceptance attempt、source A/Image 和 lineage S。
移动、删除、替换或换目录而只保留 D retirement Record 都会 fail closed；使用非默认归档
目录时，所有后续命令必须继续显式传入相同的两个受保护目录。

退休完成后，对 A/M9 创建新的 Backup 并完成同 ID Restore。取得
`<A-M9-backup-id>`、`<retirement-record-sha256>` 和 activation plan manifest 后，执行：

```bash
sudo python3 -B -m scripts.release.gatea_candidate activate-config \
  --source-version 9 \
  --source-candidate-sha <A> \
  --lineage-source-candidate-sha <S> \
  --target-sha <D> \
  --backup-id <A-M9-backup-id> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures

sudo python3 -B -m scripts.release.gatea_candidate activate-config \
  --source-version 9 \
  --source-candidate-sha <A> \
  --lineage-source-candidate-sha <S> \
  --target-sha <D> \
  --backup-id <A-M9-backup-id> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --confirm-source-sha <A> \
  --confirm-lineage-source-sha <S> \
  --confirm-target-sha <D> \
  --confirm-backup-id <A-M9-backup-id> \
  --confirm-manifest-sha256 <plan-manifest-sha256> \
  --confirm-acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures \
  --apply
```

Activation 只把 active image 从 A 换为 D，保持 claims true，`current` 继续指向 S。随后用
相同绑定执行 M9→M9 adoption 前，如果决定终止且 D 的 upgrade/evidence/replay 尚未出现，
唯一配置撤销形状如下；它只把 active image 恢复为 A，数据库保持 M9、claims 保持 true、
`current` 仍是 S，不会撤销 retirement，也不是 M9→M7 downgrade：

```bash
sudo python3 -B -m scripts.release.gatea_candidate rollback-config \
  --source-sha <A> \
  --target-sha <D> \
  --confirm-source-sha <A> \
  --confirm-target-sha <D> \
  --confirm-activation-record-sha256 <D-activation-record-sha256> \
  --lineage-source-candidate-sha <S> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --confirm-lineage-source-sha <S> \
  --confirm-acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures \
  --apply
```

D 的任一 adoption upgrade Record/evidence/replay 一旦出现，rollback 必须永久拒绝，后续只按
自己的 durable journal 恢复或停止审计。成功路径继续用
相同绑定执行 M9→M9 adoption plan/apply；apply 后再以第一条 plan 形状重放，生成不可覆盖
sidecar：

```bash
sudo python3 -B -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 9 \
  --source-candidate-sha <A> \
  --lineage-source-candidate-sha <S> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --backup-id <A-M9-backup-id> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures

sudo python3 -B -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 9 \
  --source-candidate-sha <A> \
  --lineage-source-candidate-sha <S> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --backup-id <A-M9-backup-id> \
  --confirm-source-sha <A> \
  --confirm-lineage-source-sha <S> \
  --confirm-target-sha <D> \
  --confirm-backup-id <A-M9-backup-id> \
  --confirm-manifest-sha256 <plan-manifest-sha256> \
  --confirm-acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures \
  --apply
```

Schema v2 adoption Record/evidence/replay 必须同时绑定 A、S、D、retirement、A 的既有
M7→M9 stage/activation/upgrade/replay 和新 Backup/Restore，并证明 source/target 都是
M0–M9、图片以及 M7 保留、M8 色块、M9 桌台三份内容摘要完全一致、
`database_changes_applied=false`、
`migrations_applied=[]`。该路径不得调用 M8/M9 migration、MARD、Wallet backfill、30 桌
bootstrap 或任何补数据操作。

完成 D `app-up`、完整 acceptance、绑定 acceptance 的 resilience，以及 D 的
post-acceptance M9 Backup/Restore 后，`finalize` 仍使用下文全部普通参数，但
`--source-sha`/`--confirm-source-sha` 必须是 S，并额外传入：

```bash
  --predecessor-candidate-sha <A> \
  --acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --confirm-predecessor-sha <A> \
  --confirm-acceptance-retirement-record-sha256 <retirement-record-sha256> \
  --acceptance-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-acceptance-failures \
  --retirement-failure-archive-dir \
    /srv/pinkdoohub/gatea/records/m9-retirement-failures
```

只有这一步把 `current` 从 S 原子切到 D。本文加入该路径不代表现场已执行；D 的 CI、
retirement、Backup/Restore、adoption、acceptance、resilience 或 finalize 任一步失败都必须
立即停止并保持 No-Go。

在对 source M7 创建当次新 Backup 并完成同 ID Restore 后，从目标 Release 目录先 plan，
再用其输出的 manifest 精确激活配置：

```bash
cd /srv/pinkdoohub/gatea/releases/<target-sha>

sudo python3 -B -m scripts.release.gatea_candidate activate-config \
  --source-version 7 \
  --source-candidate-sha <source-sha> \
  --target-sha <target-sha> \
  --backup-id <source-backup-id>

sudo python3 -B -m scripts.release.gatea_candidate activate-config \
  --source-version 7 \
  --source-candidate-sha <source-sha> \
  --target-sha <target-sha> \
  --backup-id <source-backup-id> \
  --confirm-source-sha <source-sha> \
  --confirm-target-sha <target-sha> \
  --confirm-backup-id <source-backup-id> \
  --confirm-manifest-sha256 <plan-manifest-sha256> \
  --apply
```

如果配置已激活但升级尚未开始，唯一受控撤销形状如下；
`<activation-record-sha256>` 必须来自未改动的
`<target-sha>.config-activation.json`：

```bash
sudo python3 -B -m scripts.release.gatea_candidate rollback-config \
  --source-sha <source-sha> \
  --target-sha <target-sha> \
  --confirm-source-sha <source-sha> \
  --confirm-target-sha <target-sha> \
  --confirm-activation-record-sha256 <activation-record-sha256> \
  --apply
```

既有同名成功 Record、Release 目录、镜像标签或证据 sidecar 冲突都必须先人工审计；own
pending 也只有满足上面的严格身份、确认值和 checkpoint 契约时才可由原命令恢复，跨阶段
或冲突 pending 一律阻断。尚未开始升级的普通 M7 source 执行顺序只能是
`stage` → source Backup/Restore → `activate-config` plan/apply → upgrade apply →
upgrade plan-replay → `app-up` → M9 admin-assisted acceptance → resilience → 新 M9
Backup/Restore → `finalize`。`rollback-config` 只在 upgrade apply 之前作为终止分支，不是
该成功路径中的一步。

### M2/M7→M9 与 M9→M9 adoption（仅按当次授权与证据执行）

`gatea_upgrade.py` 是既有库升级的受保护入口。旧调用为兼容历史流程默认只接受精确
M0–M2 Aerich 链；普通或历史 M7 source 必须显式提供 `--source-version 7`，否则在读取 Backup、停止
业务入口或产生写入前 fail closed。它不把一次性 MySQL 的其他历史起点自动批准为
持久起点。特殊 A/M9 前滚必须显式使用 `--source-version 9`，并同时传 immediate
predecessor A、lineage S 和 retirement Record digest；缺少任一绑定即在现场写入前拒绝。
执行前必须先在 source 配置下生成 24 小时内的新 Backup，并完成相同 Backup
ID 的无端口独立 Restore；随后只能通过上节 candidate `activate-config` 的 plan/逐项确认
apply，把受保护配置切换到已经 stage 的目标 SHA 镜像。

下面展示普通 M7 source 路径的参数形状；它不适用于当前已经是 A/M9 的 live Gate A。命令必须从已安装的目标 Release 目录执行。plan 默认
只读；apply 只接受与当次成功 CI、Backup/Restore、目标 SHA/Image 及明确写授权完全一致
的身份：

```bash
sudo python3 -B -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 7 \
  --source-candidate-sha <source-40位-sha> \
  --backup-id <YYYYMMDDtHHMMSSz>
```

真正写入必须把 plan 输出的四个身份逐项原样确认：

```bash
sudo python3 -B -m scripts.release.gatea_upgrade \
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
21 表 M7 保留内容摘要，并要求与停写源完全一致；随后核验 M9 四表结构、30 桌定义与
零初始 Session/Timer/Occupancy。编排先执行只读 `table_reconcile`，要求
`open_sessions`/`occupancies`/三类异常计数/`scanned`/`violations` 精确为整数零；
在 `table_sweep` 前记录一次 SQL 空表 invariant，再要求 sweep 结果精确为
`{"status":"ok","closed":0}`，并在其后重算同一组 SQL invariant。两个任务结果与前后
数据库摘要都进入 evidence step，reconcile/sweep 聚合也进入成功 Record；Record 通过
evidence SHA-256 绑定完整过程。历史 M2 路径仍按
M3 → M4 → Wallet → M5 → M6 → M7 → M8 → MARD → M9 → Table Bootstrap 执行。

只有全部通过才生成 `<target-sha>.existing-database-upgrade.json`；Record 必须绑定合法的
M2→M7、M2→M8、M2→M9 或 M7→M9 组合，M7→M9 还必须明确 `source_version=7`。成功后
App/Nginx/`table-sweeper` 继续保持停止。执行人复核 Record 后，必须在无旁路写入的同一
停写窗口立即以完全相同的
`--source-version 7`、source SHA 和 Backup ID 重跑上方 plan 命令；已有成功 Record 的
重放会校验证据路径/哈希、当前最终数据库摘要、完整图片 manifest、21 表 M7 保留内容
摘要、Record/evidence 中的 reconcile/sweep 绑定和 live M9 SQL 空表 invariant，并再次运行
只读 MARD preview 与 `table_reconcile`。plan replay 不重跑 `table_sweep`，因为 sweep 可能关闭
到期会话并产生写入；只有只读复验全部通过且返回 `already_current=true` 才能继续：

```bash
# 使用与成功 apply 完全相同的 source SHA、Backup ID 和目标 config；不得增加 --apply。
sudo python3 -B -m scripts.release.gatea_upgrade \
  --mode loopback \
  --source-version 7 \
  --source-candidate-sha <source-40位-sha> \
  --backup-id <YYYYMMDDtHHMMSSz>

# 上一命令必须成功且输出 already_current=true、mode=plan-replay 后才能执行。
sudo python3 -B -m scripts.release.gatea_operations \
  app-up \
  --mode loopback
```

Upgrade evidence 是可更新的过程 journal，但每次替换都经过同目录临时文件、file `fsync`
和父目录 `fsync`；最终 success Record 与 plan-replay sidecar 使用不可覆盖发布。只有
evidence 已为 `succeeded/completed` 且 success Record 的 canonical bytes、evidence 路径与
SHA-256 全部一致，才构成升级提交点。若 success 已经可见，随后仅临时文件清理或第二次
目录同步失败不会把这份已提交的 succeeded evidence 反写成 failed；下次 plan 会先严格
验证已有提交，再执行只读 live replay。写入中断且尚无合法 success 时保留 evidence 和
停写现场，不能覆盖或从中间迁移步骤盲目续跑。

schema v2 M9→M9 adoption 还覆盖一个更窄的 SIGKILL/断电窗口：若 canonical success 尚未
发布，但 evidence 已经完整、耐久地处于 `succeeded/completed`，只能用与原 apply 完全相同
的 A/S/D、Backup、manifest、retirement 及全部确认值再次执行 `--apply`。恢复路径会重新
验证 MySQL/Redis 健康、App/Nginx/`table-sweeper` 停止、Backup/Restore 与 lineage 绑定，
并重算 live 数据库、图片、M7/M8/M9 内容摘要和 table reconcile；全部仍与 evidence 一致
时才 no-clobber 补发唯一 success，不重跑迁移或任何业务写入。plan 模式、`failed`/未完成
evidence、身份或现场漂移、已有冲突 success 均保持停写并 fail closed，不能删 evidence
重新开始。

`app-up` 的部署 Record 只能二选一：同一 candidate 必须恰有一份空库
`initial-migration` Record 或 `existing-database-upgrade` Record。两份同时存在、两份都
不存在，或任一路径为 symlink/其他不安全对象时，必须在任何 Compose 启停前以歧义状态
拒绝，不能按优先级挑一份继续。对既有库 M9，唯一 upgrade Record 不仅校验
target SHA/Image ID/合法迁移组合，还必须消费不可覆盖的
`<target-sha>.upgrade-plan-replay.json`，复核 sidecar 对 upgrade Record/evidence SHA-256、
最终数据库摘要、图片 manifest 摘要和 table reconcile 结果的绑定；随后重新读取 live DB，
要求 Aerich 精确为 M0–M9、静态 M9 Schema 摘要仍等于 upgrade Record，并再次运行只读
`table_reconcile`，最后在启动前再验一次目标 Image ID。它仍不会现场重算图片 manifest、
21 表 M7 内容摘要或 MARD preview，因此上述紧邻 replay verification 仍是强制前置条件，
不能用“Record 已存在”代替。replay 与 `app-up` 之间也必须维持
App/Nginx/`table-sweeper` 停止且不存在直接 SQL、迁移原语或宿主图片写入。任一 sidecar
缺失、已存在冲突、哈希/快照不符或 live reconcile 出现 violation/结构矛盾都拒绝启动；
失败不自动恢复服务、不 downgrade、不 fake，必须先人工确认实际 Schema/Aerich 与
evidence 后另行批准处置。

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

sudo python3 -B -m scripts.release.gatea_bootstrap \
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

sudo python3 -B -m scripts.release.gatea_representative_data \
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

## M9 admin-assisted 内部验收

`gatea_m9_acceptance.py` 是 `app-up` 后唯一受控的 M9 持久业务验收入口。默认调用只做
plan：在唯一操作锁内绑定当前 target SHA/Image、同 SHA/Run 的 Operations sidecar、精确
M7→M9 upgrade Record，或 schema v2 M9→M9 adoption Record 与 plan-replay sidecar；
adoption 还必须传递绑定 A、S 与 retirement digest。两条路径都绑定旧 M7 代表数据
Record/`0600` 合成凭据、
五项 Healthy 服务、唯一 loopback publisher、进程内 feature flags、精确 M0–M9 和“30 桌
已 bootstrap、尚无任何 Session/Timer/Occupancy 历史”的一次性基线；同时运行只读
wallet/table reconcile。旧 success/`.complete`、未知版本或身份冲突的 pending 一律拒绝
覆盖；pending journal 固定为 schema v3，只有同一命令满足严格身份/确认值和 checkpoint
恢复契约时才可继续自己的 pending。
prepare 会先扫描 Release 目录全部五类 candidate pending（含 acceptance retirement）和
acceptance 目录全部候选的
pending/complete，再读取 TTY 或调用 API；只有从本次命令的 candidate 身份推导出的 own
sidecar 可作为恢复 allowance。allowance 只放行安全路径/元数据，随后仍须完整验证 journal、
staged success、live reconcile 和所有绑定；own sidecar 与任意第二个 sidecar 同时存在也会
立即失败。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/m9-acceptance

# 只读 plan；不请求管理员凭据，不产生业务写入。
sudo python3 -B -m scripts.release.gatea_m9_acceptance

# plan 明确 ready 后，仍从同一目标 Release 目录执行一次完整闭环。
sudo python3 -B -m scripts.release.gatea_m9_acceptance \
  --apply-admin-assisted
```

admin-assisted 模式不接受 SUPER_ADMIN username/password 参数、环境变量或 stdin；两者都
只从 `/dev/tty` 隐藏输入并各确认一次。工具随后仅经正式 loopback HTTP API 创建一个
Online Experience（60 分钟/1 人、60 分钟/2 人、120 分钟/1 人三个 Option）、一个小额
Online fixed Kit 及图片/库存，再由现有 NORMAL USER 建立数量为 `2/1/1` 的三个 Experience
item 与一个 Kit item 的混合订单。它读取 T01 Token 仅用于进程内扫码 Claim，不把 Token
写入 Record，并验证 Claim 与 wallet payment 幂等、15 分钟待支付、60 分钟两 item 合并为
一个 70 分钟 Timer、120 分钟形成另一个 130 分钟 Timer、`quantity` 只计聚合数量不乘
时长、Kit 不进入 Timer、管理员可见与幂等 release。最后运行 sweep、table/wallet
reconcile，再通过管理 API 将 Experience/Kit 下架并二次读回确认不可售，完成五服务日志
脱敏扫描并注销/验证撤销两类会话。

v3 apply 会在首次登录、因而也在首个 RefreshSession 可能产生之前，先持久写入
`authentication_started` checkpoint。只有“本次刚创建 journal、尚无任何已知会话或业务
副作用、首次管理员登录精确返回 HTTP 400 且业务码 `1003`”这一种错误密码结果，才可安全
删除该无副作用 journal 以重新输入凭据；连接中断、响应不确定、角色/响应异常、旧 v2
journal，或任一会话 cleanup/revocation 证明不完整都保留 pending 并 fail closed。v3 恢复
仍须使用完全相同的候选身份和确认值，且只能从状态机允许的 checkpoint 继续。

成功只会不可覆盖地发布 schema v1（与 pending schema 独立）的
`records/m9-acceptance/gatea-m9-runtime-acceptance-<target-sha>.json`，并绑定 upgrade/
replay/代表数据/合成凭据哈希、CI Run、五服务和全部业务布尔证据；Payment ID、Payment No
SHA-256 与 `succeeded_at` 还必须和 pending 的 payment evidence 精确一致，不保存原始 Payment
No、凭据、Token、请求/响应正文或动态路径。成功证据先写入同目录随机 `0600` 临时文件并完成 file `fsync`，
再以 hard-link no-clobber 发布 `.complete`、同步目录，随后才把 `.pending` 提交为
`verified/failure=false`；最终 Record 继续以 hard-link no-clobber 发布并完成目录同步后，
才删除 `.pending` 与 `.complete`。因此任一写入/掉电边界都不会让部分 JSON 占用成功路径；
重跑先清理安全、稳定且符合本候选 writer 命名的崩溃遗留 temp；也只有在 `.complete`、
pending/final 与全部业务绑定严格一致时才允许只完成发布收口，不得重新调用业务 API。成功
收口会保留 paid Order、closed Session、五张新图片以及 Kit
库存/钱包余额变化，供 resilience 和数据后 Backup 证明，同时两个 fixture Product 必须已经
下架。任何失败都尽力取消尚未支付的订单、释放已开 Session、把已创建 Product 转为不可售
并注销会话，但不会删除已提交的订单/支付/fixture，也不会恢复 source 卷；`.pending`
journal 保留实际阶段和脱敏 ID/哈希供人工审计。同一候选不得通过删除 pending 或修改基线
重跑。若失败 journal 精确停在 `order_created`、没有 claim/payment，且订单取消、fixture
offline、Kit 恢复和两类会话撤销全部完成，它仍是 terminal cleaned pre-claim failure：原
acceptance 只报告“requires a forward candidate”，不能恢复执行。只有上文 B
`retire-failed-acceptance` 能在只读复验、归档与脱敏 Record 均完成后退休该阻断；其他失败
继续保持 No-Go 并按现场事实另行设计前滚或取得恢复授权。

## 受控备份与隔离恢复

`gatea_backup.py` 只备份权威 MySQL 与商品图片。Redis 当前只保存 refresh-token
会话，恢复旧快照可能重新激活应失效的会话，因此恢复环境固定启动空 Redis，使
全部旧 refresh 会话失效。备份 ID 必须使用 UTC `YYYYMMDDtHHMMSSz`；备份短暂
停止 Nginx/App 形成停写窗口，MySQL/Redis 保持运行，完成后自动恢复 App/Nginx
并再次验证 health。SQL/Tar 为 `root:root 0600`，Record 只保存摘要、计数、路径、
checksum 和 Redis 策略，不保存 Secret 值。

每个 Backup ID 在停服前必须同时确认 MySQL artifact、图片 artifact、最终 Record 与
`records/backups/.<backup-id>.pending.json` 全部不存在；随后先排他创建 `0600` pending，
再停写对应业务服务、复验迁移链并读取版本化内容摘要/图片 manifest，然后才向同目录随机
`0600` 临时文件流式导出。每个临时文件完整写入并完成 file `fsync` 后，才以 hard-link
no-clobber 发布正式 `.sql`/`.tar` 并同步对应目录。只有服务恢复和最终 `0644` Backup Record
（同样经随机临时文件、file `fsync`、hard-link no-clobber 与目录 `fsync` 发布）也全部成功后
才删除 pending。导出失败、服务未恢复、Record 发布失败
或中断时会尽力删除本轮不完整 artifact，但保留 pending；同一 ID 因而不可复用，也不得
手工删 pending 后假装首次执行。先保全现场并选择新的 UTC Backup ID 或取得明确恢复处置
授权。只要同 ID 的 unresolved pending 仍存在，即使最终 Record 或两个 artifact 看似齐全，
Restore 与 Upgrade 也绝不消费这组备份；该 ID 不能通过补文件、删 pending 或原命令重试来
复用。

M7/M8/M9 的 `m7-preserved-business-v1` 由一次 20 表 `mysqldump --single-transaction` 与随后
一次 `bead_colors` M7 投影查询组成，临时内容文件为 `0600` 并在正常/错误/信号退出时
清理，Record 只保存版本、profile 和 SHA-256，不保存业务行或 PII。两次读取并不是同一个
数据库事务；其一致性前提是 App/Nginx 已停止且没有任何直接数据库写入。若无法排除旁路
写入，Backup 不得作为升级依据。

当前工具新建的 M8/M9 Backup 还必须携带独立的 `m8-swatch-content-v1`：按主键顺序对
`bead_colors.id`、`slot_no`、`swatch_hex` 的精确值取 SHA-256，避免旧 M7 投影刻意排除
`swatch_hex` 后仍漏过 HEX 内容漂移。早于该 profile 的历史 Backup 可以由兼容 Restore
读取，但不能作为本次 A→D source、post-acceptance、resilience 或 `finalize` 的新证据。

```bash
backup_id=20260902t120000z

sudo python3 -B -m scripts.release.gatea_backup \
  backup \
  --backup-id "$backup_id" \
  --mode loopback

sudo python3 -B -m scripts.release.gatea_backup \
  restore-verify \
  --backup-id "$backup_id" \
  --confirm-project "pinkdoohub-gatea-restore-$backup_id" \
  --mode loopback
```

恢复只写入精确确认的独立 project、internal network 和两个临时 named volumes；
不加入来源 project、不挂载来源卷、不发布宿主端口。工具比较数据库 Schema/诊断摘要、
图片内容 manifest；对精确 M7/M8/M9 链还重算并比较 `m7-preserved-business-v1` 内容摘要，
覆盖 20 个非 `bead_colors` 表与 `bead_colors` M7 投影；当前 profile 的 M8/M9 再重算
`m8-swatch-content-v1`，M9 另重算 `m9-table-business-v1`，覆盖桌台、Session、Timer 和
Occupancy 四表。只有前述三项 swatch 字段 all-absent 的历史 M8/M9 Backup 会走兼容分支而
不伪造该摘要。随后启动 Restore App 验证
readiness，并在成功、失败和中断路径进入同一精确清理。清理子命令在新 session/独立进程组
中运行，并最多执行两轮有界的
`down --volumes --remove-orphans`→inventory；只有该 project 的全部容器、两个临时 named
volumes 与 internal network 都不存在才算完成，不能只看 `down` 返回码。来源 Gate A 服务
和三个持久卷不属于清理目标。

Restore 成功 Record 同样不可覆盖，并额外绑定当时 Backup Record、MySQL artifact 与图片
artifact 的三个 SHA-256；它只会在所有内容比较、空 Redis、Restore App readiness、零宿主
端口和临时资源删除均成功后，以相同的完整写入、file `fsync`、hard-link no-clobber 和
目录 `fsync` 规则发布。后续 upgrade 与 candidate `finalize` 会重新计算这些
digest，而不是只相信 `passed=true`：Backup Record 或任一 artifact 在 Restore 后改变、
Restore Record 指向另一份 Backup，或 M9 的 M7/M8/M9 内容摘要任一不等，都 fail closed。

同机备份只能证明流程和恢复能力，不能覆盖服务器或系统盘故障。Gate A Go 前仍需
定义保留期，并把批准备份加密复制到独立故障域；工具不自动上传或删除备份。

### 客户端加密异机副本

`gatea_offsite_backup.py` 在受控管理电脑执行，不把解密私钥发送到服务器。它通过
现有只读 SSH 身份下载精确 Backup/Restore Record 与两个 Artifact，在权限为 `0700`
的本机临时目录重算来源 checksum；随后使用随机 AES-256-GCM 数据密钥加密、用独立
RSA-3072 OAEP-SHA256 公钥封装数据密钥。成功后必须用私钥完成 AEAD 解密、Bundle
成员白名单、数据库/图片 SHA-256 和 Restore PASS Record 的再次验证。export 前与解密
verify 都会按精确 Aerich 链重新执行内容证据契约：M7/M8/M9 必须有完全相同的
`m7-preserved-business-v1` 和 `m7_content_matches=true`；当前工具新建的 M8/M9 pair 还必须有
完全相同的 `m8-swatch-content-v1` 和 `m8_swatch_content_matches=true`，M9 另要求完全相同的
`m9-table-business-v1` 和 `m9_table_content_matches=true`。早于 swatch profile、且 Backup
snapshot、Restore snapshot 与 Restore match 三个 swatch 字段**全部缺失**的历史 M8/M9 pair
仍可兼容 export/verify；只要任一字段出现，其余字段就必须完整且精确匹配，部分出现、结构
无效、摘要不等或 match=false 均 fail closed。这种 all-absent 历史 pair 不能作为本次 A→D
source、post-acceptance、resilience 或 `finalize` 证据。未知迁移链或版本证据混装同样拒绝；
加密/文件哈希本身不代替这项语义校验。

```bash
python3 -B -m scripts.release.gatea_offsite_backup keygen \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem" \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem"

python3 -B -m scripts.release.gatea_offsite_backup export \
  --backup-id <YYYYMMDDtHHMMSSz> \
  --host <gate-a-host> \
  --user <ssh-user> \
  --identity-file <ssh-private-key> \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem" \
  --destination-dir "$HOME/Backups/pinkdoohub/gatea"

python3 -B -m scripts.release.gatea_offsite_backup verify \
  --copy "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb" \
  --record "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb.json" \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem"
```

私钥目录固定 `0700`、私钥 `0600`、公钥 `0644`；加密副本 `0400`，脱敏客户端
Record `0600`。密钥与副本必须位于仓库外且相互分离；脚本拒绝覆盖已有 key/copy，
不提供自动删除。私钥丢失会使副本不可恢复，因此其离线恢复保管仍由项目负责人负责。

## 依赖故障、应用重启与日志观察

`gatea_resilience.py` 先读取数据库的精确批准 Aerich 链，再选择整个演练必须恢复、观察和
扫描的常驻服务：M2/M7/M8 为 MySQL、Redis、App、Nginx 四项，M9 还必须包含
`table-sweeper` 共五项；未知、缺口或超前链直接拒绝。它只在代表性数据成功 Record、
Runtime/迁移绑定、选定服务全部 Healthy 和唯一 loopback publisher 全部匹配时对当前
candidate SHA 执行一次。成功 Record 固定为
`gatea-resilience-<40位SHA>.json` 且不覆盖；历史候选记录保留，但不阻断新候选重新演练。
首次迁移要求代表性数据 Record 精确匹配当前 SHA/Image；既有库升级则只接受升级
Record 冻结的 source SHA/source image 对应历史 Record；对 `source_version=7` 的 M7→M9 升级，
未显式指定路径时自动选择
`gatea-m7-representative-data-<source-sha>.json`，且无论自动还是显式路径都必须匹配 source
SHA/Image 和安全 Record 形状。该链路依赖升级过程的数据不漂移证据，不删除或伪造为新候选。
它依次停止 MySQL、Redis，要求依赖
故障时 readiness 为 503 而 liveness 保持 200；恢复各依赖并等待 readiness 200 后，
再重启 App。演练前后除了完整数据库诊断摘要与图片 manifest，精确 M7/M8 legacy Record
比较 `m7-preserved-business-v1`；精确 M9 schema-v2 Record 必须同时比较
`m7-preserved-business-v1`、`m8-swatch-content-v1` 和 `m9-table-business-v1`。Record 只写
版本化 profile/digest，不保存原始业务行或桌台 Token。最后再验证
选定服务、端口、Docker
日志轮转、24 小时 Nginx 请求数量/4xx/5xx/时延，并以内存中的四项真实 Secret 扫描
日志但不记录日志正文或 Secret 值。

M9 resilience 不能只依赖“同目录里看起来已有 acceptance”。调用方必须显式传入唯一
`gatea-m9-runtime-acceptance-<target-sha>.json` 及人工确认的 SHA-256；工具要求该文件为
`root:root 0644` 普通文件、父目录为 `root:root 0755` 真实目录且没有 pending/complete
sidecar，并在演练前和 success 发布前冻结、重验文件身份与内容。它还把 acceptance 的
candidate/Image、Operations SHA 与 CI Run、M7→M9 upgrade/replay digest、代表数据/凭据
digest、五服务、`passed=true`、attempt digest 和完成时间直接与当前现场相连，且 resilience
开始时间不得早于 acceptance 完成时间。CLI 默认受保护 acceptance 目录为
`/srv/pinkdoohub/gatea/records/m9-acceptance`，传入 Record 必须位于这个目录；若使用另一受控
目录，必须显式提供 `--acceptance-record-dir`，且它必须与 Record 父目录按不跟随软链接的
规范路径精确相等，不能让全局 sidecar 扫描一个目录却从另一个目录消费 Record。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/resilience

acceptance_record=/srv/pinkdoohub/gatea/records/m9-acceptance/gatea-m9-runtime-acceptance-<target-sha>.json

sudo python3 -B -m scripts.release.gatea_resilience \
  --runtime-acceptance-record "$acceptance_record" \
  --confirm-runtime-acceptance-record-sha256 <acceptance-record-sha256> \
  --apply
```

精确 M9 resilience 成功 Record 使用 schema v2，并直接记录
`runtime_acceptance_record_sha256`、`runtime_acceptance_attempt_id_sha256` 和
`runtime_acceptance_completed_at`，供 `finalize` 再次交叉验证。历史 M2/M7/M8 四服务演练
仍使用严格的 legacy schema v1，且不得携带或伪造这三个 M9 字段；两种 Schema 不能互换。

resilience 成功 Record 也先通过同目录随机临时文件、file `fsync`、hard-link no-clobber 和
目录 `fsync` 提交。final 已经可见时，使用完全相同参数重跑不会再次制造 MySQL/Redis
outage 或执行 App restart；它只接受 `root:root 0644` 普通 final，严格复验 schema v1/v2、
全部身份/绑定/时序、日志，并对当前 Runtime、数据库和图片执行前后两次一致性检查。若只
残留 writer 留下的最多一个临时别名，还必须证明它与 final 是同 inode、同内容、同冻结身份，
然后先同步 final 目录项、精确删除别名并再次同步。孤儿/多个/不一致 temp、同候选的另一
sidecar 或 Record/现场漂移都 fail closed，不能把同名文件当作通用重放许可。

任何阶段失败都先尝试恢复当前精确链选定的四项或五项常驻服务，再返回失败且不写
成功 Record；
不得为了得到 PASS 删除代表性数据、当前候选 Record 或绕过日志匹配。

所有持久变更入口都持有同一操作锁，并在 CLI work 前为 SIGHUP/SIGTERM/SIGINT 安装受控终止
guard；SIGINT 对外保持 Python `KeyboardInterrupt` 语义。Backup、Restore、candidate
finalization 与 resilience 还在首次停服前切入独立的 work→recovery 状态机。工作阶段首个
终止信号先把状态切为 recovery 再抛出，进入恢复后到达的终止信号只延期记账，不能再次打断
精确补偿；所有 mandatory recovery/cleanup 子命令都使用新 session/独立进程组，避免终端
`Ctrl-C` 同时直接终止父状态机和补偿子进程。服务 stop 必须通过 Compose `ps` 复核目标已
进入允许的停止状态；临时 Restore project 和 candidate 临时镜像则分别按上文的容器/两个卷/
internal network inventory 与精确 reference inventory 收口，不能以 stop/down/image-rm 的
退出码代替。异常传播优先级固定为 recovery/cleanup failure > original work/control error >
deferred signal；延期信号不得覆盖补偿失败或原始根因。只有精确恢复、清理和健康核验完成后
才传播所选异常。这不构成原子恢复保证：SIGKILL 或断电无法被捕获，有 durable pending 的
流程下一次必须先按 journal 状态机处理，不能满足严格恢复契约即 fail closed。
resilience 演练本身没有 durable pending；若它在 M9 演练中、且成功 final 尚未可见时遭遇
SIGKILL/断电，必须人工核验 MySQL、Redis、App、Nginx、`table-sweeper` 五项服务及现场状态，
不能因没有 pending 或成功 Record 就继续下一阶段。只有上段所述 final 已提交、残留精确
同 inode 临时别名的窗口可以按只读复验路径收口。

## 候选最终确认与 `current` 切换

只有 M9 admin-assisted acceptance、同 target 的 resilience，以及两者之后创建的全新 M9
Backup/同 ID Restore 都成功，才可从目标 Release 目录执行 `finalize`。传入的两个业务
Record 路径和 SHA-256 必须是实际生成值；数据后 Backup ID 不得等于升级前 source
Backup ID：

```bash
sudo python3 -B -m scripts.release.gatea_candidate finalize \
  --source-sha <source-sha> \
  --target-sha <target-sha> \
  --runtime-acceptance-record \
    /srv/pinkdoohub/gatea/records/m9-acceptance/gatea-m9-runtime-acceptance-<target-sha>.json \
  --confirm-runtime-acceptance-sha256 <runtime-acceptance-record-sha256> \
  --acceptance-record-dir /srv/pinkdoohub/gatea/records/m9-acceptance \
  --resilience-record \
    /srv/pinkdoohub/gatea/records/resilience/gatea-resilience-<target-sha>.json \
  --confirm-resilience-record-sha256 <resilience-record-sha256> \
  --resilience-record-dir /srv/pinkdoohub/gatea/records/resilience \
  --post-backup-id <m9-post-acceptance-backup-id> \
  --confirm-source-sha <source-sha> \
  --confirm-target-sha <target-sha> \
  --confirm-post-backup-id <m9-post-acceptance-backup-id> \
  --apply
```

`finalize` 首次执行和原子切换前要求 `current` 仍精确指向 source，并重新绑定 stage/config
activation、upgrade/evidence/plan-replay、acceptance、resilience、M9 Backup/Restore 及其
artifact digest；
CLI 的两个 guarded 目录默认分别为
`/srv/pinkdoohub/gatea/records/m9-acceptance` 与
`/srv/pinkdoohub/gatea/records/resilience`；传入的 acceptance/resilience Record lexical
父目录必须各自与对应 guarded 目录完全相同。使用非默认目录时必须同时显式传 Record 路径
与对应 `--acceptance-record-dir`/`--resilience-record-dir`，不能扫描一个目录却消费另一个。
入口会先扫描全候选 acceptance sidecar，再读取 Release/live 证据。它只消费已经完全收口的
`root:root 0644` resilience 普通 final：`nlink` 必须为 1、身份/内容/digest 必须稳定，目录中
不得有该 final 的 `.tmp-*` 或其他 publication alias/sidecar；`finalize` 不代替 resilience
清理崩溃残留，必须先用上一节的 resilience 自身恢复入口收口。
同时要求 acceptance 和 resilience 都早于数据后 Backup，Backup 早于 Restore，并要求
resilience 的 M7/M8/M9 内容摘要等于数据后 Backup、`image_file_count` 等于该 Backup 的完整
`image_manifest` 长度；resilience 自身还必须证明演练前后 manifest 未变。acceptance 后
图片总数必须为验收前完整 manifest 的数量加 5，不使用写死的 M7 基线总数。它先排他写
`<target-sha>.current-finalization.pending.json`，完成最后一次停写 live recheck 后用同目录
临时 symlink 原子替换 `current`；这一原子切换是 finalization 的 commit point。复核落盘、
恢复 Runtime 后才排他发布成功 Record 并删除 pending。普通 `app-up` 会拒绝任何未收口的
candidate transition（包括 finalization）journal；只有已经严格校验该 own finalization
journal 的 candidate 内部恢复调用，才可显式绕过这一项检查，且仍不得绕过其他 pending。
从准备 pending、停服、live recheck、切换 `current` 到发布 final Record 的每个关键阶段，
`finalize` 还会反复要求 acceptance pending/complete 仍不存在，并按冻结的文件身份与 digest
重读最终 acceptance；验收证据在 cutover 途中被替换或重新出现 sidecar 会立即阻断。

若中断发生后 `current` 已精确指向 target，只有 own pending 已到 `live-rechecked`、
`current-switched` 或后续 `runtime-restored`，且全部身份/确认值和持久证据仍严格匹配时，
原命令才可恢复：它复验不可变 Record/artifact digest、`current`、配置、目标 Image 与 live
M9 结构/Runtime invariant，恢复五服务并补齐最终 Record。此时 Runtime 可能已重新开放合法
业务写入，恢复流程不得再用切换前的旧 Backup 业务内容摘要（包括 pre-upgrade source 与
finalize 直接绑定的 post-acceptance Backup）和在线数据重比。checkpoint 早于该边界、任一
证据冲突、`current` 不是预期值或 final/pending 不一致都 fail closed 并要求人工审计；不得
覆盖 Record 或把 symlink 状态单独当成完成证据。

运维工具仍故意不提供备份删除、来源卷恢复、TLS 切换或公开发布命令；这些步骤
必须分别实现、测试和 Review，不能用未经审查的现场 Shell 绕过。

## 后续执行顺序

1. 取得全新 D 同一 target checkout 的 9/9 required Jobs、source archive 与 updater artifact，
   用校验过的临时 launcher 执行 schema v3 candidate `stage`，精确绑定 A failure digest 与
   B stage/prepared pending digests；不得从现场工作树直接 build，也不得复用 A/B/C/旧 Run。
2. Root 复核配置/Secret/持久运维目录、唯一全局操作锁、live candidate=A、DB=M0–M9、
   五服务健康、claims=true、`current`=S 和 canonical pending digest。任何一项不等于冻结
   现场就停止，不运行只适用于空端口首次部署的 `preflight`。
3. 从 D Release 执行 `retire-failed-acceptance` takeover，接受计划中的短暂停写：命令停止
   App/Nginx/`table-sweeper`，在 MySQL/Redis 健康且写入方持续停止的窗口中重复断言 lineage，
   再运行 D verifier 与 wallet/table reconcile。只有八阶段 journal、B/A 两份原始 `0600`
   归档、脱敏 retirement Record、B/A canonical pending 依次精确移除和 A/M9 五服务强制恢复
   全部通过后才算完成；不得人工帮助它收口。两份归档必须原位保留，供
   activation/rollback/adoption/finalize 持续重验。
4. 对 A/M9 创建新的 MySQL/图片 Backup 并完成同 ID 独立 Restore，要求 M7/M8/M9 内容摘要及
   图片 manifest 全部一致。随后执行带 A、S 和 retirement digest 的
   `activate-config --source-version 9` plan/apply；配置只从 A 切到 D，claims 保持 true，
   `current` 仍是 S。
5. 只执行 `gatea_upgrade --source-version 9` adoption apply/replay，要求
   `database_changes_applied=false`、`migrations_applied=[]` 及 source/target M9 内容零漂移；
   紧邻运行会重读 live M9、Image 和 reconcile 的 `app-up`。禁止 M8/M9 migration、MARD、
   Wallet、bootstrap 或其他修复写入。
6. 先运行 D M9 acceptance 只读 plan，再以安全 TTY 执行一次 admin-assisted 闭环；随后执行
   target resilience，并显式传入 acceptance Record 路径与人工确认 SHA-256。任一不能按
   严格状态机恢复的 pending、清理不完整、钱包/桌台 reconcile、acceptance 直连绑定或
   日志脱敏失败都停止。
7. 在 acceptance 与 resilience 之后创建 D 的新 M9 数据后 Backup/Restore，核对三个 digest
   绑定，再以 source=S、predecessor=A、target=D、retirement digest 运行 candidate
   `finalize`，只在全部证据一致时原子切换 `current`；之后才生成并解密复核加密异机副本。
8. 验证 liveness/readiness、`table-sweeper`、唯一 loopback publisher、HEX API/小程序直绘，
   以及 gzip 只压文本且不重复编码。既有 Bootstrap 与 M7 综合数据不重复创建。
9. ICP 通过后再配置 DNS、证书、80/443 和 TLS override。
10. 将同一 SHA 绑定后端、OpenAPI 和微信 RC，配置合法域名并执行真机矩阵。

任一步失败都保持 Gate A `No-Go`。本目录不授权体验版上传、分发、提审或公开
发布。
