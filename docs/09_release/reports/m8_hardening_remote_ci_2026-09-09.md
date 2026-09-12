# M8 发布加固候选远端 CI 报告

> **Result:** PASS（GitHub Actions 8/8）
> **Release Decision:** BLOCKED / No-Go
> **Executed At:** 2026-09-09 05:36–05:41（Asia/Shanghai）
> **Branch:** `feature/phase9-ci`
> **PR:** [#2 `feature/phase9-ci` → `develop`](https://github.com/EVEBios/pinkdooHub/pull/2)
> **Run:** [GitHub Actions 34281512196](https://github.com/EVEBios/pinkdooHub/actions/runs/34281512196)

## 1. 受测身份

| 项目 | 值 |
|------|----|
| PR head SHA | `fa6fce05a153321d5c4079cb50f123c7996695f2` |
| PR merge-ref SHA | `b2f02ebc65bedf736197d54ed65228320d9962a4` |
| Base | `develop@35d28bb4393350b7621072f113301c32b91fb513` |
| Workflow / Run / attempt | `.github/workflows/ci.yml` / `49` / `1` |
| Event | `pull_request` |
| Run window | `2026-09-08T21:36:11Z`–`2026-09-08T21:41:27Z` |

GitHub Run 元数据把业务候选绑定到 PR head；Job checkout 和 artifact 名称使用本次
merge-ref。两者用途不同，不能把 merge-ref 写成候选 head，也不能只记录其中一个。
本报告形成于 Run 完成后，因此报告本身不属于受测 head `fa6fce05...`；后续 docs-only
提交若再次触发 CI，不能把 Run 34281512196 冒充为那个新提交的执行结果。

本次候选把此前只存在于本地工作树的 M7→M8 发布保护和容量工具收口成干净提交：显式
`--source-version 7`、`m7-preserved-business-v1` 的 21 表内容保护、raw M7
色卡/schema/221 PNG 写前预检、Online 目录事务内 exact no-op、成功 Record 后且
`app-up` 前的停服 live replay，以及 fail-closed 的容量证据采集均包含在
`fa6fce05...`。Run 34281512196 已关闭这份代码候选的“最终干净 SHA + 完整远端 8/8”
缺口；它没有执行完整 Gate A updater 编排，也不授权任何持久写入或外部发布动作。

## 2. Job 结果

| Job | 结果 | 开始（UTC） | 完成（UTC） | 时长 | 证据边界 |
|-----|------|-------------|-------------|------|----------|
| `backend-sqlite` | success | 21:36:14 | 21:41:26 | 5m12s | 完整 SQLite Job 与 JUnit artifact 保存成功 |
| `backend-mysql-release` | success | 21:36:15 | 21:38:29 | 2m14s | 专用 MySQL、M6→M7→M8 历史迁移、真实 MySQL release gates、cleanup 与 evidence 步骤成功；不等于完整 updater 演练 |
| `frontend-quality` | success | 21:36:14 | 21:38:38 | 2m24s | TypeScript、ESLint、Stylelint、Jest 与 CI policy 成功 |
| `openapi-contract` | success | 21:36:15 | 21:38:16 | 2m01s | OpenAPI 固定文件、CLI 与生成类型无漂移 |
| `weapp-build` | success | 21:36:15 | 21:38:05 | 1m50s | production-mode 非发布微信 artifact 构建、校验和与身份读取成功；`release_eligible=false` |
| `python-dependency-audit` | success | 21:36:15 | 21:36:51 | 36s | 固定 Python 依赖与审计策略成功 |
| `npm-dependency-audit` | success | 21:36:15 | 21:37:59 | 1m44s | npm production reachability 审计策略成功 |
| `repository-hygiene` | success | 21:36:15 | 21:36:39 | 24s | tracked 文件、Secret、diff 和 clean-tree 检查成功 |

8 个 Job 均为独立完整执行，没有拼接旧 Run 或只重跑单个失败 Job。远端
`backend-mysql-release` 证明 workflow 中既有的 reviewed Aerich M6 through M8 legacy
migration、真实 MySQL release gates 和精确 cleanup；它不启动 `deploy/gatea` 的完整
生命周期，不包含 M7 Backup/独立 Restore、App/Nginx 停服、upgrade Record、重放、
`app-up` 或 M8 数据后恢复。因此该 Job 不能替代“专用一次性 MySQL 完整 updater”门槛。

## 3. Artifact 清单

Run 保存 7 组未过期 artifact，均保留至 2026-09-22。8 个 Job 中
`openapi-contract` 按 workflow 只做阻断检查、不上传 artifact，所以 7 组符合设计，
不是证据缺失。

| Artifact | Bytes | GitHub digest |
|----------|------:|---------------|
| `backend-sqlite-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 42,957 | `sha256:1780bc875268db8c48c7759d1544821774b5a6d78c38d390ea5bb2dc49550d8a` |
| `backend-mysql-release-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 3,750 | `sha256:b7b45f2433889d3dce69fb69da4e4c21ec32351954750e777205314987ae4db5` |
| `frontend-quality-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 33,093 | `sha256:ce5f331664af724587e0c27612472625ed46b066f35ccdd0ba394b51f3bd3fe8` |
| `weapp-1.0.0-b2f02ebc65be-34281512196` | 296,129 | `sha256:2f0e9af28ac10dd4f45a8d5a028c5242b7ea0ee6afa1988fca554ac26e062abf` |
| `python-dependency-audit-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 1,206 | `sha256:83b5c9f1d07d1dd7d1f65f7b73ca04110f428301436d23ad0b14e465cd8f0707` |
| `npm-dependency-audit-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 1,787 | `sha256:3b759508dc0d629b96b582acd8d7327ba16375e616f1f6c252af52caaa816f91` |
| `repository-hygiene-b2f02ebc65bedf736197d54ed65228320d9962a4-34281512196` | 269 | `sha256:318df25e65baaed64297af34ae68e1a4cfc3de673fc8518155ffd59ac8cff6bd` |

## 4. 已关闭与未关闭的门槛

本次 PASS 精确关闭以下仓库自动化缺口：

- M7→M8/Online exact no-op 发布保护和容量工具已有最终干净业务代码 SHA；
- 同一 PR merge-ref 已从头完整执行八类远端 Job并取得 8/8；
- 7 组应上传 artifact 均绑定 merge-ref、Run ID 和 GitHub digest；
- 本地独立 Review 的加固结论不再只绑定 dirty diff，而是绑定受测候选
  `fa6fce05...`。

以下事项仍为 **BLOCKED / NOT RUN**，不能因远端 CI 通过而勾选：

1. 尚未在独立、目标相似的 Linux Docker/MySQL 环境执行完整 M7→M8 updater 编排；
   workflow 的迁移/测试 Job 不包含 Backup/Restore、停服、Record、live replay、
   Runtime 切换与数据后恢复。
2. 持久 Gate A 仍停在 M7；没有运行 M8 写前只读盘点、当次新 Backup/同 ID 独立
   Restore、M7→M8、Runtime/gzip 切换、HEX/API/零 PNG 请求现场验收或 M8 数据后恢复，
   也没有取得当次持久写入授权。
3. 本地 2 核/4GiB/5Mbps 完整探索轮仍因 10 VU 未压缩色板路径超过冻结容量门槛而
   严格为 `FAIL`；尚未完成干净 SHA 的 candidate-pre 三轮，也没有独立 2 vCPU/4GiB
   Linux 主机、TLS/公网或真实网络复现。
4. 微信 artifact 仍明确为 `release_eligible=false`；真实备案 HTTPS Origin、微信合法
   域名、正式 RC、体验版上传/分发授权和 iOS/Android 真机验收均未完成。
5. PR 仍未合并，v0.6.0 未 tag/release；CI 不自动授权数据库迁移、DNS、微信上传、
   分发、提审或公开发布。

因此当前发布决定继续为 **No-Go / Not Authorized**。后续进入持久 Gate A 前，必须
先补齐完整 updater 的隔离 MySQL 演练和当次只读/备份恢复/授权门槛；容量 Gate 需完成
candidate-pre 三轮并全部通过，或由风险接受人对未压缩大 JSON 路径签署明确、有期限的
风险处置。Run 34281512196 只证明代码候选 `fa6fce05...` 的远端 CI 8/8。
