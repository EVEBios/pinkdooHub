# Phase 9.2 CI Gate Matrix

> **Status:** Design Frozen; 9.2.1–9.2.5 Eight Jobs Implemented Locally
> **Last Updated:** 2026-08-31
> **Current Provider:** GitHub Actions（8 个 Job 已本地实现；真实 PR Run 待执行）

本文件是 9.2 的实施契约。可以使用 GitHub Actions 或未来批准的等价 CI，但 Job 语义、隔离边界和阻断规则不能因供应商变化而弱化。

9.2.1–9.2.5 已在 `.github/workflows/ci.yml` 本地实现 `backend-sqlite`、
`backend-mysql-release`、`frontend-quality`、`openapi-contract`、`weapp-build`
和 `repository-hygiene`，以及 `python-dependency-audit`、`npm-dependency-audit`。
当前尚没有 GitHub PR Run，因此所有 workflow 状态都只是 `implemented-local`，不是远端 CI
通过证据。`backend-mysql-release` 已额外完成同配置本地 Docker 真实演练，但仍需
当前 SHA 的 PR Run 才能关闭 CI 风险。

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
| `backend-mysql-release` | 专用 MySQL 8+，非 3306，专用 Schema | Aerich 0→1→2；运行 `tests/inventory/mysql` 9 项 | 迁移、版本、并发、1205、HTTP、EXPLAIN 任一失败 | MySQL 版本、Aerich 版本、pytest/JUnit | Yijie Shen |
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
python -m pytest tests/ -q
```

当前普通基线：1507 passed；9 项 MySQL-only 由独立 Job 执行。测试数量变化不是失败本身，但必须解释增删原因；不能把真实失败改成 skip 来维持数字。

### 3.2 Backend MySQL Release Gate

沿用 `tests/inventory/mysql/conftest.py` 的安全边界：

- 显式 `INVENTORY_MYSQL_TEST_ENABLED=1`；
- host 是 `127.0.0.1`；
- port 不是 3306；
- Schema 以 fixture 要求的专用前缀开头；
- Job 自己创建、迁移和销毁实例/Schema；
- 运行完成后复核进程、端口和临时数据目录。

CI 配置不得放宽 fixture 来连接共享 MySQL，也不得使用 `--fake` 或应用自动建表替代迁移。

9.2.4 已实现以下边界：

- service 固定 `mysql:8.0.46`，只映射宿主 `127.0.0.1:13306`，Schema 固定为 `pinkdoohub_inventory_4311_ci`；仓库中的密码只是一容器一生命周期的 disposable test credential，不是发布 Secret；
- `check_mysql_gate.py preflight` 要求 `APP_ENV=testing`，并强制 Aerich 使用的 `DB_*` 与 pytest 使用的 `INVENTORY_MYSQL_TEST_*` 在 host/port/Schema/user/password 上完全一致；
- `aerich --app models upgrade` 真实应用三条权威迁移，snapshot 校验 MySQL 8.0.46 与精确 0、1、2 版本链；没有 `--fake`、`init-db` 或 `generate_schemas()`；
- 9 项门槛保存 JUnit；`always()` cleanup 删除精确专用 Schema、停止 GitHub service container、确认容器不再运行和 13306 关闭，再上传 preflight、迁移日志、snapshot、JUnit 与 cleanup JSON；
- 2026-08-31 本地以同一镜像、端口和 Schema 真实执行：三条迁移及 9 项门槛全部通过，cleanup 四项均为 true，容器对象和临时证据目录随后删除；未连接 3306、持久或共享数据库。

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

Python 漏洞扫描器尚未选型。新增工具前检查维护状态、许可证、锁定方式和 CI 可复现性；工具本身作为开发依赖记录，不进入生产运行环境。

## 5. 触发与权限

| 事件 | 必须 Job | Secret 权限 | 外部动作 |
|------|----------|-------------|----------|
| 普通 PR | 全部非发布 Job；MySQL Job | 无生产 Secret | 无 |
| Fork PR | 同上；使用无 Secret 的隔离服务 | 无 | 无 |
| 集成分支 | 全部 Job | 仅测试环境 Secret | 生成 artifact，不上传微信 |
| Gate A RC | 全部 Job重跑 | 受保护测试环境 Secret | 经批准后可人工上传体验版 |
| Gate B RC | 全部 Job + Gate B 专项 | 受保护生产候选 Secret | 经双人/明确审批后提审 |
| 定时 | 依赖审计、可选工具链兼容检查 | 最小读取权限 | 无发布 |

## 6. 9.2 完成定义

- [ ] CI 配置已提交并经过至少一个 PR 真实运行；
- [ ] 所有 Job 从干净 checkout 通过；
- [ ] MySQL Job 创建、迁移、测试、关闭和清理均有证据；
- [ ] 微信 artifact 绑定 SHA、checksum 和配置摘要；
- [ ] OpenAPI 漂移在修改与未修改场景均被验证；
- [ ] npm registry audit 失败会显式失败，不被吞掉；
- [x] 当前 10 项 npm 风险完成微信 reachability 分类并有 2026-11-30 到期策略；
- [x] Python 漏洞扫描已锁定，修复可升级项并只保留 1 条有期限不可达例外；
- [ ] warning 白名单精确、最小、可到期；
- [ ] 没有配置自动迁移持久数据库、自动提审或自动发布。
