# Gate A M7→M8 完整更新器远程 CI 演练报告

> **Result:** PASS（GitHub Actions 最终 9/9；Run attempt 1 的 OpenAPI 依赖安装出现一次性 TLS/truststore 错误，attempt 2 原样重跑通过）  
> **Release Decision:** BLOCKED / No-Go / Not Authorized  
> **Executed At:** 2026-09-09 07:00–07:08（Asia/Shanghai）  
> **Branch:** `feature/phase9-ci`  
> **PR:** [#2 `feature/phase9-ci` → `develop`](https://github.com/EVEBios/pinkdooHub/pull/2)  
> **Run:** [GitHub Actions 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644)

## 1. 结论与证据边界

本次在 GitHub-hosted disposable Ubuntu Runner 上，首次完整执行了本仓库的
M7→M8 完整更新器演练，而不只是单独运行 Aerich 迁移或 MARD publisher：

- 从冻结的 M7 source SHA 构建 source Runtime，建立代表性业务数据、221 色和
  225 张总图片；
- 建立 M7 写前 Backup，使用同一 Backup ID 在独立、无宿主端口的恢复实例
  完成 Restore；
- 以当次 PR merge-ref 作为 target Runtime，执行 M7→M8 `plan → apply →
  plan-replay → app-up`；
- 验证 M0–M8 精确 Aerich 链、221 个规范 HEX、gzip 原始 wire body、PNG 兼容回退和
  小响应不压缩；
- 再建立 M8 数据后 Backup/独立 Restore；
- 在成功、失败与 workflow `always()` 退出路径上都检查容器、网络、卷、镜像、
  端口和临时目录，最终为零残留。

这一结果关闭了“完整 updater 尚未在一次性 Linux/MySQL 环境运行”的候选实现
风险，但不是持久 Gate A 的执行记录。运行明确记录
`persistent_gatea_authorized=false` 和 `production_secrets_used=false`；它没有连接或修改
持久 Gate A、共享、预发布或生产数据。持久 Gate A 的最后权威留证版本仍是 M7，
因此微信内部测试版仍为 **No-Go / Not Authorized**。

## 2. 受测身份与运行环境

| 项目 | 值 |
|------|----|
| PR head SHA | `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b` |
| 实际 checkout / PR merge-ref SHA | `a9ff3d246c61a4aeede062596c32817a69834d7a` |
| 冻结 M7 source SHA | `73dca350505d43775fb1ff1158ccf6aabc221998` |
| Workflow / Run | `.github/workflows/ci.yml` / `34288613644`（UI 序号 `#54`） |
| Event | `pull_request` |
| Host | GitHub-hosted Ubuntu / Linux `x86_64` / root |
| Docker | Engine/Client `28.0.4/28.0.4`；Compose `2.38.2` |
| Docker daemon | `unix:///var/run/docker.sock`；context `default` |
| 演练权限 | disposable-only；无持久 Gate A 授权；无生产 Secret |
| 清单 SHA-256 | `45e37342ff77907556974bc78c501a3931fda9100afae4506a709ab8a11ad238` |

GitHub 把业务候选标识为 PR head，但 `pull_request` Job 实际测试的是 merge-ref。
本报告分别记录两者，不把 merge-ref 冒充为 branch head。本报告在 Run 完成后才
创建，因此报告文本本身不属于受测的 `62b1b15...`/`a9ff3d2...`。

宿主预检确认固定的演练容器、网络、卷、镜像和回环端口均为 clean start。
脚本拒绝本机、self-hosted Runner、远程 Docker daemon、非 default context 和预存同名
资源，本次没有放宽这些 guard。

## 3. CI 结果与一次性失败处置

Run 的最终状态为 9/9 success：

| Job | 最终结果 | 证据边界 |
|-----|----------|----------|
| `backend-sqlite` | success（5m25s） | 完整 SQLite 回归与 JUnit |
| `backend-mysql-release` | success（1m22s） | 实际 MySQL 8.0.46 迁移/联合门槛；与下方完整 updater Job 相互独立 |
| `gatea-m7-m8-updater` | success（4m02s） | 14 阶段完整 updater、双 Backup/Restore、Runtime 和零残留 |
| `frontend-quality` | success（1m27s） | TypeScript、ESLint、Stylelint、Jest 和 CI policy |
| `openapi-contract` | success（attempt 2，51s） | OpenAPI CLI、固定 Schema 与前端生成类型无漂移 |
| `weapp-build` | success（50s） | 不可发布的 production-mode 代码检查产物；`release_eligible=false` |
| `python-dependency-audit` | success（31s） | 锁定 Python 依赖与审计策略 |
| `npm-dependency-audit` | success（45s） | 当前 production reachability 审计与有期限例外策略 |
| `repository-hygiene` | success（14s） | tracked 文件、Secret、diff 和 clean-tree 检查 |

Attempt 1 的唯一失败为 `openapi-contract`的 `Install locked contract toolchains`步骤。
日志在 `pip` 访问包索引的 TLS/truststore 路径中报出：

```text
AttributeError: 'NoneType' object has no attribute 'get_unverified_chain'
Process completed with exit code 2.
```

该次失败发生在依赖安装阶段，`Verify OpenAPI CLI and committed schema`完全未执行，
所以不能记为 OpenAPI 漂移。同一 clean checkout 未改代码重跑失败 Job 后，安装和
契约检查在 51 秒内通过，Run 最终转为 Success。这一重跑边界在报告中保留，
不写成“首次就 9/9”，也不因为一次性 Runner 网络异常修改业务代码。

## 4. 完整 updater 的 14 个阶段

| # | 阶段 | 耗时 | 结果摘要 |
|---:|------|-----:|----------|
| 1 | `build-images` | 32.640s | 构建并验证 M7 source/M8 target 镜像身份 |
| 2 | `start-source` | 45.483s | 启动 source，精确识别 M0–M7 |
| 3 | `bootstrap-source` | 5.749s | 完成并记录幂等 Bootstrap |
| 4 | `seed-representative` | 3.121s | 26 个 API 请求建立代表数据，2 Product/3 图片 |
| 5 | `publish-source-mard` | 6.659s | 发布 221 色/221 PNG，重放为 no-op |
| 6 | `seed-color-kit` | 0.813s | 建立 Online 自选色 Kit，启用 3 色 |
| 7 | `verify-source-m7` | 1.324s | 核验 M0–M7、221 色、225 图片 |
| 8 | `backup-restore-source` | 41.056s | M7 Backup `20260908t230214z` 与同 ID 独立 Restore 通过 |
| 9 | `plan-target` | 0.447s | 以 M7 source Backup 和 target SHA 完成只读 plan |
| 10 | `apply-target` | 11.820s | 在 App/Nginx 停止时执行 M8，生成成功 Record/evidence |
| 11 | `plan-replay` | 2.739s | 启动前紧邻 live replay，`already_current=true` |
| 12 | `app-up` | 17.914s | 仅绑定回环端口，4 个服务健康 |
| 13 | `verify-m8-runtime` | 1.052s | 221 HEX、gzip、PNG 回退和小响应规则通过 |
| 14 | `backup-restore-target` | 41.007s | M8 Backup `20260908t230329z` 与同 ID 独立 Restore 通过 |

编排器从预检开始到主清理完成约 214.7 秒；GitHub Job 连同 checkout、环境准备、
artifact 上传与 `always()` 清理共 4m02s。所有 14 阶段均 `passed=true`，
`failed_stage=null`、`operation_error=null`。

## 5. 数据、恢复与 Runtime 证据

### 5.1 M7 source 与写前恢复

- source 精确为 M0–M7，`swatch_hex` 列为 0；
- 221 条 MARD 目录与冻结 manifest 精确一致；
- 共 225 张图片，其中 221 张为确定性纯色 PNG；
- M7 业务内容摘要为
  `a286bc01f1ae6b81fe1a4a451f56e04f7f26a1bb17f3c06e55d4cd67a7fa3a57`；
- Backup ID `20260908t230214z`：MySQL dump 803,316 bytes，SHA-256
  `ad75c4a85b5ca370d5f64b0eb1fef4454fc56a27a89cb4e1b09bcee72ac4708e`；图片包 348,160 bytes，
  SHA-256 `e47ab0c328a076a7dffef8ebf36f565ddbf1bb2327497504fbcdb65116ff3ea5`；
- 同 ID 独立 Restore 核验数据库、图片、M7 内容摘要、空 Redis/会话失效策略和
  Restore App，`temporary_resources_removed=true`。

### 5.2 M8 apply 与不漂移断言

- Aerich 精确从 M0–M7 增加
  `8_20260908140000_add_bead_color_swatch_hex.py`；
- `bead_colors.swatch_hex` 形状和 1–221 slot 全部通过，为 221 个唯一、规范大写
  `#RRGGBB`；
- 升级成功点的 `m7-preserved-business-v1` 内容摘要仍为
  `a286bc01f1ae6b81fe1a4a451f56e04f7f26a1bb17f3c06e55d4cd67a7fa3a57`，图片 manifest
  仍为 225 件/
  `e408e44171895f5fe99195b0f03a14e802aae66dfbac1397af40c9fc5428ccf9`；
- MARD apply 在已有 Online 自选色商品下为精确 no-op：`database_changes=0`、
  `images_to_create=0`、`images_reused=221`、`created_images=0`；
- 成功 Record 后、`app-up` 前的紧邻 replay 重新核验现场 DB、图片、内容摘要、
  MARD 与停服状态，结果 `already_current=true`。

### 5.3 M8 Runtime

| 检查 | 实测结果 |
|------|----------|
| 管理目录 | 221 个 slot，逐项 HEX 与冻结 manifest 一致 |
| 公开自选色商品 | 恰好 3 个已启用颜色，HEX 均规范 |
| identity JSON | 63,445 bytes |
| gzip JSON | 10,948 bytes |
| 压缩收益 | 减少 52,497 bytes，约 82.74% |
| gzip 语义 | 解压后逐字节相等；`Vary: Accept-Encoding` 正确 |
| 小响应 | 75 bytes，无 `Content-Encoding` |
| 兼容 PNG | 582 bytes，`image/png`，无重复压缩，字节/SHA 与冻结图片一致 |

本检查证明新链路的服务端契约和兼容路径，但它使用回环 HTTP，不是真实
Origin/TLS/CDN 或微信真机证据。

### 5.4 M8 数据后恢复

- Backup ID `20260908t230329z`：MySQL dump 947,776 bytes，SHA-256
  `4fb920f16fc8c7e9e3168a3b7b54819d2ed474743716acf37d24f338fda38156`；图片包仍为
  348,160 bytes/
  `e47ab0c328a076a7dffef8ebf36f565ddbf1bb2327497504fbcdb65116ff3ea5`；
- 同 ID 独立 Restore 通过，包含 M0–M8、221 HEX、225 图片、Restore App、空 Redis/会话
  失效策略和临时资源清理；
- target Backup 发生在 Runtime 登录/验收请求之后，因此它的 M7 投影内容摘要为
  `fa7d37df8a4f051b34662a4bd45830d051aadf8f0d5be7648868ae93b9bd301d`。这不是迁移
  漂移：升级成功点已先证明 source/final 同为 `a286bc...`；恢复器则证明数据后
  Backup 可精确恢复到 `fa7d37...`。

## 6. Artifact 安全与资源回收

`gatea-m7-m8-updater-a9ff3d246c61a4aeede062596c32817a69834d7a-34288613644-1`
包含 20 个脱敏 JSON 文件，GitHub 显示大小 41 KB，digest 为
`sha256:99f162b1dc6944ec3dd2c522f1d4ce5a3768dd6131dc2d0f20ad81f71c753098`。下载后本地重算
同一 SHA-256，与 GitHub digest 完全一致。

上传前执行了文件名白名单、文件类型/权限检查、本次生成的真实 Secret 值扫描和
credential-shaped 模式扫描，结果为 `allowlist_passed=true` 与
`secret_scan_passed=true`。Backup 原文、Secret、凭据、Token 和请求正文没有被上传。

主清理第 1 次在 `main-compose-down` 返回失败，但当时现场检查已显示容器、网络、
卷、镜像、回环端口和工作目录均无残留。编排器没有忽略返回值，而是在 1 秒后执行
有界的第 2 次清理；第 2 次 `passed=true`。Workflow `always()` 路径再次执行幂等清理，
`cleanup-report.json` 最终记录：

- 主/恢复容器、网络和卷：0；
- 任务镜像：0；
- 回环端口：可用；
- 临时 workspace：不存在；
- `errors=[]`、`passed=true`。

因此第一次 compose 返回的瞬时异常被如实记录，又没有把一次非零返回直接降级为
成功；最终成功依然以实际零残留为前提。

Run 共保存 8 组 artifact；`openapi-contract` 按设计仅阻断、不上传 artifact。

## 7. 失败—修复链

为避免只保留最后绿色结果，本次完整更新器的真实迭代保留如下：

| Run | 结果 | 根因/处置 |
|-----|------|----------|
| [34283290937](https://github.com/EVEBios/pinkdooHub/actions/runs/34283290937) | 7/8 | 新的 Joi Low 公告触发 npm fail-closed；锁文件将 Joi `17.13.4→17.13.7`，没有扩大风险例外 |
| [34287496458](https://github.com/EVEBios/pinkdooHub/actions/runs/34287496458) | Gate A `start-source` 失败 | 首次真实运行暴露 Compose CLI 差异；先增加脱敏失败证据 |
| [34287949221](https://github.com/EVEBios/pinkdooHub/actions/runs/34287949221) | Gate A `start-source` 失败/后被新推送取消 | 证据锁定 Compose 参数应为大小写敏感的 `--no-TTY`，修正全部 Gate A 入口 |
| [34288171020](https://github.com/EVEBios/pinkdooHub/actions/runs/34288171020) | 14/14 阶段通过，主清理返回失败 | `compose down` 的瞬时返回使 Job 保持失败；增加最多 2 次/1 秒间隔的有界清理，仍强制最终零残留 |
| [34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) | 最终 9/9 | Gate A 14/14、双恢复、artifact 扫描和零残留通过；OpenAPI 依赖安装瞬时失败后原样重跑通过 |

这条链表明完整 updater 的演练、失败证据、Compose 可移植性和清理补偿都已在
真实 GitHub-hosted Docker 环境中验证。失败 Run 不会被重命名或隐藏为 PASS。

## 8. 已关闭与仍阻断的项目

本次可以关闭：

- 完整 M7→M8 updater 的 GitHub-hosted disposable Linux/MySQL/Redis/图片编排缺口；
- source/target 镜像身份、M7/M8 精确迁移链与 PR head/merge-ref 混淆风险；
- M7 写前 Backup/恢复、M8 数据后 Backup/恢复的一次性工具门槛；
- 已有 Online 自选色商品下 MARD 精确 no-op 与启动前 live replay；
- 一次性 Runtime 中 221 HEX、gzip 和 PNG 兼容路径；
- 失败/中断清理的有界重试、幂等性、脱敏 artifact 与零残留证据。

仍然不能关闭：

1. **持久 Gate A M7→M8。** 仍需在精确目标上重新只读确认 M7/部署镜像/图片
   manifest，冻结当次停写窗口、新 Backup/Restore、source/target SHA/Image ID、执行与
   复核人，并取得明确写授权。
2. **真实 HTTPS/Origin/RC。** 演练仅使用回环 HTTP；备案、DNS、证书、微信 request/
   upload/download 合法域名和 `release_eligible=true` 产物仍未建立。
3. **小程序灰度/真机。** 没有授权上传、分发、提审或发布；iOS/Android 真机
   功能、弱网、生命周期、HEX 零 PNG 请求和兼容回退仍无人工证据。
4. **容量 Gate。** 本地 12/12 Profile 已采集，但 identity 10 VU 保持失败；还需
   干净候选的 candidate-pre 三轮和独立 2 vCPU/4GiB Linux/真实网络复现，或按
   规则完成有期限风险签署。
5. **最终发布决策。** PR 未合并，v0.6.0 未 tag/release；本 Run 不授权数据库
   迁移、Runtime 切换、DNS、微信后台变更、上传、灰度、提审或公开发布。

综上，下一个可执行步骤是：在用户指定的持久 Gate A 目标上只读重新预检，
再以当次窗口和精确 target SHA/Image 取得写授权。在此之前，仓库和一次性
演练已达到当前能够安全完成的边界，发布决定保持 No-Go。
