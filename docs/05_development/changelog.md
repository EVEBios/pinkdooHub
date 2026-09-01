# Development Changelog

> 每个独立功能模块完成后更新。记录做了什么、为什么这样做、有什么限制。

---

## Release Phase 9.4.4 — Gate A 持久备份与隔离恢复（本地实现，2026-09-02）

- 新增 `gatea_backup.py`：备份 ID 固定为 UTC `YYYYMMDDtHHMMSSz`，操作前验证 Root 配置/Secret、Runtime image、首次迁移 Record 和四项服务健康；短暂停止 Nginx/App 形成一致停写窗口，生成 `root:root 0600` 的 MySQL 单事务逻辑备份和图片卷 Tar，记录 SHA-256、数据库摘要、图片 manifest 与候选身份，并自动恢复 App/Nginx health。任何备份或恢复应用可用性失败都不写成功 Record。
- 新增完全独立的 `compose.restore.yml`：动态 project、internal network、MySQL 8.0.46、空 Redis、临时图片卷和 Restore App 均无宿主端口，也不引用来源 volumes。恢复要求精确 project 确认与备份 checksum，比较 Schema/业务摘要和图片内容，验证 Restore App readiness；成功、失败和中断路径均精确执行 `down --volumes` 并复核恢复容器/卷消失，来源 Gate A 不属于清理目标。
- Redis 只保存 refresh-token 会话，不作为权威备份资产；恢复使用空 Redis，使旧 refresh 会话全部失效，避免旧 AOF/RDB 重新激活已撤销 Token。当前同机 `0600` 备份只证明流程，保留期、加密异机副本和定期演练仍是 Gate A 后续门槛。
- 9 项定向、94 项 Release 与完整后端 `1634 passed, 9 skipped`；提交 `d1f3379...` 的 GitHub Actions Run 33570862787 为 8/8 success。真实 Backup `20260901t232740z` 生成 148,782-byte MySQL 与 10,240-byte 空图片归档，独立无端口 Restore project 完成 10 表/90 列/26 约束/63 statistics、业务摘要、图片 manifest、空 Redis 和 Restore App readiness 比较，并删除全部临时容器/网络/卷；来源 4 项服务保持 Healthy。当前同机备份保留，Bootstrap 后代表性数据复验、保留期与加密异机副本仍未完成，完整证据见 `docs/09_release/reports/phase94_gatea_backup_restore_2026-09-02.md`。

## Release Phase 9.4.3 — Gate A 首次部署生命周期（本地实现，2026-09-02）

真实腾讯云 Gate A 主机的 loopback 首次部署已通过。Runtime candidate `51ad3152c8960bc133c25a600418f5f850d69199` 的 GitHub Actions Run 33568184860 与 Operations revision `17114d7278860c0e09901f493280a56bf6043c3f` 的 Run 33568983950 均为 8/8 success；后者只修改运维脚本、测试和本文，服务器逐文件确认 App、迁移、依赖与 Runtime 输入完全一致，因此首次迁移记录继续严格绑定前者的 App image，没有伪造候选迁移记录。

- 扩展 `gatea_operations.py`，新增 `infra-up`、`initial-migrate`、`app-up`、脱敏 `status` 和 `safe-stop`；所有生命周期写操作当前严格限制为 loopback，TLS 模式 fail closed。
- `infra-up` 只启动 MySQL/Redis 并等待 health；启动或 health 失败会停止本次服务但不删除命名卷。`initial-migrate` 要求两项依赖 healthy、目标 application schema 为 0 张表，才使用显式 operations profile 执行 Aerich；成功后以候选 SHA、Image ID 和 UTC 时间原子记录，匹配记录的严格重放为 no-op，非空未知状态拒绝迁移且停止基础设施。
- `app-up` 验证镜像 SHA/revision、UID/GID、Entrypoint、CMD 和迁移记录，再启动 App/Nginx；失败时停止 App edge、保留基础设施与卷。成功条件同时包括 App/Nginx healthy，以及运行时唯一 publisher 精确为 `127.0.0.1:18080 -> nginx:8080`。
- `safe-stop` 只执行有序 stop，命令中不存在 `down` 或 `--volumes`；脚本仍不提供 Bootstrap、备份、恢复、删卷、TLS 切换或公开发布能力。
- 真实主机首次 `infra-up` 发现 Docker Compose v5.5 的 `ps --format json` 使用 newline-delimited JSON，而本地 v5.3 在空项目及既有契约中使用 JSON 数组；解析器已同时支持两种官方输出形状并新增回归。首次 MySQL/Redis 均曾达到 Healthy，但解析器按 fail-closed 自动停止两项服务；卷内尚无应用表或业务数据，未运行迁移。
- 第二次 `infra-up` 通过后，首次迁移在非 root Entrypoint 读取 Secret 时发现 Compose 本地文件 Secret bind mount 保留宿主 `root:root 0400`，UID/GID 10001 无读取权限；入口在 Aerich 前退出，基础设施再次由 fail-closed 路径停止，迁移记录未创建。修复保持 Secret 目录 `root:root 0700`，将三个 App Runtime Secret 收敛为 `root:10001 0440`（宿主 GID 10001 未分配），Root Secret 保持 `root:root 0400` 且不挂载给 App；预检与测试固定这组精确元数据。
- 首次 `app-up` 中 App/Nginx 均达到 Healthy，Compose v5.5 仍把 Nginx 镜像未绑定的 `EXPOSE 80/tcp` 表示为 `URL=""`、`PublishedPort=0` 的 publisher，导致精确端口断言按 fail-closed 停止 App edge。运行时 Docker 绑定已独立确认只有 `127.0.0.1:18080 -> nginx:8080`，无公网业务监听；校验器现只忽略这种无宿主 listener 的未发布元数据，任何额外、非 Nginx 或非环回宿主映射仍被严格拒绝，并新增 Compose v5 回归。
- 最终 Runtime 真实完成空库 Aerich 0→1→2 并核验 10 张应用表，MySQL/Redis/App/Nginx 全部 Healthy，Liveness/Readiness 经 loopback Nginx 返回 200。MySQL、Redis 和 App 没有宿主 publisher，Nginx 唯一绑定为 `127.0.0.1:18080`，公网 18080 不可达；App 保持 UID/GID 10001、只读根文件系统和 `no-new-privileges`。三个 named volumes、4 个长期容器、版本化 Release/Record 与回滚备份按 Gate A 要求保留；DNS/HTTPS、Bootstrap、持久备份恢复、微信合法域名和真机仍未执行，Gate A 继续 No-Go。完整证据见 `docs/09_release/reports/phase94_gatea_loopback_2026-09-02.md`。

## Release Phase 9.4.2 — Gate A 持久部署拓扑（本地实现，2026-09-02）

开始 Phase 9.4 真实内部测试环境准备。本节只记录本地仓库实现；尚未把应用部署到腾讯云主机，未写真实 Secret、运行持久迁移、启动 Gate A 容器、开放 80/443、配置 DNS/证书/微信后台或上传体验版，Gate A 仍为 No-Go。

- 将 Phase 9.3 已验证的 Python 3.10.9 非 root App Runtime 提升到共享 `deploy/runtime/`；演练编排改为构建同一 Runtime，避免 Gate A 复制并漂移入口脚本。MySQL 8.0.46、Redis 8.0.1、Nginx 1.27.5 和应用依赖没有升级。
- 新增 `deploy/gatea/`：长期 MySQL/Redis/App/Nginx 使用固定 named volumes；只有 Nginx 加入 edge network，MySQL 3306、Redis 6379 和 App 8000 均不发布。备案等待期 override 只绑定 `127.0.0.1:18080`；TLS override 单独发布 80/443，必须显式提供已批准域名、证书和 ACME 目录。
- App 继续以 UID 10001、只读根文件系统、`no-new-privileges` 运行，迁移保留为显式 `operations` profile。Bootstrap 使用独立 override 和 `bootstrap_password.pending`，没有密码参数或常驻挂载。App 不获得 MySQL Root Secret，Nginx 不获得应用 Secret。
- Nginx 覆盖客户端 `X-Forwarded-For`/`X-Real-IP` 为 `$remote_addr`，避免公网客户端伪造审计地址；access log 只记录方法与 `$uri`，不记录 query、Authorization、Cookie 或请求体。图片卷保持 App 可写/Nginx 只读。
- 新增 `scripts/release/gatea_operations.py` 只读预检：拒绝 `latest`/短 SHA、非 production/Debug、SQLite、外部 DB 目标、错误图片 Origin 和非 Secret 配置中的敏感键；只检查 Root Secret 文件元数据/非空大小，不读取或输出值。当前故意不提供启动、迁移、Bootstrap、备份、恢复或销毁子命令，避免未经 Review 的服务器写操作。
- 新增 32 项 Gate A/既有 Rehearsal 定向契约并通过，覆盖 Compose 双 mode 渲染、内部网络、唯一 Nginx 端口、固定镜像/卷、Secret 分离、显式迁移/Bootstrap、共享 Runtime、代理 Header、日志和预检命令边界；`tests/release` 74 项与完整后端 `1614 passed, 9 skipped` 同步通过。共享 Runtime 镜像完成真实构建，并验证 UID/GID、Entrypoint 与 Uvicorn CMD 后清理验证镜像。未修改业务 API、OpenAPI、数据库 Schema/Aerich 迁移、Python/npm 依赖或应用版本。

## Release Phase 9.3 Complete — 隔离发布演练（2026-08-31）

Phase 9.3 已在最终候选 `136a8bd8833f9b23433cfb3a2f9ceca7dab70db5` 完成。GitHub Actions Run 33408135841 的 8 个 Job 全部 success；Run ID `20260831t221625` 的可销毁生产相似环境完成 DR-01～DR-07 与 DR-09 服务端部分，完整脱敏证据见 `docs/09_release/reports/phase93_rehearsal_2026-08-31.md`。这不等于 Gate A 已通过，也不授权微信后台、上传、分发、提审或公开发布。

- MySQL 8.0.46 真实完成空库 0→1→2、m0/m1 代表数据升级和 opening balance 核对；订单、Items、金额/Option 快照、Product/Kit/库存与 Audit 均保持。数据库和三类图片备份恢复到独立 Restore MySQL/volume，restore-app Ready 且轮换后账号登录通过。
- 受控 migration 2 失败证明 MySQL DDL 部分提交：新表存在、Aerich 仍停 m1、opening balance 未写；失败前备份在独立 Schema 恢复后用官方迁移完成 m2。MySQL/Redis 分别中断时 Readiness 为 503，恢复后为 200；应用优雅重启后数据/图片保持。
- SUPER_ADMIN Bootstrap 首次、严格重放、唯一用户/Audit、登录和凭据轮换通过。真实 Nginx HTTPS 完成 32 请求纵向 Smoke，覆盖五类身份、Product/Option/Kit、三类上传/读取、Inventory 幂等、混合订单/取消、Paid/Completed、权限、Refresh、禁用 Token 和凭据轮换。
- 演练发现并修复四项工具问题：不存在的 Python Bookworm 标签改为 3.10.9 Bullseye；Compose one-off 环境参数改用 `--env`；m1 fixture 使用合法 OD+ULID 编号；Nginx 通过独立 edge network 发布回环 HTTPS，数据面仍在 internal network。每项均增加回归断言，发布工具契约从 50 增至 53 项。
- R-004、R-006、R-011 已关闭；R-014 的 Gate A 持久化/恢复部分完成，Gate B 高可用存储仍待后续。DR-08、真实测试 Origin/DNS/证书、微信合法域名、iOS/Android 真机和弱网/前后台矩阵保持 Phase 9.4。
- 最终精确删除 Compose containers/networks/volumes、任务端口、短期 Secret/CA/原始证据目录和任务 App 镜像；用户既有 `pinkdoohub-dev-redis` 未复用、未停止。没有访问开发 SQLite、默认 3306、持久/共享/生产数据库或微信后台；没有数据库迁移、版本升级或新增依赖。

---

## Release Phase 9.3.3–9.3.4 — 隔离拓扑与可审计演练编排（2026-08-31）

完成 Phase 9.3 写操作前的生产相似拓扑和自动化工具；本节是本地实现状态，不代表 DR 场景已经执行或 Gate A 已通过。

- 新增固定版本 Docker App 镜像、Compose 和 Nginx HTTPS：所有宿主端口只绑定回环且避开 3306，Source/Restore MySQL 8.0.46、认证 Redis 8.0.1、Source/Restore 图片卷、非 root FastAPI 和内部网络均使用唯一 project label 管理；现有 `pinkdoohub-dev-redis` 不复用、不接管。
- 新增严格演练准备/运维工具：候选必须 Git clean 且 SHA/Compose digest 不漂移；Secret/短期 CA 仅写入 0700/0600 任务目录；命令覆盖镜像 digest、DR-01 空库、DR-02/03 旧迁移合成数据、DR-04 双实例数据库与图片备份恢复、DR-05 可控 DDL 部分失败、DR-06 依赖摘流量/恢复及优雅重启、DR-07 Bootstrap 首次/重放/轮换、DR-09 服务端真实 HTTPS 纵向 Smoke、脱敏摘要和精确资源回收。
- 旧迁移与运行时 fixture 都使用 Repository、显式事务和合成身份；旧迁移 fixture 拒绝 production，运行时 fixture 只接受 Compose 内精确 production Source，二者都会拒绝未知主机、非冻结端口/Schema 或缺少显式启用。工具不会用手工 SQL fake Aerich 版本或修补业务状态；恢复、故障注入和删除卷均要求精确 project/数据库/工作区确认。
- 发布工具契约 50 项通过，Docker Compose 标准化 JSON 可解析；未新增 Python/前端依赖，未修改数据库 Schema/迁移、业务 API、OpenAPI 或版本。尚未 commit/push，也未启动演练容器、连接持久/共享数据库、执行恢复/故障注入或删除 volume。

下一步是完整回归、形成用户批准且 CI 通过的干净候选提交，再按 Runbook 取得精确写操作授权并执行 DR-01～DR-07、DR-09 服务端部分；DR-08 仍属于 9.4 真机。

---

## Backend Phase 9.3.2 — 受控 SUPER_ADMIN Bootstrap（2026-08-31）

完成 Phase 9.3 的第二个代码前置能力；本地实现和自动化通过后，仍需 DR-07 在隔离 MySQL 环境执行并安全处置初始凭据，不能据此勾选 Gate A。

- 新增 `python -m app.tasks.super_admin_bootstrap` 独立管理命令。命令要求 `--apply`，只接受 username/nickname/phone；故意不提供 `--password`，密码仅从 `PINKDOOHUB_BOOTSTRAP_PASSWORD` 或 TTY 隐藏双输入读取。非交互环境缺少 Secret 时直接拒绝，参数、校验、异常和成功日志均不回显密码。
- `SuperAdminBootstrapService` 在单事务内创建首个正常状态 SUPER_ADMIN 和自指向 `BOOTSTRAP_SUPER_ADMIN` Audit。相同 username/phone/nickname/password 且唯一 Audit 完整时只返回 replay，不更新密码、昵称、角色、状态或时间戳，也不重复写审计。
- 已有普通用户占用 username/phone、已有不同或多个 SUPER_ADMIN、手工 SUPER_ADMIN 无 Bootstrap Audit、Audit 无匹配用户、禁用账号或任一身份/密码变化都稳定拒绝；绝不把已有普通用户静默提权或把禁用管理员重新启用。审计失败时用户创建完整回滚。
- 同进程先通过有界 asyncio 锁串行化；production MySQL 再使用参数化固定名称的 `GET_LOCK/RELEASE_LOCK` 覆盖多进程竞争。成功路径显式先提交用户与审计，再释放 session lock，关闭另一进程在提交前读取旧状态的窗口；SQLite 仅作为本地与自动化适配。
- User/Audit Repository 只增加可选事务连接、角色锁定和审计计数原语；Service 不直接调用 Model、FastAPI 或 HTTP Schema。数据库字段、表、索引、Aerich 迁移、依赖、OpenAPI 和应用版本均未变化。

---

## Backend Phase 9.3.1 — Dependency-aware Liveness / Readiness（2026-08-31）

完成 Phase 9.3 的第一个代码前置能力；这只是本地实现与自动化证据，不代表生产相似演练或 Gate A 已通过。

- 保留既有无依赖 `/api/v1/health` 响应，新增 `/api/v1/health/live` 和 `/api/v1/health/ready`。Liveness 不触碰外部服务；Readiness 并行执行 Tortoise 默认数据库连接的 `SELECT 1` 与 Redis `PING`，每项独立限制 1 秒。
- 数据库和 Redis 同时可用才返回 HTTP 200 / `ready`；任一失败或超时均通过新增 `ServiceUnavailableException` 与统一异常中间件返回 HTTP 503 / code `503` / `not_ready`，并保留两项独立 `up/down` 结果。
- 探针响应不输出连接目标或驱动错误；失败日志只记录 `database/redis` 与异常类型，避免驱动异常中的 URL、用户名、密码或查询参数泄漏。
- 新增严格 Pydantic 输出与 OpenAPI 200/503 契约，固定 OpenAPI JSON 和 TypeScript 生成类型同步更新。数据库 Schema、Aerich 迁移、依赖和应用版本均未变化。
- 定向健康检查 11 项通过，覆盖真实测试 SQLite/fakeredis、兼容入口、无依赖 Liveness、全部 Up、数据库/Redis 单项及双项失败、超时、日志脱敏和 OpenAPI 类型；健康/OpenAPI 定向合计 16 项、完整后端 `1518 passed, 9 skipped`、前端 TypeScript 与 OpenAPI 类型漂移全部通过。9 项 skip 均为既有、显式隔离的 MySQL-only 门槛。R-011 调整为 `mitigating`；必须在 9.3 DR-06 使用隔离 MySQL/Redis 验证故障摘流量与恢复后才可关闭。

---

## Frontend Phase 9.2.6 — 真实 PR CI 与可移植性收口（2026-08-31）

Phase 9.2 已完成。Draft PR [#2](https://github.com/EVEBios/pinkdooHub/pull/2) 面向 `develop` 创建并保持未合并；实现 head `23a0f08` 的 GitHub Actions [Run 33355935212](https://github.com/EVEBios/pinkdooHub/actions/runs/33355935212) 在真实 Ubuntu 干净 checkout 上 8/8 Job 全部通过。

- 首轮 Run `33354728020` 为 6/8：`backend-sqlite` 暴露 Python 策略测试硬编码本地 `.venv/bin/python`，`weapp-build` 暴露检查器依赖本机构建残留。测试改用 `sys.executable`；微信检查器改为分别校验编译产物与项目根 `project.config.json`，把权威配置 SHA-256 写入 manifest，并兼容 Taro 只规范化 `miniprogramRoot` 的合法副本。
- 第二轮 Run `33355556336` 暴露更早的真实构建错误 `taro: not found`：Job 级 `NODE_ENV=production` 使 npm 省略构建期 devDependencies，而没有 `pipefail` 的 `tee` 管道吞掉了失败。微信 Job 现显式安装锁定 devDependencies 并启用 `pipefail`；以后编译失败会在构建步骤直接失败。
- 修复后本地完整后端为 `1507 passed, 9 skipped`，CI 契约 13 项、Node policy 17 项通过；一次性干净微信构建通过 97 文件/603,660 bytes 检查，临时目录已删除且未改动开发者工具使用的现有 `miniapp/dist`。
- 成功远端 Run 的 `backend-sqlite`、`backend-mysql-release`、`frontend-quality`、`openapi-contract`、`weapp-build`、双依赖审计和 repository hygiene 全部 `success`。7 组 artifact 绑定 PR merge-ref `eac0d5e8...` 与 Run ID；PR head `23a0f08...` 由 Run 元数据单独绑定。
- 远端微信证据为 97 文件、主包 425,527 bytes、`admin` 分包 178,092 bytes、总计 603,619 bytes、`release_eligible=false`；manifest SHA-256 为 `d915912d...ece92`，不会自动上传微信。
- 本阶段没有业务 API、OpenAPI Schema、数据库 Schema/迁移或新增依赖；没有连接持久数据库、修改微信后台、上传、提审、发布、合并 PR、tag 或 release。下一阶段是 9.3 隔离发布演练，仍需单独规划与授权。

---

## Frontend Phase 9.2.5 — Python/npm 依赖审计门槛（2026-08-31）

完成两个依赖审计 Job、真实报告策略检查器和 Gate A 可达性分类的本地实现；workflow 仍未 commit/push 或产生真实 PR Run，因此 9.2 尚未完成，下一步为 9.2.6。

- GitHub Actions 从 6 个 Job 扩展为 8 个，新增 `python-dependency-audit` 与 `npm-dependency-audit`。两者都保存绑定 Git SHA/run ID 的原始 JSON 与策略结果，不自动修改依赖、不发布、不迁移数据库。
- Python 扫描器选用并锁定 `pip-audit==2.10.1`，在隔离 CI venv 安装。首次对 55 个精确 pin 扫描得到 4 个包/9 条记录；可修复项分别升级 asyncmy 0.2.11→0.2.14、cryptography 49.0.0→50.0.1、python-jose 3.3.0→3.5.0，复扫降为 ecdsa 0.19.2 的 1 条 `GHSA-wj6h-64fc-37mp`。
- ecdsa 公告影响 P-256 私钥签名、密钥生成和 ECDH 的时序；项目 production 固定 HS256，只做对称 JWT encode/decode，当前路径不可达。上游没有 patched release，因此由安全负责人建议、项目负责人接受到 2026-11-30；任何 JWT 算法、包版本、公告集合或日期变化都会使门槛失败。
- npm 11.6.2 显式使用官方 registry 并只审计 `--omit=dev` production tree，当前精确结果仍为 10 个受影响包、5 个叶子公告和 4 moderate/1 high/5 critical。完整含 dev 树此前观察到的 45 项不作为 Gate A runtime 集合，也没有被隐藏或误报为已修复。
- npm 策略逐项固定 Taro 4.2.1、swiper 11.1.15、lodash-es 4.17.21、esbuild 0.21.5 的依赖路径与 actual usage：esbuild 公告只影响未启用的 development server；lodash/H5 Taro 链不进入 `TARO_ENV=weapp` artifact；业务源码不使用 Swiper，微信产物使用原生 swiper 映射而非 npm swiper 运行实现。全部例外到期日为 2026-11-30，未来 H5 Gate 或新增 Swiper 使用自动重新打开。
- 两个策略检查器拒绝审计端点/JSON 失败、新增或消失漏洞、版本/严重性/direct/range/公告集合变化、缺少 Review 字段和到期策略；npm 不执行会破坏性降级到 Taro 3.x 的 `audit fix --force`，也不做未经上游验证的 override。
- 新增 Python 与 Node 策略单元测试，覆盖当前精确报告、新公告、版本变化、过期和 registry 错误；workflow 契约同步固定 8 Job、官方 registry、原始 artifact 与禁止强制修复。
- 本地真实复验通过：Python 原始审计 1 包/1 公告及 npm 原始审计 10 包/5 公告均通过策略检查；后端完整套件 `1507 passed, 9 skipped`，前端 61 套件/387 项、CI Node policy 13 项、TypeScript、ESLint、Stylelint、OpenAPI 字节/类型漂移和 97 文件微信 production artifact 检查均通过。
- 因 asyncmy 属于生产 MySQL 边界，升级后重新启动一次性 MySQL 8.0.46，真实应用 Aerich 0→1→2 并通过 9 项并发/锁/1205/EXPLAIN/HTTP 门槛（2.30 秒）；cleanup 确认 Schema 删除、容器停止且端口 13306 关闭，容器对象和临时证据目录已删除。
- 本阶段不修改业务 API、OpenAPI 或数据库 Schema/迁移；新增/升级的是三项生产依赖和仅在隔离 CI venv 使用的审计工具，没有持久环境变更、微信后台操作、上传、提审或发布。

---

## Frontend Phase 9.2.1–9.2.4 — 工具链、运行时与隔离 MySQL CI（2026-08-31）

完成 9.2.1–9.2.4 本地实现；依赖审计、真实 PR Run 和完整 Gate 证据仍属于后续 9.2.5–9.2.6，本条不把 9.2 或 Gate A 标记为完成。

- 仓库固定 Python 3.10.9、Node 24.13.0 和 npm 11.6.2，npm 使用官方 registry、严格 engine 与既有 legacy peer 策略；干净 Python/Node 安装已在本机验证。
- production 启动现在强制 `APP_DEBUG=false`、MySQL、HS256、至少 32 字符且非已知弱值的 JWT Secret、非本机 redis/rediss，以及无凭据的绝对 HTTPS 图片地址；Pydantic 错误隐藏原始输入。
- Redis 连接成功日志只保留 scheme/host/port/db，不再输出 username、password 或 query；OpenAPI CLI 主动把 stdout/stderr 切为 UTF-8，覆盖 CP1252 父环境的中文 `--help` 与真实导出。
- 微信 `project.config.json` 关闭 source map 上传，当前发布 description 与 README 只声明 Gate A 微信内部测试版；支付宝、抖音和 H5 构建命令保留为未来能力，不是本版发布门槛。
- 新增 GitHub Actions 初版，当前包含 `backend-sqlite`、`backend-mysql-release`、`frontend-quality`、`openapi-contract`、`weapp-build` 和 `repository-hygiene` 6 个 Job；PR、main push 和手工 dispatch 触发，权限仅 `contents: read`，不会迁移持久数据库或上传/提审微信。
- `backend-mysql-release` 使用固定 MySQL 8.0.46 service、`127.0.0.1:13306` 与精确专用 Schema；安全脚本强制 Aerich 和 pytest 的 DB/Inventory 双配置完全一致，拒绝 3306、远端 host、非 testing、非专用 Schema 和目标漂移。Job 真实执行 Aerich 0→1→2、9 项 MySQL release gate，并保存 preflight、迁移日志、版本链、JUnit 和 cleanup JSON；`always()` 清理删除 Schema、停止准确 service container 并确认容器未运行和端口已关闭。
- 微信检查器验证期望 Origin、不可发布标记、source map、Secret/H5 marker、主包/分包/总包原始大小和符号链接，并生成含 SHA/run/逐文件 SHA-256 的 manifest 与聚合 checksum；repository hygiene 拒绝数据库、上传、备份、虚拟环境、非法 env、缓存/构建产物和高置信 Secret，报告不回显命中内容。
- 本地受控微信 production build 使用保留 CI Origin，通过 97 文件扫描：主包 425,527 bytes、`admin` 分包 178,092 bytes、总计 603,619 bytes、0 source map，明确为 `release_eligible=false`；它不是 Gate A RC，也没有上传。
- 新增工具链、production 配置、Redis 日志、OpenAPI CLI、微信发布配置、workflow、MySQL gate 和 repository hygiene 契约测试；完整后端 `1502 passed, 9 skipped`，CI Node policy 9 项、前端 61 套件/387 项、TypeScript、ESLint、Stylelint、OpenAPI 真实导出字节比较与类型漂移通过。OpenAPI 固定文件中的应用版本从陈旧的 0.4.0 同步为真实 0.6.0，路径和 Schema 未变化。
- 9.2.4 本地真实演练下载固定 `mysql:8.0.46` 镜像，启动唯一命名且只绑定 `127.0.0.1:13306` 的容器，成功应用三条迁移并通过 9 项门槛（2.32 秒）。清理报告确认专用 Schema 已删除、容器已停止、容器状态为非运行且端口关闭；随后删除容器对象和临时证据目录，未访问 3306 或任何持久/共享数据库。Docker 镜像作为共享缓存保留。
- `npm ci` 按 lockfile 成功，但 npm 对完整含 dev 依赖树报告 45 项（16 moderate、23 high、6 critical）；本阶段未执行破坏性自动修复或风险降级，逐项审计与 reachability 仍由 9.2.5 处理。
- 没有修改业务 API、数据库 Schema/迁移或依赖；除上述已销毁的专用 MySQL 容器外，没有连接微信后台、持久数据库或远端环境，也未上传、提审、commit、push、tag、release 或发布。

---

## Frontend Phase 9.1 — 微信发布基线审计执行（2026-08-29）

按微信单平台 Gate A 目标完成仓库级发布审计，并把规划转换为可直接用于 9.2 CI、9.3 演练和 9.4 真机验收的八类控制文档。Yijie Shen 已于 2026-08-29 完成项目负责人 Review，Phase 9.1 状态为 **Complete**，当前进入 9.2；这不代表 Gate A 已通过或已授权发布。

- 新增 `docs/09_release/` 发布文档目录：Release Decision、2026-08-29 基线证据、环境/Secret、CI Matrix、隔离演练 Runbook、微信 Functional/Smoke/E2E 矩阵、Risk Register 和 Gate A/Gate B Go/No-Go Checklist。
- 本地重新验证后端完整套件为 `1465 passed, 9 skipped`（9 项均为 MySQL-only）；前端 TypeScript、ESLint、Stylelint、61 套件/387 项 Jest、OpenAPI 类型漂移全部通过。真实 FastAPI 导出为 45 paths/109 schemas，与固定 OpenAPI JSON 字节一致。
- 微信 production build 成功（97 文件、603,604 bytes；主包侧 425,512 bytes、`admin` 分包 178,092 bytes、0 source map），但产物包含 `.example.invalid` API Origin，明确判为 Gate A No-Go，不把“编译成功”误报成可上传 RC。
- 依赖完整性 `npm ls --depth=0` 与 `pip check` 通过；官方 npm registry 审计为 10 项（4 moderate、1 high、5 critical）。风险链含直接组件、构建工具和 H5 依赖，不能继续统一归类为 H5-only；9.2 必须分析微信运行时/构建时可达性。Python 漏洞扫描尚未建立，未安装依赖，也未执行破坏性 `audit fix --force`。
- 审计确认仓库尚无 CI/部署/备份自动化、依赖 readiness 或受控 SUPER_ADMIN bootstrap；production 配置仍缺全面 fail-fast，Redis 日志存在完整 URL 泄漏风险，Node/npm 未 pin，OpenAPI CLI 在 Windows 非 UTF-8 帮助输出有编码缺口。这些均已登记责任角色、关闭 Gate 和所需证据。
- 同步 Phase 9 总规划、测试策略、README 和 AI Context。没有修改运行时代码、API、OpenAPI、数据库 Schema/迁移、依赖或版本；未连接/修改微信后台、持久数据库或远端环境，未上传、提审、commit、push、tag、release 或发布。

所有项目、前端、后端、CI/发布、测试和安全/合规责任角色统一映射为 Yijie Shen；其已确认微信单平台、Gate A 边界、production 安全配置、独立基础设施、CI→演练→真机顺序和外部操作禁区。当前进入 9.2 CI 与可重复构建；真实 MySQL、备份恢复、外部 HTTPS、微信体验版和真机证据仍未执行。

---

## Frontend Phase 9.1 — 微信发布目标与基线规划（2026-08-29）

将原“微信/H5 Functional、支付宝/抖音 Smoke”的宽泛 Phase 9 收敛为本版只发布微信小程序，并把发布拆为受控内部测试版 Gate A 与对外公开版 Gate B。当前仅完成规划和基线审计，不代表 CI、演练、体验版或公开发布已经通过。

- 新增 Phase 9 微信发布权威规划，定义 9.1–9.7 的输入、交付物和退出条件；内部测试版暂时沿用账号密码与 ADMIN+ 人工 Paid，公开版本必须单独关闭微信身份、安全、生产运维、隐私及在线收款时的微信支付门槛。
- 记录当前可复用证据与真实缺口：最新前端基线为 61 套件/387 项；OpenAPI、微信构建、后端 SQLite 和历史 MySQL 9 项门槛已有基础，但仓库尚无 CI，生产 Origin 仍为占位值，缺少生产相似备份恢复、依赖 readiness、受控 SUPER_ADMIN 初始化和正式图片存储方案。
- 冻结 CI 蓝图：后端 SQLite、隔离 MySQL 0→当前与 9 项门槛、前端 TypeScript/ESLint/Stylelint/Jest、OpenAPI 漂移、微信生产构建、生成物/Secret 和依赖审计。支付宝、抖音和 H5 不作为本版阻断项或发布承诺。
- 冻结隔离发布演练、Guest/普通用户/ADMIN/SUPER_ADMIN/禁用用户、业务、iOS/Android、弱网/断网、前后台和 unknown 矩阵，以及 Gate A/Gate B Go/No-Go 清单。
- 同步 README、学习路线、测试策略、多端策略、前端架构/API 集成契约和 AI Context。没有修改运行时代码、API、OpenAPI、数据库 Schema/迁移、依赖或版本；未启动 CI、外部服务或后台进程，未执行持久数据库迁移、微信后台变更、构建上传、提审、tag、release 或发布。

下一步是 9.2 CI 与可重复构建，不是直接实现微信支付或直接上传正式版。

---

## Frontend 管理筛选按钮即时查询、输入反馈与日期掩码（2026-08-29）

统一管理商品、管理订单、全局库存流水和指定 Kit 流水的查询交互：按钮型选项切换后立即请求第一页；文字输入继续保留显式“查询”提交，避免键入过程持续请求。管理用户的状态/角色按钮原本已经即时查询，本次补充回归覆盖但不改变行为。

- 管理商品的类型、状态和删除记录按钮会立即与上一次已提交的商品名称组合查询；“不含删除记录 / 包含删除记录”使用两个并列的互斥按钮，选中状态与其他筛选一致。
- 管理订单状态按钮会立即与上一次已提交的商品名称、订单号、用户 ID 和 UTC 日期组合；输入框中的新草稿不会因状态切换提前进入请求，只有点击“查询”并通过校验后才替换已提交快照。管理商品、管理订单和两个库存流水页在文字草稿与已提交快照不同时显示“输入条件尚未应用”浅色提示，提交或清空后消失。
- 全局与指定 Kit 库存流水的 transaction/source 按钮立即生效，并保留上一次已提交的 Product ID、Order source ID 和日期。来源从 `order` 切到其他类型时同步移除已提交 `source_id`，避免产生服务端明确拒绝的不自洽 Query。
- 管理订单和两个库存流水页复用单一数字输入源的日期掩码组件：用户可连续输入 `20260208`，界面始终按 `2026-02-08` 显示并固定两个横杠位置。查询前仍校验真实日期、闰年和起止顺序，API 仍接收原有 UTC ISO 半开区间。
- “清空”仍同时清除按钮与文字条件并立即回到默认第一页；列表 Hook 继续使用不可变筛选快照、服务端分页和 sequence token 隔离迟到响应。
- 定向 7 套件 / 39 项、完整前端 61 套件 / 387 项、TypeScript、ESLint、Stylelint、OpenAPI 类型漂移与微信端 production build 通过。支付宝/抖音/H5 并行构建在本机已有微信 watch 运行时长时间无输出，本次已精确停止任务所有进程，不记为通过。
- 2026-08-29 用户完成微信端 Functional，确认按钮即时查询与已提交文字条件组合、待应用提示、删除记录双按钮、8 位连续日期输入、固定横杠显示、清空及日期校验全部通过。
- 本次只改变前端交互与页面展示，没有后端 API、OpenAPI、数据库 Schema/迁移、新依赖或版本候选变化。

---

## Frontend 微信视觉兼容问题关闭（2026-08-29）

关闭 Phase 8.2 延期的管理页白色图案与登录输入 `_` 闪烁。用户已在微信开发者工具和真机相关页面完成复测并确认两项问题均已解决。

- 白色图案最终定位为原生 `Form` 同时承担提交语义和白色卡片背景、边框、圆角、内边距时的微信渲染异常。库存流水、管理商品、Kit 管理库存和管理订单统一改为外层 `View` 绘制卡片、内层透明 `Form` 只处理提交；没有提交语义的商品创建、编辑、Experience Option 和 Kit 价格配置容器直接改为 `View`。
- 全项目复查后，登录/注册的白色卡片本来就由外层 `View` 绘制，`Form` 只负责字段与提交，因此无需套用管理页改法；其余管理页未发现直接把白色卡片视觉样式挂到原生 `Form` 的同类风险。
- 登录输入 `_` 闪烁在后续复测中不再出现，用户确认已经消失，现按验收结论关闭；此前 `alwaysEmbed` 的单独尝试不足以证明因果关系，保留为历史排查记录而不将其表述为确定根因。
- Taro 4.2.1 微信 development build 成功，结构审计确认管理页视觉卡片均由 `View` 承担；真机构建继续使用 `.env.development.local` 的局域网 API 覆盖。用户最终确认库存流水、管理商品、Kit 管理库存、管理订单和预防性调整页面全部验证通过。
- 本次没有后端/API/OpenAPI、数据库 Schema/迁移、依赖或版本候选变化；未 commit、push、tag、release，也未执行持久数据库迁移。

---

## Frontend Phase 8.6 — Kit Inventory 管理（2026-08-28）

完成 ADMIN+ Kit 库存调整、指定 Kit 流水和全局库存流水纵向切片。工程实现、自动化、四端构建与后端完整回归均已完成；2026-08-28 用户确认微信开发者工具 Functional 全部验证完成并通过。

- 新增 `InventoryApi`，消费既有三个 ADMIN+ Inventory Endpoint；调整请求只发送 `change/reason` 和专属 `Idempotency-Key`，查询只投影允许的分页/type/source/product/UTC 条件。响应从 unknown 校验库存算术、transaction/source/operator/order 组合、UTC 与分页后白名单重建，不暴露内部 key 或额外字段。
- `ApiClient` 新增向后兼容的 `requestWithMeta()`，只为需要区分最终 HTTP 201 首次提交与 200 幂等重放的调用保留 status；既有 `request()` 继续只返回 data，refresh 后 metadata 来自最终重放响应。
- 新增调整业务意图状态机：每个新意图生成新 key，冻结 product/change/reason；进行中双击合并。network/timeout/cancel/contract/5xx 进入 unknown 且不自动重发，用户安全重试复用完全相同的 payload/key；明确失败或成功后清除意图。
- `admin` 分包新增动态 Kit 库存页和固定全局流水页；Product 管理详情与首页增加入口。Draft/Offline/Online Kit 均可调整；逻辑删除 Kit 在挂载 Inventory Hook 前阻断。全局固定页加入登录白名单，动态页不加入并让 Guest 返回固定管理商品列表；普通用户不会挂载管理 Hook，FastAPI ADMIN+ 仍是最终授权边界。
- 两类流水复用筛选/分页组件，支持 transaction/source、Order source ID、全局 Product ID 与 UTC 自然日；结束日期转次日排他上界，筛选换页保持服务端条件，sequence 隔离迟到响应。Order 来源可进入管理订单详情。
- 定向 9 套件/42 项并补充共享 Client metadata 回归，完整前端 60 套件/375 项、TypeScript strict、ESLint、Stylelint、OpenAPI 类型漂移、weapp/alipay/tt/h5 production build 及完整后端 1465 项通过，9 项 MySQL-only 按配置跳过。三端 `admin` 分包约 167 KiB；H5 主 JS 283 KiB、入口 370 KiB，继续保留既有 244 KiB 和 `[hash]` 告警。
- `npm ls --depth=0` 正常；官方 registry 审计仍为 Taro H5 上游链 10 项风险（4 moderate、1 high、5 critical），破坏性强制降级未执行。同步前端路线、架构、API 集成、测试策略、README、AI Context 与 Phase 8.6 学习笔记；后端业务/API 文档无需变化，因为没有修改任何后端契约。
- 没有数据库 Schema/迁移、OpenAPI 生成物、依赖、版本候选变化；未 commit、push、tag、release，也未执行持久数据库迁移。Phase 8.2 管理页白色图案和登录 `_` 闪烁在本阶段结束时仍为延期项，后于 2026-08-29 完成专项复测并关闭。

---

## Frontend Phase 8.8–8.9 — Product Audit、ADMIN User 与管理端 Review（2026-08-28）

完成 Product 操作历史、ADMIN 用户列表/筛选/禁用，并对当时已交付管理端执行权限、上传、幂等、隐私、分包、契约、包体与四端构建 Review。2026-08-28 用户确认微信开发者工具 Functional 全部通过，包括用独立 Swagger ADMIN Session 禁用普通用户后，旧 refresh 首次 `1005`、重放 `1006`，旧 access 触发前端 Session 清理；该次 Review 当时未包含尚未实施的 Phase 8.6，随后 8.6 已在上方独立条目完成工程与微信 Functional 收口。

- Product Audit 复用既有 ADMIN+ 分页端点，新页面从 Product 管理详情进入，支持 Draft、Offline、Online 与逻辑删除历史；动态路由要求正安全整数 ID 和 Experience/Kit 类型，Runtime Guard 绑定 `target_type=product` 与目标 ID，只投影允许的审计字段，未知 action 安全回退到服务端原值。
- ADMIN User 后端收口为严格 `page/page_size/status/role` Query、稳定 `created_at DESC,id DESC` 分页、显式 Mapper 和 typed Page；列表不返回 phone/avatar/password。禁用使用目标行锁，状态更新与 `DISABLE_USER` 审计同事务提交；重复禁用幂等且不重复写审计，审计失败会整体回滚。
- 认证边界补齐当前状态检查：禁用账号的旧 access 立即返回 code `1005`；旧 refresh 首次返回 `1005` 并撤销，后续重放返回 `1006`。前端受保护 JSON/上传请求遇到 `1005` 立即清理 Session 且不 refresh；network/timeout/cancel/contract/5xx 的禁用结果保持 unknown，不自动重发。
- `admin` 分包新增商品操作历史和用户管理页；首页只向 ADMIN+ 展示“管理用户”，管理详情新增“操作历史”。Guest 仅允许固定 `/admin/pages/users/index` 登录回跳，普通用户在挂载管理 Hook 前拦截；FastAPI ADMIN+ 仍是最终授权边界。不存在的用户详情、启用和头像上传未伪造页面按钮。
- OpenAPI 已更新为 45 paths/109 schemas。完整前端 54 套件/350 项、完整后端 1465 项通过（9 项 MySQL-only 按配置跳过）；TypeScript strict、ESLint、Stylelint、OpenAPI 类型漂移、npm 依赖树和 weapp/alipay/tt/h5 production build 全部通过。微信 `admin` 分包约 131.2 KiB；H5 主 JS 282 KiB、入口 369 KiB，继续保留既有 244 KiB 体积建议和 `[hash]` 上游告警。
- 官方 npm registry 审计报告 10 项当前 Taro H5 上游依赖链问题（4 moderate、1 high、5 critical）；建议修复会破坏性降级到 Taro 3.x，因此未执行 `npm audit fix`，需后续跟踪 Taro 升级窗口。同步 User 需求/API、前端路线/架构/集成/测试/README、AI Context 与学习笔记；没有数据库 Schema/迁移、依赖或版本候选变化。
- Phase 8.2 的管理商品列表白色图案和登录 `_` 闪烁在本阶段结束时继续延期且未被误报修复；后于 2026-08-29 完成专项复测并关闭。未 commit、push、tag、release，也未执行持久数据库迁移。

---

## ADMIN Order 历史商品名称筛选（2026-08-28）

补齐管理订单列表按商品名称查找能力。新增 `GET /api/v1/admin/orders?product_name=...`，trim 后限制 1 至 100 字符，并可与状态、精确订单号、用户 ID 和 UTC 时间范围组合；匹配事实来源固定为 `order_items.product_name` 下单快照，不关联当前 Product，因此商品改名、下架或逻辑删除不会改变历史订单检索结果。

- Repository 通过匹配 Item 的 Order ID 子查询过滤外层 Order，再沿用原有计数、`Count(items)`、`created_at DESC,id DESC` 和数据库分页；同一订单多条 Item 命中时仍只返回一单，`total/pages/item_count` 不被放大。
- 管理订单页新增“商品名称（支持部分匹配）”，筛选草稿 trim 后才提交；第一页、下一页与当前筛选提示携带同一关键词。OpenAPI、生成 TypeScript 类型和 `OrderApi` Query 白名单同步增加 `product_name`，列表响应形状不变。
- 自动化覆盖 1–100 字符契约、Router/Service 转发、历史快照与当前 Product 名称隔离、多 Item 命中去重、组合筛选、分页元数据、HTTP/OpenAPI、Endpoint 白名单、Hook 翻页和页面输入。后端定向 128 项、Order 全模块 411 项、完整 SQLite 1457 项均通过，9 项 MySQL-only 按配置跳过；前端完整 47 套件/330 项、TypeScript、ESLint、Stylelint、OpenAPI 漂移和 weapp/alipay/tt/h5 production build 均通过。
- H5 继续只有既有的 Webpack `[hash]` 弃用与 244 KiB 体积建议：主 JS 281 KiB、入口 368 KiB；Jest 继续只有 Taro Test Utils 的 React `act` 弃用告警。
- 同步 Order 需求/API、数据库查询与索引取舍、前端架构/集成/测试/学习笔记和 AI Context。包含查询的前导 `%` 无法利用普通 B-Tree；跨 MySQL 中文 FULLTEXT 与 SQLite FTS 的专用搜索设计需由生产数据和 `EXPLAIN` 驱动，因此本次不新增无效索引、数据库 Schema、迁移或依赖，也不改变版本候选。微信开发者工具的新增商品名称筛选 Functional 待用户补测。

---

## Product JPEG 导出尾部兼容与规范化（2026-08-27）

修复微信导出的有效 JPEG 被误报为 `42221 invalid_image_content`：19 个真实样本均为可解码 JPEG，但在标准 `FF D9` 后附加固定 8 字节标记和 JPEG 本体的 16-byte MD5，旧 `content.endswith(FF D9)` 检测产生假阴性。

- `LocalImageStorage` 只接受精确匹配的 24 字节尾部：JPEG 本体必须有正确头尾、固定前缀必须一致、MD5 必须匹配；随后剥离尾部并以 UUID 文件名原子保存规范化 JPEG。原始上传大小仍受 2 MiB 限制。
- 任意尾随数据、错误摘要、伪造前缀和 MIME/内容不匹配继续分别按既有 `invalid_image_content` / `content_type_mismatch` 契约拒绝；MD5 只用于识别导出格式，不作为认证或安全摘要。
- 存储单测覆盖成功规范化、错误 MD5、任意尾随、MIME 不匹配和规范化后 size/content；真实 multipart SQLite API 测试覆盖上传带尾部 JPEG、数据库/审计成功及静态文件只返回规范化 JPEG。定向 28 项通过；`D:\pinkdooPics` 的 19 个真实样本全部经正式存储类规范化成功且临时输出已清理；完整后端 1450 项通过，9 项 MySQL-only 按配置跳过。
- 同步 Product 业务规则、API 文档、前端集成/学习笔记与 AI Context。没有 API 路径、请求/响应 Schema、错误码、数据库、迁移、依赖或版本候选变化。

---

## Frontend Phase 8.4–8.5 — ADMIN Product 图片与上下架/readiness（2026-08-26）

在 Phase 8.1–8.3 管理读写聚合之上，完成 Product 公共图和 Experience Option 专属图的上传、排序、封面、逻辑删除，以及 Product 上下架和完整 readiness issues 展示。工程实现、自动化与四端构建已完成；微信 Functional 待用户验收，并包含 Phase 8.3 延期的旧/新订单价格快照联动。

- `ApiClient` 新增可注入 Upload Transport；`TaroFileUploadTransport` 使用 `Taro.uploadFile`，解析字符串响应信封，分类取消/网络/超时，并复用 Bearer、code `1006` single-flight refresh 与最多一次重放。multipart boundary 由平台生成，不手工设置 `Content-Type`。
- 新增跨端 `ImagePickerPort/TaroImagePickerAdapter`，管理页面不直接依赖平台原生 API。前端可用元数据预检 2 MiB 和 jpg/png/webp；后端继续权威验证签名、MIME/内容一致性、图片归属和封面唯一。
- `AdminProductApi` 新增 Product/Option 图片上传、图片 sort/封面 PATCH、无 body DELETE，以及 online/offline empty-body PATCH；所有响应继续从 `unknown` 做联合 Runtime Guard 与白名单投影。
- 新增图片/状态 mutation Hook 和图片管理页。Product 公共图可设唯一封面，Option 专属图无封面；Draft/Offline 可写，Online/逻辑删除只读。详情页增加“管理图片”“上架/下架”，上架失败完整、有序展示 `42201.data.issues`，不复制后端 ProductValidator。
- 写命令使用 `idle/submitting/succeeded/failed/unknown`、进行中 Promise 合并和详情页同步命令互斥；network/timeout/cancel/contract/5xx unknown 不自动重发，成功或核对均重新读取服务端管理详情。
- 定向 8 套件/66 项、完整前端 47 套件/328 项、TypeScript strict、ESLint、Stylelint、OpenAPI 漂移、weapp/alipay/tt/h5 production build、Product API 52 项及完整后端 1446 项均通过，9 项 MySQL-only 按配置跳过。保留 H5 体积、Webpack `[hash]` 和 React Test Utils `act` 既有告警。没有后端行为、数据库 Schema/迁移、OpenAPI 生成物、依赖或版本变化。
- 新增 Phase 8.4–8.5 学习笔记和微信 Functional 清单，覆盖真实选图/上传、文件拒绝、封面/排序/删除、Option 图片归属、完整 readiness、Kit 零库存上架、下架不改库存/历史、unknown 核对与订单快照；Phase 8.2 的管理页白色图案和登录 `_` 闪烁在本阶段结束时仍是独立延期问题，后于 2026-08-29 完成专项复测并关闭。

---

## Frontend Phase 8.3 — ADMIN Experience Option 与 Kit 价格管理（2026-08-26）

在 Phase 8.1 管理读模型和 8.2 Product 基本写入之上，完成 Experience Option 新增/恢复、部分修改、逻辑删除，以及 Kit 当前价格修改。图片、上下架/readiness、Inventory 与 Audit 仍由后续阶段负责。

- `AdminProductApi` 新增 Option POST/PATCH/DELETE 和 Kit price PATCH；请求严格投影，Option 完整/Base、删除与 KitPrice 响应均从 unknown 做白名单 Runtime Guard。Kit 改价绝不发送 stock。
- 新增配置 mutation Hook，四类动作共享 `idle/submitting/succeeded/failed/unknown` 与进行中 Promise 合并；network/timeout/cancel/contract/5xx 不自动重发，只引导重新加载管理详情核对。
- 管理详情新增类型专属入口和分型配置页。Experience 表单按四维组合工作，PATCH 只发送真实差异，删除确认说明历史订单快照与“再建同组合恢复原 ID”；Kit 页面把库存固定为只读。
- Online/已删除 Product 禁用配置写入只作即时反馈；FastAPI ADMIN+ 与 40001/404xx/40903/40905/40911/40912 仍是最终裁决。当前价格只影响未来下单，既有订单页面继续消费快照。
- 新增 Endpoint、路由、状态机、页面、权限和表单回归测试。8.3 定向 5 套件/48 项、完整前端 43 套件/306 项、TypeScript、ESLint、Stylelint、OpenAPI 漂移与 weapp/alipay/tt/h5 production build 均通过；Product API 52 项及完整后端 1446 项通过，9 项 MySQL-only 跳过。H5 主 JS 278 KiB、入口 362 KiB，保留既有 244 KiB 体积建议与 Webpack `[hash]` 告警。2026-08-26 用户确认微信 Functional 除改价前后订单快照外全部通过；该联动场景因当前没有上下架按钮，延期到 Phase 8.5 后补测。没有后端行为、数据库 Schema/迁移、OpenAPI 生成物、依赖或版本变化。

### Phase 8.2 视觉问题后续状态

管理商品列表左上角白色图案与登录输入 `_` 闪烁在 2026-08-26 阶段结束时尚未修复，三处 Input 的 `alwaysEmbed` 已编译生效但首次复测无效，因此当时正确标记为延期。两项后于 2026-08-29 完成专项复测并关闭：白色图案通过把卡片视觉层从原生 `Form` 移到外层 `View` 解决；登录 `_` 闪烁后续无法复现并由用户确认消失。

---

## Frontend Phase 8.2 — ADMIN Product 基本写入（2026-08-26）

在 Phase 8.1 管理读模型之上完成 Product 最小写入纵向切片：Experience/Kit 草稿创建、名称/描述编辑，以及 Draft/Offline Product 逻辑删除。范围不包含 Option、创建后的 Kit 价格、图片、上下架、Inventory、Audit 或删除恢复。

- `AdminProductApi` 新增两类创建、基本信息 PATCH 和无 body DELETE；请求严格白名单投影，响应从 `unknown` 逐字段校验。Kit 创建不接受 stock，Experience 创建不混入 Option 价格。
- 新增统一 mutation Hook，以 `idle/submitting/succeeded/failed/unknown` 表示写请求；进行中 Promise 合并，network/timeout/cancel/contract/5xx 结果未知且不自动重发。
- 管理列表新增类型明确的创建入口；新增分型创建页与权威详情驱动的编辑页；详情页增加状态边界、编辑、删除确认和 unknown 后核对入口。PATCH 只发送真实改动，区分字段缺失与 `description: null`。
- 普通用户在挂载查询或 mutation Hook 前拦截，Guest 只允许登录后返回固定管理列表；客户端禁用不替代 FastAPI ADMIN+ 与 40903/40904/40905 服务端裁决。
- Phase 8.2 定向 7 套件/56 项、完整前端 41 套件/288 项与 TypeScript strict 通过。2026-08-26 用户确认微信业务 Functional 全部通过。管理页白色图案及登录输入 `_` 闪烁当时仍未解决，`alwaysEmbed` 已编译但首次复测无效，因此延期专项处理；两项已于 2026-08-29 完成复测并关闭。未修改后端行为、数据库 Schema、OpenAPI 生成物、依赖或版本。

## Frontend Auth Backfill — 账号密码注册（2026-08-25）

补齐 Phase 5 曾延后的 Guest 账号密码注册纵向链路。`AuthApi.register()` 使用生成 `UserCreate` 类型与 User Runtime Guard；`AuthContext.register()` 只返回服务端 User，不在缺少 Token 时建立 Session。登录页新增注册入口，注册页包含用户名、昵称、手机号、密码与确认密码，成功后由用户主动登录，并在登录/注册切换间保留固定白名单 redirect。

- 注册请求只投影 username/password/nickname/phone；确认密码不进入 API。非密码字段 trim，密码不 trim、不进 URL/Storage/日志；成功响应白名单不含 password。
- 同步 ref 门闩覆盖 React state 尚未提交时的快速双击；network/timeout/cancel/contract/5xx 视为非幂等 POST 结果未知，不自动重发，先引导尝试登录。1001/1007 分别显示用户名/手机号唯一性提示。
- 审阅发现 `user_api.md` 的 username 字符集旧说明与实际 Pydantic/OpenAPI 无 pattern 不一致，已把 API 文档同步为当前事实；客户端只做实际 Schema 的长度校验，不以客户端规则代替后端安全边界。
- 新增 Endpoint、路由、登录入口、页面、成功/未知/重复提交和字段边界测试；完整前端为 38 套件/255 项。没有后端行为、数据库 Schema、OpenAPI 生成物、依赖或版本变化。
- 2026-08-25 用户确认微信注册 Functional 全部通过：普通注册、字段校验、用户名/手机号唯一性、快速连点、断网结果未知、密码不进入 URL/Storage/日志，以及订单列表 redirect 经注册和登录后正确返回“我的订单”。

## Frontend Phase 8.1 — ADMIN Product 只读管理（2026-08-25）

Phase 8 已按“安全读模型 → Product 基本写入 → Option/Kit 价格 → 图片 → readiness/状态 → Inventory → 既有 Order 整合 → Audit/User → 最终 Review”冻结为 8.1–8.9。8.1 完成 ADMIN Product 列表、组合筛选、服务端分页与 Experience/Kit 管理详情；管理读模型允许未完成 Draft 与逻辑删除历史，不复用只接受完整 Online 聚合的公开 Product Guard。

- 新增认证 `AdminProductApi`、管理 Page/Detail Runtime Guard 与请求白名单；严格校验 Product 类型/状态、金额、UTC 时间、Kit stock 上限及 Experience dimensions/Option 一致性。
- 新增管理 Product 列表/详情 Hook、正安全整数 ID + 类型动态路由、筛选换页重置、重复加载保护和 sequence 迟到响应隔离。
- `admin` 分包新增管理商品列表与详情：首页只为 ADMIN+ 展示入口，Guest 只允许固定列表回跳，普通用户在挂载 Hook 前拦截；页面展示草稿空配置、状态与删除标记，但明确不提供任何 mutation。
- 新增 Phase 8.1 Endpoint、Feature、路由和页面测试；同步学习路线、学习笔记、架构、API 集成契约、测试策略、README 与 AI Context。未改变后端 API、数据库、OpenAPI Schema 或依赖。
- Phase 8.1 定向前端 8 套件/39 项、完整前端 37 套件/240 项、TypeScript strict、全 `src` ESLint、Stylelint、OpenAPI 类型漂移、Product API 52 项、完整后端 1445 项（9 项 MySQL-only 跳过）及 weapp/alipay/tt/h5 production build 全部通过。H5 保留 276 KiB 主 JS/360 KiB 入口体积及 `[hash]` 上游告警。首页账号信息与操作按钮同步拆为两层，按钮文字固定单行，窄屏按整颗按钮换行。
- 新增受 development、仓库内 SQLite 和双显式参数保护的 `[LOCAL-ADMIN-FE]` Seed，通过正式 Product Service 幂等创建空配置 Experience Draft、无封面 Kit Draft 和逻辑删除 Kit，并保留正常审计链。2026-08-25 已写入本地开发库作为剩余 Functional 样本；不创建图片、不调整库存、不触碰既有 `[LOCAL-FE]` Online 商品。
- 2026-08-25 用户确认上述 Draft/逻辑删除真实样本的筛选、详情、空配置、删除标记及无恢复按钮均通过，Phase 8.1 微信 Functional 全部收口。

## Frontend Phase 7.4 — ADMIN 订单查询与人工 Paid/Completed（2026-08-24）

### Summary

完成 ADMIN+“全部订单列表/完整筛选 → 管理详情 → Pending 人工标记 Paid → Paid 完成 → 服务端详情核对”的最小纵向切片。状态操作严格复用现有 FastAPI 无 body PATCH；普通用户在挂载管理请求前即被页面角色边界拦截，后端 ADMIN+ 依赖仍是唯一授权事实。支付渠道、退款、任意状态编辑、订单删除和审计历史页面不在本阶段范围。

### Implemented

- 扩展 `OrderApi`：新增 ADMIN 列表/详情、`markOrderPaid()`、`completeOrder()`；列表只投影 7 个冻结 Query，响应逐字段校验并只输出 `user_id/user_nickname` 安全用户字段，两个状态 PATCH 不设置 body 且必须返回目标状态。
- 新增管理列表 Feature/Page：固定 `page_size=20`，支持状态、精确订单号、用户 ID、UTC 起止日期和服务端分页；界面包含结束日并转换为 API 次日排他上界，非法订单号/用户 ID/日期/范围在请求前拒绝；sequence 与同步 ref 隔离迟到响应和重复下一页。
- 新增管理详情状态机：服务端 Pending 只派生 `mark_paid`，Paid 只派生 `complete`，Cancelled/Completed 无命令；进行中 Promise 合并。明确 40921 后 GET 权威详情，network/timeout/cancel/contract/5xx 进入 unknown 且不自动重发；PATCH 成功后的 GET 失败不推翻成功。
- `admin` 分包注册管理列表/详情；首页只为 ADMIN+ 显示入口。列表和详情在认证并确认角色后才挂载 Hook；普通用户直接进入页面不发 ADMIN API。登录 redirect 白名单只增加固定管理列表，不允许动态详情或任意内部 URL。
- 新增 API/纯函数/Hook/页面/权限/路由和真实客户端纵向测试；纵向测试保留真实 `OrderApi → ApiClient`，固定列表→详情→Paid→详情→Complete→详情及 Bearer/Query/empty-body 契约。
- 新增 Phase 7.4 学习笔记并同步路线图、API 集成契约、前端架构、测试策略、README 与 AI Context；Phase 7.3 当时的人工状态按用户结果更新为“除 40921 双端竞态外均通过”，该竞态后于 2026-08-25 补测完成。

### Verification

- 完整前端 Jest 31 套件 / 213 项通过；TypeScript strict、全 `src` ESLint `--max-warnings=0`、Stylelint 和 OpenAPI 类型漂移检查全部通过。Taro Test Utils 仍输出既有 React 18 `act` 上游弃用告警。
- 后端 Order API 回归 107 项通过；完整后端 1445 项通过，9 项 MySQL-only 门槛按配置跳过。未修改后端代码、数据库或开发数据，未启动临时 MySQL。
- weapp、alipay、tt、h5 四端 production build 均成功。H5 app 入口 359 KiB、主 JS 276 KiB，超过 Webpack 244 KiB 建议线；保留 Taro/Webpack `[hash]` 弃用告警。
- 未新增 npm/Python 依赖、FastAPI 端点、数据库 Schema、迁移或生成 Schema；未 commit、push、tag 或 release。

### Next

2026-08-25 用户确认 Phase 7.3/7.4 剩余微信 Functional 全部通过：断网 unknown 显示“结果待确认”且不自动重发，独立 Swagger 客户端抢先变更后旧用户 cancel/旧 ADMIN 状态操作均收到 40921 并通过 GET 收敛，普通用户直调 ADMIN API 返回 403 且不 refresh。Slow 3G 约 310 ms 正常返回、未触发 timeout，严格 timeout 仅作为非阻断补测。Phase 7.1–7.4 已收口；下一步冻结 Phase 8 第一条 ADMIN Product 最小纵向切片，不提前实现审计页、退款、任意状态修改或支付占位。

---

## Frontend Phase 7.3 — 我的订单、详情与 Pending 取消（2026-08-24）

### Summary

完成用户侧“创建结果/unknown → 我的订单 → owner-only 详情 → Pending 取消 → 服务端权威重拉”的纵向切片。列表、详情、状态和取消严格复用现有 FastAPI Order/Inventory 契约；客户端不伪造支付状态、库存恢复或历史商品信息。ADMIN 人工 Paid/Completed 尚未实现，Phase 7.3 微信开发者工具 Functional 待验证。

### Implemented

- 扩展 `OrderApi`：新增认证 `GET /orders`、`GET /orders/{id}` 与无 body `PATCH /orders/{id}/cancel`；Query 只投影 page/page_size/status，Page/ListItem/Detail/Status 从 unknown 逐字段校验并白名单输出。
- 新增订单列表 Hook/Page：固定 `page_size=20`，支持全部及四种状态筛选、Loading/Empty/Error/Content、下一页错误恢复、同步重复加载保护和 sequence 迟到响应隔离；分页只采用服务端 page/pages/total。
- 新增严格 Order ID 路由和详情页：只展示服务端历史 Item/Option/金额/备注/时间快照；不存在和他人订单的 40411 使用同一不可访问提示。
- 新增取消状态机：仅服务端 Pending 显示入口，同一进行中操作复用 Promise；network/timeout/cancel、5xx 或成功响应契约损坏进入 unknown 且不自动重发。成功后 GET 详情，重拉失败不推翻已确认成功；40921 后也重拉以收敛跨端状态竞态。
- 7.2 创建成功与 unknown 均增加“我的订单”核对入口，首页 authenticated 区域增加入口；登录 redirect 白名单仅增加固定订单列表，不开放动态详情或任意内部 URL。
- 新增 Phase 7.3 学习笔记，并同步路线图、API 集成契约、前端架构、测试策略、README 与 AI Context。

### Verification

- Phase 7.3 定向 Jest 8 套件 / 61 项、完整前端 Jest 25 套件 / 172 项通过；TypeScript strict、全 `src` ESLint `--max-warnings=0`、Stylelint 与 OpenAPI 类型漂移检查全部通过。Taro Test Utils 仍输出既有 React 18 `act` 上游弃用告警。
- 真实 FastAPI + SQLite Order HTTP 集成/状态矩阵 53 项通过；完整后端 1445 项通过，9 项 MySQL-only 门槛按配置跳过。本阶段未修改或迁移数据库，未启动临时 MySQL。
- weapp、alipay、tt、h5 四端 production build 均成功。H5 app 入口 350 KiB、主 JS 266 KiB，超过 Webpack 244 KiB 建议线；保留 Taro/Webpack `[hash]` 弃用告警。
- 首次 Node 工具加载受 Windows 文件扫描影响出现长时间 I/O 等待；所有 PASS 均来自真实退出码。最终使用 Codex 工作区 Node 运行同一项目依赖，未改 `package.json` 或 lockfile。
- 未新增 npm/Python 依赖、后端 API、数据库 Schema 或迁移；未 commit、push、tag 或 release。

### Next

按学习笔记完成微信开发者工具 Functional：登录回跳、筛选/分页、7.2 unknown 核对、历史快照、40411 资源隐藏、Pending 取消与 Kit 库存恢复、终态无按钮、弱网 unknown 和 40921 竞态。通过后进入 ADMIN 订单列表/详情及人工 Pending → Paid → Completed。

---

## Frontend Phase 7.2 — Order 创建纵向切片（2026-08-24）

### Summary

完成“本地购物清单 → 登录确认 → `POST /api/v1/orders` → 服务端订单结果 → Cart 对账”的最小纵向切片。Experience 请求严格携带真实 Option ID，Kit 严格省略 Option；提交状态明确区分失败与网络结果未知，成功页只消费 FastAPI Order 快照。Phase 7.2 交付时尚未实现 Order 查询/详情/取消和 ADMIN 状态操作；用户侧查询/取消已由 Phase 7.3 补齐。

### Implemented

- 新增 `OrderApi.createOrder()`：复用现有认证 HTTP Client，显式白名单投影 items/remark，并对 OrderDetail 的订单号、状态、UTC 时间、金额聚合、Experience 完整 Option/Kit 全 null Option 快照执行运行时校验。
- 新增 `OrderSubmissionStore` 的 `idle/submitting/succeeded/failed/unknown` 判别状态机：开始时冻结 Cart/request，同一进行中提交复用 Promise；network/timeout 进入 unknown 且不自动 POST，明确失败允许修正后主动重试。
- 新增确认页和受控 remark；Cart 页面增加确认入口。Guest 登录回跳只允许注册的确认页，登录成功 `reLaunch` 返回；外部、未注册和畸形 redirect 安全回退首页。
- 成功页只展示服务端 order_no、状态、时间、Item/Option、单价/小计/总额和 remark，不使用本地预览金额生成权威结果。
- `CartStore.reconcileSubmittedItems()` 与其他 mutation 串行：相等移除、大于提交量保留差额、小于提交量保守保留并报告 conflict、无关 Item 不变；持久化失败不发布伪清理。Cart 对账失败只能附加成功警告，不把已创建订单降级为失败。
- 新增纵向集成测试，保留真实 CartStore → SubmissionStore → OrderApi → ApiClient 调用链，仅替换 Storage、transport 与 Auth 平台边界；同步新增 Phase 7.2 学习笔记并更新架构、API 契约、路线图、测试策略、README 与 AI Context。

### Verification

- 完整前端 Jest 19 套件 / 130 项通过；`npm run typecheck`、ESLint `--max-warnings=0`、Stylelint 与 OpenAPI 类型漂移检查全部通过。已知 Taro Test Utils 旧 `act` 告警不阻断。
- 真实 FastAPI + SQLite Order 创建、边界和事务失败 34 项通过，覆盖 Experience、Kit、混合订单、Inventory 校验与回滚；完整后端为 1445 项通过、9 项 MySQL-only 门槛按当前配置跳过。本轮未修改或迁移数据库，未运行临时 MySQL。
- weapp、alipay、tt、h5 四端 production build 均成功。H5 app 入口 343 KiB、主 JS 259 KiB，仍超过 244 KiB 性能建议线，并保留 Taro/Webpack `[hash]` 弃用警告。
- 未新增 npm/Python 依赖、后端 API、数据库 Schema 或迁移；未 commit、push、tag 或 release。

### Functional Result

2026-08-24 用户完成微信开发者工具 Functional，确认 Guest 登录返回、真实 Experience/Kit/混合下单、库存不足、快速连点、弱网 unknown 与成功 Cart 对账全部通过；同时确认 Phase 7.1 剩余的有库存 Kit 加入分支通过。该结果不替代真机、H5、正式 HTTPS/合法域名验收；H5 真实联调继续等待 FastAPI 严格 CORS allowlist。unknown 的我的订单核对入口和 Pending 取消已由 Phase 7.3 完成工程实现，微信 Functional 另行验证。

---

## Frontend Phase 7.1 — 本地购物车纵向切片（2026-08-22）

### Summary

完成 Phase 7 的第一条本地纵向切片：游客或登录用户可从 Product 详情把真实 Experience Option 或 Kit 加入设备级购物车，重启后恢复，并修改数量或移除；本地展示快照与后端 Order 权威事实保持明确隔离。确认页、真实 Order 创建、查询/取消和 ADMIN 状态操作尚未实现，微信开发者工具 Functional 待人工验证。

### Implemented

- 新增 Experience/Kit `CartItem` 判别联合：Experience 在类型层要求正整数 Option 和完整配置说明，Kit 固定 null Option/配置；本地唯一身份与后端一致，为 `(productId, experienceOptionId)`。
- 新增可独立测试的 `CartStore`：`pinkdoohub.cart.v1` 版本化格式、unknown Runtime Guard、白名单重写、坏数据清除、最多 10 个不同组合和每项 1–99 数量；重复组合合并，不同 Option 保持独立。
- 所有 mutation 经 Promise 队列串行化，避免快速点击基于旧数量并发写入；采用先写 Storage、成功后发布 Context 的保守更新，持久化失败不展示伪成功。
- 新增应用级 `CartProvider`，复用现有 `StoragePort`/`TaroStorageAdapter`。Cart 是不含 Token/User/密码/remark 的设备级游客状态，登录或退出不自动清除。
- Product 详情加入“查看购物车/加入购物车”：Experience 保存当前真实 Option ID、组合、预览价和 Option 图片；Kit 保存 null Option，无库存时禁用。新增 Cart 页面四态、预览单价、数量增减和移除。
- 新增 `buildOrderItems()` 白名单映射：Experience 只发送 Product/Option/quantity，Kit 只发送 Product/quantity；名称、配置、图片、预览价和 ProductType 不进入未来 Order create 请求。
- 新增 Phase 7.1 学习笔记，解释本地状态与服务端权威、判别联合、Storage unknown、版本迁移、异步 lost update、保守更新和无客户端幂等的 Order create 边界。

### Verification

- 新增 3 个 Jest 套件 / 17 项，覆盖坏缓存、白名单、并发合并、不同 Option、10/99 边界、Storage 失败、修改/删除/清空、Product→Cart 和 Cart→Order 映射及 Cart 页面四态；完整前端为 14 套件 / 87 项通过。
- `npm run typecheck`、ESLint `--max-warnings=0`、Stylelint 和 OpenAPI 类型漂移检查均通过。已知非阻断输出仍只有 Taro Test Utils 的旧 `act` 警告。
- 用户现有 weapp watcher 已产出并注册 Cart 页面；未启动第二组微信构建。alipay、tt、h5 独立生产构建通过。H5 入口为 334 KiB、主 JS 251 KiB，仍超过 244 KiB 建议线，并保留 Taro/Webpack `[hash]` 上游弃用警告。
- 后端完整 SQLite 回归 1442 项通过，9 项必须显式配置隔离 MySQL 的发布门槛按预期跳过；本轮未启动临时 MySQL。
- 未新增 npm/Python 依赖、后端 API、数据库 Schema 或迁移。

### Next

先按学习笔记完成微信开发者工具 Cart Functional：真实第二 Option、重复合并、不同 Option 分行、Kit、数量/移除、重启恢复、登录/退出保留、坏缓存清理和无库存禁用。通过后进入 Phase 7.2 确认页、登录返回和一次性 Order 创建；在服务端支持客户端幂等键前，未知结果的 POST 不自动重试。

---

## Frontend Phase 6 — 公开 Product 列表纵向链路（2026-08-20）

### Summary

完成前端 Product 浏览纵向链路：游客可通过公开首页读取 Online Product，按服务端分页、类型和 keyword 浏览 Experience 与 Kit，并进入类型专属详情选择真实 Option；Product 数据状态与 AuthContext 解耦。Endpoint、运行时契约、图片地址、分页/搜索 Feature、四态 UI、详情、自动化、四端构建和微信开发者工具 Functional 均已完成。

### Implemented

- 新增严格限定为本地开发环境的 `python -m app.tasks.product_functional_seed`：要求 development、仓库内 SQLite/图片目录、`--apply` + `--confirm-local-only` 双确认和启用的 ADMIN/SUPER_ADMIN 操作者。脚本复用 Product Service、Validator、AuditLog 与 LocalImageStorage，生成 7 Experience、6 Kit、13 条 Online Product 和 21 张相对图片；其中专用多配置 Experience 有两个不同组合、价格和配色图片的 Option。完整同名数据可幂等跳过，冲突数据安全停止，图片登记失败执行文件补偿。
- 修复 Seed PNG 夹具只有文件签名、无法真实解码的问题：改为生成带 IHDR、zlib IDAT、IEND 和逐 chunk CRC 的 2×2 RGB PNG；重复执行只原子修复 Seed Product 引用的旧错误内容或缺失文件，不覆盖其他图片。2026-08-21 首次修复当时 12 条目录的结果为 `created=0 / skipped=12 / repaired_images=18`。
- 新增 `ProductApi.listProducts()`，直接复用 OpenAPI 生成的 Product Query/Page/Item 类型；HTTP Client 结果保持 `unknown`，Endpoint 校验并白名单投影 ID、名称、Product Enum、两位小数金额、图片地址和分页字段。公开请求固定 `auth: none`，不会因本地存在 Session 而附带 Token。
- 新增唯一 `resolveAssetUrl()`：HTTP(S) 绝对 URL 原样使用，`/uploads/...` 相对已校验 API Origin 补全，其他路径拒绝；ProductCard 使用懒加载和图片失败占位。
- 新增 `useProductList` Feature，首屏固定 `page=1&page_size=10`，按服务端 `page/pages/total` 加载下一页；防止同页重复点击，并以请求 sequence 隔离迟到旧响应，不依赖所有小程序运行时未必提供的 `AbortController`。
- 首页改为公开 Product 页面，互斥展示 Loading/Empty/Error/Content；首屏失败可重试，下一页失败保留已有内容。Experience 按 `product_type.value` 显示“起”，Kit 显示固定价格；guest/authenticated/error 状态只影响账号操作，不阻断公开浏览。
- Jest setup 集中 mock Taro 4.2.1 router 循环依赖，并为 jsdom 提供 `IntersectionObserver`，支持 `Image lazyLoad` 组件测试且不隐藏现有上游 `act` 弃用告警。
- 新增 Phase 6 学习笔记，解释生成类型与 Runtime Guard、金额字符串、Enum、判别四态、服务端分页、请求竞态、相对图片和公开数据/认证状态边界。
- 首页新增“全部 / 拼豆体验 / 材料套装”类型筛选和最长 100 字符的受控 keyword 搜索；类型立即生效，keyword 在 300ms 静默期后去除首尾空白并查询。筛选变化重置第 1 页，加载更多保留查询上下文，迟到响应继续由 sequence token 隔离。
- 新增公开 Product 详情纵向链路：列表卡片根据服务端 ProductType 跳转单一详情页，严格解析正整数 ID 与 experience/kit 类型；Endpoint 分别调用两条无认证详情 API 并对 unknown JSON 执行白名单 Runtime Guard。详情 Hook 提供 Loading/Error/Content 与重试、迟到响应隔离；Experience 只允许选择服务端真实 Option 完整组合并同步价格/专属图片，Kit 展示价格、库存和 available 且明确下单仍需服务端校验。

### Verification

- 本地 Product seed 17 项隔离测试通过，覆盖环境/引擎/路径/双确认门槛、13 条两类型目录、重复执行、保留名称冲突、图片补偿、PNG chunk/CRC/像素解压、旧夹具精准修复、缺失文件恢复、旧默认 Option 配色迁移，以及一次性 SQLite + 临时图片目录中的真实 13 Product / 21 图片纵向创建；集成断言会从 Online 详情重读两个 Option 的完整组合、价格、图片关系和不同像素内容。
- 完整 Jest 11 套件 / 70 项通过，覆盖公开 Product Query/无认证头、坏契约拒绝、动态详情路由、Experience/Kit Runtime Guard、图片 URL、列表/详情四态、分页追加、完整 Option 选择及旧响应隔离。只有 Taro Test Utils 间接旧 `act` 的已知上游警告。
- `npm run typecheck`、ESLint `--max-warnings=0`、Stylelint 与 OpenAPI 类型漂移检查均以退出码 0 通过；后端完整套件为 1442 项通过、9 项显式隔离 MySQL 门槛跳过。
- weapp/alipay/tt/h5 四端生产构建均通过；为避免用户微信 watcher 竞态，weapp 在复用同一依赖的系统临时副本中隔离构建并核对详情产物。冷启动支付宝 25.11 分钟，预热后抖音 39.45 秒、微信 2.97 秒，H5 2.72 分钟。H5 入口保持 327 KiB、app JS 245 KiB，仍有 Webpack 244 KiB 性能建议和 `[hash]` 上游弃用警告。
- 未修改 FastAPI Web 运行链、数据库 Schema 或依赖；不需要迁移。2026-08-22 列表 Content、相对图片、第二页、类型筛选、keyword 防抖/组合搜索、Empty，以及详情/多配置 Option 切换微信 Functional 均已通过。本地开发库增量 Seed 先得到 `created=1 / skipped=12 / repaired_images=0`，再把多配置 Experience 第二张旧默认测试图精准迁移为备用配色，结果为 `created=0 / skipped=13 / repaired_images=1`；当前共有 13 条 Online Product 和 21 张图片，全部由 Windows `System.Drawing` 解码为 2×2 PNG。

### Next

Phase 6 自动化与微信 Functional 已收口。下一步进入 Phase 7 购物车、确认页和 Order 创建。

---

## Frontend Phase 5 — 账号密码登录纵向链路（2026-08-20）

### Summary

完成首条可运行的前端业务纵向链路：现有账号密码登录、Token 会话持久化、启动恢复、access token 刷新、`/users/me` 验证、页面守卫和登出。同步修复认证/用户成功响应在 OpenAPI 中为 `unknown`、以及 User `IntEnum` 数据库存储与 HTTP 字符串输出不一致的 Schema 描述；接口运行行为和数据库结构均未改变。

### Implemented

- 为 auth register/login/refresh/logout 和 users me/update/password 声明精确 `SuccessResponse[T]` / `ErrorResponse` OpenAPI 信封；User 输出 Schema 现在正确描述 `role=user|admin|super_admin` 与 `status=normal|disabled`，生成结果更新为 45 paths / 108 schemas。
- 新增薄 `AuthApi` Endpoint，登录请求直接使用生成类型，登录/刷新/用户响应在运行时逐字段校验并重新构造白名单对象；坏 JSON 或意外额外敏感字段不会因 TypeScript 类型断言而进入应用状态/Storage。
- 新增 Taro Storage Port/Adapter 与可注入 storage/clock/refresh 的 `SessionManager`；仅持久化 access token、refresh token、expiresAt 和公开 User，不保存密码。损坏缓存会删除，并发 refresh 共享一次 Promise。
- 新增 React `AuthProvider`/`useAuth`：启动时恢复缓存，临近过期先 refresh，再用 `/users/me` 验证当前身份；缓存身份在服务端验证前不会被视为已认证。Session 失效清理会话，网络初始化失败保留为可重试 error 状态。
- 新增受控登录表单、登录错误映射、提交中防重复、首页登录守卫、当前用户展示和登出。用户不存在与密码错误在 UI 统一为同一提示；密码提交失败后清空且永不写 Storage。
- 新增阶段学习笔记，解释生成类型/Runtime Guard、受控表单、Context、Effect、Port/Adapter、Token 生命周期、判别状态与测试边界。

### Verification

- 后端完整 SQLite 套件 1425 项通过、9 项可选 MySQL 门槛跳过；其中认证/用户相关 33 项通过，OpenAPI 测试固定成功响应引用、密码排除及输出字符串 Enum。
- 前端 `typecheck`、ESLint、Stylelint 和 OpenAPI 类型漂移检查通过；Jest 7 套件 / 29 项通过。Taro Test Utils 仍只有已记录的上游 `ReactDOMTestUtils.act` 弃用警告。
- weapp/alipay/tt/h5 四端生产构建通过；加入认证链后 H5 入口为 327 KiB，仍超过 244 KiB 建议线，比 281 KiB 空应用基线增加 46 KiB。
- 未新增 npm/Python 依赖、数据库迁移或配置密钥；尚未完成微信开发者工具/H5 对真实后端的人工 Functional，H5 仍受待实现的严格 CORS allowlist 阻挡。

### Next

先在微信开发者工具用隔离开发账号完成真实后端登录/刷新/重启恢复/登出 Functional；随后实现公开 Product 列表与详情纵向链路。微信登录仍是正式公开发布前门槛，不在本次账号密码 MVP 中伪实现。

---

## Frontend Phase 5 — 依赖复核与 API 基础层（2026-08-20）

### Summary

复核正式 `miniapp/` 的安装结果并完成下一步 OpenAPI 类型生成与 HTTP Client 基础层。依赖树已从 Spike `node_modules` 镜像残留状态收敛为 `package.json`/`package-lock.json` 可复现状态；当前尚未实现 auth Endpoint、Session Storage 或登录页面。

### Implemented

- 用官方 npm registry 确认 Taro 4.2.1 仍为最新版；清理 16 个 extraneous NutUI/React Spring 包，显式补齐 `solid-js@1.9.15` peer，并移除非目标平台插件、Taro Generator 与未启用的 Husky/Commitlint/Lint Staged，共减少 113 个未使用包。
- 新增 `scripts/export_openapi.py`，以 `TESTING=1` 从真实 FastAPI `app.openapi()` 原子导出稳定 JSON；导出结果包含 45 条路径和 99 个组件 Schema。
- 引入 `openapi-typescript@7.13.0`，使用 `--immutable --alphabetize` 生成 `miniapp/src/api/generated/schema.d.ts`，并通过 `api:types:check` 检查漂移。
- 实现可注入 Transport/AuthSession 的 HTTP Client、Taro Request Transport、统一响应信封 Runtime Guard，以及 Network/Timeout/HTTP/Business/Contract/Session/Cancel 错误模型。
- code `1006` 使用 single-flight refresh，多个并发请求共享一次刷新并各自最多重放一次；403 不刷新，普通超时和写请求不自动重试，empty-body PATCH 不添加 data/Content-Type。
- 环境 Origin 现在要求无路径、无凭据的 HTTP(S) Origin；生产环境必须 HTTPS，并拒绝 localhost、127.0.0.1、0.0.0.0 与 `[::1]`。

### Verification

- `npm ls --depth=0` 与 `npm ls --all --omit=dev` 通过，无 missing/extraneous dependency。
- `npm run typecheck`、`npm run lint`、`npm run lint:styles`、`npm run api:types:check` 全部通过。
- Jest 4 套件 / 19 用例通过，其中 14 项覆盖 API Client 与环境配置；Taro Test Utils 仍输出上游 `ReactDOMTestUtils.act` 弃用警告。
- weapp/alipay/tt/h5 四端生产构建通过；H5 空应用入口 281 KiB，超过 Webpack 244 KiB 建议线，作为后续依赖体积基线。
- 官方 registry `npm audit --omit=dev` 仍报告 10 项 Taro 4.2.1 H5 上游风险（4 moderate、1 high、5 critical）；`audit fix --force` 会破坏性降级 Taro 组件/插件，因此未执行，正式发布前必须重审。
- 未运行后端完整 pytest：后端运行时代码未修改；OpenAPI 导出脚本已通过 `py_compile` 和真实导出验证。未做真机或真实后端网络联调。

### Next

使用生成类型实现 auth Endpoint、Session/Token Storage、账号密码登录/刷新/登出纵向链路；H5 真实联调前仍需后端严格 CORS allowlist。

---

## Frontend Phase 5 — 正式 miniapp 工程创建（2026-08-15）

### Summary

创建正式跨端前端工程 `miniapp/`（Taro 4.2.1 + React 18.3.1 + TypeScript 5.9.3 strict + Webpack 5.91.0 + Jest 29.7.0），包含四端构建命令、环境变量文件、测试与 lint 工具链；工程代码目前尚未提交（待用户确认）。工程不是从 Spike 复制，Spike 仅作为依赖版本与测试 workaround 的依据。

### Verified

- `npm run typecheck`（`tsc --noEmit`，strict + skipLibCheck）、`npm test`（2 套件 / 5 用例）、`npm run lint`（`--max-warnings=0`）全部通过。
- weapp/alipay/tt/h5 四端生产构建全部通过（weapp 3.7s），产物固定输出 `dist/<TARO_ENV>`；`project.config.json` 的 `miniprogramRoot` 指向 `dist/weapp`。
- 生产包无 localhost/HTTP 泄漏；`TARO_APP_APP_ENV`/Origin 按 Spike 结论仅对字面量引用注入，当前页面尚未消费 API Origin，将在 HTTP Client 步骤生效。
- `package-lock.json` 已生成（559 KB），锁定 Taro 4.2.1 / React 18.3.1 / Jest 29.7.0 / `@tarojs/test-utils-react` 0.1.1 等版本。

### Fixed / Recorded

- npmmirror 安装多次卡死（进程无网络/磁盘/CPU 活动、包半提取），清华源不支持 scoped 包（`@babel/core` 404）；最终以 Spike 同版本完整 `node_modules` 镜像（robocopy /MIR，53,377 文件 / 397.67 MB）兜底，再以 `npm install --package-lock-only` 生成 lockfile。
- Jest 链路沿用 Spike 结论：`.npmrc` 保留 `legacy-peer-deps`、自定义 transformer 补私有方法插件、mock `@tarojs/router` 打破循环依赖。
- 正式工程尚未引入 NutUI（ADR-005 按需引入要求留待组件开发步骤）；Spike 遗留的 NutUI 相关包已在 2026-08-20 依赖复核中清理。

### Verification

- 已运行：`npm run typecheck`、`npm test`、`npm run lint`、`npm run build:weapp|alipay|tt|h5`，全部通过。
- 未运行：后端完整 pytest（本次未修改后端代码）；未做真机/开发者工具预览（需微信开发者工具导入 `dist/weapp`）。

---

## Frontend Phase 5 — Taro 四端最小技术 Spike（2026-08-15）

### Summary

完成前端阶段 2（Taro 四端最小技术 Spike），验证 Taro 4 + React 18 + TypeScript strict + Webpack 5 + NutUI + Jest 组合在 weapp/alipay/tt/h5 的技术风险，并把结论回写架构文档与 ADR。没有创建正式 `miniapp/`、没有提交前端工程代码、没有修改后端。

### Verified

- 四端生产构建全部通过（weapp/alipay/tt/h5，Webpack 5.91.0），产物固定 `dist/<TARO_ENV>`，微信项目根指向 `dist/weapp`。
- 环境变量注入：Taro 只替换字面量 `process.env.TARO_APP_*`/`TARO_ENV`；修正后四端生产包均含生产 Origin 且无 localhost。
- HTTP Client（`Taro.request`/`uploadFile` 适配层 + 统一错误模型）、Storage 封装与 NutUI Button/Toast/Dialog/Input 受控用法；13 项 Jest 测试通过，`tsc --noEmit`（strict + skipLibCheck）与 ESLint 通过。
- H5 CORS 风险：实测 FastAPI 无 CORS 头，确认缺口。

### Fixed / Recorded

- `@tarojs/test-utils-react@0.1.1` 与 Taro 4.2.1 peer 冲突（需 `--legacy-peer-deps`）、官方 transformer 缺私有方法插件、`@tarojs/router` 循环依赖与 `html()` 爆栈问题均已在 Spike 工程记录 workaround。
- NutUI 2.7.15 无按组件 JS 入口，桶导入 + 全量主题使 h5 入口 485 KiB；ADR-005 要求正式工程按需引入并纳入构建门槛。
- TypeScript strict 需 `skipLibCheck`（Taro 声明文件本身不干净）；模板 `config/index.ts` 未用解构已修正。

### Verification

- `npm run typecheck`、`npm test`（13 项）、`npm run lint` 通过；四端 `taro build` 退出码 0。
- 后端完整 pytest 未运行（本次未修改后端代码）；CORS 检查使用与测试夹具相同的 fakeredis + 临时 SQLite 隔离环境。

---

## v0.6.0 (Unreleased) — Inventory Module Final Review (Phase 4.3.12)

**Date:** 2026-08-14

### Summary

Completed the final architecture, security, transaction, concurrency, migration, API, test, and documentation review for Inventory v0.6. Phase 4.3 is code-complete and the local application candidate is now v0.6.0; this is not a Git tag, release, deployment, or persistent-database migration.

### Reviewed

- Confirmed API → Service → Repository → Model dependency direction, explicit transaction ownership, stable Product-ID lock ordering, post-lock validation, whole-use-case MySQL 1205/1213 retries, and no InventoryService call from OrderService.
- Confirmed administrator adjustment, Order deduction, and Pending cancellation keep balance, immutable ledger, Order/Audit writes, and response reloads on the owning transaction connection.
- Confirmed the idempotency UNIQUE, state-machine defense in depth, privacy-safe insufficient-stock payload, ADMIN+ ledger access, internal-key/log exclusions, strict request/query schemas, explicit response projections, and zero-SQL Mapper invariants.
- Reconciled Model, MySQL migration, named foreign keys/indexes, database design, DBML, OpenAPI, Product/Order integration contracts, and current implementation status.

### Fixed

- Added the frozen `stock <= 999999` upper bound to both public and administrator Product Kit detail Out Schemas. Added two regression cases so abnormal data cannot escape through Product responses even though ordinary Model writes already enforce the same bound.
- Replaced stale database-design, DBML, exception, and test descriptions that still called Kit OrderItem fields a future Phase 4.2 extension; they now describe the implemented pure Kit and mixed-order lifecycle.
- Corrected the AI context's stale Experience-only Order input summary and advanced the code default, `.env.example`, version contract, README, architecture example, project context, Inventory requirement, and API status to the v0.6.0 unreleased candidate.

### Verification

- Product/Order/Inventory plus version regressions pass 1358 tests without the optional MySQL directory.
- A new disposable MySQL Community Server 8.0.46 instance on `127.0.0.1:13306` applied the real Aerich 0 → 1 → 2 chain and passed all 9 Inventory MySQL concurrency, lock-wait, EXPLAIN, and HTTP gates.
- The complete suite passes 1431 tests with SQLite and MySQL gates in the same pytest process. `compileall`, `pip check`, secret/log pattern scans, and `git diff --check` pass. Ruff is not installed and was not claimed as executed.
- The temporary MySQL directory and schema were removed after a graceful shutdown. The existing 3306 `MySQL80` service remained running and was not connected or modified.

### Release and Database Boundary

- No new dependency or migration was added by the final Review. The reviewed Inventory migration remains required before any persistent environment can use the module.
- No push, tag, GitHub Release, deployment, development-database rebuild, Aerich fake, or persistent/shared/production migration was performed.

## Unreleased — Inventory MySQL Concurrency and HTTP Gate (Phase 4.3.11)

**Date:** 2026-08-14

### Summary

Completed the Inventory release gate with reproducible real-MySQL concurrency, driver-level lock-timeout retry, query-plan verification, a real MySQL FastAPI smoke, and the complete three-endpoint HTTP permission/error/boundary matrix. No Inventory business implementation, physical schema, migration, dependency, or application version changed.

### Verified

- Added a guarded MySQL test fixture that only permits explicit enablement, `127.0.0.1`, a non-3306 port, and the disposable `pinkdoohub_inventory_4311` schema prefix; it preserves Aerich versions and clears only business tables between tests. It also clears Tortoise 1.1.7's backend-agnostic global Executor SQL cache before and after MySQL tests, allowing SQLite and asyncmy suites to coexist without placeholder leakage.
- Ran the real Aerich 0 → 1 → 2 chain on an isolated MySQL Community Server 8.0.46 instance before testing, without `--fake` or `generate_schemas()`.
- Verified concurrent distinct adjustments accumulate without lost updates, while identical concurrent idempotency keys create one balance change, ledger, and Audit and return one committed result plus one replay.
- Verified exactly one of two last-item orders commits; reversed two-Kit request orders both complete through stable Product-ID locking; and concurrent cancellation of one Pending Order restores stock exactly once.
- Held an administrator adjustment row lock and observed the competing order in `performance_schema.data_lock_waits`; after release, the order read the committed balance. Induced a real MySQL 1205 with `innodb_lock_wait_timeout=1` and verified the Service succeeds in its second fresh transaction without duplicate writes.
- Seeded representative selective data and 5,000 valid ledger rows, refreshed statistics, and verified `EXPLAIN` selects ProductKit `product_id`, `idx_inventory_product_created_id`, and `idx_inventory_created_id` for the frozen lock/Product/global pagination queries.
- Added a real MySQL FastAPI concurrent replay/query smoke and 41 SQLite-backed HTTP matrix cases covering every Inventory route's authentication, authorization, resource errors, balance/idempotency conflicts, strict validation, filters, pagination, UTC bounds, Order source metadata, and privacy exclusions.

### Verification

- The isolated MySQL gate passes 9 tests; the new complete HTTP matrix passes 41 tests; all Inventory tests pass together with 241 tests. The complete project suite, with MySQL gates explicitly enabled in the same pytest process as SQLite regressions, passes 1429 tests. `compileall`, dependency integrity, documentation contracts, and diff whitespace checks also pass.
- The temporary server and schema are destroyed after verification; the existing `MySQL80` service and all persistent/shared/production databases remain untouched.

## Unreleased — Inventory Management API (Phase 4.3.10)

**Date:** 2026-08-14

### Summary

Exposed Inventory adjustment and ledger queries through three ADMIN+ FastAPI endpoints, with strict Header/Body/Query adaptation, exact success/error envelopes, explicit Mapper serialization, and first-create versus replay status handling. Completed the frozen v0.6 breaking switch by removing Product's direct stock overwrite route and Kit creation stock input.

### Implemented

- Added `get_inventory_service()` as the sole composition root for InventoryRepository, ProductRepository, and shared AuditLogService.
- Registered POST adjustment, Product-scoped ledger GET, and global ledger GET routes under `/api/v1/admin`, all protected by the existing JWT ADMIN+ dependency.
- Required and normalized `Idempotency-Key`; mapped first commits to HTTP 201 and exact committed replays to HTTP 200 without moving transport semantics into Service.
- Adapted all validated filters explicitly and serialized every successful result through Inventory Mapper, strict Out Schema, and the shared success envelope. OpenAPI declares precise generic success models and 400/401/403/404/409/422 error envelopes.
- Removed the legacy `PATCH .../stock` route, `KitStockUpdate`, `KitStockOut`, Product stock Mapper, and `ProductService.update_kit_stock()` so application business code has one stock-write path.
- Removed `stock` from `KitProductCreate`; ProductService now creates ProductKit with the Repository's fixed zero default, and any initial stock must be added through Inventory adjustment.

### Verification

- Added composition, layering, registration, OpenAPI, permission, strict validation, query adaptation, privacy, real SQLite adjustment/replay/query, zero-opening Kit, and legacy-request rejection tests.
- Product and Inventory regression suites pass together with 909 tests; the complete project suite passes 1379 tests. `compileall`, dependency integrity, documentation contracts, and diff whitespace checks also pass.

## Unreleased — Inventory Query Service and API Mapper (Phase 4.3.9)

**Date:** 2026-08-14

### Summary

Implemented the two Inventory ledger query use cases and the synchronous API mapping boundary. Product-scoped reads now validate the complete Kit resource identity, global reads preserve filter-only semantics, and ledger/adjustment responses are explicitly projected without SQL, ORM mutation, internal idempotency data, or user privacy fields. Inventory composition and HTTP routes remain Phase 4.3.10.

### Implemented

- Added `InventoryService.list_product_transactions()` with the stable Product missing/deleted/type/Kit-extension error priority before delegating all frozen filters and pagination to InventoryRepository.
- Added `InventoryService.list_transactions()` for global filtering; an unknown Product ID is not treated as a resource lookup and returns an ordinary empty `Page`.
- Kept both reads transaction-free and lock-free, with no duplicated ORM filtering or ordering in Service.
- Added synchronous Inventory transaction, list-item, page, and adjustment Mappers. Every output is built from an explicit field whitelist and validated by its strict Out Schema.
- Consumed only Repository-preloaded operator nicknames and batched Order numbers. Mapping performs zero SQL and zero ORM mutation, and excludes `idempotency_key`, technical `updated_at`, username, phone, password, Token, and order remark.
- Kept the adjustment Mapper independent from `InventoryAdjustmentResult`; the future Router supplies its domain values and retains ownership of first-create 201 versus replay 200.

### Verification

- Added 18 focused Service/Mapper tests covering exact filter forwarding, resource error priority, global empty results, all four ledger metadata shapes, pagination, adjustment consistency, field isolation, layer direction, real SQLite data, zero SQL, and zero ORM mutation.
- All 172 Inventory tests and the complete 1382-test project suite pass. `compileall` and diff whitespace checks also pass.

## Unreleased — Pending Order Inventory Restoration (Phase 4.3.8)

**Date:** 2026-08-14

### Summary

Extended the existing owner cancellation endpoint so Pending Kit and mixed orders restore every Kit balance exactly once. Restoration, immutable ledgers, Cancelled status, audit, and response reload now form one transaction; payment and completion remain inventory-neutral.

### Implemented

- Added server-owned restore identities and reason: `inventory:order:{order_id}:restore:product:{product_id}` and `Order cancellation stock restore`.
- Added a minimal immutable Order cancellation projection containing only Product ID, nullable Option ID, and quantity, loaded on the caller's transaction connection in stable Item order.
- Added one Inventory Repository batch lookup for restore identities; empty sets execute no SQL, and Repository remains free of transaction ownership and business exceptions.
- Split owner cancellation from the generic payment/completion transition helper. Cancellation now locks the owner-visible Order first, rechecks Pending, loads Items, aggregates Kit quantities, locks all Kit rows in ascending Product ID order, and checks every restore identity before writes.
- Restored balances with one bulk update and wrote all `order_cancellation_restore` rows with one bulk insert before committing Cancelled, `CANCEL_ORDER` audit, and response reload.
- Preserved catalog independence: restoration uses immutable OrderItem quantities and does not require the Product to remain Online or reuse its current price. Missing Kit rows and Pending/restore-identity contradictions fail as consistency conflicts instead of silently skipping stock.
- Enforced the `0..999999` balance range during restoration. Any inventory, ledger, status, audit, or reload failure rolls back the complete use case.
- Kept duplicate cancellation safe through two layers: the locked Order state rejects ordinary repeats, while the restore UNIQUE identity protects transaction replay and future automatic cancellation paths.
- Added whole-use-case retries only for MySQL 1205/1213, using a fresh transaction and at most three attempts; other database errors are not retried.

### Verification

- Added Repository, Service orchestration, real SQLite transaction, real HTTP, rollback, idempotency-conflict, balance-boundary, duplicate-cancel, and transient-retry tests. The complete project suite passes 1364 tests.

## Unreleased — Kit and Mixed Order Deduction (Phase 4.3.7)

**Date:** 2026-08-14

### Summary

Enabled pure Kit and Experience/Kit mixed creation through the existing Order endpoint. Pending Order creation now owns stable Kit locking, post-lock sellability and sufficiency checks, bulk balance/ledger persistence, and atomic Order/Items/Audit response creation. Pending cancellation restoration remains Phase 4.3.8.

### Implemented

- Made `experience_option_id` optional at the request/domain boundary: Experience requires a valid owned Option, while Kit requires omission/null. Order responses accept either a complete Experience Option snapshot or an all-null Kit Option snapshot.
- Added one batched ProductKit candidate-price loader to ProductRepository and one `bulk_update_stocks()` primitive to InventoryRepository; empty collections execute no SQL and multi-Kit writes do not loop over awaited saves.
- Injected InventoryRepository directly into OrderService and the API composition root without calling InventoryService. Pure Experience creation short-circuits before any InventoryRepository operation.
- Preserved the frozen transaction order: build authoritative candidate snapshots outside the transaction, create Pending Order first, acquire all ProductKit locks in ascending Product ID order, re-read Product state on the same connection, then bulk-write balances and `order_deduction` rows before Items, Audit, and detail reload.
- Generated one stable Order-source ledger identity per Kit: `inventory:order:{order_id}:deduct:product:{product_id}`, with the requesting user as operator and `Order stock deduction` as the server-owned reason.
- Returned the first insufficient Kit in request order through privacy-safe `40931` data containing only Product ID and requested quantity. Any unavailable/insufficient Kit or downstream failure rolls back the complete Order, stock, ledger, Item, and Audit write set.
- Kept order-number collision attribution ahead of all inventory locks/writes. Added whole-write-transaction retries only for MySQL 1205/1213, with a fresh transaction and at most three attempts; IntegrityError remains reserved for order-number attribution.
- Removed the obsolete `40922 KitOrderingRequiresInventory` constant, exception, exports, tests, and current API registration.
- Moved shared database error-code extraction into a stateless utility used by InventoryService and OrderService while preserving Python 3.10 compatibility through `timezone.utc`.

### Verification

- Added unit, architecture, real SQLite Service, and real HTTP tests for pure Kit and mixed orders, null Option snapshots, server prices, stable ledger metadata, multi-Kit rollback, audit rollback, order-number collision before deduction, insufficient-stock privacy, and transient retry limits.
- The complete project suite passes 1350 tests; `compileall`, dependency integrity, and diff whitespace checks also pass.

## Unreleased — Inventory Admin Adjustment Service (Phase 4.3.6)

**Date:** 2026-08-14

### Summary

Implemented the administrator stock-adjustment use case with row-locked balance arithmetic, immutable ledger and shared-audit atomicity, exact idempotent replay, and bounded MySQL transient-error retries. No Inventory Mapper, composition dependency, or HTTP route is registered yet.

### Implemented

- Added `InventoryService.adjust_stock()` with constructor-injected Inventory/Product repositories and shared AuditLogService; the Service owns only the administrator-adjustment transaction and does not call ProductService or access Models directly.
- Locked ProductKit before revalidating Product existence, deletion state, Kit type, extension presence, and the post-change `0..999999` balance boundary.
- Persisted balance, `admin_adjustment` ledger row, compact `ADJUST_INVENTORY` Product audit, and response detail reload on the same transaction connection so any failure rolls back the complete write set.
- Namespaced client keys as `inventory:admin:adjust:{key}` and bound an existing identity to the exact Product/change/normalized reason/operator tuple. Identical retries return the originally committed transaction and its original after-balance; mismatches raise `40933`.
- Resolved concurrent unique-key races only after the failed transaction exits: a matching committed row becomes a replay, an absent row preserves the original IntegrityError, and a different payload becomes a business conflict.
- Retried only MySQL 1205/1213 for the whole use case with a fresh transaction, at most three attempts. Logs include operator/product/error/attempt context but never the reason or idempotency key.
- Added frozen `InventoryAdjustmentResult.is_replay` so a future Router can select HTTP 201 for first creation and 200 for replay without introducing transport concepts into the Service.

### Verification

- Added real SQLite transaction tests for Draft/Online/Offline Kits, closed balance boundaries, rollback at every write/reload failure, missing/deleted/wrong-type resources, exact replay after later adjustments, conflict dimensions, maximum client-key capacity, ledger/audit privacy, and atomicity.
- Added isolated retry/error-chain tests for 1205, 1213, retry exhaustion, non-retryable errors, concurrent unique resolution, and preservation of unrelated database exceptions.
- Added architecture contracts for dependency direction, transaction ownership, frozen results, no direct ORM persistence, and sensitive logging exclusions.
- Inventory passes 150 tests, Order passes 375 regression tests, and the complete project suite passes 1331 tests.

## Unreleased — Fix OrderStatus MySQL Persistence

**Date:** 2026-08-14

### Fixed

- Fixed MySQL 1366 failures caused by passing `OrderStatus(IntEnum)` objects through Tortoise `SmallIntField` to asyncmy: the Model Pending default, Repository status updates, and Repository status filters now cross the persistence boundary as native integers.
- Kept the public Order enum/API contract and physical `orders.status SMALLINT DEFAULT 0` Schema unchanged; no database migration or dependency change is required.
- Added connection-parameter regression tests that reject `OrderStatus` objects and require exact `int` values for creation, updates, and filters.
- Re-ran the complete 0 → 1 → 2 migration chain on an isolated MySQL 8.0.46 instance and verified default creation (`0`), Pending filtering, update to Paid (`1`), and Paid filtering through the real `OrderRepository` and asyncmy driver.

## Unreleased — Real MySQL Migration and Repository Smoke

**Date:** 2026-08-14

### Verification

- Ran the complete Aerich 0 → 1 → 2 chain against an isolated MySQL Community Server 8.0.46 instance and verified InnoDB/utf8mb4 table metadata, columns, named indexes, the idempotency UNIQUE, foreign keys, and Aerich version rows.
- Downgraded only Inventory version 2 in the disposable schema, seeded stock=7 and stock=0 Kit fixtures, and re-upgraded: the positive Kit received exactly one `0 → 7` opening row, the zero Kit received none, and the mismatch query returned zero.
- Ran a real asyncmy/MySQL `InventoryRepository` smoke covering ordered multi-Kit locks, atomic balance/ledger commit, forced rollback, unique-key propagation, bulk rows, same-connection reads, detail hydration, and Order-source pagination.
- Did not apply migrations to any persistent/shared/production database and did not use `--fake`; the temporary instance and test Schema were destroyed after verification.
- Found a pre-existing release blocker outside InventoryRepository: plain `IntField` writes of `OrderStatus` were encoded as Enum strings by asyncmy, so `OrderRepository.create_order()` defaults and `update_status()` failed with MySQL 1366. The subsequent OrderStatus persistence fix above resolves this blocker and has its own real-MySQL regression.

## Unreleased — Inventory Repository (Phase 4.3.5)

**Date:** 2026-08-14

### Summary

Implemented the Inventory data-access primitives for stable row locking, balance persistence, immutable ledger writes, idempotency reads, detail hydration, and filtered pagination without adding business decisions or runtime endpoints.

### Implemented

- Added `InventoryRepository.get_kit_for_update()` and a deduplicated, single-query `get_kits_for_update()` using the caller connection, `ORDER BY product_id`, and `SELECT ... FOR UPDATE`.
- Added final-balance persistence that updates only `stock`/`updated_at` and leaves sufficiency/range decisions to the owning Service.
- Added an immutable `InventoryTransactionCreateData` DTO, single-row creation for admin adjustments, and one-statement bulk creation for multi-Kit automatic events; empty collections execute no SQL.
- Added lightweight same-connection idempotency lookup and same-connection detail reload for uncommitted adjustment responses.
- Added Product/type/source/UTC-range filters, `created_at DESC, id DESC` pagination, operator preloading, and one batched Order lookup for safe `source_order_no` hydration. Order-source pages remain a constant three SELECTs regardless of row count.
- Kept the Repository free of FastAPI, Schema, Service, Validator, business exceptions, Redis, transaction ownership, retry loops, Product status checks, inventory arithmetic, and error translation.

### Verification

- Added 24 Inventory Repository contracts covering architecture, static lock/bulk guarantees, empty-set SQL avoidance, deterministic lock order, balance/ledger rollback, bulk rollback, uniqueness propagation, uncommitted visibility, metadata hydration, every filter, stable pagination, time boundaries, empty pages, and constant query count.
- The complete project suite passes with 1297 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Offline MySQL Migration (Phase 4.3.4)

**Date:** 2026-08-14

### Summary

Generated and statically reviewed the MySQL 8+ Inventory incremental migration, including deterministic opening-balance ledger rows for existing positive Kit stock, without connecting to or changing any database.

### Implemented

- Generated `2_20260814104655_add_inventory_transactions.py` with `AERICH_MYSQL_VERSION=8.0` and Aerich offline mode, preserving the generated model state for future diffs.
- Reviewed the table DDL for exact fields, nullable generic source/operator columns, two `RESTRICT` foreign keys, the named idempotency UNIQUE, and four stable-pagination indexes.
- Removed `CREATE TABLE IF NOT EXISTS` so Schema drift cannot be silently treated as success, and declared `RUN_IN_TRANSACTION=False` because MySQL DDL implicitly commits.
- Added one ordered `INSERT ... SELECT` that writes `opening_balance` only for `product_kits.stock > 0`, with UTC microsecond timestamps, stable reason/idempotency identity, null source/operator, and no balance mutation.
- Kept zero stock as an implicit baseline and rejected silent recovery constructs such as `INSERT IGNORE` or `ON DUPLICATE KEY UPDATE`.
- Documented the required stock-range preflight, write-quiescence window, backup, temporary-MySQL rehearsal, post-migration one-to-one verification, partial-failure forward-recovery process, and destructive downgrade semantics.
- Kept all runtime boundaries unchanged: the migration is not applied, Kit ordering remains blocked, and Inventory Repository/Service/Mapper/routes remain unimplemented.

### Verification

- Added five static migration contracts covering scope, fields/FKs/indexes, positive-only backfill, destructive downgrade boundary, and compressed model state.
- The complete project suite passes with 1273 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Model and Database Design (Phase 4.3.3)

**Date:** 2026-08-14

### Summary

Implemented the Inventory ledger persistence shape and synchronized its authoritative database design without generating or executing a migration.

### Implemented

- Added and registered `InventoryTransaction` with Product and nullable operator `RESTRICT` foreign keys, stable string Enum fields, non-zero/range Model validators, required source/reason, nullable generic `source_id`, and a 256-character internal idempotency identity.
- Added the named unique idempotency index plus Product, source, transaction-type, and global stable-pagination indexes. The generic source ID deliberately has no polymorphic foreign key.
- Kept `product_kits.stock` as the authoritative balance and aligned its Model plus transitional Product request boundary to `0..999999`.
- Added a reusable non-zero integer Model validator and documented that cross-field arithmetic/type-source rules remain Service responsibilities rather than Model business behavior.
- Updated the database design and DBML with the ledger table, relations, index rationale, BaseModel `updated_at` boundary, and the current no-`CHECK` cross-dialect strategy.
- Kept runtime behavior unchanged: Kit ordering is still blocked, the old direct stock endpoint still exists, and no Inventory migration, Repository, Service, Mapper, route, or database operation was added.

### Verification

- Added Inventory Model metadata, field boundary, round-trip, nullable migration actor/source, idempotency uniqueness, FK deletion protection, reverse relation, and real SQLite DDL tests; expanded Product stock upper-bound regressions.
- The complete project suite passes with 1268 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Domain Language and Schema (Phase 4.3.2)

**Date:** 2026-08-14

### Summary

Implemented the frozen Inventory domain vocabulary and strict Pydantic boundaries without introducing persistence or runtime endpoints.

### Implemented

- Added stable string Enums for four transaction types and three source types, plus named constants for stock/change limits, reason and idempotency-key lengths, audit identity, and bounded transaction retry attempts.
- Added `InsufficientStock`, `InventoryBalanceExceeded`, and `InventoryTransactionConflict` as HTTP-semantic `ConflictException` subclasses and exported them through the common exception package.
- Added strict adjustment input, standalone idempotency-header type, Product/global transaction queries, and UTC/time/source cross-field validation.
- Added balance, transaction/list item, and adjustment response schemas with explicit field projection, internal-key/privacy isolation, UTC datetime enforcement, arithmetic consistency, transaction-direction/source metadata validation, and adjustment-result consistency.
- Kept Order and Product runtime boundaries unchanged: Kit ordering remains blocked, direct stock setting remains available, and no Inventory table, migration, Repository, Service, Mapper, route, or database operation was added.

### Verification

- Added Inventory domain, exception middleware, request/query, response privacy, and cross-field contract tests.
- The complete project suite passes with 1249 tests; `compileall` and `git diff --check` also pass.

## Unreleased — Inventory Contract Freeze (Phase 4.3.1)

**Date:** 2026-08-13

### Summary

Completed the Phase 4.3.1 current-state audit and froze the authoritative Inventory business/API contracts without implementing runtime Inventory code.

### Important Decisions

1. `product_kits.stock` remains the single authoritative sellable balance and will be paired with immutable same-transaction ledger entries.
2. Pending Kit/mixed order creation deducts immediately; Pending cancellation restores idempotently; payment and completion do not change stock.
3. Pure Experience, pure Kit, and mixed orders are supported by the target contract. Multi-Kit writes lock ProductKit rows in ascending Product ID order and remain atomic with Order/Items/Audit.
4. ADMIN+ adjustments use strict `change`, a trimmed 1–256 character reason, and mandatory `Idempotency-Key`; Online Kit adjustment is allowed. Balance is bounded to `0..999999`.
5. The v0.6.0 Inventory cutover will remove direct `PATCH .../stock` and non-zero stock from Kit creation instead of retaining a semantically ambiguous compatibility wrapper.
6. Ledger types are `opening_balance`, `admin_adjustment`, `order_deduction`, and `order_cancellation_restore`. Existing positive balances receive migration baseline entries; zero balances do not create zero-change entries.
7. User-facing insufficient-stock errors do not expose exact availability. Database unique identities, Order state validation, stable lock ordering, and bounded whole-transaction deadlock retries provide layered protection.
8. Real MySQL 8+ concurrency tests are a release gate for v0.6.0. This step does not change the application version, schema, migration, dependencies, development database, or current runtime endpoints.

### Documentation and Verification

- Added authoritative Inventory requirement and API contract documents.
- Synchronized Product, Order, API conventions, AI context, README, and project instructions while preserving clear implemented-versus-frozen boundaries.
- Added documentation contract tests for the frozen decisions and current runtime boundary.

## Unreleased — Test Suite Domain and Layer Layout

**Date:** 2026-08-13

### Summary

Reorganized the previously flat 98-file test suite by business domain and application layer without changing test names or behavior. The root now contains only global fixtures, shared data factories, and a navigation document; Product and Order tests can be run independently or narrowed to API, Schema, Model, Repository, Service, Mapper, Validator, or storage boundaries.

### Important Decisions

1. Tests are grouped by domain first because this matches production ownership and makes Phase-focused verification discoverable.
2. Product and Order are grouped by their principal tested layer instead of a rigid unit/integration split; many existing contracts deliberately combine boundary assertions with real SQLite behavior.
3. Global fixtures remain in `tests/conftest.py`, and reusable response factories remain in `tests/support/`, so no duplicate fixture trees or nested override rules were introduced.
4. Pytest configuration remains unchanged: recursive discovery under `tests/` collects the same suite, while paths such as `tests/order/` and `tests/product/services/` provide focused runs.

### Verification

- Pytest collection finds the unchanged total of 1178 tests after all moves.
- The repository-root lookup in the relocated version contract was updated to remain location-correct.

---

## v0.5.0 (Unreleased) — Order Module Final Review (Phase 4.2.12)

**Date:** 2026-08-13

### Summary

Completed the final architecture, security, transaction, query-performance, migration, test, and documentation review for Order v1.0. Phase 4.2 is code-complete and release-ready as the unreleased v0.5.0 candidate; Phase 4.3 Inventory is the next business stage.

### Reviewed and Changed

- Reviewed all nine HTTP operations against the frozen Order requirements/API contracts and verified API → Service → Repository → Model dependency direction, authenticated identity ownership, unified envelopes, and explicit user/admin response projection.
- Reviewed creation and state-change transaction boundaries, post-lock state validation, sequential audit writes, rollback injection, order-number collision attribution/retry, stable pagination ordering, batch Product/Option loading, database item counts, and preloaded detail relations.
- Reviewed `1_20260813130455_add_order_tables.py` as a MySQL 8+ additive migration: it creates only `orders` and `order_items`, preserves four historical `RESTRICT` foreign keys and five query indexes, declares the non-transactional DDL boundary, and contains no upgrade-side destructive SQL.
- Added a cross-module amount-capacity invariant proving the maximum legal request (`10 × 99 × 99999.00`) remains below `DECIMAL(10,2)` Order capacity. This documents why no additional total-overflow business error is necessary while the existing Product price and Order item bounds remain unchanged.
- Hardened shared audit IP extraction: only valid, length-safe IPv4/IPv6 literals are persisted; malformed, overlong, or IPv6 scope-bearing `X-Forwarded-For` values fall back to the direct peer, and an invalid/missing peer becomes `unknown`. A real Order HTTP test proves hostile proxy text cannot turn an otherwise valid audited mutation into a 500 or partial write.
- Advanced the unreleased application candidate from v0.4.0 to v0.5.0 in code defaults, example environment, version contracts, README, project instructions, architecture context, and Order requirement/API status. Advanced the database design document to v1.4 for the Order table addition.

### Important Decisions

1. **Release candidate, not a release:** v0.5.0 identifies the completed local code candidate. No Git tag, GitHub Release, commit, push, MySQL migration execution, Aerich fake, or development-database rebuild is implied.
2. **Aggregate constraints are reviewed together:** individual price, item-count, and quantity limits form a safe maximum total. A regression invariant now alerts future maintainers if any one bound changes enough to exceed storage capacity.
3. **Proxy input remains a trust boundary:** syntax and storage safety are enforced in the application, while deployment must still configure the ingress proxy to overwrite untrusted forwarding headers.
4. **Inventory remains out of scope:** Order continues to reject every Kit item before writes and never reads, deducts, or restores `ProductKit.stock`; those concurrency semantics belong to Phase 4.3.
5. **Migration execution is separately authorized:** the reviewed Order migration remains offline and unapplied. Production rollout still requires target-schema audit, backup/snapshot, staging verification, explicit authorization, and a tested rollback plan.

### Verification

- All 392 Order-related tests pass, including contracts, Models, migration DDL, Repository, Service, Mapper, routes, real JWT/SQLite HTTP flows, transaction rollback, and amount-capacity invariants.
- Six focused request-IP tests pass, plus the real Order audit integration regression.
- The complete project suite passes with 1178 tests.
- `compileall`, dependency integrity (`pip check`), and whitespace/error-marker review (`git diff --check`) pass.
- Ruff was not run because it is not installed in the project environment or declared in `requirements.txt`.

### Release Notes

- No dependency was added.
- The MySQL initial migration and Order incremental migration remain unapplied; the local development database was not rebuilt or mutated.
- `docs/02_database/er_diagram.png` remains an untracked user-owned artifact and was not modified.

---

## Unreleased — Order HTTP Error and Boundary Matrix (Phase 4.2.11)

**Date:** 2026-08-13

### Summary

Completed the full real-JWT/SQLite HTTP error and boundary matrix for all nine Order endpoints. The matrix now verifies authoritative Experience snapshots and Decimal totals, request-shape anti-forgery, Product/Option/Kit rejection, visibility and ADMIN+ permissions, pagination and combined filters, every illegal state precondition, ordered audit history, transactional failure rollback, and order-number collision retry behavior.

### Added

- Real HTTP creation coverage for multiple distinct Options, exact Decimal arithmetic, immutable historical snapshots, 1/99 quantity bounds, 500-character remarks, empty-remark normalization, duplicate/empty/oversized item collections, strict scalar types, and all server-owned field forgery attempts.
- Product and Option availability cases for missing, draft/offline/deleted, missing/deleted/mismatched Option, plus explicit Kit rejection with unchanged `ProductKit.stock` and no partial Order/audit writes.
- Full authentication and ADMIN+ route matrices, uniform missing-order/resource-hiding 404 behavior, user/admin list visibility, pagination, exact lookup, status/user/time combined filters, UTC/range validation, and reverse-chronological audit pagination.
- All nine illegal status-operation preconditions across cancel, mark-paid, and complete, with stable `40921` payloads and proof that neither status nor audit changes.
- HTTP-level fault injection after audit writes and at post-write reloads, proving atomic rollback of Order/Items/status/audit, plus collision retry success and third-collision exhaustion without partial artifacts.
- A shared transport dependency that rejects any non-empty request body on cancel/paid/complete while preserving body-free OpenAPI operations.

### Important Decisions

1. **Negative-space contracts are enforced:** omitting `requestBody` from OpenAPI is documentation, not runtime validation. The three fixed state-use-case PATCH routes now explicitly reject `{}`, `null`, or any other non-empty body with the unified HTTP 422 envelope before mutation.
2. **HTTP tests exercise real boundaries:** business-error and rollback cases use real JWT authentication, SQLite, repositories, services, mappers, and exception middleware. Dependency overrides are limited to deterministic generators and deliberate failure injection.
3. **Server authority is tested end to end:** authenticated identity, order status, Product/Option snapshots, unit prices, subtotals, and totals cannot be supplied by clients and remain frozen after source catalog changes.
4. **Failure responses disclose no internals:** injected runtime and database-integrity failures are logged server-side, return only the shared generic 500 envelope, and leave no partial aggregate or audit state.

### Verification

- 79 new focused HTTP matrix test instances pass across creation boundaries, query/permission/state behavior, and transaction/collision failure injection.
- Existing route architecture and mocked adaptation tests continue to pass with strict no-body enforcement and unchanged OpenAPI request-body declarations.
- 104 focused Order HTTP/route/architecture tests pass together; all 390 Order-related tests pass.
- The complete project suite passes with 1170 tests.

### Release Notes

- No dependency, database schema, migration, or application-version change was made in this step.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.12 final checklist, migration review, and version decision remain pending before declaring the Order module release-ready.

---

## Unreleased — Order FastAPI Routes (Phase 4.2.10)

**Date:** 2026-08-13

### Summary

Exposed the implemented Order domain through four authenticated user endpoints and five ADMIN+ endpoints. Added the Order composition root, strict request-to-domain adaptation, Mapper serialization, unified success/error envelopes, exact OpenAPI contracts, and core real JWT/SQLite HTTP lifecycle coverage. The exhaustive Phase 4.2.11 HTTP error/boundary matrix and Phase 4.2.12 final review remain pending.

### Added

- `get_order_service()` composition root wiring OrderRepository, ProductRepository, and the shared AuditLogService/AuditLogRepository.
- User routes for Experience creation, paginated own-order listing, owner-scoped detail, and Pending cancellation.
- ADMIN+ routes for filtered listing, unrestricted detail, manual payment confirmation, completion, and paginated Order audit history.
- Explicit OrderCreate-item to `OrderItemInput` adaptation so Service remains independent of transport Schemas.
- Authenticated identity as the sole source of `user_id`/`operator_id`, plus shared client-IP extraction for every audited HTTP mutation.
- Precise `SuccessResponse[T]` and shared `ErrorResponse` declarations, HTTP 201 creation, HTTP 200 queries/mutations, PATCH operations without request bodies, and one-time router registration tests.
- Real JWT/SQLite flows covering creation, Decimal snapshot response, user list, resource hiding, ADMIN+ access, paid/completed transitions, owner cancellation, ordered audits, source IPs, and audit privacy.
- Unified missing-Bearer handling through `AuthenticationException` by setting HTTPBearer `auto_error=False`; all routes using the existing authentication dependency now return the project error envelope for missing credentials.

### Important Decisions

1. **Composition root:** concrete repositories and shared infrastructure are assembled only in `app/api/deps.py`. Route modules import Service/Mapper/Schemas but never business repositories or Order/Product persistence models.
2. **Identity is server-owned:** create and owner-scoped routes use `current_user.id`; admin mutations use `current_admin.id`. Extra `user_id`, price, amount, or snapshot fields are rejected by strict request Schemas before Service execution.
3. **Authentication versus authorization:** missing credentials return HTTP 401 with the unified envelope, while an authenticated normal user accessing ADMIN+ routes returns HTTP 403. The pre-existing invalid/expired Token exception remains code `1006`/HTTP 400 pending a separate User-contract migration, so Order OpenAPI documents both 400 and 401.
4. **Single serialization pass:** routes call the dedicated Mapper and `model_dump(mode="json")`, then pass the validated data to `success()` with `response_model=None`; OpenAPI uses explicit generic response declarations without runtime Decimal revalidation.
5. **No body for state PATCH:** cancel, paid, and complete select fixed Service use cases entirely through the path and authenticated identity; clients cannot submit an arbitrary target state.

### Verification

- 25 focused Order route/architecture/integration test instances were added and pass after the unified-auth additions.
- 84 combined Order/User/Product route regressions pass after changing the shared HTTPBearer behavior.
- All 311 Order-related contracts pass together.
- Python compilation and dependency integrity checks pass; the complete suite passes with 1091 tests.

### Release Notes

- The nine documented Order endpoints are now registered and callable.
- No new dependency, database schema change, migration, or application-version change was made.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.11 must still expand the complete HTTP business-error/input-boundary matrix. Phase 4.2.12 must perform final checklist/migration/version review before declaring the Order module release-ready.

---

## Unreleased — Order API Mapper (Phase 4.2.9)

**Date:** 2026-08-13

### Summary

Implemented the synchronous Order API mapping boundary for user/admin lists, user/admin details, OrderItem snapshots, and lightweight status-transition responses. The Mapper performs explicit field projection and strict Out Schema validation without querying or mutating ORM aggregates. Dependency wiring and HTTP routes remain outside this slice.

### Added

- Authoritative OrderStatus and DayType `{value, label}` mapping using the existing common registries.
- Explicit OrderItem snapshot mapping with Decimal price/subtotal preservation and no live Product/Option reads.
- Separate user/admin list and detail projections; user responses never read User relations, while admin responses add only `user_id` and `user_nickname`.
- User/admin Page mapping that preserves total, page, page size, and pages while consuming Repository `item_count` annotations.
- Lightweight status-response mapping from a relation-free Order returned by the status transaction reload.
- Aggregate-integrity checks that reject an OrderItem attached to a different Order before serialization.
- Architecture, atomic conversion, projection, strict validation, real Repository zero-SQL, and non-mutation tests.

### Important Decisions

1. **Explicit projection:** each endpoint class has a dedicated mapper and Out Schema. Fields are assembled from a whitelist rather than passing ORM models directly to Pydantic, making user/admin isolation visible in code.
2. **Zero-SQL mapping:** lists consume the Repository's `item_count` annotation, details consume preloaded Items/User, and status responses consume a lightweight Order. Mapper functions contain no async code, Repository/Service imports, or ORM query calls.
3. **Snapshot-only items:** historical Item output uses the stored name, Option dimensions, day type, unit price, quantity, and subtotal. It never follows Product or ExperienceOption relationships that may have changed since purchase.
4. **Schema owns wire formatting:** Mapper preserves domain `Decimal` and Enum values; strict response Schemas validate arithmetic and serialize amounts as two-decimal strings. This avoids duplicating formatting rules in two layers.
5. **Non-mutating composition:** Mapper builds new dictionaries and Schema objects. Real aggregate snapshots prove the source Order, User, Items, relationship lists, and annotated fields are unchanged.

### Verification

- 23 focused Order Mapper tests pass.
- All 286 Order-related contracts pass together.
- The complete suite passes with 1066 tests after the Mapper and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until dependency composition and user/admin routes are implemented.

---

## Unreleased — Order Status Transition Service (Phase 4.2.8)

**Date:** 2026-08-13

### Summary

Implemented the three frozen Order state-transition use cases: owner cancellation, ADMIN+ manual payment confirmation, and ADMIN+ completion. Each use case locks the visible Order inside its transaction, validates the latest state, and atomically persists the status, audit, and lightweight response reload. Mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderService.cancel_order()` for owner-scoped `pending → cancelled` with SQL-level visibility hiding.
- `OrderService.mark_order_paid()` for the temporary ADMIN+ `pending → paid` operational entry point.
- `OrderService.complete_order()` for ADMIN+ `paid → completed`.
- Stable `cancel`, `mark_paid`, and `complete` operation constants for `OrderStatusConflict` payloads.
- A private transition template that performs transaction-bound row locking, post-lock state validation, status persistence, sequential audit, and response reload without exposing a generic public status mutator.
- Unit and real SQLite tests for all success paths, status conflicts, missing/hidden resources, audit summaries, repeated-transition serial results, and audit/reload rollback.
- A static Repository contract proving `get_order_for_update()` retains `select_for_update()` for MySQL pessimistic locking semantics.

### Important Decisions

1. **Lock then decide:** state validity is checked only after `SELECT ... FOR UPDATE` returns the latest visible row. A pre-transaction read cannot authorize a mutation because another transaction may change the state before the write.
2. **Visibility in the lock query:** owner cancellation applies `(order_id, user_id)` before locking. Missing and foreign Orders therefore produce the same `40411 OrderNotFound`, without loading and revealing another user's row.
3. **No generic transition API:** callers select one of three named use cases and cannot supply an arbitrary target status. The private template receives only constants fixed by those public methods.
4. **Atomic status event:** status update, compact `before_status`/`after_status` audit, and response reload share one connection. Audit or reload failure restores the original status and leaves no audit row.
5. **SQLite verification boundary:** real SQLite tests prove equivalent serial outcomes and rollback behavior; a static `select_for_update()` contract preserves the intended MySQL row-lock implementation because SQLite itself cannot demonstrate MySQL row-level locking.
6. State transitions do not read or restore ProductKit stock. Inventory effects remain Phase 4.3 work.

### Verification

- 18 new status-transition test instances were added; the focused status-Service and architecture command passes with 20 tests including existing architecture guards.
- All 262 Order-related contracts pass together.
- The complete suite passes with 1043 tests after the status-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented.

---

## Unreleased — Order Creation Service (Phase 4.2.7)

**Date:** 2026-08-13

### Summary

Implemented the Experience-only Order creation orchestration layer. The Service now validates Product/Option aggregates in batches, creates database-authoritative Decimal snapshots, and atomically persists the Order aggregate plus its non-sensitive audit record. Status transitions, mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderItemInput` as a Service-domain input containing only Product ID, ExperienceOption ID, and quantity; no client-controlled snapshot fields enter the use case.
- Batch Product/Option resolution with stable request-order errors, Kit-before-Option behavior, and unified unavailable semantics for missing, deleted, offline, or mismatched aggregates.
- Database-authoritative Product name, Option configuration, price, subtotal, and total snapshots using `Decimal` arithmetic.
- One transaction for Order creation, one-shot Item bulk insertion, sequential `CREATE_ORDER` audit, and complete aggregate reload on the same connection.
- `OrderRepository.order_number_exists()` for post-rollback collision attribution and whole-transaction retry with a fresh order number, capped at three attempts.
- Unit and real SQLite tests for validation priority, batch access, snapshot immutability, audit privacy, complete rollback, collision success, retry exhaustion, and non-collision `IntegrityError` preservation.

### Important Decisions

1. **Database source of truth:** clients cannot submit names, configuration, prices, subtotals, totals, status, user ID, or order number. Every persisted and returned snapshot is reconstructed from the current valid Product/Option rows.
2. **Stable error priority:** bulk loading reduces query count without changing observable validation order. Items are checked in request order; each Item checks the known Kit boundary before Product availability and Option validity/ownership.
3. **Atomic aggregate:** Order, Items, audit, and response reload use one transaction connection. Even an exception after the audit INSERT rolls back every write, and validation failures occur before a transaction or audit begins.
4. **Fresh-transaction retry:** an `IntegrityError` leaves a transaction unusable. Collision attribution therefore occurs only after leaving the transaction context; a confirmed order-number collision opens a new transaction, while unrelated integrity errors retain their original cause.
5. Phase 4.2 creation performs no ProductKit stock read or write. Kit remains an explicit `40922` boundary until the Inventory concurrency model is designed in Phase 4.3.

### Verification

- 16 focused creation-Service unit and real SQLite integration tests pass.
- All 245 Order-related contracts pass together.
- The complete suite passes with 1025 tests after the creation-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required by this slice.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented. State-transition Services also remain unimplemented.

---

## Unreleased — Order Query Service (Phase 4.2.6)

**Date:** 2026-08-13

### Summary

Implemented the read-only Order business orchestration layer: user/admin lists, user/admin details, and administrator Order audit-history queries. This slice adds visibility and error semantics without introducing creation, status transitions, response mapping, dependency wiring, or routes.

### Added

- `OrderService.list_user_orders()` / `get_user_order_detail()` with SQL-scoped user visibility and uniform `OrderNotFound` behavior for missing and foreign resources.
- `OrderService.list_admin_orders()` / `get_admin_order_detail()` forwarding the frozen paging, exact order-number, user, status, and UTC time-range contract.
- `OrderService.list_order_audit_logs()` with a lightweight Order existence check before delegation to the shared `AuditLogService` and `target_type="order"` pagination.
- `OrderRepository.get_order_by_id()` as a relation-free existence lookup with optional caller connection.
- A common `OrderStatusValue` API type plus complete `ORDER_STATUS_BY_VALUE` reverse registry for explicit API-string-to-database-Enum translation.
- Mock orchestration, architecture, real SQLite visibility, aggregation, relation-preloading, audit isolation, orphan-audit, and named-exception tests.

### Important Decisions

1. **Resource-enumeration protection:** user detail always queries by `(order_id, user_id)`. Both a missing ID and another user's ID produce Repository `None` and the same `40411 OrderNotFound`; Service never loads a foreign Order and exposes a different ownership error.
2. **Boundary translation:** Query Schema and Service accept stable API values (`pending`, `paid`, `cancelled`, `completed`), while Repository accepts `OrderStatus`. The explicit reverse registry is the only translation boundary, preventing HTTP strings from leaking into persistence code and IntEnum integers from leaking into the API.
3. **Existence before history:** an Order audit query first proves the Order row exists. A stale or orphan `audit_logs` row cannot make a nonexistent Order appear queryable.
4. Query Service performs no direct ORM operation, opens no transaction for pure reads, does not call ProductService, and delegates audit access only through the documented shared-service exception.

### Verification

- 59 focused Enum/Query Schema/Service/Repository tests pass after boundary translation.
- All 212 `test_order_*.py` contracts pass together.
- The complete suite passes with 1009 tests after the query-Service and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The Order API remains unavailable until Mapper and routes are implemented.
- Order creation transaction, order-number collision retry, state-transition/audit transactions, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Repository and Number Generator (Phase 4.2.5)

**Date:** 2026-08-13

### Summary

Implemented the Order data-access boundary and dependency-free order-number generator. This slice provides the transaction-aware primitives required by the later query, creation, and state-transition Services without introducing business exceptions, service orchestration, mapping, or HTTP routes.

### Added

- Standard-library `OD` + 26-character Crockford Base32 ULID generation using UTC Unix milliseconds and `secrets.token_bytes()`; no Redis, database sequence, third-party ULID package, or mutable generator state.
- `OrderRepository` creation, one-shot OrderItem `bulk_create()`, ID/number detail loading, optional SQL-level user visibility, transaction-bound `SELECT ... FOR UPDATE`, status persistence, and user/admin pagination.
- Database `COUNT(items)` list summaries, stable `created_at DESC, id DESC` pagination, exact admin order-number/user/status filters, inclusive `created_from`, exclusive `created_to`, and admin User preloading.
- Product/ExperienceOption set loaders in `ProductRepository`; each executes one query, includes logically deleted rows for Service-level availability decisions, and accepts the caller's transaction connection.
- Architecture, source-selection, real SQLite transaction, rollback, query-count, visibility, filtering, paging, snapshot, and order-number tests.

### Important Decisions

1. Repository methods do not raise Order business exceptions or decide ownership, availability, Kit policy, snapshot arithmetic, retry policy, or state transitions. User visibility is expressed as an optional SQL predicate so the query Service can hide missing and foreign resources uniformly.
2. List queries aggregate Item row count and do not preload Item collections. Detail queries preload stable Item order and the User relation in constant query count; the later Mapper must perform zero SQL.
3. `update_status()` persists only a status already approved by Service. Every state-transition Service must lock and recheck the row in the same transaction before calling it.
4. The generator provides approximate time ordering only. `created_at DESC, id DESC` remains authoritative; the database unique constraint and later Service transaction retry remain the collision boundary.

### Verification

- 28 focused generator, Repository, Product batch-loader, architecture, transaction, and performance tests pass, including uncommitted aggregate reload on the caller's transaction connection.
- All 195 `test_order_*.py` domain, Schema, Model, migration, generator, and Repository tests pass together; including the three Product batch-loader contracts, the combined slice has 198 passing tests.
- The complete suite passes with 992 tests after the Repository and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The existing Order MySQL migration remains offline and unapplied. No development database was rebuilt or modified outside disposable test schemas.
- Order query Service, creation transaction, status/audit Service, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Models and MySQL Migration (Phase 4.2.4)

**Date:** 2026-08-13

### Summary

Implemented the Order persistence contract: registered `Order` / `OrderItem` Tortoise Models, verified their real SQLite schema and behavior, and generated a reviewed MySQL 8+ incremental migration without connecting to or changing any database.

### Added

- `Order` with unique `OD` + ULID order number, User `RESTRICT` relation, exact Decimal total, `SmallIntField` status with ORM/database default `0`, nullable remark, and four named stable-pagination indexes.
- `OrderItem` with Order/Product/ExperienceOption `RESTRICT` relations, nullable future-Kit Option fields, immutable product/configuration/price snapshots, strict quantities and amounts, and the named `(order_id, id)` index.
- Real temporary-SQLite contracts for Model metadata, default values, Decimal/Enum round trips, reverse relations, field boundaries, unique order numbers, physical-delete protection, exact index columns, nullable extension fields, and DDL foreign keys.
- Offline MySQL migration `1_20260813130455_add_order_tables.py` plus static contracts for its exact table scope, field types, defaults, four foreign keys, five indexes, non-transactional MySQL DDL semantics, safe child-before-parent downgrade order, and Aerich model state.

### Important Decisions

1. Order status uses the project's actual Tortoise/MySQL integer-enum mapping, `SmallIntField` / `SMALLINT`, rather than the stale `TINYINT` wording in the frozen draft. Database design and DBML were corrected together.
2. Cross-field Option completeness, duplicate Item combinations, Product availability, snapshot arithmetic, Kit rejection, and state transitions remain Schema/Service responsibilities; Models contain no business workflow or database queries.
3. Nullable Option fields remain in the physical table for Phase 4.3 Kit compatibility, while Phase 4.2 Service must reject every Kit Item.
4. Aerich's generated MySQL migration was reviewed to remove `IF NOT EXISTS`, declare `RUN_IN_TRANSACTION = False`, and drop `order_items` before `orders` on an explicitly authorized downgrade.

### Verification

- 22 focused Order Model tests pass.
- 29 combined Order Model, Order migration, and initial MySQL migration tests pass.
- The complete suite passes with 964 tests after the persistence and documentation updates.

### Release Notes

- The incremental migration was generated with `AERICH_MYSQL_VERSION=8.0` and `aerich --app models migrate --offline`; no `upgrade`, `downgrade`, `--fake`, development-database rebuild, or live database connection was performed.
- Applying the migration later requires a separately authorized target, schema audit, backup, and execution plan. Its downgrade deletes all Order data and must never be treated as routine rollback.
- No dependency, endpoint, or application-version change is required. Order Repository, Service, Mapper, routes, and order-number generator remain unimplemented.

---

## Unreleased — Order Schema Contracts (Phase 4.2.3)

**Date:** 2026-08-13

### Summary

Implemented strict Order creation, list-query, and user/admin response Schema contracts without introducing database Models, business Services, Mappers, or routes.

### Added

- `OrderItemCreate` and `OrderCreate` with strict IDs/quantity, 1–10 Items, duplicate Product/Option rejection, remark normalization, unknown-field rejection, and server-owned field isolation.
- `OrderListQuery` and `AdminOrderListQuery` with API-string status values, exact order-number filtering, safe query-ID parsing, UTC-aware date ranges, and strict range ordering.
- `OrderItemOut`, user/admin list and detail outputs, and lightweight status output with explicit field whitelists.
- Decimal-only response amounts serialized as fixed two-place strings, Product-price upper bounds, status/day-type value-label consistency, Item subtotal validation, and Order total validation.
- User/admin isolation contracts: user responses omit all user data; admin responses add only `user_id` and `user_nickname`; detail responses do not repeat the list-derived `item_count`.

### Important Decisions

1. Query status accepts only API values (`pending`, `paid`, `cancelled`, `completed`) and never database IntEnum integers.
2. Query datetimes and response datetimes must be explicitly UTC; naive and non-UTC-offset values are rejected.
3. Out Schema accepts internal monetary values only as `Decimal`; strings and floats are rejected before fixed two-place serialization.
4. The response layer validates snapshot arithmetic but does not query or mutate any ORM object.

### Verification

- 116 focused Order Schema tests pass; all 144 Order domain and Schema tests pass together.
- The complete suite passes with 938 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## Unreleased — Order Domain Contracts (Phase 4.2.2)

**Date:** 2026-08-13

### Summary

Implemented the first Order code slice after the v1.0 contract freeze: database status Enum, fixed business boundaries, API display registries, audit constants, and HTTP-semantic named exceptions. No database, Schema, Service, or route behavior is introduced by this slice.

### Added

- `OrderStatus(IntEnum)` with stable database values 0–3.
- Explicit OrderStatus API value and Chinese label registries, preventing IntEnum database integers from leaking into API status output.
- Frozen constants for Item count, quantity, remark length, ULID order-number shape and retry limit, Phase 4.3 Kit boundary, and four audit actions.
- `OrderNotFound`, `OrderStatusConflict`, `KitOrderingRequiresInventory`, `OrderProductUnavailable`, and `OrderOptionUnavailable`, exported through the common exception package.
- Enum/constant and exception contracts covering inheritance, payloads, invalid construction, JSON behavior, and global HTTP 404/409/422 mappings.

### Important Decisions

1. OrderStatus remains an `IntEnum` for the database; API values are obtained only through an explicit registry.
2. Named exceptions validate their structured payload at construction so invalid IDs or status types cannot produce unstable public error data.
3. Request-shape errors remain the responsibility of the next Schema stage and are not duplicated as business exceptions.

### Verification

- 27 focused Order domain contract tests pass.
- The complete suite passes with 821 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Schema, Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## v0.4.0 — Product Module Implementation (Unreleased)

**Date:** 2026-08-13

### Summary

Completed the Product module implementation and its final architecture, OpenAPI, documentation, and release-readiness review. The Product API contract is now v1.0 Implemented. This section is the v0.4.0 release-candidate summary; the following Unreleased Phase 4.1 sections retain the detailed implementation history.

### Changed

- Added precise generic OpenAPI success and error envelopes for all 22 Product operations while preserving the Mapper as the single runtime serialization boundary.
- Verified that all 19 admin Product operations require Bearer authentication, all 3 public Product operations remain anonymous, and every application operation ID is unique.
- Removed the obsolete Phase 3 demo `GET /api/v1/admin/users` registration; the formal admin-users router remains the only owner of that path.
- Synchronized Product business rules, API conventions, architecture, AI context, and project instructions with the implemented Phase 4.1 state.

### Important Decisions

1. Product routes declare precise OpenAPI models through `responses` with `response_model=None`; this avoids revalidating Mapper-produced decimal strings while retaining strict one-pass Out Schema validation.
2. The Product API document advances from Draft v0.9 to Implemented v1.0. This is a contract-document version, not an application release or Git tag.
3. The code/default configuration advances from v0.3.0 to the unreleased v0.4.0 candidate because this release adds the complete Product feature set rather than a backward-compatible bug fix. No Git tag or release is created by this change.

### Verification

- 51 focused Product API route, OpenAPI, and real SQLite HTTP tests pass.
- The complete suite passes with 794 tests, including two application-version consistency contracts.
- Python compilation, dependency integrity, OpenAPI warning/operation/security checks, whitespace, debug-output, and unfinished-marker checks pass.

### Release Notes

- No new database migration is introduced by this review. The existing MySQL 8+ initial migration remains unapplied and still requires an explicitly authorized deployment procedure.
- No cleanup command was run against the development database or upload directory.

---

## Unreleased — Product Image Delayed Cleanup (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented a retryable operational batch that removes local files only after ProductImage logical deletion is durably committed, without coupling irreversible file I/O to the DELETE request transaction.

### Added

- Repository ID-cursor scan for deleted images at or before an explicit cutoff.
- `ProductImageCleanupService` with managed-URL validation, active-reference protection, idempotent deletion, per-item failure isolation, and batch statistics.
- `python -m app.tasks.product_image_cleanup --before <timezone-aware ISO 8601>` operational command with bounded batches and failure exit status.
- Real SQLite and temporary-filesystem tests for cutoff selection, cursor pagination, managed/external URLs, active URL references, missing objects, failures, and unsafe parameters.

### Important Decisions

1. Cleanup does not run inside ProductService, FastAPI BackgroundTasks, application startup, or the logical-delete transaction.
2. Existing `is_deleted`, `updated_at`, and `image_url` fields are the durable retry source; ProductImage and AuditLog records remain intact, so no cleanup-status table or migration is needed.
3. The cutoff is mandatory and timezone-aware. Retention policy remains an explicit deployment choice rather than an application magic number; the command defaults to preview and requires `--apply` for deletion.
4. A failed object remains discoverable on the next run. A missing object is treated as idempotent success, while unmanaged/external URLs are never passed to local storage deletion.

### Verification

- 39 focused storage, Repository, cleanup Service, task orchestration, architecture, real SQLite, filesystem, batch-query, and preview-safety tests pass.

### Operational Note

- The command is implemented but was not executed against the workspace development database or upload directory. Production scheduling remains a deployment responsibility.
- No database migration, dependency, API endpoint, or application version change is required.

---

## Unreleased — Product Audit History API (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the shared AuditLog read path and exposed Product operation history as an ADMIN+ paginated endpoint without embedding audit data in Product detail or duplicating its Schema in the Product module.

### Added

- Shared `AuditLogRepository.list_logs()` and `AuditLogService.list_logs()` target-scoped pagination.
- Shared `AuditLogOut`, strict pagination query Schema, and Audit API Mapper field whitelist.
- `GET /api/v1/admin/products/{product_id}/audit-logs`, including logically deleted Product records.
- Repository, Service, Mapper, permission, validation, route-contract, and real SQLite HTTP tests.

### Important Decisions

1. ProductService checks Product existence with `include_deleted=true`, then delegates the actual query to the shared AuditLogService.
2. Logs are ordered by `created_at DESC, id DESC` so pagination remains deterministic when timestamps collide.
3. The public audit shape omits `updated_at`; audit entries are immutable event records for this read contract.
4. Audit logs remain an independent paginated resource and are not loaded into Product list or detail queries.

### Verification

- 54 focused Audit/Product route, Service, Mapper, architecture, permission, validation, and real SQLite tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- No database migration, dependency, or application version change is required.

---

## Unreleased — Product Multipart Image Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected Product and ExperienceOption image uploads to ADMIN+ multipart FastAPI routes, the completed local storage adapter, ProductService, API mappers, and development static-file serving.

### Added

- HTTP 201 `POST /api/v1/admin/products/{product_id}/images` and `POST /api/v1/admin/options/{option_id}/images`.
- Strict multipart Pydantic forms: public images accept only file/is_cover/sort; Option images accept only file/sort and reject `is_cover`.
- API upload orchestration that runs synchronous storage off the event loop, closes spooled upload files, and compensates a stored file when ProductService fails without masking the original exception.
- Deferred-directory local static serving for generated `/uploads/products/{uuid}.{ext}` URLs.
- Real SQLite multipart tests covering file persistence, Product/Option ownership, audit ordering, safe filenames, response mapping, and static retrieval.

### Important Decisions

1. ProductService remains unaware of UploadFile and storage. The API boundary passes only the generated image URL.
2. Multipart validation errors use the existing unified request-validation envelope; invalid content/MIME/size uses named `42221 InvalidImageFile`.
3. Compensation failures are logged with the opaque storage key and do not replace the original Service exception.
4. Local static serving is a development adapter. A non-path external base URL is not mounted and can be supplied by a future object-storage deployment adapter.

### Verification

- 57 focused multipart route, real SQLite, storage, security, and architecture tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- Product audit-history listing was completed by the later stage above.
- No database migration or application version change is required. Runtime dependency `python-multipart==0.0.32` was added.

---

## Unreleased — Product Image Storage Adapter (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the Product image validation and local-storage boundary without coupling ProductService to FastAPI or file I/O. Multipart routes remain a separate next step.

### Added

- `LocalImageStorage` with a 2 MiB bounded read, jpg/png/webp signature detection, declared-MIME consistency checks, server-generated UUID keys, non-overwriting atomic publication, URL generation, and idempotent compensation deletion.
- Named `42221 InvalidImageFile` with a stable `data.reason` contract.
- Environment-configurable local upload directory/base URL, plus repository ignore rules for runtime uploads.
- Unit, security, architecture, and global exception-mapping tests.

### Important Decisions

1. Client filenames never enter the storage key or filesystem path; only adapter-generated lowercase UUID keys and allowlisted extensions are accepted.
2. Validation happens before the destination directory or final object is created. Temporary files are cleaned on any publication failure, and an existing target is never overwritten.
3. The adapter returns both a public URL for ProductService and an opaque key for route-level compensation. It does not import FastAPI, Models, Repositories, or Services.
4. Multipart parsing, calling ProductService, compensating a stored file when Service fails, static-file serving, and delayed cleanup after logical deletion remain in the next API integration step.

### Verification

- 23 focused storage, security, architecture, exception-contract, and HTTP exception-mapping tests pass.

### Known Limitations

- Resolved by the later Product Multipart Image Routes stage above: both image-create endpoints are now registered and callable.
- No database schema, migration, dependency, or application version change is required.

---

## Unreleased — Product JSON FastAPI Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected the completed Product Service and API Mapper layers to 19 callable FastAPI endpoints for public/admin queries and ordinary JSON mutations. Multipart image creation and audit-history listing were separate follow-up stages at that point and are now complete above.

### Added

- Public Product list plus Experience/Kit detail routes.
- ADMIN+ Product list/detail, create/update/delete, online/offline, Option lifecycle, Kit price/stock, and ProductImage metadata/delete routes.
- `get_product_service()` API composition dependency for ProductRepository + shared AuditLogService + ProductService.
- Global `RequestValidationError` conversion to the project response envelope without echoing original input values.
- Route contract, architecture, permission, validation, status-code, response isolation, and real SQLite HTTP lifecycle tests.

### Important Decisions

1. Routes depend on ProductService, never Product Model/Repository; they only validate transport input, invoke Service, map the result, and call `success()`.
2. Product creates return HTTP 201. ExperienceOption creates return 201 for a new record and 200 when restoring its historical ID.
3. Query parameter models use FastAPI `Query()` so `extra="forbid"` rejects unknown query parameters at the HTTP boundary.
4. PATCH routes pass `model_dump(exclude_unset=True)` to preserve missing versus explicit null semantics.
5. ProductImage JSON PATCH/DELETE were included in this stage because they required no file content; the later Product Multipart Image Routes stage above registered both image POST routes.
6. Request validation errors expose only location, message, and type. Raw request values are not included in the response or warning log.

### Verification

- 31 focused Product API route, architecture, and real SQLite integration tests pass.
- All 629 Product tests pass.
- Real HTTP flows cover Experience/Kit creation, queries, state transitions, mutations, response IDs, availability, and persisted ordered audits.

### Known Limitations

- Product/Option multipart creation, validation/storage, Service-failure compensation, delayed cleanup, and Product audit-history listing were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product API Mapper (Phase 4.1)

**Date:** 2026-08-13

### Summary

Completed the Product API response adaptation boundary. Product Service ORM/Page results can now be converted synchronously and without SQL into strict user/admin Out Schemas. FastAPI routes and image file storage remain separate pending work.

### Added

- `app/api/mappers/product.py` mappings for user/admin pages, Experience/Kit details, Product/Option/Image/Kit mutation responses, image ownership, dimensions, availability, covers, prices, and value labels.
- Authoritative Product type/status/day-type label registries and open duration/participant label rules in Product constants.
- Architecture tests prohibiting async/await, ORM query/mutation calls, and Service/Repository/FastAPI/Redis dependencies.
- Unit and real SQLite tests for response whitelists, user/admin isolation, aggregate completeness, ID semantics, stable dimensions, zero SQL, and zero ORM mutation.

### Important Decisions

1. Mapper functions construct explicit whitelisted dictionaries and immediately validate them with the corresponding Product Out Schema; prices remain `Decimal` until Schema serialization fixes them to two decimal places.
2. User mappers fail fast for non-Online/deleted/incomplete aggregates instead of fabricating empty covers, zero prices, or missing Kit extensions. Admin mappers permit documented Draft emptiness.
3. Mapper consumes Repository-established relation ordering and never reloads or expands the data scope. Unprefetched relationships remain programming errors.
4. Kit price/stock mutation response IDs use `ProductKit.product_id`, never the ProductKit table primary key.
5. Existing Service return values and Repository preloads already satisfy response mapping, so no Service/Repository compatibility changes were needed.

### Verification

- 32 focused Mapper unit and architecture tests pass.
- 3 real SQLite Mapper integration tests pass with SQL execution disabled after Repository loading.
- All 597 Product tests pass.

### Known Limitations

- Ordinary Product JSON FastAPI routes, ADMIN+ dependencies, and `success()` integration are complete. Multipart parsing, image validation/storage, and external-file compensation remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductImage Lifecycle Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed ProductImage database lifecycle orchestration: public and Option image creation, atomic cover switching, partial metadata updates, and logical deletion. Multipart validation, external storage, and API routing remain separate pending integration work.

### Added

- `ProductImageNotFound` (`40403`) and `OptionImageCannotBeCover` (`40021`) with stable HTTP mappings.
- Product and Option image creation Services with fixed ownership, Option non-cover enforcement, cover clearing, and Product-targeted audits.
- Image sort/cover update and logical-delete Services with hidden deleted parents, ordered one/two-audit flows, and compact snapshots.
- Repository Product-row lock and cover lookup on the caller transaction, with mock/real SQLite tests for cover invariants and rollback.

### Important Decisions

1. Service accepts a storage-generated image URL; FastAPI UploadFile, 2MB/type/content checks, external storage, and `42221` remain API/infrastructure responsibilities.
2. If storage succeeds before a database Service failure, the future caller must delete the object or enqueue delayed cleanup because the database transaction cannot roll back external storage.
3. Cover creation/switching locks the Product row so concurrent cover requests for one aggregate are serialized before bulk cover clearing.
4. Deleted Image/Product/Option ownership is hidden behind `40403`; an Option image cover attempt uses the registered `40021` contract.
5. Delete audit omits the potentially 2048-character URL to fit the existing 256-character AuditLog description. The logical-deleted ProductImage remains the authoritative URL record addressable by image ID.

### Verification

- 71 focused Image Service, Repository, exception, and architecture tests pass.
- All 559 Product tests pass.
- Full regression: 666 tests pass.
- Real SQLite tests prove one effective public cover and rollback of cover creation, second cover audit, and deletion failures.

### Known Limitations

- Multipart routes, image validation, storage adapter, compensation/delayed cleanup, and response mapping were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductKit Mutation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Kit price changes and direct final-stock settings, completing the ProductKit mutation Service boundary. The HTTP endpoints remain unavailable until API integration.

### Added

- `ProductService.update_kit_price()` and `update_kit_stock()` with shared ordered Product/Kit aggregate checks.
- Named `ProductKitNotFound` using the existing `40404` API allocation when a valid Kit Product lacks its required extension record.
- Compact `UPDATE_PRICE` and `UPDATE_STOCK` before/after snapshots in the existing AuditLog description field.
- Mock and real SQLite tests for error precedence, Draft/Offline writes, zero stock, field preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. Checks run in the stable order missing Product, deleted Product, type mismatch, Online state, and missing ProductKit extension.
2. Price and stock remain separate use cases and each changes exactly one ProductKit field.
3. Phase 4.1 stock mutation sets the final value; stock movements, reasons, automatic deduction/restoration, and concurrency control remain Phase 4.3 Inventory work.
4. ProductKit mutation and its Product-targeted audit share one transaction. Service returns ProductKit; the future API Mapper uses `product_id` as the response ID.

### Verification

- 51 focused Kit mutation, exception, and architecture tests pass.
- All 530 Product tests pass.
- Full regression: 637 tests pass.
- Real SQLite tests prove field preservation and audit-failure rollback for both mutations.

### Known Limitations

- Kit price/stock API routes and response mappings remain pending.
- Product image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the ExperienceOption lifecycle Service by implementing status-safe logical deletion with atomic snapshot auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductService.delete_experience_option()` with ordered missing/deleted/Product-state checks and Draft/Offline logical deletion.
- Compact `DELETE_OPTION` snapshots containing Option identity, dimensions, day type, and two-decimal price in the existing AuditLog description field.
- Mock and real SQLite tests for conflict precedence, deleting the final active Option, Product status preservation, image record/foreign-key preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. A deleted parent Product hides its Option behind `40402`; an already-deleted Option retains `40912` precedence over Product Online status.
2. Deletion changes only `ExperienceOption.is_deleted`. Product status and ProductImage records are not modified, and no physical delete occurs.
3. Draft/Offline may reach zero active Options. The delete workflow does not count siblings or invoke ProductValidator; a later online request owns aggregate completeness enforcement.
4. Option mutation and `DELETE_OPTION` audit share one transaction and target the Product for unified product-history lookup.

### Verification

- 39 focused Option delete, exception, and architecture tests pass.
- All 506 Product tests pass.
- Full regression: 613 tests pass.
- Real SQLite tests prove final-Option deletion, unchanged Product/image state, and audit-failure rollback.

### Known Limitations

- The ExperienceOption delete API route and response mapping remain pending.
- Kit mutation and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Update Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented partial ExperienceOption mutation with merged all-history uniqueness checks and atomic configuration/price auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ExperienceOptionNotFound` (`40402`) and `ExperienceOptionAlreadyDeleted` (`40912`) with fixed HTTP contracts.
- `ProductService.update_experience_option()` with non-empty field allowlisting, API-to-Model duration mapping, Product state protection, merged final-combination validation, and race-time unique conflict translation.
- Separate `UPDATE_OPTION` dimension snapshots and `UPDATE_PRICE` price snapshots; one PATCH can atomically write both actions in deterministic order.
- Mock and real SQLite tests for omitted-field preservation, current-ID exclusion, active/deleted history collisions, deleted Product hiding, Online protection, image preservation, Validator isolation, and rollback on first/second audit or response reload failure.

### Important Decisions

1. Service receives `model_dump(exclude_unset=True)` output rather than a Pydantic Schema and rejects empty or internal-field mappings before any lookup.
2. Uniqueness is evaluated against the merged final dimensions. The current Option row is allowed; any other historical row is a `40911`, including deleted rows.
3. Configuration and price use their authoritative separate audit actions. Both audit rows target the Product so the existing product-history endpoint can return them.
4. Update, all audits, and response aggregate reload use the same transaction connection. Option images are neither modified nor included by the future `ExperienceOptionBaseOut` response.

### Verification

- 58 focused Option update, exception, Repository, and architecture tests pass.
- 512 Product/Option/audit tests and the complete 600-test suite pass.
- Real SQLite tests prove field persistence, image preservation, deterministic dual audits, and complete rollback when either audit or response reload fails.

### Known Limitations

- The ExperienceOption update API route and response mapping remain pending.
- Option delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Create and Restore Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic ExperienceOption creation and historical-record restoration while preserving the all-history combination identity contract. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductTypeMismatch` (`40001`) and `ExperienceOptionAlreadyExists` (`40911`) with frozen response data.
- `ProductService.create_experience_option()` with Product preconditions, all-history combination lookup, INSERT/restore branching, and shared transaction audit persistence.
- `ExperienceOptionCreationResult(option, restored)` so the API can select HTTP 201 for creation and HTTP 200 for restoration without introducing transport concerns into Service.
- Repository Option detail loading with parent Product and sorted active images, including caller-owned transaction support.
- Mock and real SQLite tests for Draft/Offline creation, Product conflicts, active duplicates, concurrent unique-index translation, original ID/image preservation, price snapshot auditing, Validator isolation, and audit-failure rollback.

### Important Decisions

1. A deleted matching combination is restored in place with its original Option ID and image foreign keys; only current price and `is_deleted` change.
2. The Service lookup gives an early `40911`, while the database all-history unique index remains the concurrency authority. A race-time `IntegrityError` is translated to the same business conflict.
3. Creation/restoration, audit, and response aggregate reload use one transaction connection. `CREATE_OPTION` and `RESTORE_OPTION` target the Product so the existing product-history endpoint can return them.
4. AuditLog has no metadata column; restoration stores compact JSON with Option ID and before/after price strings in the existing `description` field. No migration is introduced.

### Verification

- 47 focused Option create/restore, exception, Repository, and architecture tests pass.
- 484 Product/Option/audit tests and the complete 572-test suite pass.
- Real SQLite tests prove new-record persistence, restoration identity/image preservation, and rollback of both paths when audit fails.

### Known Limitations

- The ExperienceOption create/restore API route and response mapping remain pending.
- Option update/delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Update and Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented Product basic-information PATCH orchestration and Product logical deletion with stable conflicts and atomic audit persistence. The HTTP endpoints remain unavailable until API integration.

### Added

- `OnlineProductCannotBeModified` (`40905`) and `ProductMustBeOfflineBeforeDelete` (`40904`) with fixed messages and HTTP 409 mapping.
- `ProductService.update_product()` with non-empty `name` / `description` field allowlisting, PATCH missing/null preservation, ordered preconditions, and atomic `UPDATE_PRODUCT` audit persistence.
- `ProductService.delete_product()` with Draft/Offline support, status-preserving logical deletion, and atomic `DELETE_PRODUCT` audit persistence.
- Mock and real SQLite tests for missing/deleted/Online conflicts, deletion precedence, forbidden internal fields, Validator isolation, child-record preservation, shared transaction connections, failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. API passes `ProductUpdate.model_dump(exclude_unset=True)` as a normalized field mapping; Service remains independent of Pydantic while preserving omitted fields versus explicit `description=None`.
2. Service allowlists only `name` and `description`, so type, status, and deletion state remain owned by their dedicated use cases.
3. Logical deletion changes only `Product.is_deleted`; status and Product child records remain untouched for traceability.
4. Neither workflow loads the aggregate or invokes ProductValidator because no online-readiness transition occurs.

### Verification

- 39 focused update/delete, exception, and architecture tests pass.
- 447 Product/audit transaction tests and the complete 549-test suite pass.
- Real SQLite tests prove successful field/deletion persistence and audit-failure rollback.

### Known Limitations

- Product update/delete API routes and response mapping remain pending.
- Option, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Creation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Experience and Kit Draft creation workflows with mandatory Product audit logging. Product HTTP creation endpoints remain unavailable until API integration.

### Added

- `create_experience_product()` with fixed Experience type and atomic Product plus `CREATE_PRODUCT` audit persistence.
- `create_kit_product()` with fixed Kit type and atomic Product, ProductKit, and audit persistence.
- Mock orchestration tests and real SQLite tests for shared transaction connections, fixed types/defaults, zero-stock Kit creation, failure short-circuiting, and full rollback on audit failure.

### Important Decisions

1. Service accepts normalized domain fields rather than Pydantic request objects and returns the created Product Model.
2. ProductType is selected by the Service method; Draft and non-deleted defaults remain Model-owned and cannot be overridden by callers.
3. Draft creation does not invoke ProductValidator and permits incomplete descriptions, images, and Experience Options.

### Verification

- 44 focused Product creation/query/status/architecture tests pass.
- The complete suite passes with 524 tests.

### Known Limitations

- Product creation API routes and response mapping remain pending.
- Product update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Query Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the Product query orchestration boundary for admin and public consumers while deliberately leaving presentation mapping to the future API layer.

### Added

- Admin Product list orchestration with pagination, type/status/keyword filters, and explicit logical-deletion scope.
- Public Product list orchestration that forces Online and non-deleted visibility and searches both name and description.
- Admin typed-detail lookup that includes deleted aggregates while hiding type mismatches as `40401`.
- Public typed-detail lookup that hides missing, deleted, non-Online, and type-mismatched resources behind the same `40401` contract.
- Mock contract tests and real SQLite tests for visibility, description search, type isolation, pagination delegation, and relation preloading.

### Important Decisions

1. Query Service returns `Product` or `Page[Product]`; it does not depend on API response Schemas.
2. `cover_image`, `display_price`, dimensions, availability, and value labels belong to an API Mapper built from preloaded aggregates.
3. Query operations do not open transactions, write audit logs, or invoke ProductValidator.

### Verification

- 35 focused Product query/status/architecture tests pass.
- The complete suite passes with 515 tests.

### Known Limitations

- Product API routes and presentation mapping are still unavailable.
- Product creation, update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Offline Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the Product status-transition Service pair by implementing atomic Online-to-Offline orchestration. The Product HTTP endpoint remains unavailable until the API layer is implemented.

### Added

- `ProductAlreadyOffline` (`40902`) as the stable conflict for both Draft and Offline Products receiving an offline request.
- `ProductService.offline_product(product_id, *, operator_id, ip_address) -> Product` using a lightweight Product lookup, ordered precondition checks, and atomic status plus `OFFLINE_PRODUCT` audit persistence.
- Tests for missing/deleted/non-Online Products, deletion precedence, absence of Validator calls, exact load/update/audit order, shared transaction connections, update failure, successful real persistence, and audit-failure rollback.

### Important Decisions

1. Draft and Offline share `40902` because both are already non-selling states; no additional Draft-specific code is introduced.
2. Offline uses `get_product_by_id(..., include_deleted=True)` because it needs no aggregate relations and never calls the online-readiness Validator.
3. Resource and status conflicts occur before the transaction; the status update and audit remain atomic within one caller-owned transaction.

### Verification

- 34 focused Product status-transition, exception, and architecture tests pass.
- The complete suite passes with 503 tests.
- Real SQLite tests prove successful persistence and audit-failure rollback to Online.

### Known Limitations

- No Product API routes are registered yet.
- Remaining Product query, creation, update/delete, Option, Kit, and image Service operations remain pending.

---

## Unreleased — Product Online Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the first Product Service slice: precondition checks, Validator orchestration, and atomic online-status plus audit persistence. Product API routes remain unavailable; this milestone exposes no new HTTP endpoint.

### Added

- General `ConflictException` and HTTP 409 middleware mapping without error-code-range inference.
- Named `ProductNotFound`, `ProductIsDeleted`, and `ProductAlreadyOnline` exceptions with frozen 404/409 contracts.
- Caller-owned transaction support in `AuditLogRepository.create()` and `AuditLogService.log()` through optional `using_db` propagation.
- `ProductService.online_product(product_id, *, operator_id, ip_address) -> Product` with complete aggregate loading, ordered resource/state checks, synchronous Validator invocation, atomic status update, and `ONLINE_PRODUCT` audit.
- Service tests for exact orchestration order, Draft and Offline transitions, Experience and Kit aggregates, failure short-circuiting, shared transaction connections, update failure, audit failure rollback, and architecture boundaries.

### Important Decisions

1. Product named exceptions directly inherit the matching HTTP-semantic base; the former 422-only `ProductException` pseudo-base was removed.
2. Service returns the updated ORM Product. API remains responsible for ADMIN+ authorization and `ProductOnlineOut` serialization.
3. Validation and resource/state conflicts occur before the write transaction. Status persistence and audit persistence share one transaction connection and roll back together.
4. This slice does not add row locking, conditional status updates, or cross-request idempotency; concurrent online requests remain a documented future concurrency concern.

### Verification

- 72 Product online/exception/Validator/audit/architecture tests pass.
- The complete suite passes with 493 tests.
- Real SQLite tests prove both successful Experience/Kit persistence and audit-failure status rollback.

### Known Limitations

- No Product API route is registered yet, so the documented online endpoint remains unavailable.
- Remaining Product Service operations—query, create/update/delete, offline, Options, Kit edits, and images—remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Validator (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented and reviewed the Product pre-online aggregate-integrity Validator as a synchronous, pure business component. It reports all readiness issues in stable order through the frozen HTTP 422 / `42201` contract. Product Service and API routes remain unavailable and are intentionally outside this milestone.

### Added

- `UnprocessableEntityException` as the general HTTP 422 business-exception type while preserving HTTP 400 for ordinary `BusinessException` instances.
- `ProductException` and `ProductNotReadyForOnline`, fixing code `42201`, message `Product is not ready to go online`, and non-empty `data.issues` structure.
- `ProductValidator.validate_before_online(product) -> None` as a synchronous entry point that reads a Service-preloaded Product aggregate and either returns `None` or raises the named exception.
- Common online-readiness rules for non-blank Product name and description plus an active public cover.
- Experience rules for at least one public image, at least one active Option, positive Option prices, and at least one active image per Option.
- Kit rules for a required ProductKit extension, price in `(0, 99999]`, and non-negative stock, including support for online products with zero stock.
- Contract tests for exception mapping, every common and type-specific boundary, multi-issue aggregation, stable issue ordering, fail-closed ProductType dispatch, real Repository-loaded aggregates, zero validation-time SQL, no aggregate mutation, and unprefetched-relation programming errors.

### Important Decisions

1. **Validator is a separate component serving Service.** Service owns lookup, resource/state conflicts, transactions, persistence, and audit; Validator owns only aggregate-integrity decisions.
2. **Purity is expressed by a synchronous API.** Validator performs no database, Repository, Service, Redis, transaction, permission, audit, or state-mutation work.
3. **Input must be a complete aggregate.** Service must call `ProductRepository.get_product_detail(product_id, include_deleted=True)` before validation. Missing prefetches remain visible programming errors instead of becoming `42201`.
4. **All issues are returned together.** Stable English strings and ordering are part of the API contract; the Product business rules document is their authoritative list.
5. **Type dispatch fails closed.** Unknown Product types raise an internal programming error rather than passing only common checks or being mislabeled as incomplete business data.
6. **Option identity is not revalidated online.** The Option write flow and the all-history database unique index own configuration conflicts and their `40911` response.

### Verification

- Validator stage tests pass: 6 exception-contract, 11 common-rule, 10 Experience, 11 Kit, and 5 purity/integration tests.
- Product-related tests pass with 366 tests; the complete suite passes with 464 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, debug-output, and unfinished-marker checks pass.

### Known Limitations

- Product Service, API routes, permissions, state-transition persistence, transactions, and Product audit-log writes remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- Image file upload and MIME/size validation remain pending; `42221` is reserved for that later boundary.
- The committed MySQL initial migration remains unapplied. This Validator milestone changes no schema and requires no migration.

---

## Unreleased — Product Repository (Phase 4.1)

**Date:** 2026-08-11

### Summary

Implemented and reviewed the Product aggregate Repository as the data-access boundary for the upcoming Validator and Service slices. Product endpoints remain unavailable until Validator, Service, and API integration are complete.

### Added

- `ProductRepository` with Product create/update, logical-delete-aware lookup, filtered pagination, and aggregate detail loading.
- ExperienceOption lookup by ID and all-history configuration identity, plus transaction-aware create/update operations that support restoration orchestration without creating a second version row.
- ProductKit and ProductImage lookup/create/update operations, including one-statement public-cover clearing scoped by Product, logical deletion, and optional current-image exclusion.
- Use-case-specific relation loading: list summaries preload Kit, active Options, and active public images; details additionally preload active Option images; Option/Image ID lookups preload the parent records required by Service rules.
- Repository contract tests for normal paths, deletion scope, stable ordering, pagination metadata, transaction rollback, parent relations, and constant-query-count protection against N+1 behavior.

### Changed

- `Page[T]` now permits ORM Model item types so Repository code can return `Page[Product]` while API code continues using response-Schema pages.
- Consolidated the identical partial-update persistence mechanism behind a private bounded generic helper while retaining entity-specific public methods and return types.
- Rebuilt the active SQLite development database from current Tortoise Models after creating a recoverable backup. No MySQL migration was applied to SQLite and no Aerich version was faked.

### Important Decisions

1. **Repository returns Models, not API DTOs.** Service owns derived fields such as `cover_image` and `display_price`; API owns Out-Schema serialization.
2. **Transactions are Service-owned.** Repository writes accept an optional database client and join the caller's transaction without deciding transaction boundaries.
3. **Loading follows the use case.** Lists do not fetch Option images, details do, and child-resource lookups join only the parent records needed by Service checks.
4. **Logical deletion is explicit per query.** Ordinary lookups hide deleted rows, while the all-history Option identity query intentionally includes deleted records so Service can restore the stable Option ID.
5. **Cover switching is batch persistence, not a Repository business rule.** Repository provides one scoped UPDATE; Service must decide whether a cover change is valid and execute the full switch atomically.
6. **Reuse stays local until generalized behavior is proven.** Common update mechanics are private to the Product Repository module rather than imposed through a premature global BaseRepository.

### Verification

- 38 Product Repository tests pass, including bounded query-count and transaction rollback contracts.
- The complete test suite passes with 421 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, and debug-output checks pass.

### Known Limitations

- Product Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- The committed MySQL initial migration remains unapplied; deployment still requires explicit authorization, a reviewed target, and a backup/rollback plan.

---

## Unreleased — Product Schema and Model Foundation (Phase 4.1)

**Date:** 2026-08-10

### Summary

Implemented the complete Product request/query/response Schema layer plus the Product aggregate-root, ExperienceOption, ProductKit, and ProductImage Models as the first executable slices of Phase 4.1. This milestone freezes API data shapes and all four Product tables; it does **not** make Product endpoints available yet.

### Added

- `ProductType`, `ProductStatus`, and `DayType` as Python 3.10-compatible string Enums.
- Product validation constants for names, descriptions, prices, open positive experience dimensions, stock, image order, and search keywords.
- Strict JSON request Schemas for Product create/update, Experience Option CRUD input, image PATCH, Kit price/stock updates, and user/admin list queries.
- Response Schemas for user/admin lists, Experience/Kit details, create/update/status/delete actions, Options, images, dimensions, and Kit price/stock results.
- `LabeledValue[T]` for stable `{value, label}` response DTOs and `Page[T]` reuse for Product lists.
- Product Schema contract tests covering normal paths, invalid values, PATCH missing-vs-null semantics, field isolation, pagination nesting, and ORM/internal field filtering.
- Product aggregate-root Tortoise Model with string Enum fields, ORM validators, application and database defaults, a stable named status/deletion index, and real SQLite DDL tests.
- ExperienceOption Tortoise Model with a RESTRICT Product FK, open positive dimensions, DayType string Enum, strict Decimal price validation, logical deletion default, and a stable named all-history unique index.
- Reusable `UniqueIndex` and `StrictDecimalField` infrastructure for cross-database named uniqueness and pre-quantization Decimal precision validation.
- ExperienceOption Model contract tests covering ORM round trips, reverse relations, invalid boundaries, unknown Enums, logical-delete uniqueness, cross-Product scope, FK deletion protection, and real SQLite DDL.
- ProductKit Tortoise Model with a RESTRICT one-to-one Product relation, strict Decimal price, dual-layer stock default, non-negative stock validation, and parent-owned logical deletion.
- ProductKit Model contract tests covering reverse one-to-one access, price/stock boundaries, per-Product uniqueness, multiple independent Kit products, FK deletion protection, and real SQLite DDL.
- ProductImage Tortoise Model with Product RESTRICT and nullable ExperienceOption SET NULL relations, validated URL/sort fields, dual-layer defaults, logical deletion, and three stable named query indexes.
- ProductImage Model contract tests covering public/Option image relations, URL/sort boundaries, logical-delete preservation, Option physical-delete fallback, Product deletion protection, and real SQLite DDL.
- `asyncmy==0.2.11` as the required Tortoise ORM runtime driver for the production MySQL path.
- Integrated Product Model contract tests covering unified ORM registration, the complete forward/reverse relation graph, migration reconstruction of custom fields/indexes, exact SQLite named-index inventory, and offline MySQL DDL generation.
- Enterprise database migration runbook covering Aerich command boundaries, MySQL-authoritative SQL generation, review gates, existing-database baselines, backup/rollback requirements, and CHECK-constraint prerequisites.

### Changed

- Split Product Schemas by trust boundary: `app/schemas/product.py` owns requests/queries; `app/schemas/product_response.py` owns response allowlists.
- Product monetary requests accept plain decimal strings and convert to `Decimal`; responses require `Decimal` internally and serialize fixed two-place strings.
- Retired Product-specific `42211`–`42215`; static field and request-shape failures use global HTTP 422 validation. `42201` remains for database-dependent online readiness and `42221` for image file validation.
- Admin list/detail contracts now always return `is_deleted`; user responses never expose it.
- Experience duration and participants remain open positive integers rather than fixed Enums.
- Normalized the pending Product Model contract across business rules, API, database design, DBML, and coding standards: online Option writes require prior offline status, Kit stock is a Phase 4.1 final-value field, and Product string Enums use the Python 3.10-compatible `str, Enum` form.
- Replaced deprecated `BigIntField(pk=True)` with `BigIntField(primary_key=True)` in `BaseModel` and all documentation examples.
- Corrected the stale Kit pricing sentence in the business rules: price lives in `product_kits.price`, and online Product writes require prior offline status, matching the database and API contracts.
- Pinned pytest-asyncio's fixture loop scope to `function`, preserving per-test database isolation and preventing a future default change from silently altering test behavior.
- Replaced the hand-built MySQL URL with structured Tortoise credentials so reserved characters in database passwords cannot be misparsed as URL syntax, and added configuration contract tests.
- Corrected the Product relation-loading example to use the implemented `kit`, `experience_options`, and `images` reverse relation names; synchronized the documented/example application version with the v0.3.0 baseline.
- Added the missing database-level unique constraint for `users.phone`, matching the existing registration/update conflict contract and closing the concurrent-write gap left by Service pre-checks alone.
- Restored the documented User admin-list and AuditLog tracing indexes in their Models so the initial migration matches established query plans instead of silently omitting them.

### Important Decisions

1. **Strict write boundary.** Unknown JSON fields are rejected; body integers reject booleans, floats, and numeric strings.
2. **PATCH preserves intent.** Empty PATCH bodies are rejected, missing fields mean “unchanged,” and explicit null follows field-specific rules. Services must use `model_dump(exclude_unset=True)`.
3. **User/Admin output separation.** Online user responses require complete sellable shapes, while admin Draft responses allow empty images, Options, and dimensions.
4. **Response allowlists.** Out Schemas ignore undeclared internal attributes so relation IDs, deletion flags, type-specific fields, and sensitive data cannot leak across endpoints.
5. **Option identity is stable.** The named unique index excludes `is_deleted`, so `(product_id, duration, participants, day_type)` remains unique across all rows. Reposting a logically deleted combination must restore the same Option ID and update its current price instead of creating or physically deleting historical rows.
6. **Defaults exist at both boundaries.** Product `status` and `is_deleted` declare both ORM `default` and database `db_default`, so ORM and direct SQL inserts share the same defaults.
7. **Money is validated before ORM quantization.** Product price fields use `StrictDecimalField` because native Tortoise Decimal conversion can round extra fractional digits before ordinary validators run.
8. **Kit extension is one-to-one.** `ProductKit.product` uses `OneToOneField`, so the database allows at most one Kit row per Product and ORM reverse access is a single `product.kit` object rather than a collection.
9. **Kit lifecycle belongs to Product.** ProductKit has no independent `is_deleted`; Product logical deletion controls visibility while the RESTRICT FK prevents accidental physical deletion of the parent.
10. **Phase 4.1 stock is a final value.** `product_kits.stock` is stored and validated now, but inventory ledgers, automatic deduction/restoration, and concurrency control remain Phase 4.3 concerns.
11. **Image ownership has two levels.** A null `experience_option_id` represents a Product public image; a non-null value represents an Option image while retaining the mandatory Product FK for direct Product queries.
12. **Option physical deletion is a fallback path.** ProductImage uses SET NULL for its nullable Option FK so an abnormal physical Option deletion preserves the image; normal business operations still logically delete Options.
13. **Cover consistency belongs to Service.** The three image indexes are non-unique query indexes. Service must enforce same-Product Option ownership, prevent Option covers, and switch the single Product cover inside a transaction.
14. **Both database paths are executable contracts.** SQLite integration tests exercise real tables, while offline MySQL schema generation verifies production DDL without requiring or mutating a live MySQL instance.
15. **Schema generation is environment-gated.** Application startup may auto-create tables only in local development. Tests own disposable schemas, while production must use reviewed migrations and cannot mutate schema as a startup side effect.
16. **Integrity has explicit enforcement layers.** Structural constraints live in the database, value ranges are currently enforced by Schema/Model validation, and cross-row/cross-table invariants belong to Service/Validator. Database CHECK constraints remain a migration-review decision rather than an implicit claim.
17. **Production migrations are MySQL-authoritative.** Aerich stores dialect-specific raw SQL, so MySQL generates and reviews deployable migrations; SQLite remains a development/test compatibility target and does not supply SQL for MySQL releases.
18. **The initial migration fails on schema drift.** Reviewed MySQL DDL omits `IF NOT EXISTS`, runs outside a claimed transaction, and has an intentionally non-destructive empty downgrade instead of dropping every user and business table.

### Database

All four Product Models now declare `products`, `experience_options`, `product_kits`, and `product_images`, including RESTRICT/SET NULL relations, Option uniqueness, Kit one-to-one uniqueness, dual defaults, and stable query indexes. Real SQLite DDL and offline MySQL DDL generation both pass their contracts. A MySQL 8+ initial migration has been generated and statically reviewed offline; it has not been applied to any database.

### Known Limitations

- Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until those layers are implemented and endpoint integration tests pass.
- FastAPI `RequestValidationError` still needs global envelope verification/handling during API integration; direct Schema tests do not prove the HTTP 422 response body contract.
- Shared audit-log listing (`AuditLogService.list_logs` / `AuditLogOut`) is not part of Product Schema and remains pending.
- The MySQL initial migration is committed but unapplied. Production startup does not auto-create tables; deployment still requires a separately authorized migration execution against a reviewed target and backup plan.
- Positive/range rules are not yet duplicated as physical database `CHECK` constraints; direct SQL can bypass Schema/Model validators and must remain a controlled operational path.

---

## v0.3.0 — RBAC + Audit Logging + Product Module Design

**Date:** 2026-07-30

### Summary

Added role-based access control (RBAC) with permission cascading, admin user
management with paginated listing and disable, sequential audit logging for
all sensitive operations, and completed Product module design (Phase 4.1).

### Added

- **RBAC Depends chain:** `get_current_user` → `get_current_admin` → `get_current_super_admin`
- **Admin API (`/api/v1/admin/`):** paginated user list (filterable by status/role),
  disable user endpoint (with role hierarchy protection)
- **Audit logging:** `AuditLog` model tracking operator_id, action, target_type,
  target_id, description, ip_address. Sequential (non-fire-and-forget) writes for
  register, login, disable_user. Failed operations produce no audit log.
- **Client IP detection:** `get_client_ip()` with X-Forwarded-For support for
  proxy environments.
- **Page[T] generic** for consistent paginated responses (items, total, page,
  page_size, pages)
- **Product Business Rules (`docs/01_requirements/product_business_rules.md`):**
  complete domain model (Product 1→N ExperienceOption), aggregate rules,
  lifecycle, constraints, and design decisions for Phase 4.1.
- **ER diagram redesign:** `product_experiences` → `experience_options` (1:N),
  price separation, `sort` field, `is_deleted`, `audit_logs` table,
  `ON DELETE RESTRICT` FK constraints.

### Changed

- PATCH semantics for `/users/me` (partial update) instead of PUT
- Phone field now required on `UserCreate` and User model

### Database

**New table:** `audit_logs`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| operator_id | BIGINT FK | Who performed the action |
| action | VARCHAR(50) | REGISTER, LOGIN, DISABLE_USER |
| target_type | VARCHAR(50) | user |
| target_id | BIGINT | Affected entity |
| description | VARCHAR(256) | nullable |
| ip_address | VARCHAR(45) | IPv4/IPv6 |
| created_at | DATETIME | auto |

### Important Decisions

1. **Sequential audit logging.** Audit writes are awaited inline, not
   fire-and-forget. If the audit log fails, the operation fails — no silent
   audit gaps.

2. **Guard before log.** Audit logs are only written after the business
   operation succeeds. Failed disables produce no audit entry.

3. **Depends chain for RBAC.** Each permission level wraps the previous one,
   reusing `get_current_user` → `get_current_admin` → `get_current_super_admin`.
   No repeated token parsing, clean extensibility.

### Known Limitations

- No refresh token rotation (Phase 4)
- No rate limiting on login/register
- Product module: design complete, implementation pending (Phase 4.1)
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred
- Avatar upload deferred

---

## v0.2.0 — User Authentication System

**Date:** 2026-07-25

### Summary

Implemented the complete user authentication system, covering the full
layered architecture from Model to API. Users can now register, login
with JWT, view their profile, and change their password.

### Added

**API Endpoints**

| Method | URI | Auth | Description |
|--------|-----|------|-------------|
| POST | `/api/v1/auth/register` | No | User registration |
| POST | `/api/v1/auth/login` | No | Login, returns access + refresh tokens |
| POST | `/api/v1/auth/refresh` | No | Exchange refresh for new access token |
| POST | `/api/v1/auth/logout` | Bearer | Revoke refresh token |
| GET | `/api/v1/users/me` | Bearer | Get current user |
| PATCH | `/api/v1/users/me` | Bearer | Update profile |
| PUT | `/api/v1/users/me/password` | Bearer | Change password |
| GET | `/api/v1/admin/users` | Bearer (ADMIN+) | List users (paginated, filtered) |
| PUT | `/api/v1/admin/users/{id}/disable` | Bearer (ADMIN+) | Disable user |
| GET | `/api/v1/admin/config` | Bearer (SUPER_ADMIN) | System config |

**Models**

| Model | Table | Fields |
|-------|-------|--------|
| `BaseModel` | (abstract) | id, created_at, updated_at |
| `User` | users | username, password (hashed), nickname, phone, avatar, role, status, last_login_at |

**Enums**

| Enum | Values |
|------|--------|
| `UserRole` | USER (1), ADMIN (2), SUPER_ADMIN (3) |
| `UserStatus` | NORMAL (1), DISABLED (2) |

**Schemas (schemas/user.py)**

| Schema | Purpose |
|--------|---------|
| `UserCreate` | Registration request |
| `UserUpdate` | Profile update (nickname, phone, avatar) |
| `PasswordChange` | Password change request |
| `UserOut` | Full user detail response |
| `UserListItem` | Lightweight list item |

**Schemas (schemas/auth.py)**

| Schema | Purpose |
|--------|---------|
| `LoginRequest` | Login request |
| `TokenOut` | Login response — access + refresh tokens + user |
| `RefreshRequest` | Refresh token exchange request |
| `RefreshOut` | Refresh response — new access token only |

**Exceptions (app/common/exceptions/user.py)**

7 named exception classes: `UsernameAlreadyExists` (1001), `UserNotFound` (1002),
`IncorrectPassword` (1003), `OldPasswordIncorrect` (1004), `UserDisabled` (1005),
`TokenExpired` (1006), `PhoneAlreadyExists` (1007).

**Infrastructure**

| Component | File |
|-----------|------|
| Configuration | `app/core/config.py` — 14 fields via pydantic-settings |
| Security | `app/core/security.py` — bcrypt + JWT (HS256, jti, type validation) |
| Redis | `app/core/redis.py` — Refresh token store (rt:{jti}) |
| Logging | `app/core/logging.py` — DEBUG/INFO env-aware |
| Database | `app/db/database.py` — register_tortoise (SQLite/MySQL) |
| DI | `app/api/deps.py` — get_current_user / admin / super_admin Depends chain |
| Pagination | `app/common/pagination.py` — PageParams + Page[T] |
| RBAC | `app/api/v1/admin_users.py` — paginated user list + disable |
| Audit | `app/models/audit_log.py` — operator_id, action, target_type, ip |
| Tests | `tests/` — 38 tests covering all endpoints |

### Changed

- **Exception handling:** Replaced single catch-all handler with per-type
  registration to fix Starlette re-raise issue.
- **Response format:** All endpoints now use `success()` envelope instead of
  `response_model` — ensures 100% consistent `{"code":0, "data":...}` format.
- **API layer:** Removed `response_model` decorators; `UserOut.model_validate()`
  handles serialization and password exclusion.

### Database

**New table:** `users`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| username | VARCHAR(32) UNIQUE | |
| password | VARCHAR(128) | bcrypt hashed |
| nickname | VARCHAR(32) | |
| phone | VARCHAR(11) | nullable |
| avatar | VARCHAR(256) | nullable |
| role | SMALLINT | default 1 |
| status | SMALLINT | default 1 |
| last_login_at | DATETIME | nullable |
| created_at | DATETIME | auto |
| updated_at | DATETIME | auto |

### Important Decisions

1. **JWT over sessions.** RESTful, no server-side state, suitable for
   separated frontend/backend. See architecture.md §6.3.

2. **Service layer owns business logic.** Repository is pure data access,
   all checks (dedup, password verification, status validation) live in
   `UserService`. This keeps the API layer thin and testable.

3. **Named exceptions over generic codes.** `raise UsernameAlreadyExists()`
   instead of `raise BusinessException(code=1001, ...)`. Self-documenting,
   impossible to get the wrong code number.

4. **pydantic-settings over os.getenv().** Automatic type coercion (bool,
   int from .env strings), field validation at startup, cleaner code.

5. **`success()` envelope over `response_model`.** The `{"code":0,
   "data":...}` format is enforced at the API layer, not delegated to
   FastAPI serialization. This prevents mixed response formats.

6. **`field_serializer` for IntEnum.** Stored as TINYINT in DB, exposed
   as lowercase string in API (`"user"` not `1`). This matches the
   API design conventions.

### Known Limitations

- No refresh token rotation (Phase 4)
- No login audit log
- No rate limiting on login/register
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred to Phase 3
- Avatar upload deferred to Phase 3

### Dependencies Added

| Package | Version | Purpose |
|---------|---------|---------|
| pydantic-settings | 2.14 | Configuration management |
| passlib[bcrypt] | 1.7.4 | Password hashing |
| python-jose[cryptography] | 3.3.0 | JWT signing/verification |
| tzdata | — | Timezone data (Windows) |
| pytest | 9.1 | Test framework |
| pytest-asyncio | 1.4 | Async test support |
| httpx | — | HTTP test client |

---

## v0.1.0 — Project Bootstrap

**Date:** 2026-07-24

### Summary

Project initialized with FastAPI skeleton, configuration system, logging,
exception handling, and database connection. No business logic.

### Added

- FastAPI application with lifespan (startup/shutdown lifecycle)
- pydantic-settings configuration with .env / .env.example
- Structured logging (DEBUG/INFO env-aware)
- AppException hierarchy with 4 HTTP-mapped types
- Tortoise ORM with SQLite/MySQL auto-switch
- BaseModel with id, created_at, updated_at
- Unified response envelope (`success()` / `error()`)
- Health check endpoint

### Known Limitations

- No business modules
- No authentication
- No tests
