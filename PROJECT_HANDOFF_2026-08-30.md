# pinkdooHub 项目迁移与 Phase 9 交接

> 快照日期：2026-08-30（Asia/Shanghai）
> 原工作目录：`D:\pinkdooHub`
> 当前版本候选：`v0.6.0`，未发布
> 当前工作分支：`feature/phase5-frontend`
> 当前重点：Phase 9.2 CI 与可重复构建（本地实现中，尚未完成）

本文用于把项目从当前电脑迁移到另一台电脑继续开发。它记录的是 2026-08-30 的实际仓库、工作树和本地运行数据状态；“历史已验证”“本地已有实现”“远端已保存”“当前 Gate 已通过”是四种不同状态，不可互相替代。

---

## 1. 一页结论

- 后端 Product、Order、Inventory 三个业务模块及 User/RBAC/Audit 基础能力已经完成；代码候选仍为未发布的 `v0.6.0`。
- Taro 前端 Phase 5–8 已完成账号、商品、购物车、订单和管理端纵向链路，并完成微信开发者工具 Functional；本版发布范围后来冻结为**只发布微信小程序**。
- Phase 9.1 的规划、基线审计和八类发布控制文档已经完成并 Review，已提交为 `ad4968d`（`docs(release): complete phase 9.1 baseline audit`）并推送到 `origin/feature/phase5-frontend`。
- Phase 9.2 已经在本机开始实现：存在 GitHub Actions、版本固定、微信 artifact 检查、依赖审计策略、production fail-fast、Redis 日志脱敏和配套测试；但尚未 commit/push，也没有 PR/CI Run 证据，因此状态只能记为**实现中**，不能记为 Complete。
- Phase 9.1 和本文会作为两个独立纯文档提交保存在远端；本文提交后，工作树仍会保留 **8 个已跟踪 Phase 9.2 文件修改、14 个未跟踪 Phase 9.2 文件、0 个 staged 文件**。新电脑 `git clone` 能取得 9.1 和交接文档，但不能取得这批 9.2 WIP。
- 当前 Gate A 仍是 **No-Go**。9.2 的 CI 真实运行、9.3 的隔离迁移/备份恢复/readiness/bootstrap、真实 HTTPS 和微信合法域名、9.4 的 iOS/Android 真机 RC 都未完成。
- 没有执行持久数据库迁移、微信后台修改、体验版上传、提审、tag、GitHub Release 或正式发布。

---

## 2. 项目定位与技术结构

pinkdooHub 是拼豆门店管理系统，后端提供统一 API，前端是 Taro/React/TypeScript 小程序工程。

### 2.1 后端

| 领域 | 当前技术/约束 |
|------|---------------|
| Web | FastAPI 0.139.2、Uvicorn 0.51.0 |
| ORM / Migration | Tortoise ORM 1.1.7、Aerich 0.9.3 |
| Schema / Config | Pydantic 2.13.4、pydantic-settings 2.14.2 |
| Database | SQLite 用于开发/普通自动化；MySQL 8+ 是生产和迁移权威方言 |
| Redis | Redis 8.0.1，用于 refresh token 状态 |
| Test | pytest 9.1.1、pytest-asyncio、HTTPX、fakeredis |
| Python 基线 | 3.10.9；以根目录 `.python-version` 和 CI 配置为准 |

核心分层必须保持：

```text
API -> Service -> Repository -> Model -> MySQL / SQLite
          |
          +-> Validator
          +-> Redis / shared infrastructure
```

- API 只做协议适配、认证/权限、Schema、Mapper 和统一响应。
- Service 负责业务规则、事务边界和跨 Repository 编排。
- Repository 只负责 ORM 查询/原子 CRUD，不抛业务异常。
- Validator 是纯业务校验，不查库、不写库。
- 禁止 API 直连 Repository/Model，禁止 Service 直操 Model，禁止反向依赖。

### 2.2 前端

| 领域 | 当前技术/约束 |
|------|---------------|
| Framework | Taro 4.2.1 + React + TypeScript |
| 当前发布目标 | 微信小程序 `weapp` |
| Node | 24.13.0；见 `miniapp/.node-version` |
| npm | 11.6.2；见 `miniapp/package.json#packageManager` |
| 安装 | `npm ci --legacy-peer-deps`；`miniapp/.npmrc` 已固定官方 registry、legacy peer 解析和 engine strict |
| 测试/检查 | Jest、TypeScript、ESLint、Stylelint、OpenAPI 类型漂移 |

支付宝、抖音和 H5 的源码/构建入口仍保留，但不属于当前 Phase 9 的发布承诺、CI 阻断项或验收矩阵。不要把“代码仍可构建”写成“本版支持或发布四端”。

### 2.3 关键目录

| 路径 | 用途 |
|------|------|
| `app/` | FastAPI 后端代码 |
| `tests/` | 后端测试；`tests/inventory/mysql/` 是显式启用的真实 MySQL 门槛 |
| `migrations/` | MySQL 权威 Aerich 迁移链 |
| `miniapp/` | Taro 微信小程序工程及固定 OpenAPI/生成类型 |
| `docs/01_requirements/` | 业务规则事实来源 |
| `docs/03_api/` | HTTP 契约事实来源 |
| `docs/08_frontend/` | 前端架构、测试、路线及 Phase 9 总规划 |
| `docs/09_release/` | Phase 9 发布决策、审计、风险、CI、演练和验收清单 |
| `.github/workflows/ci.yml` | Phase 9.2 GitHub Actions 初版；当前未跟踪/未运行 |
| `scripts/ci/` | CI policy 与 artifact 检查器；当前未跟踪 |
| `security/dependency_audit/` | npm/Python 漏洞例外策略；当前未跟踪 |

---

## 3. 已完成能力与整体进度

### 3.1 后端业务阶段

| 阶段 | 状态 | 主要结果 |
|------|------|----------|
| Phase 1–3 | 已完成 | 项目基础设施、统一响应/异常、配置、数据库/Redis、注册登录、refresh/logout、资料/密码、RBAC、审计 |
| Phase 4.1 Product | 已实现并最终 Review | Product/ExperienceOption/ProductKit/ProductImage、21 个 Product 操作、图片上传与补偿/延迟清理、Product Audit |
| Phase 4.2 Order | 已实现并最终 Review | Experience/Kit/混合下单、快照、查询、取消、人工 Paid、Completed、审计、事务/锁/订单号重试 |
| Phase 4.3 Inventory | 4.3.1–4.3.12 已完成并最终 Review | Kit 权威余额、订单扣减/取消恢复、ADMIN 调整幂等、流水查询、MySQL 并发/1205/EXPLAIN/HTTP 门槛 |

数据库迁移链已经在一次性 MySQL 8.0.46 上历史验证并销毁，但从未应用到持久、共享或生产数据库。SQLite 通过不能代替 MySQL 类型兼容证据；历史上真实 MySQL 曾发现并修复 `OrderStatus(IntEnum)` 被 asyncmy 错误编码的问题。

### 3.2 前端阶段

| 阶段 | 状态 | 主要结果 |
|------|------|----------|
| Phase 5 | 已完成 | Taro 工程、API Client、账号密码登录/注册、Session/refresh 基础 |
| Phase 6 | 已完成 | 公开 Product 列表/详情和 UI 状态 |
| Phase 7 | 已完成 | 本地购物车、Order 创建、我的订单/取消、ADMIN Order 查询与人工状态流转 |
| Phase 8 | 已完成 | ADMIN Product、Option/Kit、图片、上下架、Inventory、Audit、User 管理及管理端 Review |
| Phase 9 | 进行中 | 9.1 本地完成；9.2 本地实现中；9.3–9.4 未开始；9.5–9.7 延后到公开发布决策 |

2026-08-29 的 Phase 9.1 文档记录的历史本地基线为：后端 `1465 passed, 9 skipped`（9 项均为 MySQL-only）、前端 61 suites/387 tests、TypeScript/ESLint/Stylelint/OpenAPI 漂移通过，OpenAPI 为 45 paths/109 schemas，微信 production build 成功。该微信产物仍含 `.example.invalid` Origin，因此只是“构建成功”，不是可上传的 Gate A RC。

本交接盘点没有把上述历史结果升级为当前 WIP 的验证结论；Phase 9.2 未提交改动必须在新电脑重新安装依赖并重跑。

### 3.3 已知长期限制

- refresh token 尚未轮换；登录/注册尚未限流。
- 邮件验证、OAuth、管理员启用用户和头像上传尚未实现。
- Gate A 仍缺依赖 readiness、受控且幂等/可审计的首个 SUPER_ADMIN bootstrap、持久图片与备份恢复实证。
- Gate B 仍缺微信登录、Order create 服务端幂等、认证强化、生产 Secret/监控/隐私，以及在线收款时的微信支付可信闭环。

---

## 4. Phase 9 权威范围与路线

### 4.1 冻结的发布边界

本版唯一发布平台是微信小程序，先 Gate A，再决定是否进入 Gate B：

| Gate | 用户范围 | 身份/支付 | 当前结论 |
|------|----------|-----------|----------|
| Gate A：内部微信测试版 | 开发、测试、受邀业务人员 | 暂用账号密码；ADMIN+ 人工标记 Paid；无真实资金 | **No-Go**，9.2–9.4 证据未完成 |
| Gate B：公开微信小程序 | 不受控公众用户 | 必须有微信身份；若在线收款必须有完整微信支付闭环 | 未授权、未开始 |

Gate A 不得公开分发，也不能把账号密码/人工 Paid 描述成微信登录或线上支付。Gate A 通过不会自动授权提审、公开发布、生产迁移或 Gate B。

### 4.2 Phase 9 子阶段进度

| 子阶段 | 目标 | 当前实际状态 | 退出所需 |
|--------|------|--------------|----------|
| 9.1 发布目标与基线审计 | 冻结范围、现状、风险和控制文档 | **Complete；`ad4968d` 已推送远端** | 已满足；后续保持链接、状态和证据一致 |
| 9.2 CI 与可重复构建 | 干净 checkout 自动完成全门槛，artifact 绑定 SHA | **本地实现中；无远端 CI Run** | commit + PR 真实运行；8 Job 通过；依赖策略、MySQL、artifact、OpenAPI、clean tree 均有证据 |
| 9.3 隔离发布演练 | 迁移、升级、备份恢复、启动、Redis、图片、readiness、bootstrap、回滚 | **未开始** | DR-01–DR-09 在可销毁生产相似环境有完整报告 |
| 9.4 微信内部测试版 | 同一 RC 的 iOS/Android 真机、HTTPS/合法域名、弱网/生命周期、业务 Functional | **未开始** | Gate A Checklist 全部通过，且仍标记内部不可公开 |
| 9.5 公开安全与身份 | 微信登录、账号绑定、安全、Secret、监控、隐私 | **未开始 / Gate B deferred** | 公开身份和数据处理完成测试与 Review |
| 9.6 微信交易闭环 | Order create 幂等；需要收款时完成支付/回调/查单/退款/对账 | **未开始 / Gate B deferred** | 正常、重复、延迟、伪造、未知、退款和对账全通过 |
| 9.7 公开 RC 与发布 | 提审、灰度、发布观察和回滚 | **未授权 / 未开始** | Gate B 全部通过并取得明确外部操作授权 |

### 4.3 Phase 9.1 已完成并提交的交付物

`docs/09_release/` 当前包含九个文件：

1. `README.md`：发布文档索引、责任角色和状态词；
2. `baseline_audit_2026-08-29.md`：9.1 本地基线审计；
3. `release_decision_record.md`：RDR-001，微信单平台 Gate A 决策；
4. `environment_and_secrets.md`：环境矩阵和 Secret inventory；
5. `ci_gate_matrix.md`：9.2 CI 实施契约；
6. `release_drill_runbook.md`：9.3 演练顺序、停止条件和清理；
7. `wechat_acceptance_matrix.md`：9.4 自动化/真机验收矩阵；
8. `risk_register.md`：R-001–R-023 风险与关闭 Gate；
9. `go_no_go_checklist.md`：Gate A/Gate B Go/No-Go 清单。

所有默认责任角色均记录为 Yijie Shen。同一人承担多角色时，实施、复核、风险接受和发布授权仍需分开记录时间与结论。

---

## 5. Phase 9.2 当前 WIP：已经做了什么

以下内容存在于当前未提交工作树，不能当作远端能力或已通过证据。

### 5.1 GitHub Actions 初版

`.github/workflows/ci.yml` 定义了 8 个 Job：

| Job | 当前设计 |
|-----|----------|
| `backend-sqlite` | Ubuntu 24.04、Python 3.10.9、固定 pip/requirements，排除 MySQL 专项运行普通完整套件并上传 JUnit |
| `backend-mysql-release` | MySQL 8.0.46 service、宿主端口 13306、专用测试 Schema，Aerich 0→当前后跑 9 项 MySQL release gate |
| `frontend-quality` | Node 24.13.0/npm 11.6.2；typecheck、ESLint、Stylelint、Jest 和 CI 脚本测试 |
| `openapi-contract` | 非 UTF-8 父环境 CLI smoke、临时真实导出、固定 JSON 比较、TypeScript 生成物 check、clean diff |
| `weapp-build` | production/weapp 构建、Origin/Secret/source map/包体/H5 marker 扫描、manifest/checksum、上传非发布 CI artifact |
| `repository-hygiene` | `git diff --check`、已跟踪生成物/数据库/环境文件和高置信 Secret 扫描、clean tree |
| `python-dependency-audit` | `pip check`、固定 `pip-audit==2.10.1`、精确 policy enforcement 和报告 artifact |
| `npm-dependency-audit` | 官方 registry、production tree audit、精确 advisory/version/reachability/expiry policy 和报告 artifact |

当前 workflow 只在 PR、`main` push 或手工 dispatch 触发。把 feature 分支单纯 push 到远端不会自动产生 PR CI，除非手工 dispatch 或创建 PR。

微信 Job 使用 `https://api.ci.pinkdoohub.test`、`WEAPP_RELEASE_ELIGIBLE=0`，所以它只能证明 CI 构建/扫描可重复，**明确不是 Gate A 可发布 artifact**。真实 Gate A 必须改用批准的 HTTPS 测试 Origin，并重新绑定 SHA/checksum。

### 5.2 版本和依赖收口

- 新增根 `.python-version`：Python `3.10.9`。
- 新增 `miniapp/.node-version`：Node `24.13.0`。
- `miniapp/package.json` 固定 npm `11.6.2`、Node/npm engines，并新增 CI policy test 和微信产物检查命令。
- `requirements.txt` 当前 WIP 升级：`asyncmy 0.2.11 -> 0.2.14`、`cryptography 49.0.0 -> 50.0.1`、`python-jose 3.3.0 -> 3.5.0`。
- npm lockfile 有对应机械变化。不能只拷贝 `package.json` 而遗漏 `package-lock.json`。

这些是依赖变更，迁移后必须从干净环境安装并跑完整回归；不要复制旧 `.venv` 或 `node_modules` 代替安装。

### 5.3 安全和可重复构建改动

- `app/core/config.py` 对 production 增加 fail-fast：debug 必须关闭、DB 必须 MySQL、JWT 必须 HS256 且 secret 至少 32 字符、Redis 必须为非 loopback 的 `redis/rediss`、图片 Base URL 必须是无凭据 HTTPS。
- `app/core/redis.py` 不再记录完整 Redis URL，仅记录 scheme/host/port/db，避免凭据泄漏。
- `scripts/export_openapi.py` 强制 stdout/stderr 兼容 UTF-8，修复 Windows 非 UTF-8 控制台帮助输出失败。
- `miniapp/project.config.json` 关闭 source map 上传，并把描述收敛为 Gate A 内部微信测试版。
- `scripts/ci/check_weapp_artifact.mjs` 检查期望 Origin、占位/localhost、Secret marker、source map、主包/分包/总包 raw size、H5 依赖 marker，并生成逐文件 SHA-256 manifest。
- `scripts/ci/check_repository_hygiene.py` 拒绝跟踪数据库、上传、备份、虚拟环境、非法 `.env` 和高置信 Secret。

### 5.4 依赖风险策略

- npm 10 项风险已经在 `security/dependency_audit/npm-policy.json` 中逐项给出 reachability/decision/owner/expiry；微信原生组件、H5-only 和一次性构建链被区分，策略到期日统一为 2026-11-30。
- Python `ecdsa 0.19.2` 的 `PYSEC-2026-1325` 在 `python-policy.json` 中记录为当前 HS256-only 路径不可达，到期日同为 2026-11-30。
- 当前 requirements 升级与 policy 文件表明本地正在处置依赖风险，但没有已提交的原始 audit 报告，也没有远端 CI 执行结果。迁移后必须重新执行，不能沿用本机临时虚拟环境作为证据。

### 5.5 配套测试

当前新增但未跟踪：

- `tests/common/test_export_openapi_cli.py`
- `tests/common/test_production_config.py`
- `tests/common/test_python_audit_policy.py`
- `scripts/ci/tests/check_npm_audit.test.mjs`
- `scripts/ci/tests/check_weapp_artifact.test.mjs`

### 5.6 9.2 尚未完成的事项

1. 当前全部 WIP 尚未形成 Git commit，也没有 PR。
2. GitHub Actions 没有对当前 SHA 产生任何真实 Run；8 Job 的 Linux/MySQL 行为未获证据。
3. 9.2 Complete 要求“干净 checkout 可重复通过”，当前工作树本身并不干净。
4. 新 requirements、lockfile、生产配置和 CI policy 的完整后端/前端回归需要在新电脑重跑。
5. MySQL 8.0.46 Job 必须真实执行迁移、9 项门槛并验证服务/临时资源清理。
6. 微信 artifact 目前的 CI Origin 是保留 `.test` 域，release eligibility 被故意关闭；真实 Gate A Origin 尚未冻结。
7. 风险登记、CI Matrix、README/AI Context/changelog 仍以“CI 未实现/风险未知”为主；实现通过后要按证据更新，不能提前把风险标 closed。
8. 必须补充 Phase 9.2 的 changelog/Review 结论，并检查 warning 白名单是否满足“精确、最小、可到期”的完成定义。
9. 只有在至少一个真实 PR Run 全绿且 artifact/SHA/checksum 可追溯后，才能考虑把 9.2 标为 Complete。

---

## 6. 当前 Git 状态（必须先保护）

### 6.1 Phase 9.1 远端 checkpoint

```text
branch:   feature/phase5-frontend
upstream: origin/feature/phase5-frontend
remote:   git@github.com:EVEBios/pinkdooHub.git
Phase 9.1 commit: ad4968d
subject:  docs(release): complete phase 9.1 baseline audit
push:     8451632..ad4968d feature/phase5-frontend -> feature/phase5-frontend
```

`ad4968d` 包含 18 个纯文档文件，统计为 `1629 insertions / 72 deletions`。提交前已执行并通过：

```text
git diff --cached --name-only
git diff --cached --stat
git diff --cached --check
git status --short
```

首次 `--check` 发现 Phase 9 新文档元数据行使用 Markdown 行尾双空格；移除这些 trailing whitespace、重新暂存后，四项检查全部通过。由于该提交没有代码、配置、依赖、OpenAPI、Schema 或迁移变化，没有为提交动作重复运行 pytest/前端测试；2026-08-29 的历史代码基线仍记录在 9.1 审计中。

本文会作为紧随 `ad4968d` 的独立纯文档提交推送。提交哈希具有自引用问题，本文不硬编码自己的最终哈希；在新电脑用 `git log -2 --oneline` 获取实际分支顶端。本文推送后应为 `ahead 0 / behind 0 / staged 0`，但 Phase 9.2 工作树仍不干净。

### 6.2 本文提交后仍未提交的 8 个已跟踪文件

```text
app/core/config.py
app/core/redis.py
miniapp/.npmrc
miniapp/package-lock.json
miniapp/package.json
miniapp/project.config.json
requirements.txt
scripts/export_openapi.py
```

这些 Phase 9.2 tracked diff 合计为 `170 insertions / 105 deletions`，全部保持 unstaged。Git 同时提示部分 LF 文件在 Windows 下未来可能被转换为 CRLF；迁移时不要顺手全仓换行规范化，否则会制造大量无关 diff。

### 6.3 本文提交后仍未提交的 14 个 Phase 9.2 文件

```text
.github/workflows/ci.yml
.python-version
miniapp/.node-version
scripts/ci/check_npm_audit.mjs
scripts/ci/check_python_audit.py
scripts/ci/check_repository_hygiene.py
scripts/ci/check_weapp_artifact.mjs
scripts/ci/tests/check_npm_audit.test.mjs
scripts/ci/tests/check_weapp_artifact.test.mjs
security/dependency_audit/npm-policy.json
security/dependency_audit/python-policy.json
tests/common/test_export_openapi_cli.py
tests/common/test_production_config.py
tests/common/test_python_audit_policy.py
```

这些文件仍只存在于旧电脑。最终迁移前必须再次运行 `git status --short --branch` 和 `git ls-files --others --exclude-standard`；若还没有为 Phase 9.2 创建 checkpoint，不能只依赖远端 clone。

### 6.4 当前未纳入 Git 的本地数据/生成物

盘点到以下重要忽略项：

| 路径 | 当前盘点 | 是否直接复制 |
|------|----------|--------------|
| `.env` | 1 个文件，约 1.3 KiB；可能含本机配置/Secret | 不进 Git；需要时用加密渠道单独迁移，更推荐在新机基于 `.env.example` 重建并轮换 Secret |
| `db.sqlite3` | 约 208 KiB | 仅在需要保留本地开发数据时迁移；先停止所有写入并做一致性备份 |
| `db.sqlite3-wal` / `db.sqlite3-shm` | 当前存在，约 20 KiB / 32 KiB | 不要在数据库活跃时只复制主库；先 checkpoint/关闭连接，优先使用 SQLite `.backup` |
| `uploads/` | 35 个文件，约 3.37 MB | 若要保留本地商品图片，和数据库快照作为同一批次单独迁移 |
| `backups/` | 10 个文件，约 277 KB | 先确认用途/敏感性，再用加密介质单独保存；不要提交 |
| `miniapp/dist/` | 约 102 个文件、735 KB | 生成物，不作为源码迁移；新机从相同 SHA/配置重新构建 |
| `.phase92-pip-audit-venv/` | 临时审计环境，约 71.6 MB | 不复制；新机重建并重新审计 |
| `.venv/` | Python 虚拟环境，约 93.7 MB | 不复制；新机使用 Python 3.10.9 重建 |
| `miniapp/node_modules/` | 若存在，为本地依赖树 | 不复制；使用 lockfile 和 `npm ci` 重建 |

还应检查并按需单独迁移所有 `miniapp/.env*.local`、IDE 本地配置和微信开发者工具本地项目设置；它们不是远端源码的一部分，也不得混入 Secret/凭据提交。

---

## 7. 推荐迁移方案

### 7.1 推荐：先做 WIP checkpoint，再在新机 clone

Phase 9.1 和本文已经保存在远端；以下 checkpoint 专门用于仍留在旧电脑的 Phase 9.2 WIP。这是最不容易丢失后续工作的方式。执行前仍要 Review 代码、依赖和测试，不能把“迁移保存”误写成“9.2 Complete”。

1. 在旧电脑重新检查 diff、Secret 和意外生成物：

   ```powershell
   git status --short --branch
   git diff --check
   git diff --stat
   git ls-files --others --exclude-standard
   ```

2. 建议把当前 WIP 放到明确的临时/功能分支，而不是误标为完成：

   ```powershell
   git switch -c feature/phase9-ci
   git add --all
   git status --short
   git commit -m "chore(ci): checkpoint phase 9.2 handoff"
   git push -u origin feature/phase9-ci
   ```

3. 在 GitHub 确认新分支和 commit 可见，并记录新 commit SHA。当前 workflow 需要创建 PR、push `main` 或手工 dispatch 才会运行；建议创建面向 `develop` 的 Draft PR 来取得第一轮真实 CI 证据，但不要在未 Review 时合并。

4. 在新电脑：

   ```powershell
   git clone git@github.com:EVEBios/pinkdooHub.git
   Set-Location pinkdooHub
   git fetch --all --prune
   git switch feature/phase9-ci
   git rev-parse HEAD
   git status --short --branch
   ```

5. 比对新旧电脑记录的 SHA 和文件清单，再重建环境。

如果不允许把 WIP 推到共享远端，应离线复制整个仓库（包含 `.git` 和所有未跟踪源码），或生成 tracked binary patch + 14 个未跟踪 Phase 9.2 文件清单并使用加密介质传输。不要只复制 `git diff`：它不会包含未跟踪文件；也不要只 `git stash -u` 后在新机 clone，因为 stash 只保存在旧电脑 `.git` 中。

### 7.2 本地数据的单独迁移

源码 checkpoint 与本地数据必须分开处理：

- `.env`：在新机重建；若必须复制，用加密渠道，完成后评估 JWT/数据库/Redis 凭据轮换。
- SQLite：停止 Uvicorn、测试、数据库查看器和所有写入，使用 SQLite 自带 `.backup` 生成单文件一致性快照，再在新机执行 `PRAGMA integrity_check;`。不要直接复制活动中的 `db.sqlite3`。
- `uploads/`：与同一时间点的数据库快照一起复制，并在新机核对数量、总大小和必要时的 SHA-256。
- `backups/`：先检查内容和保留必要性，避免把旧凭据、个人数据或不明数据库备份带入新环境。
- 微信开发者工具：重新登录/授权；不要把 AppSecret、session key 或私钥放进项目目录。

---

## 8. 新电脑环境恢复

### 8.1 必需工具

- Git 与访问 `EVEBios/pinkdooHub` 的 GitHub SSH 凭据；
- Python 3.10.9；
- Node 24.13.0、npm 11.6.2；
- Redis（本地开发可用 loopback；production 语义会拒绝 loopback）；
- 需要运行 release gate 时使用可销毁的 MySQL 8.0.46/8+，不得连接共享 3306 或生产库；
- 微信开发者工具，用于 9.4 之前的开发者工具检查和最终真机流程。

### 8.2 后端恢复

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
Copy-Item .env.example .env
```

开发配置至少确认：

```text
APP_ENV=development
APP_DEBUG=true
DB_ENGINE=sqlite
REDIS_URL=redis://localhost:6379/0
PRODUCT_IMAGE_UPLOAD_DIR=./uploads/products
PRODUCT_IMAGE_BASE_URL=/uploads/products
```

启动 Redis 后：

```powershell
uvicorn app.main:app --reload
```

常用地址：API `http://127.0.0.1:8000/api/v1`、Swagger `http://127.0.0.1:8000/docs`、health `http://127.0.0.1:8000/api/v1/health`。

### 8.3 前端恢复

```powershell
Set-Location miniapp
npm install --global npm@11.6.2 --registry=https://registry.npmjs.org
npm ci --legacy-peer-deps --registry=https://registry.npmjs.org
npm run typecheck
npm run lint
npm run lint:styles
npm test -- --runInBand
npm run api:types:check
```

本地微信开发使用项目现有的 `dev:weapp` 命令；生产语义构建使用：

```powershell
$env:NODE_ENV = 'production'
$env:TARO_ENV = 'weapp'
$env:TARO_APP_APP_ENV = 'production'
$env:TARO_APP_API_ORIGIN = 'https://<approved-origin>'
npm run build:weapp
```

不要把 `<approved-origin>`、CI 的保留 `.test` Origin 或 `.example.invalid` 当作真实 Gate A Origin。打开微信开发者工具时项目根为 `miniapp`，`miniprogramRoot` 指向 `dist/weapp/`。

### 8.4 新机第一轮验证顺序

1. `git status --short --branch`：确认 SHA 和工作树状态。
2. `python -m pip check` 与 `npm ls --depth=0`。
3. Phase 9.2 新增的 Python/Node policy 单测。
4. 后端完整 SQLite 测试：`python -m pytest tests/ -q`；确认 skip 只来自显式 MySQL-only。
5. 前端 typecheck、ESLint、Stylelint、Jest、OpenAPI type check。
6. OpenAPI 真实导出到临时文件并与 `miniapp/openapi/openapi.json` 比较。
7. 微信 production build + `npm run build:weapp:check`，记录 manifest/checksum；测试 artifact 仍不得上传。
8. 创建 Draft PR，让 GitHub Actions 的 8 个 Job 在干净 checkout 真跑。
9. 检查 MySQL Job 的 service、Schema、端口、迁移和清理证据。
10. 只有 CI 证据稳定后同步风险登记、changelog、README/AI Context，并评估 9.2 Complete。

---

## 9. Phase 9 接手后的建议执行顺序

### 优先级 P0：先防止工作丢失

1. 保存当前未提交工作树到可恢复的分支/介质。
2. 在新机确认 Phase 9 的所有新增文件都存在，尤其 `.github/`、`docs/09_release/`、`scripts/ci/`、`security/` 和新增测试。
3. 不要在保存前执行 `git reset --hard`、`git clean -fdx`、覆盖式解压或只 clone 远端。

### 优先级 P0：收口 Phase 9.2

1. Review 当前 workflow 与 policy 是否符合 `docs/09_release/ci_gate_matrix.md`。
2. 从干净 checkout 重装 Python/npm 依赖并跑本地完整矩阵。
3. 创建 Draft PR，逐一修复 8 Job 的真实失败，禁止通过 skip/吞错误维持绿灯。
4. 保存当前 SHA 的 JUnit、依赖审计 JSON、微信 manifest/checksum、OpenAPI 摘要和 MySQL 版本/迁移证据。
5. 对 npm/Python policy 的 advisory、版本、可达性、决定和 2026-11-30 到期日做正式 Review。
6. 更新 `risk_register.md`：只有有 CI Run/报告证据的风险才能关闭；合并代码本身不等于关闭。
7. 增加 Phase 9.2 changelog，总结依赖升级、运行时配置变化、测试、文档、无数据库迁移和外部操作边界。

### 优先级 P0/P1：进入 Phase 9.3 前补能力

1. 设计并实现 liveness/readiness 分离，readiness 至少真实检查 MySQL/Redis，错误不泄漏连接信息。
2. 设计受控、幂等、可审计的首个 SUPER_ADMIN bootstrap；重复执行不得创建第二账号，初始凭据必须安全处置。
3. 冻结 Gate A 专用 MySQL、Redis、持久图片存储、测试 HTTPS Origin、DNS/证书和 Secret 保管方式。
4. 严格按 `release_drill_runbook.md` 执行 DR-01–DR-09：0→当前、受支持升级、独立恢复、可控失败、应用/依赖、bootstrap、Smoke 和资源清理。

### Phase 9.4：内部测试版

1. 只使用同一已通过 CI 的 SHA/artifact，禁止开发者电脑二次修改后上传。
2. 取得单独微信后台/上传授权后再操作体验版。
3. 在 iOS/Android 真机完成 request/upload/download 合法域名、HTTPS、弱网/断网、前后台、上传 unknown、Guest/User/ADMIN/SUPER_ADMIN/Disabled 用户和完整业务矩阵。
4. Gate A 所有 P0/P1 关闭或满足严格例外前，结论保持 No-Go；体验版始终明确“内部、受邀、不可公开”。

### Phase 9.5–9.7：不要提前混做

公开版另行冻结微信登录/账号绑定、限流/refresh 轮换、Order create 服务端幂等、正式 Secret/监控/隐私。需要在线收款时才实施完整微信支付/通知/查单/退款/对账。最终提审、灰度和公开发布必须有新的 Gate B Go/No-Go 与外部操作授权。

---

## 10. 数据库、发布和安全红线

- 不得把开发 SQLite 当作生产迁移证据。
- 不得连接共享 3306、持久或生产 MySQL 执行 CI/演练。
- 不得用应用自动建表或 `--fake` 替代 Aerich 权威迁移。
- 正式迁移前必须停写、只读审计、可验证备份、隔离演练、明确授权和失败处置。
- `.env`、Token、JWT secret、Redis/MySQL 密码、AppSecret、私钥、真实连接串不得进入 Git、日志、artifact 或本文。
- CI 成功不自动授权持久迁移、微信上传、提审、tag、release 或发布。
- Gate A 账号密码与人工 Paid 只用于受控内部闭环；不得面向公众冒充微信登录/在线支付。
- 图片本地目录不是公开版的最终存储方案；Gate A 至少要有持久化与备份恢复证据。

---

## 11. 关键文档阅读顺序

接手后建议按以下顺序阅读：

1. `AGENTS.md`：项目级强制开发规则；
2. `docs/06_ai/AI_CONTEXT.md`：全局上下文与能力速查；
3. `docs/08_frontend/phase9_wechat_release_plan.md`：Phase 9 权威路线；
4. `docs/09_release/README.md`：发布交付物索引；
5. `docs/09_release/ci_gate_matrix.md`：当前 9.2 实施契约；
6. `docs/09_release/risk_register.md` 与 `go_no_go_checklist.md`：当前 No-Go 原因；
7. `docs/09_release/release_drill_runbook.md`：9.3 演练；
8. `docs/09_release/wechat_acceptance_matrix.md`：9.4 真机验收；
9. `docs/05_development/changelog.md`：各阶段实现/验证历史；
10. 修改具体业务时，再读对应 `docs/01_requirements/`、`docs/03_api/`、数据库设计和实际代码/测试。

---

## 12. 迁移完成验收清单

- [ ] 旧机当前 WIP 已保存到可恢复分支或加密离线介质；
- [ ] 新机 `HEAD` 与记录 SHA 一致，Phase 9 新增文件齐全；
- [ ] `.env` 已安全重建，没有 Secret 进入 Git；
- [ ] Python 3.10.9、Node 24.13.0、npm 11.6.2 已确认；
- [ ] Python/npm 依赖从清单和 lockfile 干净安装；
- [ ] Redis 可用；SQLite 本地数据若迁移，已做一致性/完整性检查；
- [ ] `uploads/` 若迁移，与数据库快照匹配；
- [ ] 后端、前端、OpenAPI 和微信构建本地门槛已重跑；
- [ ] Draft PR 的 8 个 CI Job 已实际运行并保存证据；
- [ ] 当前 Git status、未解决风险和下一任务已更新到本文件或 Phase 9 文档；
- [ ] 没有误执行持久迁移、微信后台修改、上传、提审、tag、release 或发布。

---

## 13. 本次交接文档的验证边界

- 本文依据 2026-08-30 的实际 `git status`、分支/远端 SHA、文件树、tracked diff、Phase 9 总规划、`docs/09_release/`、CI workflow、policy/scripts/tests 和项目 changelog 整理。
- Phase 9.1 的 18 个纯文档文件已经在四项 staged 检查通过后提交为 `ad4968d` 并推送；本文作为独立纯文档提交继续推送。Phase 9.2 的 8 个 tracked 修改和 14 个未跟踪文件没有被暂存或修改。
- 2026-08-29 的测试数字是已存在基线审计中的历史本地证据；当前 Phase 9.2 WIP 尚未由远端 CI 复验。
- 本次没有执行 pytest、前端测试、MySQL、数据库迁移或微信构建；原因是两个交付提交均为纯文档，运行时代码仍保持在 unstaged WIP 中。
- 没有执行持久迁移、微信后台修改、体验版上传、提审、tag、GitHub Release 或正式发布。
- 本次未创建或接管任何需要长期保留的服务、容器、数据库、浏览器或 watcher。
