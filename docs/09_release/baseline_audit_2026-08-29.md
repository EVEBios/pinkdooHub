# Phase 9.1 发布基线审计（2026-08-29）

> **Status:** Evidence Collected
> **Audit Scope:** 本地仓库、当前工作树、公开微信规则
> **Audited Git HEAD:** `8451632981d8052d270d3f7bf1b7769f53cdb8cf`
> **Release Authorization:** None

## 1. 审计方法与边界

本次只执行安全的本地读写检查、测试和微信构建：

- 没有连接或修改持久、共享、生产 MySQL；
- 没有启动本机 MySQL/Redis/FastAPI 长驻服务；
- 没有登录或修改微信公众平台后台；
- 没有上传开发版/体验版、提交审核或发布；
- 没有写入、打印或传播真实密码、Token、AppSecret、私钥或连接串；
- MySQL-only 9 项按现有安全 fixture 跳过，留给 9.2/9.3 的专用隔离实例。

审计开始时 HEAD 与远端跟踪分支一致，工作树只包含 Phase 9 规划文档变更；运行时代码没有未提交修改。构建生成 `miniapp/dist/weapp`，该目录被 Git 忽略，不是发布 artifact。

## 2. 工具与版本

| 工具 | 审计值 | 状态 |
|------|--------|------|
| Python | 3.10.9 | 符合项目 Python 3.10 基线 |
| Node.js | 24.13.0 | 可运行当前工具链；仓库尚未用 `engines`/版本文件冻结 CI 版本 |
| npm | 11.6.2 | 可运行；默认 registry 是 npmmirror，audit API 不可用 |
| Taro CLI | 4.2.1 | 与项目精确 Taro 版本一致 |
| FastAPI | 以 `requirements.txt` 锁定版本为准 | `pip check` 通过 |
| OpenAPI | 45 paths / 109 schemas | 真实重新导出与固定 JSON 字节一致 |

## 3. 本次执行结果

### 3.1 后端

```text
.venv\Scripts\python.exe -m pytest tests/ -q
1465 passed, 9 skipped in 161.22s
```

结论：

- SQLite/普通测试基线 `verified`；
- 9 项跳过项全部是显式启用的 MySQL-only 发布门槛；
- MySQL 门槛本次未执行，因此真实 MySQL 仍为 Gate A `blocked`，不能用历史结果替代。

Python 依赖完整性：

```text
python -m pip check
No broken requirements found.
```

当前虚拟环境没有 `pip-audit`。本次只能证明依赖关系完整，不能证明 Python 依赖没有已知漏洞；安全扫描工具选型和锁定属于 9.2。

### 3.2 前端

以下命令均返回 0：

```text
npm run typecheck
npm run lint
npm run lint:styles
npm test -- --runInBand
npm run api:types:check
```

Jest 结果：

```text
61 suites passed
387 tests passed
0 snapshots
```

已知非阻断输出：`@tarojs/test-utils-react` 在 React 18.3 下持续输出 `ReactDOMTestUtils.act` 弃用告警。该告警没有改变退出码，但已进入风险登记；后续升级测试工具时必须消除或重新批准。

`npm ls --depth=0` 成功，未报告 extraneous、missing 或 invalid dependency。

### 3.3 OpenAPI

使用当前 FastAPI 重新导出到任务临时文件，结果为 45 paths / 109 schemas；SHA-256 与 `miniapp/openapi/openapi.json` 一致，随后已删除临时文件。

补充发现：Windows 非 UTF-8 控制台直接执行 `scripts/export_openapi.py --help` 会因中文帮助文本触发 CP1252 `UnicodeEncodeError`；设置 `PYTHONUTF8=1` 后正常。真实导出不受影响，但 9.2 应在 CI 固定 UTF-8 环境并增加脚本 CLI smoke。

### 3.4 微信生产构建

```text
npm run build:weapp
Taro 4.2.1
Webpack compiled successfully in 18.29s
```

文件系统统计：

| 项目 | 原始字节数 |
|------|------------|
| 全部 `dist/weapp` 文件 | 603,604 |
| 主包侧文件（排除 `admin/`） | 425,512 |
| `admin/` 分包文件 | 178,092 |
| source map | 0 个 |

这只是本地输出目录的原始大小，不是微信开发者工具或上传接口的最终包体判定。2026-08-29 官方分包文档当前显示单个主包/分包不超过 2 MiB、所有分包合计不超过 30 MiB；每个 RC 仍需用当日微信工具和规则记录正式结果。

产物扫描：

- 未发现 JWT/AppSecret/数据库密码/私钥标记；
- 发现生产占位 Origin `api.pinkdoohub.example.invalid`，因此该构建不可用于 Gate A；
- `common.js` 中包含 localhost/127.0.0.1/0.0.0.0 字面量，它们来自生产配置的禁止本机地址校验集合，不是当前 API Origin；9.2 的扫描必须区分禁止列表与实际注入值，不能只做无上下文字符串阻断；
- 没有 source map 文件，但 `project.config.json` 仍启用 `uploadWithSourceMap`，微信上传阶段的 source map 策略尚未冻结。

### 3.5 依赖审计

本机 npm 默认 registry 为 `https://registry.npmmirror.com/`，其 audit endpoint 返回 404。显式使用官方 registry 后：

```text
total: 10
moderate: 4
high: 1
critical: 5
```

当前结果涉及 Taro components/helper/H5 依赖链、swiper、lodash-es 和 esbuild。历史文档把它概括为 H5 上游风险，但本次结果也通过直接依赖 `@tarojs/components` 报告 swiper，因此不能在完成微信构建可达性分析前把 10 项全部判定为 H5-only。处理原则：

- 9.2 CI 显式使用支持 audit 的 registry；
- 保留原始 JSON 报告和审计日期；
- 分别判断 build-time、H5-only 和微信 runtime 可达性；
- 微信可达的未处置 high/critical 阻断 Gate A；
- 不执行会把 Taro 破坏性降级到 3.x 的 `npm audit fix --force`。

## 4. 仓库能力审计

| 领域 | 当前证据 | 状态 | 责任角色 | 关闭 Gate |
|------|----------|------|----------|-----------|
| CI | 没有 `.github/workflows/` 或其他流水线配置 | `blocked` | Yijie Shen | 9.2 / Gate A |
| 部署编排 | 没有 Dockerfile、Compose、服务单元、反向代理或部署目录 | `planned` | Yijie Shen | 9.3 / Gate A |
| 备份恢复 | 有迁移流程文档，没有可执行备份/恢复演练记录 | `blocked` | Yijie Shen | 9.3 / Gate A |
| MySQL | 历史隔离演练通过，本次 9 项安全跳过 | `historical` | Yijie Shen | 9.2 / Gate A |
| Redis | 应用启动 `PING`；未验证生产相似认证/TLS/故障 | `partial` | Yijie Shen | 9.3 / Gate A |
| 健康检查 | `/api/v1/health` 只返回应用状态，不检查 DB/Redis | `blocked` | Yijie Shen | Gate A |
| 管理员初始化 | 无生产 bootstrap task/CLI | `blocked` | Yijie Shen | Gate A |
| 图片 | 本地目录 + 相对 `/uploads/products` | `partial` | Yijie Shen | Gate A 持久化；Gate B 高可用 |
| 前端生产 Origin | `.example.invalid` 占位值进入构建 | `blocked` | Yijie Shen | Gate A |
| 微信域名 | `urlCheck=true`，后台实际域名状态未验证 | `blocked` | Yijie Shen | Gate A |
| Secret | `.env` 被忽略、生产拒绝默认 JWT；无 Secret Manager/轮换记录 | `partial` | Yijie Shen | Gate A 最小基线；Gate B 完整 |
| 日志 | 统一 logging；Redis 连接日志会输出完整 URL | `blocked` | Yijie Shen | Gate A |
| 监控告警 | 未发现 Sentry/Prometheus/OpenTelemetry 或等价接入 | `planned` | Yijie Shen | Gate B；Gate A 最低运行观察 |
| Python 漏洞扫描 | `pip check` 通过，未安装安全扫描器 | `gap` | Yijie Shen | 9.2 / Gate A |
| Node 版本 | 本机可运行，仓库未冻结 CI Node 版本 | `gap` | Yijie Shen | 9.2 |
| 微信登录 | 未实现 | `deferred` | Yijie Shen | Gate B |
| 微信支付 | 未实现 | `deferred` | Yijie Shen | Gate B；仅在线收款时 |
| Order create 幂等 | 未实现 | `deferred` | Yijie Shen | Gate B |
| 认证强化 | 无限流、refresh 不轮换 | `deferred` | Yijie Shen | Gate B |

## 5. 微信官方规则快照

以下内容在 2026-08-29 从微信官方文档只读核对，RC 前必须再次复核：

- [网络使用说明](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)：小程序只与已配置域名通信；request/upload/download 使用 HTTPS；域名不能是 IP 或 localhost；域名需要按平台要求完成备案；`api.weixin.qq.com` 不能作为小程序服务器域名，AppSecret 应保存在后端。
- [小程序登录](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)：`wx.login` 的临时 code 由客户端交给开发者服务器，服务器调用 `auth.code2Session`；code 只能使用一次，`session_key` 不应下发小程序。
- [分包加载](https://developers.weixin.qq.com/miniprogram/dev/framework/subpackages.html)：当前单个主包/分包不超过 2 MiB，全部分包合计不超过 30 MiB（服务商代开发口径另有区别）。
- [隐私协议开发指南](https://developers.weixin.qq.com/miniprogram/dev/framework/user-privacy/PrivacyAuthorize.html)：涉及个人信息时需配置隐私保护指引，并在调用已声明隐私接口前同步用户阅读同意状态。

## 6. 审计结论

代码质量和微信可编译性具备进入 9.2 的基础，但当前不能创建 Gate A RC。最短阻断链为：

```text
CI 与版本固定
  → 真实测试 Origin/HTTPS/微信合法域名
  → 隔离 MySQL + Redis + 图片持久化
  → readiness、日志脱敏、管理员 bootstrap
  → 迁移/备份恢复演练
  → 当前 SHA 的微信真机矩阵
```

Yijie Shen 已于 2026-08-29 完成 Phase 9.1 Review，项目进入 9.2；本审计和 9.1 Complete 均不构成 Gate A、微信后台变更、上传、提审或发布授权。
